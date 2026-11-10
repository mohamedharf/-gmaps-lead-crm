from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.contrib.auth.models import User
from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.urls import reverse
from django.utils import timezone
from .models import Lead, SubscriptionOrder, SalesAgentProfile, SystemSettings
from .paymob_utils import (
    get_paymob_auth_token,
    create_paymob_order,
    create_payment_key,
    get_iframe_url,
    verify_paymob_hmac,
)
import hmac as hmac_lib
import hashlib
import json
import logging

logger = logging.getLogger(__name__)
_receipt_signer = TimestampSigner(salt='payment-receipt')


def _sign_order_id(order_id):
    return _receipt_signer.sign(str(order_id))


def _can_view_order(request, order):
    if request.user.is_authenticated and (
        request.user.is_staff or order.sales_agent_id == request.user.id
    ):
        return True
    token = request.GET.get('token')
    if token:
        try:
            unsigned = _receipt_signer.unsign(token, max_age=3600)
            return str(order.id) == unsigned
        except (BadSignature, SignatureExpired):
            return False
    return False


def _verify_paymob_get_hmac(params, hmac_secret):
    received_hmac = params.get('hmac', '')
    if not hmac_secret or not received_hmac:
        return False
    fields = [
        'amount_cents', 'created_at', 'currency', 'error_occured',
        'has_parent_transaction', 'id', 'integration_id', 'is_3d_secure',
        'is_auth', 'is_capture', 'is_refunded', 'is_standalone_payment',
        'is_voided', 'order', 'owner', 'pending', 'source_data.pan',
        'source_data.sub_type', 'source_data.type', 'success',
    ]
    concatenated = ''.join(str(params.get(f, '')) for f in fields)
    calculated = hmac_lib.new(
        hmac_secret.encode('utf-8'),
        concatenated.encode('utf-8'),
        hashlib.sha512,
    ).hexdigest()
    return hmac_lib.compare_digest(calculated, str(received_hmac))

def checkout_page(request, lead_id):
    """Display checkout form with current product price"""
    lead = get_object_or_404(Lead, id=lead_id)
    agent_identifier = request.GET.get('agent')
    sales_agent = None
    
    if agent_identifier:
        try:
            # Try to resolve by UUID first
            profile = SalesAgentProfile.objects.filter(agent_uuid=agent_identifier).first()
            if profile:
                sales_agent = profile.user
            else:
                # Fallback: try to resolve by ID (for backward compatibility during migration)
                sales_agent = User.objects.filter(id=agent_identifier).first()
        except:
            pass
            
    # Fallback: If no agent found, try M2M first, then legacy assigned_to
    if not sales_agent:
        first_agent = lead.assigned_agents.first()
        if first_agent:
            sales_agent = first_agent
        elif lead.assigned_to:
            sales_agent = lead.assigned_to
    
    # Get current system settings as base
    system_settings = SystemSettings.get_settings()
    
    # Dataset overrides
    settings_data = {
        'product_name': system_settings.product_name,
        'product_price': system_settings.product_price,
        'product_description': system_settings.product_description,
        'currency': system_settings.currency
    }
    
    if lead.dataset:
        if lead.dataset.product_name:
            settings_data['product_name'] = lead.dataset.product_name
        if lead.dataset.product_price is not None:
            settings_data['product_price'] = lead.dataset.product_price
        if lead.dataset.product_description:
            settings_data['product_description'] = lead.dataset.product_description
    
    # Pre-fill customer data if available
    initial_data = {
        'customer_name': lead.name if lead.name else '',
        'customer_email': lead.contact_details.email_list[0] if hasattr(lead, 'contact_details') and lead.contact_details.email_list else '',
        'customer_phone': lead.contact_details.phone_primary if hasattr(lead, 'contact_details') and lead.contact_details.phone_primary else '',
    }
    
    context = {
        'lead': lead,
        'agent': sales_agent,
        'checkout_settings': settings_data,
        'initial_data': initial_data,
    }

    return render(request, 'sales/checkout_form.html', context)


def public_checkout(request, agent_uuid):
    """Public generic checkout form linked directly to a sales agent without a predefined lead"""
    # Verify the agent exists
    profile = get_object_or_404(SalesAgentProfile, agent_uuid=agent_uuid)

    # Get global settings for public checkout
    system_settings = SystemSettings.get_settings()
    settings_data = {
        'product_name': system_settings.product_name,
        'product_price': system_settings.product_price,
        'product_description': system_settings.product_description,
        'currency': system_settings.currency
    }

    # Render the exact same checkout form, but pass the agent and leave lead blank
    context = {
        'agent': profile.user,
        'checkout_settings': settings_data,
        'initial_data': {}
    }
    return render(request, 'sales/checkout_form.html', context)

