from unittest.mock import patch
import time

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import ExpenseItem
from .views import TOKEN_AGE


class ExpenseItemsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("expense_items-test", password="test-only-password")
        self.client.force_login(self.user)
        self.url = reverse("expense_items:index")

    def row(self, pk=None):
        rows = self.client.get(self.url).context["rows"]
        return next(row for row in rows if row["id"] == pk) if pk else rows[0]

    def preview(self, operation, pk=None, name="بند صرف جديد", active="1"):
        if operation == "add":
            snapshot = self.client.get(self.url).context["add_snapshot"]
        else:
            snapshot = self.row(pk)[f"{operation}_snapshot"]
        return self.client.post(self.url, {"action": "preview", "operation": operation, "snapshot": snapshot, "name": name, "is_active": active})

    def confirm(self, response):
        return self.client.post(self.url, {"action": "confirm", "token": response.context["pending"]["token"]})

    def test_initial_records_and_security_headers(self):
        self.assertEqual(list(ExpenseItem.objects.values_list("name", "is_active")), [('مواد لوجستية', True), ('مصروف جيب', True), ('سيولة نقدية', True), ('مصروف جيب نقدي', True), ('تكاليف التشغيل والإدارة', True), ('أجور ورواتب العاملين التدريب والتطوير', True), ('شراء المعدات والأجهزة', True), ('المواد والمستلزمات التشغيلية', True), ('الصيانة والإصلاحات', True), ('الإيجارات والخدمات (كهرباء، ماء، إنترنت)', True)])
        response = self.client.get(self.url)
        self.assertContains(response, "إضافة بند صرف")
        self.assertNotContains(response, "لوحة الإدارة")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])

    def test_anonymous_get_and_post_redirect_to_login(self):
        self.client.logout()
        for method in [self.client.get, self.client.post]:
            self.assertEqual(method(self.url).status_code, 302)
        self.assertEqual(ExpenseItem.objects.count(), 10)

    def test_add_requires_confirmation_and_cancel_does_not_write(self):
        response = self.preview("add", name="بند صرف مخصص", active="0")
        self.assertContains(response, "تأكيد إضافة بند الصرف")
        self.assertEqual(ExpenseItem.objects.count(), 10)
        self.client.get(self.url)
        self.assertEqual(ExpenseItem.objects.count(), 10)
        self.assertRedirects(self.confirm(response), self.url)
        self.assertFalse(ExpenseItem.objects.get(name="بند صرف مخصص").is_active)
        self.assertEqual(self.confirm(response).status_code, 409)
        self.assertEqual(ExpenseItem.objects.filter(name="بند صرف مخصص").count(), 1)

    def test_edit_updates_name_and_status_only_after_confirmation(self):
        item = ExpenseItem.objects.first()
        response = self.preview("edit", item.pk, name="مواد لوجستية محدث", active="0")
        item.refresh_from_db()
        self.assertEqual(item.name, "مواد لوجستية")
        self.assertRedirects(self.confirm(response), self.url)
        item.refresh_from_db()
        self.assertEqual((item.name, item.is_active, item.version), ("مواد لوجستية محدث", False, 2))

    def test_status_toggle_both_directions_and_cancel(self):
        item = ExpenseItem.objects.first()
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
        item = ExpenseItem.objects.first()
        response = self.preview("delete", item.pk)
        self.assertContains(response, "تأكيد حذف بند الصرف")
        self.assertTrue(ExpenseItem.objects.filter(pk=item.pk).exists())
        self.client.get(self.url, {"action": "delete", "id": item.pk})
        self.assertTrue(ExpenseItem.objects.filter(pk=item.pk).exists())
        self.assertRedirects(self.confirm(response), self.url)
        self.assertFalse(ExpenseItem.objects.filter(pk=item.pk).exists())
        self.assertEqual(self.confirm(response).status_code, 409)

    def test_duplicate_names_and_normalization(self):
        for name in ["مواد لوجستية", "  مواد لوجستية   "]:
            response = self.preview("add", name=name)
            self.assertEqual(response.status_code, 400)
            self.assertContains(response, "يوجد بند صرف بهذا الاسم", status_code=400)
        response = self.preview("add", name="  Test   ExpenseItem  ")
        self.assertRedirects(self.confirm(response), self.url)
        self.assertEqual(ExpenseItem.objects.get(name_key="test expenseitem").name, "Test ExpenseItem")
        self.assertEqual(self.preview("add", name="test expenseitem").status_code, 400)
        item = ExpenseItem.objects.first()
        self.assertEqual(self.preview("edit", item.pk, name="مصروف جيب").status_code, 400)

    def test_invalid_names_status_and_actions(self):
        for name in ["", "   ", "a" * 201, "<script>alert(1)</script>", "bad\x00name", "bad\u202ename", "＜script＞"]:
            self.assertEqual(self.preview("add", name=name).status_code, 400, repr(name))
        self.assertEqual(self.preview("add", active="unexpected").status_code, 400)
        self.assertEqual(self.client.post(self.url, {"action": "delete"}).status_code, 400)
        self.assertEqual(ExpenseItem.objects.count(), 10)

    def test_no_changes_and_edit_fallback(self):
        item = ExpenseItem.objects.first()
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
        other = get_user_model().objects.create_user("another-expense-item-test")
        self.client.force_login(other)
        self.assertEqual(self.client.post(self.url, {"action": "confirm", "token": token}).status_code, 400)
        self.assertEqual(ExpenseItem.objects.count(), 10)

    def test_stale_edit_toggle_delete_and_snapshot(self):
        item = ExpenseItem.objects.first()
        stale_snapshot = self.row(item.pk)["edit_snapshot"]
        pending = [self.preview(operation, item.pk, name="بند صرف محدث") for operation in ["edit", "toggle", "delete"]]
        item.version += 1
        item.save()
        for response in pending:
            self.assertEqual(self.confirm(response).status_code, 409)
        self.assertEqual(self.client.post(self.url, {"action": "preview", "operation": "edit", "snapshot": stale_snapshot, "name": "other", "is_active": "1"}).status_code, 409)
        item.refresh_from_db()
        self.assertEqual(item.name, "مواد لوجستية")
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
        ExpenseItem.objects.all().delete()
        self.assertContains(self.client.get(self.url), "لا توجد بنود صرف بعد")
        for i in range(16):
            ExpenseItem.objects.create(name=f"ExpenseItem {i}")
        self.assertEqual(len(self.client.get(self.url).context["rows"]), 15)
        self.assertEqual(len(self.client.get(self.url, {"page": "2"}).context["rows"]), 1)
        ExpenseItem.objects.all().delete()
        ExpenseItem.objects.create(name='<script>alert("x")</script>')
        response = self.client.get(self.url)
        self.assertNotContains(response, '<script>alert("x")</script>')
        self.assertContains(response, "&lt;script&gt;")

    def test_sidebar_preserves_care_states_and_hides_admin(self):
        self.user.is_staff = True
        self.user.save()
        for url in ["/", reverse("care_states:index"), reverse("levels:index"), reverse("regions:index"), reverse("entities:index"), reverse("specializations:index"), reverse("sectors:index"), self.url]:
            response = self.client.get(url)
            self.assertContains(response, 'href="/settings/expense-items/"')
            self.assertContains(response, 'href="/settings/development-states/"')
            self.assertNotContains(response, "لوحة الإدارة")
