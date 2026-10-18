from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.db.models.deletion import ProtectedError
from django.test import TestCase, TransactionTestCase, Client
from django.utils import timezone

from care_states.models import DevelopmentState
from levels.models import Level
from market_needs import services
from market_needs.funding import level_key, expense_funding
from market_needs.models import Sponsorship, SponsorshipAllocation, AuditEvent
from .test_market import MarketFixtures


class FundingDetailsTests(MarketFixtures, TestCase):
    def allocation_data(self, need, values, **extra):
        lines = list(need.expense_lines.order_by("position"))
        return {**{f"allocation_{line.pk}": str(value) for line, value in zip(lines, values) if value is not None}, **extra}

    def submit(self, need, record, data, operation="approve", actor=None):
        need.refresh_from_db(); record.refresh_from_db()
        return services.followup(need.pk, need.version, record.pk, record.version, operation, data, {}, actor or self.user)

    def test_exact_band_boundaries_and_no_rounded_promotion(self):
        for value, expected in [("0", None), ("0.01", "bronze"), ("59.99", "bronze"), ("60", "silver"), ("79.99", "silver"), ("80", "gold"), ("99.99", "gold"), ("100", "strategic")]:
            self.assertEqual(level_key(Decimal(value), Decimal("100")), expected)
        self.assertEqual(level_key(Decimal("99999.99"), Decimal("100000")), "gold")

    def test_percentage_approval_distributes_exact_money_and_tracks_actor(self):
        need = self.create_need(); record = self.attach(need, self.organization())
        self.submit(need, record, self.allocation_data(need, ["15", "10"], support_percent="25"))
        record.refresh_from_db(); need.refresh_from_db()
        self.assertEqual(record.amount, Decimal("25")); self.assertEqual(record.level.funding_key, "bronze")
        self.assertEqual(record.level_name, "برونزي"); self.assertEqual(record.updated_by, self.user)
        self.assertEqual(record.allocated_amount, Decimal("25")); self.assertEqual(record.unallocated_amount, 0)
        funded = expense_funding(need)
        self.assertEqual([x.approved_amount for x in funded], [Decimal("15"), Decimal("10")])
        self.assertEqual([x.coverage_percent for x in funded], [Decimal("25.00"), Decimal("25.00")])
        event = AuditEvent.objects.filter(sponsorship=record, action="اعتماد مساهمة").get()
        self.assertIn("allocations", event.after); self.assertEqual(event.actor, self.user)

    def test_forged_computed_amount_is_rejected_without_changes(self):
        need = self.create_need(); record = self.attach(need, self.organization())
        with self.assertRaises(services.InvalidForm):
            self.submit(need, record, self.allocation_data(need, ["25"], support_percent="25", amount="99"))
        self.assertFalse(SponsorshipAllocation.objects.exists()); record.refresh_from_db(); self.assertEqual(record.status, "new")

    def test_rounding_to_halalas_matches_allocation_sum(self):
        import json
        need = self.create_need(requested_support="0.03", beneficiaries="1", lines=json.dumps([
            {"expense": self.expense.pk, "shape": self.shape.pk, "amount": "0.01"},
            {"expense": self.expense2.pk, "shape": self.shape2.pk, "amount": "0.02"},
        ]))
        record = self.attach(need, self.organization())
        self.submit(need, record, self.allocation_data(need, ["0.01", "0.01"], support_percent="50"))
        record.refresh_from_db(); self.assertEqual(record.amount, Decimal(".02"))
        self.assertEqual(record.percent, Decimal("66.67")); self.assertEqual(record.level.funding_key, "silver")

    def test_percentages_invalid_zero_too_large_and_excess_precision(self):
        need = self.create_need(); record = self.attach(need, self.organization())
        for value in ("0", "-1", "100.01", "1.001", "NaN", "<script>"):
            with self.subTest(value=value), self.assertRaises(services.InvalidForm):
                self.submit(need, record, self.allocation_data(need, ["10"], support_percent=value))
        self.assertFalse(SponsorshipAllocation.objects.exists())

    def test_distribution_required_and_wrong_total_rejected(self):
        need = self.create_need(); record = self.attach(need, self.organization())
        for data in [{"support_percent":"25"}, self.allocation_data(need, ["10"], support_percent="25"), self.allocation_data(need, ["26"], support_percent="25")]:
            with self.assertRaises(services.InvalidForm): self.submit(need, record, data)
        self.assertFalse(SponsorshipAllocation.objects.exists())

    def test_foreign_line_and_negative_distribution_rejected(self):
        need = self.create_need(); other = self.create_need(); record = self.attach(need, self.organization())
        bad_line = other.expense_lines.first()
        for data in [{"support_percent":"25", f"allocation_{bad_line.pk}":"25"}, self.allocation_data(need, ["-1", "26"], support_percent="25")]:
            with self.assertRaises(services.InvalidForm): self.submit(need, record, data)

    def test_line_cannot_be_overfunded_even_when_card_has_remaining_money(self):
        need = self.create_need(); first = self.attach(need, self.organization()); second = self.attach(need, self.organization("جهة ثانية"))
        self.submit(need, first, self.allocation_data(need, ["50"], support_percent="50"))
        with self.assertRaises(services.InvalidForm):
            self.submit(need, second, self.allocation_data(need, ["20"], support_percent="20"))
        self.submit(need, second, self.allocation_data(need, ["10", "10"], support_percent="20"))
        need.refresh_from_db(); self.assertEqual(need.approved_support, 70)
        self.assertEqual([x.approved_amount for x in expense_funding(need)], [Decimal("60"), Decimal("10")])

    def test_partial_match_cannot_fund_an_unsupported_sponsorship_shape(self):
        need=self.create_need();record=self.attach(need,self.organization(shapes=[self.shape]))
        with self.assertRaises(services.InvalidForm):
            self.submit(need,record,self.allocation_data(need,[None,"20"],support_percent="20"))
        self.submit(need,record,self.allocation_data(need,["20"],support_percent="20"))
        self.assertEqual(record.allocations.count(),1)

    def test_alliance_members_keep_independent_levels(self):
        need = self.create_need(); first = self.attach(need, self.organization()); second = self.attach(need, self.organization("جهة تحالف ثانية"))
        self.approve(need, first, "80"); self.approve(need, second, "20")
        first.refresh_from_db(); second.refresh_from_db(); need.refresh_from_db()
        self.assertEqual((first.level.funding_key, second.level.funding_key), ("gold", "bronze"))
        self.assertEqual(need.arrangement, "تحالف"); self.assertEqual(need.status, "complete")

    def test_single_full_support_strategic_and_level_reference_protected(self):
        need = self.create_need(); record = self.attach(need, self.organization()); self.approve(need, record, "100")
        record.refresh_from_db(); self.assertEqual(record.level.funding_key, "strategic")
        with self.assertRaises(ProtectedError): record.level.delete()

    def test_approval_level_snapshot_survives_reference_rename(self):
        need = self.create_need(); record = self.attach(need, self.organization()); self.approve(need, record, "20")
        record.refresh_from_db(); level = record.level; level.name = "برونزي معدل"; level.save()
        record.refresh_from_db(); self.assertEqual(record.level_name, "برونزي")

    def test_description_edit_preserves_allocations_and_funded_line_ids(self):
        need = self.create_need(); record = self.attach(need, self.organization()); self.approve(need, record, "20")
        before = list(SponsorshipAllocation.objects.values_list("pk", "expense_line_id", "amount"))
        need.refresh_from_db(); services.save_need(self.data(description="وصف معدل للبطاقة"), self.user, need.pk, need.version)
        self.assertEqual(list(SponsorshipAllocation.objects.values_list("pk", "expense_line_id", "amount")), before)

    def test_legacy_distribution_is_explicit_and_keeps_approval_and_state_dates(self):
        need = self.create_need(); org = self.organization(state="care"); record = self.attach(need, org)
        entered, decided = org.development_state_at, timezone.now() - timedelta(days=10)
        record.status, record.amount, record.decided_at = "approved", Decimal("30"), decided
        record.save(); services.recompute(need, self.user)
        self.assertEqual(record.unallocated_amount, Decimal("30"))
        preview=self.client.get(f"/market-needs/{need.pk}/sponsors/", {"record":record.pk,"operation":"allocate"})
        self.assertEqual(preview.context["followup_form"]["support_percent"].value(), Decimal("30.00"))
        self.assertEqual(preview.context["followup_form"]["amount"].value(), Decimal("30"))
        self.submit(need, record, self.allocation_data(need, ["20", "10"]), "allocate", self.other)
        record.refresh_from_db(); org.refresh_from_db(); need.refresh_from_db()
        self.assertEqual(record.amount, 30); self.assertEqual(record.decided_at, decided); self.assertEqual(org.development_state_at, entered)
        self.assertEqual(record.updated_by, self.other); self.assertEqual(record.unallocated_amount, 0)
        self.assertEqual(need.approved_support, 30)
        with self.assertRaises(services.Conflict): self.submit(need, record, self.allocation_data(need, ["20", "10"]), "allocate")

    def test_database_positive_unique_and_protected_line_constraints(self):
        need = self.create_need(); record = self.attach(need, self.organization()); self.approve(need, record, "20")
        allocation = record.allocations.first()
        with self.assertRaises(IntegrityError), transaction.atomic():
            SponsorshipAllocation.objects.create(sponsorship=record, expense_line=allocation.expense_line, amount=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            SponsorshipAllocation.objects.create(sponsorship=record, expense_line=need.expense_lines.last(), amount=0)
        with self.assertRaises(ProtectedError): allocation.expense_line.delete()

    def test_details_are_authenticated_scoped_escaped_and_read_only(self):
        need = self.create_need(); other = self.create_need(); record = self.attach(need, self.organization())
        self.approve(need, record, "20")
        Sponsorship.objects.filter(pk=record.pk).update(notes='<script>alert(1)</script>')
        path = f"/market-needs/{need.pk}/sponsors/"
        before = AuditEvent.objects.count()
        response = self.client.get(path, {"record": record.pk, "operation":"details"})
        self.assertContains(response, "record-detail-title"); self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, "<script>alert(1)</script>")
        self.assertContains(response, "تتبع حالة تطور المنظمة للرعاية")
        self.assertEqual(AuditEvent.objects.count(), before)
        self.assertEqual(Client().get(path, {"record":record.pk,"operation":"details"}).status_code, 302)
        self.assertEqual(self.client.get(f"/market-needs/{other.pk}/sponsors/", {"record":record.pk,"operation":"details"}).status_code, 404)

    def test_timeline_does_not_fabricate_willingness_and_preserves_care_date(self):
        need = self.create_need(); org = self.organization(state="capability"); record = self.attach(need, org)
        self.approve(need, record, "20"); org.refresh_from_db(); entered = org.development_state_at
        response = self.client.get(f"/market-needs/{need.pk}/sponsors/", {"record":record.pk,"operation":"details"})
        timeline = response.context["development_history"]
        self.assertIsNone(next(x for x in timeline if x["label"] == "رغبة")["date"])
        self.submit(need, record, {"notes":"متابعة بعد الاعتماد"}, "notes")
        org.refresh_from_db(); self.assertEqual(org.development_state_at, entered)

    def test_nojs_percentage_and_allocation_approval(self):
        need = self.create_need(); record = self.attach(need, self.organization()); path=f"/market-needs/{need.pk}/sponsors/"
        response=self.client.get(path,{"record":record.pk,"operation":"approve"})
        result=self.client.post(path,self.allocation_data(need,["15","10"],support_percent="25",snapshot=response.context['followup_snapshot']))
        self.assertEqual(result.status_code,302);record.refresh_from_db();self.assertEqual(record.amount,25)

    def test_table_headers_follow_requested_order_and_extra_data_remains(self):
        need=self.create_need(); record=self.attach(need,self.organization())
        response=self.client.get('/market-needs/')
        headers=['حاجة السوق','القطاع','التخصص','البرنامج التدريبي','حالة البرنامج','نوع الرعاية','عدد المتدربين','تكلفة البرنامج','نوع التدريب','الإجراء']
        html=response.content.decode();positions=[html.index(f'<th scope="col">{text}</th>') for text in headers]
        self.assertEqual(positions,sorted(positions));self.assertContains(response,need.number)
        response=self.client.get(f'/market-needs/{need.pk}/sponsors/')
        for label in ['الكيان / نوعه','نطاق الكيان','مستوى','تاريخ التعديل','المستخدم / التعديل']:
            self.assertContains(response,f'<th scope="col">{label}</th>',html=True)


