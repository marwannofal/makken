# MAKKEN RBAC BUSINESS FIXTURES v1
# MAKKEN RBAC INTEGRATION v1
# MAKKEN PAGINATION AND DEPENDENCY TEST COMPAT v2
from unittest.mock import patch
import time

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from .models import Entity, EntityType, EntityBranch
from .forms import EntityForm
from .views import TOKEN_AGE


class EntitiesTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user("entities-test", password="test-only-password", is_superuser=True)
        self.client.force_login(self.user)
        self.url = reverse("entities:index")

    def row(self, pk=None):
        rows = self.client.get(self.url).context["rows"]
        return next(row for row in rows if row["id"] == pk) if pk else rows[0]

    def preview(self, operation, pk=None, name="كيان جديد", active="1", kind="government", branch=""):
        if operation == "add":
            snapshot = self.client.get(self.url).context["add_snapshot"]
        else:
            snapshot = self.row(pk)[f"{operation}_snapshot"]
        return self.client.post(self.url, {"action": "preview", "operation": operation, "snapshot": snapshot, "name": name, "is_active": active, "entity_type": kind, "branch": branch})

    def confirm(self, response):
        return self.client.post(self.url, {"action": "confirm", "token": response.context["pending"]["token"]})

    def test_initial_records_and_security_headers(self):
        self.assertEqual(list(Entity.objects.values_list("name", "entity_type", "branch", "is_active")), [
            ("حكومي", "government", "", True),
            ("خاص كبير", "non_government", "private_large", True),
            ("خاص صغير ومتوسط", "non_government", "private_sme", True),
            ("غير ربحي مهني", "non_government", "nonprofit_professional", True),
            ("غير ربحي مجتمعي", "non_government", "nonprofit_community", True),
        ])
        response = self.client.get(self.url)
        self.assertContains(response, "إضافة كيان")
        self.assertNotContains(response, "لوحة الإدارة")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])

    def test_anonymous_get_and_post_redirect_to_login(self):
        self.client.logout()
        for method in [self.client.get, self.client.post]:
            self.assertEqual(method(self.url).status_code, 302)
        self.assertEqual(Entity.objects.count(), 5)

    def test_add_requires_confirmation_and_cancel_does_not_write(self):
        response = self.preview("add", name="كيان مخصص", active="0")
        self.assertContains(response, "تأكيد إضافة الكيان")
        self.assertEqual(Entity.objects.count(), 5)
        self.client.get(self.url)
        self.assertEqual(Entity.objects.count(), 5)
        self.assertRedirects(self.confirm(response), self.url)
        self.assertFalse(Entity.objects.get(name=response.context["pending"]["name"]).is_active)
        self.assertEqual(self.confirm(response).status_code, 409)
        self.assertEqual(Entity.objects.filter(name=response.context["pending"]["name"]).count(), 1)

    def test_edit_preserves_historical_name_and_changes_status_after_confirmation(self):
        item = Entity.objects.first()
        response = self.preview("edit", item.pk, name="حكومي محدث", active="0")
        item.refresh_from_db()
        self.assertEqual(item.name, "حكومي")
        self.assertRedirects(self.confirm(response), self.url)
        item.refresh_from_db()
        self.assertEqual((item.name, item.is_active, item.version), ("حكومي", False, 2))

    def test_status_toggle_both_directions_and_cancel(self):
        item = Entity.objects.first()
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
        item = Entity.objects.first()
        response = self.preview("delete", item.pk)
        self.assertContains(response, "تأكيد حذف الكيان")
        self.assertTrue(Entity.objects.filter(pk=item.pk).exists())
        self.client.get(self.url, {"action": "delete", "id": item.pk})
        self.assertTrue(Entity.objects.filter(pk=item.pk).exists())
        self.assertRedirects(self.confirm(response), self.url)
        self.assertFalse(Entity.objects.filter(pk=item.pk).exists())
        self.assertEqual(self.confirm(response).status_code, 409)

    def test_generated_labels_are_unique_and_posted_names_are_ignored(self):
        names = []
        for supplied in ["", "   ", "a" * 201, "<script>alert(1)</script>", "اسم غير مطلوب"]:
            response = self.preview("add", name=supplied)
            self.assertEqual(response.status_code, 200)
            names.append(response.context["pending"]["name"])
            self.assertRedirects(self.confirm(response), self.url)
        self.assertEqual(len(set(names)), len(names))
        self.assertTrue(all(name.startswith("حكومي (") for name in names))
        self.assertEqual(Entity.objects.get(pk=1).name, "حكومي")

    def test_invalid_status_and_actions(self):
        self.assertEqual(self.preview("add", active="unexpected").status_code, 400)
        self.assertEqual(self.client.post(self.url, {"action": "delete"}).status_code, 400)
        self.assertEqual(Entity.objects.count(), 5)

    def test_no_changes_and_edit_fallback(self):
        item = Entity.objects.first()
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
        other = get_user_model().objects.create_user("another-entity-test", is_superuser=True)
        self.client.force_login(other)
        self.assertEqual(self.client.post(self.url, {"action": "confirm", "token": token}).status_code, 400)
        self.assertEqual(Entity.objects.count(), 5)

    def test_stale_edit_toggle_delete_and_snapshot(self):
        item = Entity.objects.first()
        stale_snapshot = self.row(item.pk)["edit_snapshot"]
        pending = [self.preview(operation, item.pk, name="كيان محدث", active="0") for operation in ["edit", "toggle", "delete"]]
        item.version += 1
        item.save()
        for response in pending:
            self.assertEqual(self.confirm(response).status_code, 409)
        self.assertEqual(self.client.post(self.url, {"action": "preview", "operation": "edit", "snapshot": stale_snapshot, "name": "other", "is_active": "1"}).status_code, 409)
        item.refresh_from_db()
        self.assertEqual(item.name, "حكومي")
        self.assertTrue(item.is_active)

    def test_csrf_for_preview_and_confirm(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        page = client.get(self.url)
        snapshot = page.context["add_snapshot"]
        data = {"action": "preview", "operation": "add", "snapshot": snapshot, "name": "CSRF test", "is_active": "1", "entity_type": "government"}
        self.assertEqual(client.post(self.url, data).status_code, 403)
        csrf = client.cookies["csrftoken"].value
        response = client.post(self.url, {**data, "csrfmiddlewaretoken": csrf})
        data = {"action": "confirm", "token": response.context["pending"]["token"]}
        self.assertEqual(client.post(self.url, data).status_code, 403)
        self.assertEqual(client.post(self.url, {**data, "csrfmiddlewaretoken": csrf}).status_code, 302)

    def test_pagination_empty_state_and_escaping(self):
        Entity.objects.all().delete()
        empty = self.client.get(self.url)
        self.assertContains(empty, "لا توجد كيانات بعد")
        page_size = empty.context["page_obj"].paginator.per_page
        for i in range(page_size + 1):
            Entity.objects.create(name=f"Entity {i}", entity_type="government")
        first = self.client.get(self.url)
        second = self.client.get(self.url, {"page": "2"})
        self.assertEqual(first.context["page_obj"].paginator.count, page_size + 1)
        self.assertEqual(first.context["page_obj"].paginator.num_pages, 2)
        self.assertEqual(len(first.context["rows"]), page_size)
        self.assertEqual(len(second.context["rows"]), 1)
        first_ids = {row["id"] for row in first.context["rows"]}
        second_ids = {row["id"] for row in second.context["rows"]}
        self.assertFalse(first_ids & second_ids)
        self.assertEqual(first_ids | second_ids, set(Entity.objects.values_list("pk", flat=True)))
        Entity.objects.all().delete()
        Entity.objects.create(name='<script>alert("x")</script>', entity_type="government")
        response = self.client.get(self.url)
        self.assertNotContains(response, '<script>alert("x")</script>')
        self.assertNotContains(response, "entity-name")

    def test_sidebar_preserves_care_states_and_hides_admin(self):
        self.user.is_staff = True
        self.user.save()
        for url in ["/", reverse("care_states:index"), reverse("levels:index"), reverse("regions:index"), self.url]:
            response = self.client.get(url)
            self.assertContains(response, 'href="/settings/entities/"')
            self.assertContains(response, 'href="/settings/development-states/"')
            self.assertNotContains(response, "لوحة الإدارة")

    def test_type_dropdown_has_exactly_two_choices_and_four_static_branches(self):
        form = EntityForm(initial={"entity_type": "government"})
        self.assertEqual(list(form.fields["entity_type"].choices), [("government", "حكومي"), ("non_government", "غير حكومي")])
        self.assertEqual(EntityBranch.labels, ["خاص كبير", "خاص صغير ومتوسط", "غير ربحي مهني", "غير ربحي مجتمعي"])
        self.assertFalse(form.show_branch)
        self.assertTrue(form.fields["branch"].disabled)
        self.assertFalse(form.fields["branch"].required)

    def test_non_government_branch_required_and_all_branches_can_be_created(self):
        for branch in ["", "invalid", "government"]:
            response = self.preview("add", kind="non_government", branch=branch)
            self.assertEqual(response.status_code, 400)
            self.assertIn("branch", response.context["editor_form"].errors)
            self.assertTrue(response.context["editor_form"].show_branch)
        for branch in EntityBranch:
            response = self.preview("add", name=f"كيان {branch.label}", kind="non_government", branch=branch.value)
            self.assertRedirects(self.confirm(response), self.url)
            self.assertEqual(Entity.objects.get(name=response.context["pending"]["name"]).branch, branch.value)

    def test_government_discards_forged_or_stale_branch(self):
        for i, branch in enumerate(["private_large", "invented", ""]):
            response = self.preview("add", name=f"كيان حكومي {i}", kind="government", branch=branch)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["pending"]["branch"], "")
            self.assertRedirects(self.confirm(response), self.url)
            self.assertEqual(Entity.objects.get(name=response.context["pending"]["name"]).branch, "")

    def test_switching_non_government_to_government_clears_branch_only_after_confirmation(self):
        item = Entity.objects.get(branch="private_large")
        response = self.preview("edit", item.pk, name=item.name, kind="government", branch="private_large")
        self.assertTrue(response.context["pending"]["clears_branch"])
        item.refresh_from_db()
        self.assertEqual(item.branch, "private_large")
        self.assertRedirects(self.confirm(response), self.url)
        item.refresh_from_db()
        self.assertEqual((item.entity_type, item.branch, item.version), ("government", "", 2))

    def test_switching_government_to_non_government_requires_branch(self):
        item = Entity.objects.get(entity_type="government")
        self.assertEqual(self.preview("edit", item.pk, name=item.name, kind="non_government").status_code, 400)
        response = self.preview("edit", item.pk, name=item.name, kind="non_government", branch="nonprofit_community")
        self.assertRedirects(self.confirm(response), self.url)
        item.refresh_from_db()
        self.assertEqual((item.entity_type, item.branch), ("non_government", "nonprofit_community"))

    def test_unknown_type_and_missing_required_fields_are_rejected(self):
        for kind in ["", "private", "third_type"]:
            self.assertEqual(self.preview("add", kind=kind).status_code, 400)
        snapshot = self.client.get(self.url).context["add_snapshot"]
        base = {"action": "preview", "operation": "add", "snapshot": snapshot, "name": "اسم", "entity_type": "non_government", "branch": "private_sme", "is_active": "1"}
        for key in ["entity_type", "branch", "is_active"]:
            data = base.copy()
            del data[key]
            self.assertEqual(self.client.post(self.url, data).status_code, 400, key)

    def test_database_rejects_invalid_type_branch_combinations(self):
        from django.db import IntegrityError, transaction
        for kind, branch in [("third_type", ""), ("government", "private_large"), ("non_government", ""), ("non_government", "forged")]:
            with self.assertRaises(IntegrityError), transaction.atomic():
                Entity.objects.create(name=f"invalid {kind}-{branch}", entity_type=kind, branch=branch)

    def test_edit_fallback_restores_non_government_fields(self):
        item = Entity.objects.get(branch="nonprofit_community")
        response = self.client.get(self.url, {"edit": item.pk})
        form = response.context["editor_form"]
        self.assertTrue(form.show_branch)
        self.assertTrue(form.fields["branch"].required)
        self.assertFalse(form.fields["branch"].disabled)
        self.assertEqual(form.initial["branch"], "nonprofit_community")

    def test_name_absent_from_form_table_and_confirmation(self):
        form = EntityForm()
        self.assertNotIn("name", form.fields)
        response = self.client.get(self.url, {"edit": "new"})
        self.assertNotContains(response, "اسم الكيان")
        self.assertNotContains(response, 'name="name"')
        preview = self.preview("add")
        self.assertNotContains(preview, "اسم الكيان")
        self.assertEqual([f["label"] for f in preview.context["pending"]["fields"]], ["الكيان", "حالة السجل"])

    def test_concurrent_duplicate_internal_label_rejected_without_duplicate_record(self):
        first, second = self.preview("add"), self.preview("add")
        self.assertEqual(first.context["pending"]["name"], second.context["pending"]["name"])
        self.assertEqual(self.confirm(first).status_code, 302)
        self.assertEqual(self.confirm(second).status_code, 409)
        self.assertEqual(Entity.objects.count(), 6)

    def test_existing_partnership_reference_and_name_preserved(self):
        from uuid import uuid4
        from django.urls import reverse
        from entities.models import Entity
        from entities import views
        from partnerships.models import Partnership

        suffix = uuid4().hex[:8]
        entity = Entity.objects.create(
            name="كيان تاريخي " + suffix,
            entity_type="government",
            branch="",
        )
        partner = Partnership.objects.create(
            name="جهة مرتبطة " + suffix,
            representative="الممثل",
            phone="+966501234567",
            email="linked@example.com",
            entity=entity,
            scope="local",
        )

        before = (entity.name, entity.version, entity.is_active)
        original_partner_name = partner.name

        for operation in ["toggle", "delete"]:
            response = self.client.post(
                reverse("entities:index"),
                {
                    "action": "preview",
                    "snapshot": views._snapshot(entity, operation, self.user),
                },
            )
            self.assertEqual(response.status_code, 409)
            self.assertContains(response, "سجل الشراكات", status_code=409)
            self.assertIsNone(response.context.get("pending"))

            entity.refresh_from_db()
            partner.refresh_from_db()
            self.assertEqual(
                (entity.name, entity.version, entity.is_active),
                before,
            )
            self.assertEqual(partner.entity_id, entity.pk)
            self.assertEqual(partner.name, original_partner_name)
