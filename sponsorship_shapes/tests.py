# MAKKEN PAGINATION AND DEPENDENCY TEST COMPAT v2
from unittest.mock import patch
import time

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import SponsorshipShape
from .views import TOKEN_AGE


class SponsorshipShapesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("sponsorship_shapes-test", password="test-only-password")
        self.client.force_login(self.user)
        self.url = reverse("sponsorship_shapes:index")

    def row(self, pk=None):
        pk = getattr(pk, "pk", pk)
        response = self.client.get(self.url)
        if pk is None:
            return response.context["rows"][0]

        for number in response.context["page_obj"].paginator.page_range:
            current = (
                response if number == 1
                else self.client.get(self.url, {"page": number})
            )
            for row in current.context["rows"]:
                if row["id"] == pk:
                    return row

        raise AssertionError("Test record not found on any page: " + str(pk))

    def preview(self, operation, pk=None, name="شكل رعاية جديد", active="1", description=None, employment="0"):
        if operation == "add":
            snapshot = self.client.get(self.url).context["add_snapshot"]
        else:
            snapshot = self.row(pk)[f"{operation}_snapshot"]
        if description is None:
            description = SponsorshipShape.objects.get(pk=pk).description if pk else ""
        return self.client.post(self.url, {"action": "preview", "operation": operation, "snapshot": snapshot, "name": name, "description": description, "is_employment": employment, "is_active": active})

    def confirm(self, response):
        return self.client.post(self.url, {"action": "confirm", "token": response.context["pending"]["token"]})

    def test_initial_records_and_security_headers(self):
        self.assertEqual(list(SponsorshipShape.objects.values_list("name", "description", "is_employment", "is_active")), [('رعاية مالية كاملة', 'تغطية كامل تكلفة البرنامج التدريبي من راع واحد', False, True), ('رعاية مالية جزئية', 'مساهمة الراعي بجزء من تكلفة البرنامج', False, True), ('رعاية متعددة الجهات (تحالف)', 'مشاركة أكثر من منظمة في تمويل برنامج واحد بنسب محددة', False, True), ('رعاية عينية', 'تقديم خدمات أو منتجات أو تجهيزات بدلاً من الدعم المالي', False, True), ('رعاية تدريبية', 'تحمل تكلفة التدريب أو توفير مدربين أو محتوى تدريبي', False, False), ('رعاية توظيف', 'دعم التدريب المرتبط بالتوظيف أو التدريب العملي الميداني', True, True), ('رعاية تجهيزات ومعدات', 'توفير أجهزة أو أدوات أو تجهيزات لازمة للتدريب', False, True), ('رعاية منح تدريبية', 'تمويل مقاعد تدريبية لفئات مستهدفة', False, True), ('رعاية استضافة وتنفيذ', 'توفير موقع أو منشأة لتنفيذ البرنامج', False, True), ('رعاية مشتركة (مالي + عيني)', 'دمج الدعم المالي مع دعم عيني أو خدمات', False, True)])
        response = self.client.get(self.url)
        self.assertContains(response, "إضافة شكل رعاية")
        self.assertNotContains(response, "لوحة الإدارة")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])

    def test_anonymous_get_and_post_redirect_to_login(self):
        self.client.logout()
        for method in [self.client.get, self.client.post]:
            self.assertEqual(method(self.url).status_code, 302)
        self.assertEqual(SponsorshipShape.objects.count(), 10)

    def test_add_requires_confirmation_and_cancel_does_not_write(self):
        response = self.preview("add", name="شكل رعاية مخصص", active="0")
        self.assertContains(response, "تأكيد إضافة شكل الرعاية")
        self.assertEqual(SponsorshipShape.objects.count(), 10)
        self.client.get(self.url)
        self.assertEqual(SponsorshipShape.objects.count(), 10)
        self.assertRedirects(self.confirm(response), self.url)
        self.assertFalse(SponsorshipShape.objects.get(name="شكل رعاية مخصص").is_active)
        self.assertEqual(self.confirm(response).status_code, 409)
        self.assertEqual(SponsorshipShape.objects.filter(name="شكل رعاية مخصص").count(), 1)

    def test_edit_updates_name_and_status_only_after_confirmation(self):
        item = SponsorshipShape.objects.first()
        response = self.preview("edit", item.pk, name="رعاية مالية كاملة محدث", active="0")
        item.refresh_from_db()
        self.assertEqual(item.name, "رعاية مالية كاملة")
        self.assertRedirects(self.confirm(response), self.url)
        item.refresh_from_db()
        self.assertEqual((item.name, item.is_active, item.version), ("رعاية مالية كاملة محدث", False, 2))

    def test_status_toggle_both_directions_and_cancel(self):
        item = SponsorshipShape.objects.first()
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
        item = SponsorshipShape.objects.first()
        response = self.preview("delete", item.pk)
        self.assertContains(response, "تأكيد حذف شكل الرعاية")
        self.assertTrue(SponsorshipShape.objects.filter(pk=item.pk).exists())
        self.client.get(self.url, {"action": "delete", "id": item.pk})
        self.assertTrue(SponsorshipShape.objects.filter(pk=item.pk).exists())
        self.assertRedirects(self.confirm(response), self.url)
        self.assertFalse(SponsorshipShape.objects.filter(pk=item.pk).exists())
        self.assertEqual(self.confirm(response).status_code, 409)

    def test_duplicate_names_and_normalization(self):
        for name in ["رعاية مالية كاملة", "  رعاية مالية كاملة   "]:
            response = self.preview("add", name=name)
            self.assertEqual(response.status_code, 400)
            self.assertContains(response, "يوجد شكل رعاية بهذا الاسم", status_code=400)
        response = self.preview("add", name="  Test   SponsorshipShape  ")
        self.assertRedirects(self.confirm(response), self.url)
        self.assertEqual(SponsorshipShape.objects.get(name_key="test sponsorshipshape").name, "Test SponsorshipShape")
        self.assertEqual(self.preview("add", name="test sponsorshipshape").status_code, 400)
        item = SponsorshipShape.objects.first()
        self.assertEqual(self.preview("edit", item.pk, name="رعاية مالية جزئية").status_code, 400)

    def test_invalid_names_status_and_actions(self):
        for name in ["", "   ", "a" * 201, "<script>alert(1)</script>", "bad\x00name", "bad\u202ename", "＜script＞"]:
            self.assertEqual(self.preview("add", name=name).status_code, 400, repr(name))
        self.assertEqual(self.preview("add", active="unexpected").status_code, 400)
        self.assertEqual(self.client.post(self.url, {"action": "delete"}).status_code, 400)
        self.assertEqual(SponsorshipShape.objects.count(), 10)

    def test_no_changes_and_edit_fallback(self):
        item = SponsorshipShape.objects.first()
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
        other = get_user_model().objects.create_user("another-sponsorship-shape-test")
        self.client.force_login(other)
        self.assertEqual(self.client.post(self.url, {"action": "confirm", "token": token}).status_code, 400)
        self.assertEqual(SponsorshipShape.objects.count(), 10)

    def test_stale_edit_toggle_delete_and_snapshot(self):
        item = SponsorshipShape.objects.first()
        stale_snapshot = self.row(item.pk)["edit_snapshot"]
        pending = [self.preview(operation, item.pk, name="شكل رعاية محدث") for operation in ["edit", "toggle", "delete"]]
        item.version += 1
        item.save()
        for response in pending:
            self.assertEqual(self.confirm(response).status_code, 409)
        self.assertEqual(self.client.post(self.url, {"action": "preview", "operation": "edit", "snapshot": stale_snapshot, "name": "other", "is_active": "1"}).status_code, 409)
        item.refresh_from_db()
        self.assertEqual(item.name, "رعاية مالية كاملة")
        self.assertTrue(item.is_active)

    def test_csrf_for_preview_and_confirm(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        page = client.get(self.url)
        snapshot = page.context["add_snapshot"]
        data = {"action": "preview", "operation": "add", "snapshot": snapshot, "name": "CSRF test", "is_employment": "0", "is_active": "1"}
        self.assertEqual(client.post(self.url, data).status_code, 403)
        csrf = client.cookies["csrftoken"].value
        response = client.post(self.url, {**data, "csrfmiddlewaretoken": csrf})
        data = {"action": "confirm", "token": response.context["pending"]["token"]}
        self.assertEqual(client.post(self.url, data).status_code, 403)
        self.assertEqual(client.post(self.url, {**data, "csrfmiddlewaretoken": csrf}).status_code, 302)

    def test_pagination_empty_state_and_escaping(self):
        from django.utils.html import escape
        from uuid import uuid4
        label = "فحص الصفحات " + uuid4().hex[:10]
        for index in range(37):
            SponsorshipShape.objects.create(name=label + " " + str(index))

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        page = response.context["page_obj"]
        size = page.paginator.per_page
        self.assertGreater(size, 0)
        self.assertEqual(page.paginator.count, SponsorshipShape.objects.count())
        self.assertEqual(
            len(response.context["rows"]),
            min(size, page.paginator.count),
        )

        seen = []
        for number in page.paginator.page_range:
            result = self.client.get(self.url, {"page": number})
            self.assertEqual(result.status_code, 200)
            rows = result.context["rows"]
            self.assertEqual(
                len(rows),
                min(size, page.paginator.count - (number - 1) * size),
            )
            seen.extend(row["id"] for row in rows)

        self.assertEqual(len(seen), len(set(seen)))
        self.assertEqual(
            set(seen),
            set(SponsorshipShape.objects.values_list("pk", flat=True)),
        )

        item = SponsorshipShape.objects.create(name=label + " unsafe")
        unsafe = "<img src=x onerror=alert(1)>"
        SponsorshipShape.objects.filter(pk=item.pk).update(name=unsafe)
        result = self.client.get(self.url, {"q": "onerror=alert"})
        self.assertContains(result, str(escape(unsafe)))
        self.assertNotContains(result, unsafe)

        empty = self.client.get(self.url, {"q": uuid4().hex})
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.context["page_obj"].paginator.count, 0)
        self.assertEqual(len(empty.context["rows"]), 0)

    def test_sidebar_preserves_care_states_and_hides_admin(self):
        self.user.is_staff = True
        self.user.save()
        for url in ["/", reverse("care_states:index"), reverse("levels:index"), reverse("regions:index"), reverse("entities:index"), reverse("specializations:index"), reverse("sectors:index"), reverse("training_programs:index"), self.url]:
            response = self.client.get(url)
            self.assertContains(response, 'href="/settings/sponsorship-shapes/"')
            self.assertContains(response, 'href="/settings/development-states/"')
            self.assertNotContains(response, "لوحة الإدارة")

    def test_description_and_employment_saved_only_after_confirmation(self):
        response = self.preview("add", name="رعاية مخصصة", description="وصف الرعاية\nتفاصيل إضافية", employment="1", active="0")
        self.assertContains(response, "وصف الرعاية")
        self.assertFalse(SponsorshipShape.objects.filter(name="رعاية مخصصة").exists())
        self.assertEqual(self.confirm(response).status_code, 302)
        item = SponsorshipShape.objects.get(name="رعاية مخصصة")
        self.assertEqual((item.description, item.is_employment, item.is_active), ("وصف الرعاية\nتفاصيل إضافية", True, False))
        response = self.preview("edit", item.pk, name=item.name, description="وصف محدث", employment="0", active="1")
        self.assertContains(response, "تفاصيل إضافية")
        item.refresh_from_db()
        self.assertTrue(item.is_employment)
        self.assertEqual(self.confirm(response).status_code, 302)
        item.refresh_from_db()
        self.assertEqual((item.description, item.is_employment, item.is_active), ("وصف محدث", False, True))

    def test_description_optional_and_clearable(self):
        response = self.preview("add", name="بدون وصف", description="")
        self.assertContains(response, "بدون وصف")
        self.assertEqual(self.confirm(response).status_code, 302)
        self.assertEqual(SponsorshipShape.objects.get(name="بدون وصف").description, "")
        item = SponsorshipShape.objects.first()
        self.assertEqual(self.confirm(self.preview("edit", item.pk, name=item.name, description="")).status_code, 302)
        item.refresh_from_db()
        self.assertEqual(item.description, "")

    def test_description_length_and_long_unicode_confirmation(self):
        description = "".join(chr(0x4E00 + i) for i in range(2000))
        response = self.preview("add", name="وصف طويل", description=description)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.confirm(response).status_code, 302)
        self.assertEqual(SponsorshipShape.objects.get(name="وصف طويل").description, description)
        self.assertEqual(self.preview("add", description=description + "أ").status_code, 400)

    def test_description_validation_and_newline_normalization(self):
        for value in ["<script>x</script>", "＜script＞", "bad\x00text", "bad\u202etext"]:
            self.assertEqual(self.preview("add", description=value).status_code, 400)
        response = self.preview("add", name="فقرات", description="  سطر أول\r\nسطر ثان\tتفاصيل  ")
        self.assertEqual(self.confirm(response).status_code, 302)
        self.assertEqual(SponsorshipShape.objects.get(name="فقرات").description, "سطر أول\nسطر ثان\tتفاصيل")

    def test_employment_and_status_are_independent(self):
        item = SponsorshipShape.objects.get(name="رعاية توظيف")
        self.assertTrue(item.is_employment)
        self.assertEqual(self.confirm(self.preview("toggle", item.pk)).status_code, 302)
        item.refresh_from_db()
        self.assertTrue(item.is_employment)
        self.assertFalse(item.is_active)
        self.assertEqual(self.confirm(self.preview("edit", item.pk, name=item.name, employment="0", active="0")).status_code, 302)
        item.refresh_from_db()
        self.assertFalse(item.is_employment)
        self.assertFalse(item.is_active)

    def test_required_single_yes_no_and_status(self):
        for employment in ["", "unexpected", ["1", "0"], ["0", "1"]]:
            self.assertEqual(self.preview("add", employment=employment).status_code, 400)
        self.assertEqual(self.preview("add", active=["1", "0"]).status_code, 400)
        response = self.client.get(self.url, {"edit": "new"})
        self.assertEqual(response.context["editor_form"].fields["is_employment"].widget.input_type, "radio")
        self.assertFalse(response.context["editor_form"].fields["description"].required)
        self.assertEqual(SponsorshipShape.objects.count(), 10)

    def test_five_table_columns_and_description_escaping(self):
        from html.parser import HTMLParser
        item = SponsorshipShape.objects.first()
        item.description = '<script>alert("x")</script>'
        item.save()
        class Cells(HTMLParser):
            def __init__(self):
                super().__init__(); self.row = False; self.count = 0
            def handle_starttag(self, tag, attrs):
                if tag == "tr": self.row = dict(attrs).get("data-sponsorship-shape-row") == str(item.pk)
                if self.row and tag in {"th", "td"}: self.count += 1
            def handle_endtag(self, tag):
                if tag == "tr": self.row = False
        response = self.client.get(self.url)
        parser = Cells(); parser.feed(response.content.decode())
        self.assertEqual(parser.count, 5)
        self.assertNotContains(response, '<script>alert("x")</script>')
        self.assertContains(response, "&lt;script&gt;")