def initiate_payment(request):
    """Process checkout form and initiate Paymob payment"""
    if request.method != 'POST':
        return redirect('data_explorer')
    
    try:
        # 1. Get form data
        lead_id = request.POST.get('lead_id')
        sales_agent_id = request.POST.get('sales_agent_id')
        customer_name = request.POST.get('customer_name')
        customer_email = request.POST.get('customer_email')
        customer_phone = request.POST.get('customer_phone')
        domain_name = request.POST.get('domain_name')
        
        # Fallback: If no sales_agent_id in POST, use lead's assigned_agents or assigned_to
        if not sales_agent_id and lead_id:
            try:
                lead = Lead.objects.prefetch_related('assigned_agents').get(id=lead_id)
                first_agent = lead.assigned_agents.first()
                if first_agent:
                    sales_agent_id = first_agent.id
                    logger.info(f"Using lead assigned_agents as sales_agent: {sales_agent_id}")
                elif lead.assigned_to:
                    sales_agent_id = lead.assigned_to.id
                    logger.info(f"Using lead legacy assigned_to as sales_agent: {sales_agent_id}")
            except Lead.DoesNotExist:
                pass
        
        # 2. Determine price (Check dataset override first)
        system_settings = SystemSettings.get_settings()
        current_price = system_settings.product_price
        
        if lead_id:
            try:
                lead = Lead.objects.get(id=lead_id)
                if lead.dataset and lead.dataset.product_price is not None:
                    current_price = lead.dataset.product_price
                    logger.info(f"Using dataset override price: {current_price}")
            except Lead.DoesNotExist:
                pass

        # 3. Get commission rate and manager tracking
        agent_user = None
        commission_rate = system_settings.default_commission_rate
        manager_user = None
        manager_rate = 0.00
        
        if sales_agent_id:
            try:
                # Try to get agent by UUID or ID
                from django.contrib.auth.models import User
                profile = SalesAgentProfile.objects.filter(agent_uuid=sales_agent_id).first()
                if profile:
                    agent_user = profile.user
                    commission_rate = profile.commission_rate
                    if hasattr(profile, 'manager') and profile.manager:
                        manager_user = profile.manager.user
                        manager_rate = profile.manager.team_commission_rate
                else:
                    # Fallback for ID
                    agent_user = User.objects.filter(id=sales_agent_id).first()
                    if agent_user and hasattr(agent_user, 'sales_profile'):
                        commission_rate = agent_user.sales_profile.commission_rate
                        profile = agent_user.sales_profile
                        if hasattr(profile, 'manager') and profile.manager:
                            manager_user = profile.manager.user
                            manager_rate = profile.manager.team_commission_rate
            except Exception as e:
                logger.warning(f"Could not find sales agent: {e}")
        
        # 4. Create Order (status=PENDING)
        order = SubscriptionOrder.objects.create(
            lead_id=lead_id if lead_id else None,
            sales_agent=agent_user,
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            domain_name=domain_name,
            price=current_price,  # Snapshot current price
            currency='EGP',
            commission_rate=commission_rate,  # Snapshot commission rate
            manager=manager_user, # Snapshot manager
            manager_commission_rate=manager_rate, # Snapshot team rate
            status='PENDING'
        )
        
        # 5. Paymob Integration (3-step process)
        
        # Step 1: Get Auth Token
        logger.info(f"[Order {order.id}] Step 1: Requesting Auth Token...")
        try:
            auth_token = get_paymob_auth_token()
            logger.info(f"[Order {order.id}] Auth Token obtained successfully")
        except Exception as e:
            logger.error(f"[Order {order.id}] Auth Token FAILED: {str(e)}")
            raise
        
        # Step 2: Create Paymob Order
        logger.info(f"[Order {order.id}] Step 2: Creating Paymob Order...")
        amount_cents = int(order.price * 100)  # Convert EGP to cents
        try:
            paymob_order = create_paymob_order(
                auth_token=auth_token,
                amount_cents=amount_cents,
                merchant_order_id=order.id
            )
            logger.info(f"[Order {order.id}] Paymob Order created: {paymob_order['id']}")
        except Exception as e:
            logger.error(f"[Order {order.id}] Paymob Order creation FAILED: {str(e)}")
            raise
        
        # Save Paymob Order ID
        order.paymob_order_id = str(paymob_order['id'])
        order.save()
        
        # Step 3: Generate Payment Key
        logger.info(f"[Order {order.id}] Step 3: Generating Payment Key...")
        # Split name for Paymob requirement
        names = customer_name.split()
        first_name = names[0] if names else "Customer"
        last_name = names[-1] if len(names) > 1 else "User"
        
        billing_data = {
            "apartment": "NA",
            "email": customer_email,
            "floor": "NA",
            "first_name": first_name,
            "street": "NA",
            "building": "NA",
            "phone_number": customer_phone,
            "shipping_method": "NA",
            "postal_code": "NA",
            "city": "Cairo",
            "country": "EG",
            "last_name": last_name,
            "state": "NA"
        }
        
        try:
            payment_key = create_payment_key(
                auth_token=auth_token,
                order_id=paymob_order['id'],
                amount_cents=amount_cents,
                billing_data=billing_data
            )
            logger.info(f"[Order {order.id}] Payment Key generated successfully")
        except Exception as e:
            logger.warning(f"[Order {order.id}] Payment key creation failed, retrying with dummy phone: {e}")
            # Sometimes phone number validation fails, try fallback
            billing_data["phone_number"] = "01000000000"
            try:
                payment_key = create_payment_key(
                    auth_token=auth_token,
                    order_id=paymob_order['id'],
                    amount_cents=amount_cents,
                    billing_data=billing_data
                )
                logger.info(f"[Order {order.id}] Payment Key generated with fallback phone")
            except Exception as e2:
                logger.error(f"[Order {order.id}] Payment Key FAILED even with fallback: {str(e2)}")
                raise
        
        # Save payment token
        order.payment_token = payment_key
        order.status = 'PROCESSING'
        order.save()
        logger.info(f"[Order {order.id}] Order status updated to PROCESSING")
        
        # 6. Redirect to Paymob iFrame
        iframe_url = get_iframe_url(payment_key)
        logger.info(f"[Order {order.id}] Redirecting to Paymob iFrame: {iframe_url[:100]}...")
        return redirect(iframe_url)
        
    except Exception as e:
        # Log error and show error page
        logger.error(f"Payment initiation error: {str(e)}", exc_info=True)
        if 'order' in locals():
            order.status = 'FAILED'
            order.save()
            token = _sign_order_id(order.id)
            return redirect(f"{reverse('payment_failure', args=[order.id])}?token={token}")

        return render(request, 'sales/payment_error.html', {
            'error': 'Unable to initialize payment right now. Please try again later.'
        })

