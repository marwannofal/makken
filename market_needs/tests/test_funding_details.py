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
from partnerships.models import Partnership
from .test_market import MarketFixtures


class FundingDetailsTests(MarketFixtures, TestCase):
    def allocation_data(self, need, values, **extra):
        lines = list(need.expense_lines.order_by("position"))
        return {**{f"allocation_{line.pk}": str(value) for line, value in zip(lines, values) if value is not None}, **extra}

    def submit(self, need, record, data, operation="approve", actor=None, files=None):
        need.refresh_from_db(); record.refresh_from_db()
        if files is None:
            files = {"attachments": [self.png()]} if operation == "approve" else {}
        return services.followup(need.pk, need.version, record.pk, record.version, operation, data, files, actor or self.user)

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
        for data in [self.allocation_data(need, ["10"], support_percent="25"), self.allocation_data(need, ["26"], support_percent="25")]:
            with self.assertRaises(services.InvalidForm): self.submit(need, record, data)
        self.assertFalse(SponsorshipAllocation.objects.exists())

    def test_percentage_only_approval_auto_allocates_without_manual_distribution(self):
        need = self.create_need(); record = self.attach(need, self.organization())
        self.submit(need, record, {"support_percent": "25"})
        record.refresh_from_db(); need.refresh_from_db()
        self.assertEqual(record.amount, Decimal("25.00"))
        self.assertEqual(need.approved_support, Decimal("25.00"))
        allocs = list(record.allocations.order_by("expense_line_id").values_list("amount", flat=True))
        self.assertEqual(sum(allocs, Decimal("0.00")), Decimal("25.00"))
        self.assertTrue(all(v > 0 for v in allocs))

    def test_foreign_line_and_negative_distribution_rejected(self):
        need = self.create_need(); other = self.create_need(); record = self.attach(need, self.organization())
        bad_line = other.expense_lines.first()
        for data in [{"support_percent":"25", f"allocation_{bad_line.pk}":"25"}, self.allocation_data(need, ["-1", "26"], support_percent="25")]:
            with self.assertRaises(services.InvalidForm): self.submit(need, record, data)

    def test_line_cannot_be_overfunded_even_when_card_has_remaining_money(self):
        need = self.create_need(); first = self.attach(need, self.organization()); second = self.attach(need, self.organization("جهة ثانية"))
        self.submit(need, first, self.allocation_data(need, ["50"], support_percent="50"))
        with self.assertRaises(services.InvalidForm):
            self.submit(need, second, self.allocation_data(need, ["20"], support_percent="40"))
        self.submit(need, second, self.allocation_data(need, ["10", "10"], support_percent="40"))
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
        result=self.client.post(path,self.allocation_data(need,["15","10"],support_percent="25",snapshot=response.context['followup_snapshot'],attachments=self.png()))
        self.assertEqual(result.status_code,302);record.refresh_from_db();self.assertEqual(record.amount,25)

    def test_table_headers_follow_requested_order_and_extra_data_remains(self):
        need=self.create_need(); record=self.attach(need,self.organization())
        response=self.client.get('/market-needs/')
        headers=['حاجة السوق','القطاع','التخصص','البرنامج التدريبي','حالة الدعم','نوع الرعاية','عدد المتدربين','تكلفة البرنامج','نوع التدريب','الإجراء']
        html=response.content.decode();positions=[html.index(f'<th scope="col">{text}</th>') for text in headers]
        self.assertEqual(positions,sorted(positions));self.assertContains(response,need.number)
        response=self.client.get(f'/market-needs/{need.pk}/sponsors/')
        self.assertNotContains(response, 'إسناد متابعة البطاقة')
        for label in ['الكيان / نوعه','نطاق الكيان','مستوى']:
            self.assertContains(response,f'<th scope="col">{label}</th>',html=True)
        for label in ['تاريخ التعديل','المستخدم / التعديل']:
            self.assertNotContains(response,f'<th scope="col">{label}</th>',html=True)


    def test_sponsors_criteria_section_is_reselectable_and_filters(self):
        need = self.create_need()
        need.search_states = ['capability', 'willingness']
        need.search_scopes = ['local']
        need.save(update_fields=['search_states', 'search_scopes'])
        org_cap = self.organization("جهة قدرة محلية", state='capability')
        org_cap.scope = 'local'; org_cap.save(update_fields=['scope'])
        org_care = self.organization("جهة رعاية عالمية", state='care')
        org_care.scope = 'global'; org_care.save(update_fields=['scope'])
        res = self.client.get(f'/market-needs/{need.pk}/sponsors/')
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'class="market-sponsors-criteria-form"')
        self.assertContains(res, 'name="states"')
        self.assertContains(res, 'name="scopes"')
        self.assertContains(res, org_cap.name)
        self.assertNotContains(res, org_care.name)
        res2 = self.client.get(f'/market-needs/{need.pk}/sponsors/', {'states': ['care'], 'scopes': ['global']})
        self.assertEqual(res2.status_code, 200)
        self.assertContains(res2, org_care.name)
        self.assertNotContains(res2, org_cap.name)


    def test_remaining_based_percentage_and_simplified_approval_popup(self):
        need = self.create_need()
        first = self.attach(need, self.organization("جهة أولى"))
        second = self.attach(need, self.organization("جهة ثانية"))
        self.submit(need, first, {"support_percent": "80"})
        need.refresh_from_db()
        self.assertEqual(need.remaining, Decimal("20.00"))
        res = self.client.get(f'/market-needs/{need.pk}/sponsors/', {'record': second.pk, 'operation': 'approve'})
        self.assertEqual(res.status_code, 200)
        html = res.content.decode()
        self.assertNotIn('market-care-mode-bar', html)
        self.assertNotIn('إجمالي تكلفة الحاجة (أساس النسبة)', html)
        self.assertNotIn('المستوى المتوقع', html)
        self.assertIn('المستوى:', html)
        self.assertLess(html.index('data-funding-summary'), html.index('id="id_notes"'))
        self.submit(need, second, {"support_percent": "100"})
        second.refresh_from_db(); need.refresh_from_db()
        self.assertEqual(second.amount, Decimal("20.00"))
        self.assertEqual(second.level.funding_key, "bronze")
        self.assertEqual(need.approved_support, Decimal("100.00"))
        self.assertEqual(need.arrangement_key, "alliance")


