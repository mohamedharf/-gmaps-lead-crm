from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from notifications.models import Notification


class NotificationAPITests(TestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(username="user_a", password="Password123!")
        self.user_b = User.objects.create_user(username="user_b", password="Password123!")
        self.notif_a1 = Notification.objects.create(
            recipient=self.user_a,
            type="SYSTEM_ALERT",
            title="Alert A1",
            message="First alert for A",
        )
        self.notif_a2 = Notification.objects.create(
            recipient=self.user_a,
            type="SYSTEM_ALERT",
            title="Alert A2",
            message="Second alert for A",
        )
        self.notif_b1 = Notification.objects.create(
            recipient=self.user_b,
            type="SYSTEM_ALERT",
            title="Alert B1",
            message="First alert for B",
        )

    def test_unread_count_is_scoped_to_user(self):
        self.client.force_login(self.user_a)
        resp = self.client.get(reverse("notifications:unread_count"))
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["unread_count"], 2)
        self.assertEqual(len(data["notifications"]), 2)

    def test_cannot_mark_other_user_notification_read(self):
        self.client.force_login(self.user_a)
        resp = self.client.post(reverse("notifications:mark_read", args=[self.notif_b1.id]))
        self.assertEqual(resp.status_code, 404)
        self.notif_b1.refresh_from_db()
        self.assertFalse(self.notif_b1.is_read)

    def test_mark_all_as_read(self):
        self.client.force_login(self.user_a)
        resp = self.client.post(reverse("notifications:mark_all_read"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Notification.objects.filter(recipient=self.user_a, is_read=False).count(), 0)
        self.assertEqual(Notification.objects.filter(recipient=self.user_b, is_read=False).count(), 1)
