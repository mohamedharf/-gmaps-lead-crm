import requests
import hmac
import hashlib
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def _require_paymob_config():
    if not settings.PAYMOB_API_KEY or not settings.PAYMOB_INTEGRATION_ID or not settings.PAYMOB_IFRAME_ID:
        raise ValueError("Paymob credentials are not configured in environment variables.")


def get_paymob_auth_token():
    """Step 1: Get Paymob authentication token"""
    try:
        _require_paymob_config()
        url = f"{settings.PAYMOB_BASE_URL}/auth/tokens"
        payload = {
            "api_key": settings.PAYMOB_API_KEY
        }

        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()

        data = response.json()
        return data['token']
    except Exception as e:
        logger.error(f"Error getting Paymob auth token: {str(e)}")
        raise

def create_paymob_order(auth_token, amount_cents, merchant_order_id=None):
    """Step 2: Create Paymob order"""
    try:
        url = f"{settings.PAYMOB_BASE_URL}/ecommerce/orders"

        payload = {
            "auth_token": auth_token,
            "delivery_needed": "false",
            "amount_cents": str(amount_cents),
            "currency": "EGP",
            "items": []
        }

        if merchant_order_id:
            payload["merchant_order_id"] = str(merchant_order_id)

        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()

        return response.json()
    except Exception as e:
        logger.error(f"Error creating Paymob order: {str(e)}")
        raise

def create_payment_key(auth_token, order_id, amount_cents, billing_data):
    """Step 3: Generate payment key for iFrame"""
    try:
        _require_paymob_config()
        url = f"{settings.PAYMOB_BASE_URL}/acceptance/payment_keys"

        payload = {
            "auth_token": auth_token,
            "amount_cents": str(amount_cents),
            "expiration": 3600,
            "order_id": str(order_id),
            "billing_data": billing_data,
            "currency": "EGP",
            "integration_id": settings.PAYMOB_INTEGRATION_ID
        }

        response = requests.post(url, json=payload, timeout=15)
        response.raise_for_status()

        data = response.json()
        return data['token']
    except Exception as e:
        logger.error(f"Error creating payment key: {str(e)}")
        raise

def get_iframe_url(payment_token):
    """Generate iFrame URL for payment"""
    _require_paymob_config()
    return f"https://accept.paymob.com/api/acceptance/iframes/{settings.PAYMOB_IFRAME_ID}?payment_token={payment_token}"

def verify_paymob_hmac(callback_data, hmac_secret):
    """Verify HMAC signature from Paymob callback using timing-safe comparison."""
    try:
        received_hmac = callback_data.get('hmac', '')
        if not hmac_secret or not received_hmac:
            return False

        obj = callback_data.get('obj', {})
        if not isinstance(obj, dict):
            return False

        # Build concatenated string (order matters per Paymob specification)
        concatenated_string = (
            str(obj.get('amount_cents', '')) +
            str(obj.get('created_at', '')) +
            str(obj.get('currency', '')) +
            str(obj.get('error_occured', '')).lower() +
            str(obj.get('has_parent_transaction', '')).lower() +
            str(obj.get('id', '')) +
            str(obj.get('integration_id', '')) +
            str(obj.get('is_3d_secure', '')).lower() +
            str(obj.get('is_auth', '')).lower() +
            str(obj.get('is_capture', '')).lower() +
            str(obj.get('is_refunded', '')).lower() +
            str(obj.get('is_standalone_payment', '')).lower() +
            str(obj.get('is_voided', '')).lower() +
            str(obj.get('order', {}).get('id', '')) +
            str(obj.get('owner', '')) +
            str(obj.get('pending', '')).lower() +
            str(obj.get('source_data', {}).get('pan', '')) +
            str(obj.get('source_data', {}).get('sub_type', '')) +
            str(obj.get('source_data', {}).get('type', '')) +
            str(obj.get('success', '')).lower()
        )

        calculated_hmac = hmac.new(
            hmac_secret.encode('utf-8'),
            concatenated_string.encode('utf-8'),
            hashlib.sha512
        ).hexdigest()

        return hmac.compare_digest(calculated_hmac, str(received_hmac))

    except Exception as e:
        logger.error(f"HMAC verification error: {str(e)}")
        return False