@csrf_exempt
def payment_callback(request):
    """Handle Paymob callback (webhook and browser redirect)"""
    if request.method != 'POST':
        success = request.GET.get('success')
        merchant_order_id = request.GET.get('merchant_order_id')

        if not merchant_order_id:
            return HttpResponse("Method not allowed", status=405)

        if _verify_paymob_get_hmac(request.GET, settings.PAYMOB_HMAC_SECRET):
            token = _sign_order_id(merchant_order_id)
            target = 'payment_success' if success == 'true' else 'payment_failure'
            return redirect(f"{reverse(target, args=[merchant_order_id])}?token={token}")

        if request.user.is_authenticated:
            target = 'payment_success' if success == 'true' else 'payment_failure'
            return redirect(target, order_id=merchant_order_id)

        template = 'sales/payment_success.html' if success == 'true' else 'sales/payment_failure.html'
        return render(request, template, {'order': None})

    try:
        # Parse callback data
        data = json.loads(request.body)

        # Verify HMAC and reject forged requests
        hmac_valid = verify_paymob_hmac(data, settings.PAYMOB_HMAC_SECRET)
        obj = data.get('obj', {})
        paymob_order_id = str(obj.get('order', {}).get('id', ''))

        if not hmac_valid:
            logger.warning(f"Rejected Paymob webhook with invalid HMAC for order {paymob_order_id}")
            return HttpResponse("Invalid HMAC signature", status=403)

        transaction_id = str(obj.get('id', ''))
        success = obj.get('success', False)

        # Find order
        try:
            order = SubscriptionOrder.objects.get(paymob_order_id=paymob_order_id)
        except SubscriptionOrder.DoesNotExist:
            logger.error(f"Order not found for Paymob ID: {paymob_order_id}")
            return HttpResponse("Order not found", status=404)

        # Update order
        order.paymob_transaction_id = transaction_id
        order.hmac_verified = True
        order.payment_method = obj.get('source_data', {}).get('sub_type', 'Unknown')

        if success:
            order.status = 'COMPLETED'
            order.paid_at = timezone.now()

            if order.lead and hasattr(order.lead, 'outreach_status'):
                order.lead.outreach_status.status = 'DEAL'
                order.lead.outreach_status.save()
        else:
            order.status = 'FAILED'

        order.save()

        return HttpResponse("OK", status=200)

    except Exception as e:
        logger.error(f"Callback error: {str(e)}")
        return HttpResponse("Callback processing error", status=500)

def payment_success(request, order_id):
    """Display payment success page"""
    order = get_object_or_404(SubscriptionOrder, id=order_id)
    if not _can_view_order(request, order):
        return HttpResponse("Unauthorized", status=403)

    context = {
        'order': order,
        'commission': order.commission_amount,
        'net_revenue': order.net_revenue,
    }

    return render(request, 'sales/payment_success.html', context)

def payment_failure(request, order_id):
    """Display payment failure page"""
    order = get_object_or_404(SubscriptionOrder, id=order_id)
    if not _can_view_order(request, order):
        return HttpResponse("Unauthorized", status=403)

    context = {
        'order': order,
    }

    return render(request, 'sales/payment_failure.html', context)
