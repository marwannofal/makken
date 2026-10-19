# MAKKEN DEPENDENCY TEST POLICY v1
import time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from specializations.models import Specialization
from .models import Sector
from .views import TOKEN_AGE


class SectorsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("sectors-test", password="test-password-only")
        self.client.force_login(self.user)
        self.url = reverse("sectors:index")
        self.specializations = list(Specialization.objects.all())
        self.ids = [s.pk for s in self.specializations]

    def row(self, pk):
        return next(r for r in self.client.get(self.url).context["rows"] if r["id"] == pk)

    def preview(self, operation="add", item=None, name="قطاع تجريبي", selected=None, active="1"):
        snapshot = self.client.get(self.url).context["add_snapshot"] if operation == "add" else self.row(item.pk)[f"{operation}_snapshot"]
        return self.client.post(self.url, {"action": "preview", "operation": operation, "snapshot": snapshot,
                                          "name": name, "specializations": selected if selected is not None else self.ids[:2], "is_active": active})

    def confirm(self, response):
        return self.client.post(self.url, {"action": "confirm", "token": response.context["pending"]["token"]})

    def create(self, **kwargs):
        response = self.preview(**kwargs)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.confirm(response).status_code, 302)
        return Sector.objects.latest("pk")

    def choices(self, item=None):
        response = self.client.get(self.url, {"edit": item.pk if item else "new"})
        return set(response.context["editor_form"].fields["specializations"].queryset.values_list("pk", flat=True))

    def test_initial_empty_state_security_headers_and_sidebar(self):
        response = self.client.get(self.url)
        self.assertContains(response, "لا توجد قطاعات بعد")
        self.assertContains(response, 'href="/settings/sectors/"')
        self.assertNotContains(response, "لوحة الإدارة")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
        self.assertEqual(self.choices(), set(self.ids))

    def test_login_required_get_and_post(self):
        self.client.logout()
        for method in [self.client.get, self.client.post]:
            self.assertEqual(method(self.url).status_code, 302)
        self.assertEqual(Sector.objects.count(), 0)

    def test_add_multi_selection_requires_confirmation_cancel_does_not_write(self):
        response = self.preview(active="0")
        self.assertContains(response, "تأكيد إضافة القطاع")
        self.assertEqual(Sector.objects.count(), 0)
        self.client.get(self.url)
        self.assertTrue(all(s.sector_id is None for s in Specialization.objects.all()))
        self.assertEqual(self.confirm(response).status_code, 302)
        item = Sector.objects.get()
        self.assertFalse(item.is_active)
        self.assertEqual(set(item.specializations.values_list("pk", flat=True)), set(self.ids[:2]))
        self.assertEqual(self.confirm(response).status_code, 409)
        self.assertEqual(Sector.objects.count(), 1)

    def test_assignment_excluded_from_new_and_other_sector_edit_but_kept_in_own_edit(self):
        one = self.create(name="قطاع أول", selected=self.ids[:2])
        two = self.create(name="قطاع ثان", selected=self.ids[2:4])
        self.assertEqual(self.choices(), set(self.ids[4:]))
        self.assertEqual(self.choices(one), set(self.ids[:2] + self.ids[4:]))
        self.assertEqual(self.choices(two), set(self.ids[2:]))
        form = self.client.get(self.url, {"edit": one.pk}).context["editor_form"]
        self.assertEqual(set(form.initial["specializations"]), set(self.ids[:2]))

    def test_forged_assigned_choices_rejected_on_add_and_edit(self):
        one = self.create(selected=self.ids[:1])
        two = self.create(name="قطاع ثان", selected=self.ids[1:2])
        self.assertEqual(self.preview(name="قطاع متعارض", selected=self.ids[:1]).status_code, 400)
        self.assertEqual(self.preview("edit", two, selected=self.ids[:2]).status_code, 400)
        self.assertEqual(Specialization.objects.get(pk=self.ids[0]).sector_id, one.pk)
        self.assertEqual(Specialization.objects.get(pk=self.ids[1]).sector_id, two.pk)

    def test_two_pending_sectors_cannot_claim_same_specialization(self):
        first = self.preview(name="قطاع أول", selected=self.ids[:2])
        second = self.preview(name="قطاع ثان", selected=self.ids[1:3])
        self.assertEqual(self.confirm(first).status_code, 302)
        self.assertEqual(self.confirm(second).status_code, 409)
        self.assertEqual(Sector.objects.count(), 1)
        self.assertIsNone(Specialization.objects.get(pk=self.ids[2]).sector_id)

    def test_conflicting_edit_rolls_back_name_status_and_assignments(self):
        one = self.create(name="قطاع أول", selected=self.ids[:1])
        pending = self.preview("edit", one, name="اسم غير محفوظ", active="1", selected=self.ids[:2])
        self.create(name="قطاع ثان", selected=self.ids[1:2])
        self.assertEqual(self.confirm(pending).status_code, 409)
        one.refresh_from_db()
        self.assertEqual((one.name, one.is_active), ("قطاع أول", True))
        self.assertEqual(set(one.specializations.values_list("pk", flat=True)), set(self.ids[:1]))

    def test_edit_renames_and_releases_removed_choices_while_active(self):
        one = self.create()
        response = self.preview("edit", one, name="قطاع محدث", selected=self.ids[1:3], active="1")
        self.assertContains(response, self.specializations[0].name)
        self.assertEqual(self.confirm(response).status_code, 302)
        one.refresh_from_db()
        self.assertEqual((one.name, one.is_active, one.version), ("قطاع محدث", True, 2))
        self.assertEqual(set(one.specializations.values_list("pk", flat=True)), set(self.ids[1:3]))
        self.assertIn(self.ids[0], self.choices())
        self.assertNotIn(self.ids[1], self.choices())

    def test_linked_sector_cannot_be_deactivated(self):
        one = self.create()
        response = self.preview("toggle", one)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "التخصصات", status_code=409)
        one.refresh_from_db()
        self.assertTrue(one.is_active)
        self.assertNotIn(self.ids[0], self.choices())
        self.assertEqual(set(one.specializations.values_list("pk", flat=True)), set(self.ids[:2]))

    def test_linked_sector_delete_is_blocked_without_detaching_specializations(self):
        one = self.create()
        response = self.preview("delete", one)
        self.assertEqual(response.status_code, 409)
        self.assertContains(response, "التخصصات", status_code=409)
        self.assertIsNone(response.context.get("pending"))
        self.assertTrue(Sector.objects.filter(pk=one.pk).exists())
        self.assertEqual(set(one.specializations.values_list("pk", flat=True)), set(self.ids[:2]))
        self.assertEqual(Specialization.objects.count(), len(self.ids))

    def test_direct_sector_delete_is_also_blocked(self):
        from core.dependencies import DependencyBlocked
        from django.db import transaction
        one = self.create()
        with self.assertRaises(DependencyBlocked), transaction.atomic():
            one.delete()
        self.assertEqual(set(one.specializations.values_list("pk", flat=True)), set(self.ids[:2]))

    def test_inactive_specializations_labelled_and_assignable(self):
        inactive = Specialization.objects.get(is_active=False)
        response = self.client.get(self.url, {"edit": "new"})
        self.assertContains(response, inactive.name + " (غير نشط)")
        one = self.create(selected=[inactive.pk])
        self.assertEqual(inactive.pk, one.specializations.get().pk)

    def test_required_fields_and_invalid_ids(self):
        for selected in [[], ["not-an-id"], [999999], [self.ids[0], 999999]]:
            self.assertEqual(self.preview(selected=selected).status_code, 400)
        self.assertEqual(self.preview(active="unknown").status_code, 400)
        for name in ["", "  ", "a" * 201, "<script>x</script>", "bad\x00name", "bad\u202ename", "＜script＞"]:
            self.assertEqual(self.preview(name=name).status_code, 400)
        self.assertEqual(Sector.objects.count(), 0)
        self.assertEqual(self.client.post(self.url, {"action": "delete"}).status_code, 400)

    def test_duplicate_name_normalization_and_no_changes(self):
        one = self.create(name="  Test   Sector  ")
        self.assertEqual(one.name, "Test Sector")
        self.assertEqual(self.preview(name="test sector", selected=self.ids[2:3]).status_code, 400)
        response = self.preview("edit", one, name="Test Sector")
        self.assertIn("notice", response.context)
        self.assertNotIn("pending", response.context)

    def test_stale_sector_snapshots_and_confirmations(self):
        one = self.create()
        snapshot = self.row(one.pk)["edit_snapshot"]
        pending = [self.preview(operation, one, name="قطاع محدث") for operation in ["edit"]]
        one.version += 1
        one.save()
        for response in pending:
            self.assertEqual(self.confirm(response).status_code, 409)
        self.assertEqual(self.client.post(self.url, {"action": "preview", "operation": "edit", "snapshot": snapshot,
                                                    "name": "اسم", "specializations": self.ids[:1], "is_active": "1"}).status_code, 409)

    def test_child_delete_or_edit_invalidates_pending_sector_confirmation(self):
        one = self.create()
        for mutate in ["edit", "delete"]:
            response = self.preview("edit", one, name="اسم جديد")
            child = one.specializations.first()
            if mutate == "edit":
                child.version += 1
                child.name = "تخصص محدث"
                child.save()
            else:
                child.delete()
            self.assertEqual(self.confirm(response).status_code, 409)

    def test_newly_selected_specialization_rename_or_delete_invalidates_confirmation(self):
        for mutate, pk in zip(["rename", "delete"], self.ids):
            response = self.preview(name="قطاع " + mutate, selected=[pk])
            child = Specialization.objects.get(pk=pk)
            if mutate == "rename":
                child.name = "اسم تخصص جديد"
                child.version += 1
                child.save()
            else:
                child.delete()
            self.assertEqual(self.confirm(response).status_code, 409)
        self.assertEqual(Sector.objects.count(), 0)

    def test_assignment_invalidates_pending_specialization_edit(self):
        url = reverse("specializations:index")
        row = self.client.get(url).context["rows"][0]
        pending = self.client.post(url, {"action": "preview", "operation": "edit", "snapshot": row["edit_snapshot"],
                                         "name": "تخصص محدث", "is_active": "1"})
        self.create(selected=[row["id"]])
        response = self.client.post(url, {"action": "confirm", "token": pending.context["pending"]["token"]})
        self.assertEqual(response.status_code, 409)

    def test_token_tamper_expiry_cross_user_and_operation_change(self):
        response = self.preview()
        token = response.context["pending"]["token"]
        self.assertEqual(self.client.post(self.url, {"action": "confirm", "token": token + "changed"}).status_code, 400)
        with patch("django.core.signing.time.time", return_value=time.time() + TOKEN_AGE + 10):
            self.assertEqual(self.client.post(self.url, {"action": "confirm", "token": token}).status_code, 400)
        snapshot = self.client.get(self.url).context["add_snapshot"]
        self.assertEqual(self.client.post(self.url, {"action": "preview", "operation": "edit", "snapshot": snapshot}).status_code, 400)
        other = get_user_model().objects.create_user("other-sector-user")
        self.client.force_login(other)
        self.assertEqual(self.client.post(self.url, {"action": "confirm", "token": token}).status_code, 400)
        self.assertEqual(Sector.objects.count(), 0)

    def test_csrf_preview_and_confirmation(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        page = client.get(self.url)
        data = {"action": "preview", "operation": "add", "snapshot": page.context["add_snapshot"], "name": "قطاع آمن",
                "specializations": self.ids[:1], "is_active": "1"}
        self.assertEqual(client.post(self.url, data).status_code, 403)
        csrf = client.cookies["csrftoken"].value
        response = client.post(self.url, {**data, "csrfmiddlewaretoken": csrf})
        data = {"action": "confirm", "token": response.context["pending"]["token"]}
        self.assertEqual(client.post(self.url, data).status_code, 403)
        self.assertEqual(client.post(self.url, {**data, "csrfmiddlewaretoken": csrf}).status_code, 302)

    def test_pagination_missing_editor_and_html_escaping(self):
        # MAKKEN pagination fixture follows configured page size
        per_page = self.client.get(self.url).context["page_obj"].paginator.per_page
        self.assertGreater(per_page, 0)
        for i in range(per_page + 1):
            Sector.objects.create(name=f"Sector {i}")
        first = self.client.get(self.url)
        second = self.client.get(self.url, {"page": "2"})
        self.assertEqual(len(first.context["rows"]), per_page)
        self.assertEqual(len(second.context["rows"]), 1)
        self.assertEqual(first.context["page_obj"].paginator.num_pages, 2)
        self.assertEqual(second.context["page_obj"].number, 2)
        ids = [row["id"] for row in first.context["rows"] + second.context["rows"]]
        self.assertEqual(len(set(ids)), per_page + 1)
        self.assertSetEqual(set(ids), set(Sector.objects.values_list("id", flat=True)))
        for value in ["0", "not-a-number", "9" * 30]:
            self.assertEqual(self.client.get(self.url, {"edit": value}).status_code, 404)
        Sector.objects.all().delete()
        Sector.objects.create(name='<script>alert("x")</script>')
        response = self.client.get(self.url)
        self.assertNotContains(response, '<script>alert("x")</script>')
        self.assertContains(response, "&lt;script&gt;")

