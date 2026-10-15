from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse

from .models import DEFAULT_COLORS, DevelopmentState, StateColor
from .views import TOKEN_AGE


class StateColorsTests(TestCase):
    def setUp(self):
        # Re-create the fixture explicitly because TransactionTestCase/flush can
        # run before this suite without rerunning data migrations.
        for state in DevelopmentState:
            StateColor.objects.get_or_create(state=state.value, defaults={"color": DEFAULT_COLORS[state]})
        self.user = get_user_model().objects.create_user("color-test", password="test-only-password")
        self.client.force_login(self.user)
        self.url = reverse("care_states:index")

    def preview(self, color="#123ABC", state="capability"):
        page = self.client.get(self.url)
        row = next(row for row in page.context["rows"] if row["state"] == state)
        return self.client.post(self.url, {"action": "preview", "state": state, "color": color, "snapshot": row["snapshot"]})

    def test_seed_and_fixed_order(self):
        self.assertEqual(StateColor.objects.count(), 3)
        page = self.client.get(self.url)
        self.assertEqual([r["label"] for r in page.context["rows"]], ["قدرة", "رغبة", "رعاية"])
        self.assertEqual([r["color"] for r in page.context["rows"]], list(DEFAULT_COLORS.values()))
        self.assertNotContains(page, "لوحة الإدارة")
        self.assertIn("no-store", page["Cache-Control"])

    def test_anonymous_cannot_view_or_write(self):
        self.client.logout()
        for method in [self.client.get, self.client.post]:
            response = method(self.url)
            self.assertEqual(response.status_code, 302)
            self.assertTrue(response.url.startswith("/login?next="))
        self.assertEqual(StateColor.objects.get(state="capability").color, "#BA1D1D")

    def test_preview_does_not_write_and_confirmation_persists(self):
        response = self.preview("#abcdef")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "تأكيد تغيير اللون")
        self.assertEqual(StateColor.objects.get(state="capability").color, "#BA1D1D")
        token = response.context["pending"]["token"]
        response = self.client.post(self.url, {"action": "confirm", "token": token})
        self.assertRedirects(response, self.url)
        item = StateColor.objects.get(state="capability")
        self.assertEqual((item.color, item.version), ("#ABCDEF", 2))
        self.assertEqual(self.client.get(self.url).context["rows"][0]["color"], "#ABCDEF")

    def test_cancel_and_identical_color_do_not_write(self):
        self.preview()
        self.client.get(self.url)
        self.assertEqual(StateColor.objects.get(state="capability").version, 1)
        response = self.preview("#ba1d1d")
        self.assertNotIn("pending", response.context)
        self.assertEqual(StateColor.objects.get(state="capability").version, 1)

    def test_invalid_state_color_and_actions(self):
        row = self.client.get(self.url).context["rows"][0]
        for color in ["red", "#ABC", "#GGGGGG", "#12345678", "#123456\n", '<script>']:
            response = self.client.post(self.url, {"action": "preview", "state": "capability", "color": color, "snapshot": row["snapshot"]})
            self.assertEqual(response.status_code, 400, color)
        for state in ["other", "care; DROP TABLE", "", "capability"]:
            response = self.client.post(self.url, {"action": "preview", "state": state, "color": "#123ABC", "snapshot": "forged"})
            self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.post(self.url, {"action": "delete", "state": "care"}).status_code, 400)
        self.assertEqual(StateColor.objects.count(), 3)
        self.assertEqual(StateColor.objects.get(state="capability").version, 1)

    def test_tampering_expired_confirmation_and_cross_user_tokens(self):
        from unittest.mock import patch
        token = self.preview().context["pending"]["token"]
        self.assertEqual(self.client.post(self.url, {"action": "confirm", "token": token + "bad"}).status_code, 400)
        import time
        with patch("django.core.signing.time.time", return_value=time.time() + TOKEN_AGE + 10):
            self.assertEqual(self.client.post(self.url, {"action": "confirm", "token": token}).status_code, 400)
        other = get_user_model().objects.create_user("other-color-test", password="test-only-password")
        self.client.force_login(other)
        self.assertEqual(self.client.post(self.url, {"action": "confirm", "token": token}).status_code, 400)
        self.assertEqual(StateColor.objects.get(state="capability").version, 1)

    def test_replay_and_concurrent_confirmations_are_rejected(self):
        first = self.preview("#112233").context["pending"]["token"]
        second = self.preview("#334455").context["pending"]["token"]
        self.assertEqual(self.client.post(self.url, {"action": "confirm", "token": first}).status_code, 302)
        self.assertEqual(self.client.post(self.url, {"action": "confirm", "token": second}).status_code, 409)
        self.assertEqual(self.client.post(self.url, {"action": "confirm", "token": first}).status_code, 409)
        self.assertEqual(StateColor.objects.get(state="capability").color, "#112233")

    def test_stale_snapshot_and_cross_state_snapshot_are_rejected(self):
        row = self.client.get(self.url).context["rows"][0]
        for state in ["capability", "care"]:
            StateColor.objects.filter(state="capability").update(version=2)
            response = self.client.post(self.url, {"action": "preview", "state": state, "color": "#123ABC", "snapshot": row["snapshot"]})
            self.assertEqual(response.status_code, 409 if state == "capability" else 400)

    def test_csrf_required_for_preview_and_confirm(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        page = client.get(self.url)
        row = page.context["rows"][0]
        data = {"action": "preview", "state": row["state"], "color": "#123ABC", "snapshot": row["snapshot"]}
        self.assertEqual(client.post(self.url, data).status_code, 403)
        csrf = client.cookies["csrftoken"].value
        response = client.post(self.url, {**data, "csrfmiddlewaretoken": csrf})
        token = response.context["pending"]["token"]
        self.assertEqual(client.post(self.url, {"action": "confirm", "token": token}).status_code, 403)
        self.assertEqual(client.post(self.url, {"action": "confirm", "token": token, "csrfmiddlewaretoken": csrf}).status_code, 302)

    def test_database_rejects_non_enum_states(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            StateColor.objects.create(state="unknown", color="#123ABC")

    def test_staff_also_has_no_admin_sidebar_link(self):
        self.user.is_staff = True
        self.user.save()
        for url in ["/", self.url]:
            self.assertNotContains(self.client.get(url), "لوحة الإدارة")