class FundingMigrationTests(MarketFixtures, TransactionTestCase):
    def setUp(self):
        pass  # Historical models are prepared after rolling back this migration.

    def restore_latest(self):
        executor=MigrationExecutor(connection); executor.migrate(executor.loader.graph.leaf_nodes())

    def test_existing_approved_funding_gets_level_without_invented_allocations(self):
        self.addCleanup(self.restore_latest)
        executor=MigrationExecutor(connection); executor.migrate([('market_needs','0001_initial')])
        self.setUpTestData()
        # Build historical 0001_initial records via the migration project state
        # so later columns (e.g. search_states/search_scopes) are not referenced.
        executor = MigrationExecutor(connection)
        old = executor.loader.project_state(list(executor.loader.applied_migrations)).apps
        OldNeed = old.get_model('market_needs', 'Need')
        need = OldNeed.objects.create(
            title='حاجة الهجرة للتمويل',
            description='وصف',
            duration=3,
            duration_unit='month',
            source='دراسة السوق',
            beneficiaries=3,
            program_id=self.program.pk,
            program_name=self.program.name,
            program_category=self.program.category,
            training_type='training',
            sector_id=self.sector.pk,
            specialization_id=self.spec.pk,
            total_cost='100.00',
            requested_support='90.00',
            created_by_id=self.user.pk,
        )
        old.get_model('market_needs', 'NeedRegion').objects.create(need_id=need.pk, region_id=self.region.pk)
        old.get_model('market_needs', 'ExpenseLine').objects.create(
            need_id=need.pk,
            expense_item_id=self.expense.pk,
            sponsorship_shape_id=self.shape.pk,
            amount='100.00',
            position=0,
        )
        OldPartnership = old.get_model('partnerships', 'Partnership')
        org = OldPartnership.objects.create(
            name='جهة الهجرة للتمويل',
            name_key='جهة الهجرة للتمويل',
            representative='الممثل',
            phone='+966501234567',
            email='person@example.com',
            entity_id=self.entity.pk,
            scope='local',
            financial_capacity=1,
            is_active=True,
            development_state_id='care',
        )
        entered = org.development_state_at
        decided=timezone.now()-timedelta(days=3)
        record=old.get_model('market_needs','Sponsorship').objects.create(need_id=need.pk,partnership_id=org.pk,status='approved',amount='80.00',decided_at=decided)
        event=old.get_model('market_needs','AuditEvent').objects.create(need_id=need.pk,need_number=f'MN-{need.pk}',sponsorship_id=record.pk,actor_id=self.user.pk,action='اعتماد مساهمة',after={'amount':'80.00'})
        self.restore_latest()
        current=Sponsorship.objects.get(pk=record.pk);org=Partnership.objects.get(pk=org.pk)
        self.assertEqual(current.amount,80);self.assertEqual(current.decided_at,decided)
        self.assertEqual(current.level.funding_key,'gold');self.assertEqual(current.level_name,'ذهبي')
        self.assertEqual(current.updated_at,event.created_at);self.assertEqual(current.updated_by,self.user)
        self.assertFalse(current.allocations.exists());self.assertEqual(current.unallocated_amount,80)
        self.assertEqual(org.development_state_at,entered)
