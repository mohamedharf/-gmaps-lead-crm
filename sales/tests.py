import hashlib
import hmac
import json
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.test import TestCase, override_settings
from django.urls import reverse

from notifications.models import Notification
from sales.models import (
    ContactDetails,
    Dataset,
    DealRequest,
    Lead,
    OutreachStatus,
    SalesAgentProfile,
    SubscriptionOrder,
    SystemSettings,
)
from sales.payment_views import _sign_order_id
from sales.paymob_utils import verify_paymob_hmac


def _build_paymob_payload(order_id, success=True, secret="test_hmac_secret"):
    obj = {
        "amount_cents": 1500000,
        "created_at": "2026-11-10T12:00:00",
        "currency": "EGP",
        "error_occured": False,
        "has_parent_transaction": False,
        "id": 998877,
        "integration_id": 12345,
        "is_3d_secure": True,
        "is_auth": False,
        "is_capture": False,
        "is_refunded": False,
        "is_standalone_payment": True,
        "is_voided": False,
        "order": {"id": order_id},
        "owner": 1001,
        "pending": False,
        "source_data": {"pan": "2346", "sub_type": "MasterCard", "type": "card"},
        "success": success,
    }
    concatenated = (
        str(obj["amount_cents"])
        + str(obj["created_at"])
        + str(obj["currency"])
        + str(obj["error_occured"]).lower()
        + str(obj["has_parent_transaction"]).lower()
        + str(obj["id"])
        + str(obj["integration_id"])
        + str(obj["is_3d_secure"]).lower()
        + str(obj["is_auth"]).lower()
        + str(obj["is_capture"]).lower()
        + str(obj["is_refunded"]).lower()
        + str(obj["is_standalone_payment"]).lower()
        + str(obj["is_voided"]).lower()
        + str(obj["order"]["id"])
        + str(obj["owner"])
        + str(obj["pending"]).lower()
        + str(obj["source_data"]["pan"])
        + str(obj["source_data"]["sub_type"])
        + str(obj["source_data"]["type"])
        + str(obj["success"]).lower()
    )
    sig = hmac.new(
        secret.encode("utf-8"),
        concatenated.encode("utf-8"),
        hashlib.sha512,
    ).hexdigest()
    return {"obj": obj, "hmac": sig}


class BaseCRMTestCase(TestCase):
    def setUp(self):
        self.sales_group, _ = Group.objects.get_or_create(name="Sales")

        self.admin = User.objects.create_user(
            username="admin_user", password="Password123!", is_staff=True, is_superuser=True
        )
        SalesAgentProfile.objects.create(user=self.admin, commission_rate=Decimal("15.00"))

        self.manager = User.objects.create_user(username="manager_user", password="Password123!")
        self.manager.groups.add(self.sales_group)
        self.manager_profile = SalesAgentProfile.objects.create(
            user=self.manager, commission_rate=Decimal("12.00"), team_commission_rate=Decimal("3.00")
        )

        self.agent = User.objects.create_user(username="agent_user", password="Password123!")
        self.agent.groups.add(self.sales_group)
        self.agent_profile = SalesAgentProfile.objects.create(
            user=self.agent,
            manager=self.manager_profile,
            commission_rate=Decimal("10.00"),
        )

        self.other_agent = User.objects.create_user(username="other_agent", password="Password123!")
        self.other_agent.groups.add(self.sales_group)
        SalesAgentProfile.objects.create(user=self.other_agent, commission_rate=Decimal("10.00"))

        self.sys_settings = SystemSettings.get_settings()
        self.sys_settings.site_name = "GMaps Lead CRM"
        self.sys_settings.product_price = Decimal("15000.00")
        self.sys_settings.save()

        self.dataset = Dataset.objects.create(name="Cairo Leads")
        self.lead = Lead.objects.create(
            name="Nile Bistro",
            city="Cairo",
            dataset=self.dataset,
            assigned_to=self.agent,
        )
        self.lead.assigned_agents.add(self.agent)
        ContactDetails.objects.create(lead=self.lead, phone_primary="+201012345678")
        OutreachStatus.objects.create(lead=self.lead, status="FOLLOW_UP")


