# MAKKEN RBAC BUSINESS FIXTURES v1
# MAKKEN RBAC INTEGRATION v1
from unittest.mock import patch
import time

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import Region
from .views import TOKEN_AGE


class RegionsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("regions-test", password="test-only-password", is_superuser=True)
        self.client.force_login(self.user)
        self.url = reverse("regions:index")

    def row(self, pk=None):
        rows = self.client.get(self.url).context["rows"]
        return next(row for row in rows if row["id"] == pk) if pk else rows[0]

    def preview(self, operation, pk=None, name="منطقة جديدة", active="1"):
        if operation == "add":
            snapshot = self.client.get(self.url).context["add_snapshot"]
        else:
            snapshot = self.row(pk)[f"{operation}_snapshot"]
        return self.client.post(self.url, {"action": "preview", "operation": operation, "snapshot": snapshot, "name": name, "is_active": active})

    def confirm(self, response):
        return self.client.post(self.url, {"action": "confirm", "token": response.context["pending"]["token"]})

    def test_initial_records_and_security_headers(self):
        self.assertEqual(list(Region.objects.values_list("name", flat=True)), ['منطقة الرياض', 'منطقة مكة المكرمة', 'منطقة المدينة المنورة', 'منطقة القصيم', 'المنطقة الشرقية', 'منطقة عسير', 'منطقة تبوك', 'منطقة حائل', 'منطقة الحدود الشمالية', 'منطقة جازان', 'منطقة نجران', 'منطقة الباحة', 'منطقة الجوف'])
        self.assertEqual(Region.objects.filter(is_active=True).count(), 13)
        response = self.client.get(self.url)
        self.assertContains(response, "إضافة منطقة")
        self.assertNotContains(response, "لوحة الإدارة")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])

    def test_anonymous_get_and_post_redirect_to_login(self):
        self.client.logout()
        for method in [self.client.get, self.client.post]:
            self.assertEqual(method(self.url).status_code, 302)
        self.assertEqual(Region.objects.count(), 13)

    def test_add_requires_confirmation_and_cancel_does_not_write(self):
        response = self.preview("add", name="منطقة مخصصة", active="0")
        self.assertContains(response, "تأكيد إضافة المنطقة")
        self.assertEqual(Region.objects.count(), 13)
        self.client.get(self.url)
        self.assertEqual(Region.objects.count(), 13)
        self.assertRedirects(self.confirm(response), self.url)
        self.assertFalse(Region.objects.get(name="منطقة مخصصة").is_active)
        self.assertEqual(self.confirm(response).status_code, 409)
        self.assertEqual(Region.objects.filter(name="منطقة مخصصة").count(), 1)

    def test_edit_updates_name_and_status_only_after_confirmation(self):
        item = Region.objects.first()
        response = self.preview("edit", item.pk, name="منطقة الرياض محدث", active="0")
        item.refresh_from_db()
        self.assertEqual(item.name, "منطقة الرياض")
        self.assertRedirects(self.confirm(response), self.url)
        item.refresh_from_db()
        self.assertEqual((item.name, item.is_active, item.version), ("منطقة الرياض محدث", False, 2))

    def test_status_toggle_both_directions_and_cancel(self):
        item = Region.objects.first()
        response = self.preview("toggle", item.pk)
        item.refresh_from_db()
        self.assertTrue(item.is_active)
        self.assertRedirects(self.confirm(response), self.url)
        item.refresh_from_db()
        self.assertFalse(item.is_active)
        self.assertRedirects(self.confirm(self.preview("toggle", item.pk)), self.url)
        item.refresh_from_db()
        self.assertTrue(item.is_active)

    def test_delete_requires_confirmation_get_does_not_mutate(self):
        item = Region.objects.first()
        response = self.preview("delete", item.pk)
        self.assertContains(response, "تأكيد حذف المنطقة")
        self.assertTrue(Region.objects.filter(pk=item.pk).exists())
        self.client.get(self.url, {"action": "delete", "id": item.pk})
        self.assertTrue(Region.objects.filter(pk=item.pk).exists())
        self.assertRedirects(self.confirm(response), self.url)
        self.assertFalse(Region.objects.filter(pk=item.pk).exists())
        self.assertEqual(self.confirm(response).status_code, 409)

    def test_duplicate_names_and_normalization(self):
        for name in ["منطقة الرياض", "  منطقة الرياض   ", "الرياض", "الشرقية", "منطقة الشرقية", "المنطقة الشرقية"]:
            response = self.preview("add", name=name)
            self.assertEqual(response.status_code, 400)
            self.assertContains(response, "توجد منطقة بهذا الاسم", status_code=400)
        response = self.preview("add", name="  Test   Region  ")
        self.assertRedirects(self.confirm(response), self.url)
        self.assertEqual(Region.objects.get(name_key="test region").name, "Test Region")
        self.assertEqual(self.preview("add", name="test region").status_code, 400)
        item = Region.objects.first()
        self.assertEqual(self.preview("edit", item.pk, name="منطقة مكة المكرمة").status_code, 400)

    def test_invalid_names_status_and_actions(self):
        for name in ["", "   ", "منطقة", "المنطقة", "a" * 101, "<script>alert(1)</script>", "bad\x00name", "bad\u202ename", "＜script＞"]:
            self.assertEqual(self.preview("add", name=name).status_code, 400, repr(name))
        self.assertEqual(self.preview("add", active="unexpected").status_code, 400)
        self.assertEqual(self.client.post(self.url, {"action": "delete"}).status_code, 400)
        self.assertEqual(Region.objects.count(), 13)

    def test_no_changes_and_edit_fallback(self):
        item = Region.objects.first()
        response = self.preview("edit", item.pk, name=item.name)
        self.assertIn("notice", response.context)
        self.assertNotIn("pending", response.context)
        response = self.client.get(self.url, {"edit": item.pk})
        self.assertTrue(response.context["editing"])
        self.assertEqual(response.context["editor_form"].initial["name"], item.name)
        self.assertTrue(self.client.get(self.url, {"edit": "new"}).context["editing"])
        for missing in ["9999999999999999999999999", "not-an-id", "0"]:
            self.assertEqual(self.client.get(self.url, {"edit": missing}).status_code, 404)

    def test_signed_token_tampering_user_binding_and_expiration(self):
        response = self.preview("add")
        token = response.context["pending"]["token"]
        self.assertEqual(self.client.post(self.url, {"action": "confirm", "token": token + "tampered"}).status_code, 400)
        with patch("django.core.signing.time.time", return_value=time.time() + TOKEN_AGE + 10):
            self.assertEqual(self.client.post(self.url, {"action": "confirm", "token": token}).status_code, 400)
        other = get_user_model().objects.create_user("another-region-test", is_superuser=True)
        self.client.force_login(other)
        self.assertEqual(self.client.post(self.url, {"action": "confirm", "token": token}).status_code, 400)
        self.assertEqual(Region.objects.count(), 13)

    def test_stale_edit_toggle_delete_and_snapshot(self):
        item = Region.objects.first()
        stale_snapshot = self.row(item.pk)["edit_snapshot"]
        pending = [self.preview(operation, item.pk, name="منطقة محدثة") for operation in ["edit", "toggle", "delete"]]
        item.version += 1
        item.save()
        for response in pending:
            self.assertEqual(self.confirm(response).status_code, 409)
        self.assertEqual(self.client.post(self.url, {"action": "preview", "operation": "edit", "snapshot": stale_snapshot, "name": "other", "is_active": "1"}).status_code, 409)
        item.refresh_from_db()
        self.assertEqual(item.name, "منطقة الرياض")
        self.assertTrue(item.is_active)

    def test_csrf_for_preview_and_confirm(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        page = client.get(self.url)
        snapshot = page.context["add_snapshot"]
        data = {"action": "preview", "operation": "add", "snapshot": snapshot, "name": "CSRF test", "is_active": "1"}
        self.assertEqual(client.post(self.url, data).status_code, 403)
        csrf = client.cookies["csrftoken"].value
        response = client.post(self.url, {**data, "csrfmiddlewaretoken": csrf})
        data = {"action": "confirm", "token": response.context["pending"]["token"]}
        self.assertEqual(client.post(self.url, data).status_code, 403)
        self.assertEqual(client.post(self.url, {**data, "csrfmiddlewaretoken": csrf}).status_code, 302)

    def test_pagination_empty_state_and_escaping(self):
        Region.objects.all().delete()
        self.assertContains(self.client.get(self.url), "لا توجد مناطق بعد")
        # MAKKEN pagination fixture follows configured page size
        per_page = self.client.get(self.url).context["page_obj"].paginator.per_page
        self.assertGreater(per_page, 0)
        for i in range(per_page + 1):
            Region.objects.create(name=f"Region {i}")
        first = self.client.get(self.url)
        second = self.client.get(self.url, {"page": "2"})
        self.assertEqual(len(first.context["rows"]), per_page)
        self.assertEqual(len(second.context["rows"]), 1)
        self.assertEqual(first.context["page_obj"].paginator.num_pages, 2)
        self.assertEqual(second.context["page_obj"].number, 2)
        ids = [row["id"] for row in first.context["rows"] + second.context["rows"]]
        self.assertEqual(len(set(ids)), per_page + 1)
        self.assertSetEqual(set(ids), set(Region.objects.values_list("id", flat=True)))
        Region.objects.all().delete()
        Region.objects.create(name='<script>alert("x")</script>')
        response = self.client.get(self.url)
        self.assertNotContains(response, '<script>alert("x")</script>')
        self.assertContains(response, "&lt;script&gt;")


    def test_sidebar_preserves_care_states_and_hides_admin(self):
        self.user.is_staff = True
        self.user.save()
        for url in ["/", reverse("care_states:index"), reverse("levels:index"), self.url]:
            response = self.client.get(url)
            self.assertContains(response, 'href="/settings/regions/"')
            self.assertContains(response, 'href="/settings/development-states/"')
            self.assertNotContains(response, "لوحة الإدارة")