class FundingMigrationTests(MarketFixtures, TransactionTestCase):
    def setUp(self):
        pass  # Historical models are prepared after rolling back this migration.

    def restore_latest(self):
        executor=MigrationExecutor(connection); executor.migrate(executor.loader.graph.leaf_nodes())

    def test_existing_approved_funding_gets_level_without_invented_allocations(self):
        self.addCleanup(self.restore_latest)
        executor=MigrationExecutor(connection); executor.migrate([('market_needs','0001_initial')])
        self.setUpTestData()
        need=self.create_need(); org=self.organization(state='care'); entered=org.development_state_at
        old=executor.loader.project_state([('market_needs','0001_initial'),('levels','0002_funding_key')]).apps
        decided=timezone.now()-timedelta(days=3)
        record=old.get_model('market_needs','Sponsorship').objects.create(need_id=need.pk,partnership_id=org.pk,status='approved',amount='80.00',decided_at=decided)
        event=AuditEvent.objects.create(need=need,need_number=need.number,sponsorship_id=record.pk,actor=self.user,action='اعتماد مساهمة',after={'amount':'80.00'})
        self.restore_latest()
        current=Sponsorship.objects.get(pk=record.pk);org.refresh_from_db()
        self.assertEqual(current.amount,80);self.assertEqual(current.decided_at,decided)
        self.assertEqual(current.level.funding_key,'gold');self.assertEqual(current.level_name,'ذهبي')
        self.assertEqual(current.updated_at,event.created_at);self.assertEqual(current.updated_by,self.user)
        self.assertFalse(current.allocations.exists());self.assertEqual(current.unallocated_amount,80)
        self.assertEqual(org.development_state_at,entered)
