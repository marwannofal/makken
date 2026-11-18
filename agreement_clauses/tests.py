from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from access_control.models import PermissionOverride, UserAccess, UserActivity
from core.dependencies import DependencyBlocked, ensure_allowed
from makken_mail.models import Delivery, EventRule, RecipientMute, SMTPConfig
from makken_mail.worker import run_batch
from market_needs.services import InvalidForm, save_need
from market_needs.tests.test_market import MarketFixtures
from .models import AgreementClause, ClauseAssignment, NeedClause, ProgramClause


class AgreementClauseTests(MarketFixtures, TestCase):
    def setUp(self):
        super().setUp()
        self.clause = AgreementClause.objects.create(name="تسليم التقرير")
        self.second = AgreementClause.objects.create(name="تنفيذ الورشة")
        self.inactive = AgreementClause.objects.create(name="بند غير نشط", is_active=False)
        self.partner = self.organization()
        self.partner.administrative_regions.add(self.region)
        self.url = reverse("partnerships:clauses", args=[self.partner.pk])

    def add(self, url, *clauses, code="shared"):
        review = self.client.get(url)
        return self.client.post(url, {"operation": "add_clauses", "snapshot": review.context["add_token"],
                                      "clauses": [clause.pk for clause in clauses], "responsibility": code})

    def create_agreement(self, title="اتفاقية التعاون"):
        response = self.client.post(self.url, {"operation": "create_agreement",
            "snapshot": self.client.get(self.url).context["title_token"], "main-title": title})
        self.assertEqual(response.status_code, 302)
        agreement = self.partner.agreements.get(title=title)
        return agreement, reverse("partnerships:agreement", args=[self.partner.pk, agreement.pk])

    def progress(self, url, row_id, snapshot, value, responsibility="partner"):
        return self.client.post(url, {"operation": "update_clause", "snapshot": snapshot,
            f"row-{row_id}-responsibility": responsibility, f"row-{row_id}-progress": value})

    def limited_user(self, username, region=None, modules=None):
        user = get_user_model().objects.create_user(username, f"{username}@example.org")
        access = UserAccess.objects.create(user=user, page_scope="all", region_scope="selected")
        access.allowed_regions.add(region or self.region)
        for module, ops in (modules or {"partnerships": ("view",)}).items():
            for op in ops:
                PermissionOverride.objects.create(user=user, module_id=module, operation=op, effect="grant")
        return user

    def test_catalog_mirrors_expense_approval_and_preserves_referenced_clauses(self):
        url = reverse("agreement_clauses:index")
        initial = self.client.get(url)
        self.assertContains(initial, "إدارة بنود الاتفاقية")
        self.assertContains(initial, "expense_items/expense_items.js")
        self.assertNotContains(initial, "__ASSET")
        preview = self.client.post(url, {"action": "preview", "operation": "add",
            "snapshot": initial.context["add_snapshot"], "name": "  تسجيل   النتائج ", "is_active": "1"})
        self.assertFalse(AgreementClause.objects.filter(name="تسجيل النتائج").exists())
        self.assertEqual(self.client.post(url, {"action": "confirm", "token": preview.context["pending"]["token"]}).status_code, 302)
        self.assertContains(self.client.get(url, {"q": "تسجيل النتائج"}), "تسجيل النتائج")
        self.assertEqual(self.add(self.url, self.clause).status_code, 302)
        filtered = self.client.get(url, {"q": self.clause.name})
        for operation in ("toggle", "delete"):
            token = filtered.context["rows"][0][f"{operation}_snapshot"]
            self.assertContains(self.client.post(url, {"action": "preview", "snapshot": token}), "لارتباطه بسجلات أخرى", status_code=409)
        self.clause.refresh_from_db()
        self.assertTrue(self.clause.is_active)

    def test_catalog_confirmation_rechecks_links_and_permissions(self):
        url = reverse("agreement_clauses:index")
        page = self.client.get(url, {"q": self.clause.name})
        review = self.client.post(url, {"action": "preview", "snapshot": page.context["rows"][0]["toggle_snapshot"]})
        ProgramClause.objects.create(program=self.program, clause=self.clause)
        self.assertEqual(self.client.post(url, {"action": "confirm", "token": review.context["pending"]["token"]}).status_code, 409)
        user = self.limited_user("clause-watcher", modules={"agreement_clauses": ("view",)})
        self.client.force_login(user)
        page = self.client.get(url)
        self.assertContains(page, self.clause.name)
        self.assertNotContains(page, "data-add-expense-item")
        self.assertEqual(self.client.post(url, {"action": "preview", "operation": "add", "snapshot": page.context["add_snapshot"],
            "name": "بند غير مصرح", "is_active": "1"}).status_code, 403)

    def test_reuse_independent_responsibility_and_progress_rollups(self):
        agreement, url = self.create_agreement()
        other, second_url = self.create_agreement("اتفاقية التدريب")
        self.assertEqual(self.add(url, self.clause, self.second).status_code, 302)
        self.assertEqual(self.add(second_url, self.clause, code="institution").status_code, 302)
        self.assertEqual(self.add(self.url, self.clause).status_code, 302)
        page = self.client.get(url)
        self.assertEqual(page.context["progress"], 0)
        row, _, signed = page.context["rows"][0]
        self.assertEqual(self.progress(url, row.pk, signed, 85).status_code, 302)
        self.assertEqual(self.client.get(url).context["progress"], Decimal("42.50"))
        self.assertEqual(self.client.get(second_url).context["progress"], 0)
        self.assertEqual(self.client.get(self.url).context["overall"], Decimal("21.25"))
        self.assertEqual(agreement.clause_assignments.get(clause=self.clause).responsibility, "partner")
        self.assertEqual(other.clause_assignments.get(clause=self.clause).responsibility, "institution")
        record = self.client.get(reverse("partnerships:index"), {"detail": self.partner.pk})
        self.assertEqual(record.context["clause_panel"]["overall"], Decimal("21.25"))
        event = UserActivity.objects.get(description="تحديث إنجاز بند الاتفاقية")
        self.assertEqual((event.after["progress"], event.after["agreement_number"]), (85, agreement.number))

    def test_validation_stale_and_cross_owner_tokens(self):
        agreement, url = self.create_agreement()
        self.assertEqual(self.add(url, self.inactive).status_code, 400)
        self.assertEqual(self.add(url, self.clause, self.clause).status_code, 400)
        self.assertEqual(self.add(url, self.clause).status_code, 302)
        self.assertEqual(self.add(url, self.clause).status_code, 400)
        page = self.client.get(url)
        row, _, signed = page.context["rows"][0]
        for value in ("101", "-1", "text", "50.5"):
            self.assertEqual(self.progress(url, row.pk, signed, value).status_code, 400)
        self.assertEqual(self.progress(self.url, row.pk, signed, 99).status_code, 400)
        self.assertEqual(self.progress(url, row.pk, signed, 100).status_code, 302)
        self.assertEqual(self.progress(url, row.pk, signed, 0).status_code, 409)
        row.refresh_from_db()
        self.assertEqual(row.progress, 100)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ClauseAssignment.objects.filter(pk=row.pk).update(progress=101)
        other = self.organization(name="جهة مختلفة")
        self.assertEqual(self.client.get(reverse("partnerships:agreement", args=[other.pk, agreement.pk])).status_code, 404)

    def test_regional_scope_and_edit_delete_are_separate(self):
        self.add(self.url, self.clause)
        self.partner.administrative_regions.add(self.region2)
        user = self.limited_user("regional-clause-editor", modules={"partnerships": ("view", "edit")})
        self.client.force_login(user)
        read = self.client.get(self.url)
        self.assertContains(read, self.clause.name)
        row, _, signed = read.context["rows"][0]
        self.assertEqual(self.progress(self.url, row.pk, signed, 80).status_code, 403)
        self.partner.administrative_regions.remove(self.region2)
        self.assertEqual(self.client.post(self.url, {"operation": "remove_clause", "snapshot": signed}).status_code, 403)
        self.assertEqual(self.progress(self.url, row.pk, signed, 80).status_code, 302)
        self.partner.administrative_regions.set([self.region2])
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_program_and_need_clauses_do_not_touch_financial_items(self):
        url = reverse("training_programs:index")
        page = self.client.get(url, {"edit": self.program.pk})
        preview = self.client.post(url, {"action": "preview", "operation": "edit", "snapshot": page.context["editor_form"].initial["snapshot"],
            "name": self.program.name, "category": self.program.category, "training_types": "training", "is_active": "1",
            "expense_items": [self.expense.pk, self.expense2.pk], "agreement_clause_picker": "1", "agreement_clauses": [self.clause.pk]})
        self.assertContains(preview, self.clause.name)
        self.assertEqual(self.client.post(url, {"action": "confirm", "token": preview.context["pending"]["token"]}).status_code, 302)
        self.assertTrue(ProgramClause.objects.filter(program=self.program, clause=self.clause).exists())
        self.assertContains(self.client.get(url, {"q": self.clause.name}), self.program.name)
        need = self.create_need(agreement_clauses=[self.clause.pk])
        self.assertContains(self.client.get(reverse("market_needs:followup", args=[need.pk])), self.clause.name)
        self.assertEqual(need.total_cost, Decimal("100.00"))
        self.assertEqual(need.expense_lines.count(), 2)
        self.assertTrue(NeedClause.objects.filter(need=need, clause=self.clause).exists())
        need = save_need(self.data(), self.user, pk=need.pk, version=need.version)
        self.assertTrue(NeedClause.objects.filter(need=need, clause=self.clause).exists())
        need = save_need(self.data(agreement_clause_picker="1"), self.user, pk=need.pk, version=need.version)
        self.assertFalse(NeedClause.objects.filter(need=need).exists())
        with self.assertRaises(InvalidForm):
            self.create_need(agreement_clauses=[self.inactive.pk])
        with self.assertRaises(DependencyBlocked):
            ensure_allowed(self.clause, "delete")

    def test_opt_in_progress_email_contains_the_saved_snapshot_and_is_not_duplicated(self):
        SMTPConfig.objects.update(host="smtp.example.org", sender="makken@example.org", enabled=True)
        rule = EventRule.objects.get(pk="agreement.clause_progress")
        self.assertFalse(rule.enabled)
        rule.enabled = True
        rule.save(update_fields=["enabled"])
        eligible = self.limited_user("eligible")
        muted = self.limited_user("muted")
        outside = self.limited_user("outside", self.region2)
        rule.recipients.add(eligible, muted, outside)
        RecipientMute.objects.create(rule=rule, user=muted)
        self.add(self.url, self.clause)
        row, _, signed = self.client.get(self.url).context["rows"][0]
        with self.captureOnCommitCallbacks(execute=True):
            response = self.progress(self.url, row.pk, signed, 35)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(list(Delivery.objects.filter(rule=rule).values_list("recipient_id", flat=True)), [eligible.pk])
        with patch("makken_mail.worker.send") as send:
            run_batch()
        self.assertEqual(send.call_args.args[1], eligible.email)
        self.assertIn(("نسبة الإنجاز", "35%"), send.call_args.args[2]["details"])

    def test_detach_preserves_catalog_and_other_agreements(self):
        agreement, agreement_url = self.create_agreement()
        self.add(agreement_url, self.clause)
        self.add(self.url, self.clause)
        row, _, signed = self.client.get(agreement_url).context["rows"][0]
        self.assertEqual(self.client.post(agreement_url, {"operation": "remove_clause", "snapshot": signed}).status_code, 302)
        self.assertFalse(ClauseAssignment.objects.filter(pk=row.pk).exists())
        self.assertTrue(AgreementClause.objects.filter(pk=self.clause.pk).exists())
        self.assertTrue(ClauseAssignment.objects.filter(partnership=self.partner, clause=self.clause).exists())
        self.assertIsNone(self.client.get(agreement_url).context["progress"])
        self.assertTrue(UserActivity.objects.filter(description="إزالة إسناد بند", before__clause=self.clause.name).exists())

    def test_catalog_xlsx_requires_its_own_grant_and_respects_search(self):
        from io import BytesIO
        from zipfile import ZipFile
        url = reverse("agreement_clauses:index")
        user = self.limited_user("catalog-exporter", modules={"agreement_clauses": ("view",)})
        self.client.force_login(user)
        request = {"q": self.second.name, "_mk_export": "xlsx"}
        self.assertEqual(self.client.get(url, request).status_code, 403)
        PermissionOverride.objects.create(user=user, module_id="agreement_clauses", operation="export_xlsx", effect="grant")
        response = self.client.get(url, request)
        self.assertEqual(response.status_code, 200)
        with ZipFile(BytesIO(response.content)) as workbook:
            cells = workbook.read("xl/worksheets/sheet1.xml").decode()
        self.assertIn(self.second.name, cells)
        self.assertNotIn(self.clause.name, cells)
        self.assertEqual(self.client.get(url, {"_mk_export": "pdf"}).status_code, 403)