class AuthAndRBACTests(BaseCRMTestCase):
    def test_login_page_hides_sidebar_and_signout(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b"Sign Out", response.content)
        self.assertNotIn(b"<aside", response.content)

    def test_anonymous_blocked_from_protected_endpoints(self):
        for url_name in ("dashboard", "data_explorer", "manage_team", "scraper_control"):
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 302)
            self.assertIn("/accounts/login/", resp.url)

        update_resp = self.client.post(reverse("update_status", args=[self.lead.id]), {"status": "SENT"})
        self.assertEqual(update_resp.status_code, 302)
        self.assertIn("/accounts/login/", update_resp.url)

    def test_sales_agent_cannot_access_admin_views(self):
        self.client.force_login(self.agent)
        for url_name in ("scraper_control", "manage_system_settings", "pending_deals"):
            resp = self.client.get(reverse(url_name))
            self.assertEqual(resp.status_code, 403)

    def test_unassigned_agent_cannot_update_lead_status(self):
        self.client.force_login(self.other_agent)
        resp = self.client.post(reverse("update_status", args=[self.lead.id]), {"status": "SENT"})
        self.assertEqual(resp.status_code, 403)

    def test_assigned_agent_can_update_lead_status(self):
        self.client.force_login(self.agent)
        resp = self.client.post(
            reverse("update_status", args=[self.lead.id]),
            {"status": "REPLIED"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.lead.outreach_status.refresh_from_db()
        self.assertEqual(self.lead.outreach_status.status, "REPLIED")

    def test_agent_submitting_deal_creates_pending_deal_request_and_notifies(self):
        self.client.force_login(self.agent)
        resp = self.client.post(
            reverse("update_status", args=[self.lead.id]),
            {"status": "DEAL", "deal_price": "15000", "deal_notes": "Closed annual plan"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        deal = DealRequest.objects.get(lead=self.lead)
        self.assertEqual(deal.status, "PENDING")
        self.assertEqual(deal.price, Decimal("15000.00"))
        self.assertTrue(Notification.objects.filter(recipient=self.admin, type="DEAL_REQUEST_NEW").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.manager, type="DEAL_REQUEST_NEW").exists())


class DealAndCommissionTests(BaseCRMTestCase):
    def test_subscription_order_commission_and_net_revenue(self):
        order = SubscriptionOrder.objects.create(
            lead=self.lead,
            customer_name="Nile Bistro",
            customer_email="owner@nilebistro.example.com",
            customer_phone="01012345678",
            domain_name="nilebistro.com",
            price=Decimal("10000.00"),
            sales_agent=self.agent,
            commission_rate=Decimal("10.00"),
            manager=self.manager,
            manager_commission_rate=Decimal("3.00"),
            status="COMPLETED",
        )
        self.assertEqual(order.commission_amount, Decimal("1000.00"))
        self.assertEqual(order.manager_commission_amount, Decimal("300.00"))
        self.assertEqual(order.net_revenue, Decimal("8700.00"))

    def test_confirm_deal_creates_order_and_notifications(self):
        deal = DealRequest.objects.create(
            lead=self.lead, sales_agent=self.agent, price=Decimal("15000.00"), status="PENDING"
        )
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("confirm_deal", args=[deal.id]))
        self.assertEqual(resp.status_code, 200)

        deal.refresh_from_db()
        self.assertEqual(deal.status, "APPROVED")
        order = SubscriptionOrder.objects.get(lead=self.lead, status="COMPLETED")
        self.assertEqual(order.commission_rate, Decimal("10.00"))
        self.assertEqual(order.manager, self.manager)
        self.assertEqual(order.manager_commission_rate, Decimal("3.00"))
        self.assertTrue(Notification.objects.filter(recipient=self.agent, type="DEAL_APPROVED").exists())
        self.assertTrue(Notification.objects.filter(recipient=self.manager, type="DEAL_APPROVED").exists())

    def test_reject_deal_resets_lead_to_follow_up(self):
        self.lead.outreach_status.status = "DEAL"
        self.lead.outreach_status.save()
        deal = DealRequest.objects.create(
            lead=self.lead, sales_agent=self.agent, price=Decimal("15000.00"), status="PENDING"
        )
        self.client.force_login(self.admin)
        resp = self.client.post(reverse("reject_deal", args=[deal.id]))
        self.assertEqual(resp.status_code, 200)

        deal.refresh_from_db()
        self.lead.outreach_status.refresh_from_db()
        self.assertEqual(deal.status, "REJECTED")
        self.assertEqual(self.lead.outreach_status.status, "FOLLOW_UP")

    def test_manage_team_includes_total_earned(self):
        SubscriptionOrder.objects.create(
            lead=self.lead,
            customer_name="Nile Bistro",
            customer_email="owner@example.com",
            customer_phone="01012345678",
            domain_name="nilebistro.com",
            price=Decimal("10000.00"),
            sales_agent=self.agent,
            commission_rate=Decimal("10.00"),
            manager=self.manager,
            manager_commission_rate=Decimal("2.00"),
            status="COMPLETED",
        )
        self.client.force_login(self.admin)
        resp = self.client.get(reverse("manage_team"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["team_stats"]["total_earned"], Decimal("1200.00"))


@override_settings(PAYMOB_HMAC_SECRET="test_hmac_secret")
class PaymobSecurityTests(BaseCRMTestCase):
    def setUp(self):
        super().setUp()
        self.order = SubscriptionOrder.objects.create(
            lead=self.lead,
            customer_name="Nile Bistro",
            customer_email="owner@example.com",
            customer_phone="01012345678",
            domain_name="nilebistro.com",
            price=Decimal("15000.00"),
            sales_agent=self.agent,
            paymob_order_id="555001",
            status="PROCESSING",
        )

    def test_verify_paymob_hmac_valid_and_tampered(self):
        payload = _build_paymob_payload("555001", success=True, secret="test_hmac_secret")
        self.assertTrue(verify_paymob_hmac(payload, "test_hmac_secret"))
        self.assertFalse(verify_paymob_hmac(payload, ""))
        payload["obj"]["amount_cents"] = 1
        self.assertFalse(verify_paymob_hmac(payload, "test_hmac_secret"))

    def test_webhook_rejects_invalid_hmac(self):
        payload = _build_paymob_payload("555001", success=True, secret="wrong_secret")
        resp = self.client.post(
            reverse("payment_callback"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 403)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, "PROCESSING")

    def test_webhook_accepts_valid_hmac_and_marks_deal(self):
        payload = _build_paymob_payload("555001", success=True, secret="test_hmac_secret")
        resp = self.client.post(
            reverse("payment_callback"),
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        self.order.refresh_from_db()
        self.lead.outreach_status.refresh_from_db()
        self.assertEqual(self.order.status, "COMPLETED")
        self.assertTrue(self.order.hmac_verified)
        self.assertEqual(self.lead.outreach_status.status, "DEAL")

    def test_payment_receipt_blocks_idor_and_allows_authorized(self):
        url = reverse("payment_success", args=[self.order.id])
        self.assertEqual(self.client.get(url).status_code, 403)

        self.client.force_login(self.other_agent)
        self.assertEqual(self.client.get(url).status_code, 403)

        self.client.force_login(self.agent)
        self.assertEqual(self.client.get(url).status_code, 200)

        self.client.logout()
        token = _sign_order_id(self.order.id)
        self.assertEqual(self.client.get(f"{url}?token={token}").status_code, 200)

    def test_checkout_preserves_global_branding(self):
        self.client.force_login(self.agent)
        resp = self.client.get(reverse("checkout_page", args=[self.lead.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"GMaps Lead CRM", resp.content)
