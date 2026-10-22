import json
import uuid
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from access_control.models import UserAccess, PermissionOverride, Module
from core.dependencies import DependencyBlocked, ensure_allowed
from service_providers.models import ServiceProvider, ProviderCoverage
from service_providers.forms import ProviderForm
from .test_market import MarketFixtures
from market_needs.models import Need, Sponsorship, NeedExecution, ExecutionProvider, ExecutionStatus
from market_needs import execution_matching as matching
from market_needs.execution_services import save_execution, ExecutionConflict
from partnerships.models import PartnershipOffering
from sponsorship_shapes.models import SponsorshipShape
from training_programs.models import TrainingProgram


class ExecutionTests(MarketFixtures, TestCase):
    def funded(self, operational=False):
        if operational:
            self.program.is_training, self.program.is_operational = False, True
            self.program.save()
        need = self.create_need()
        funder = self.organization(name="ممّول " + str(need.pk))
        Sponsorship.objects.create(need=need, partnership=funder, status="approved", amount=need.total_cost)
        need.approved_support, need.status = need.total_cost, "complete"
        need.save()
        return matching.approved_needs().get(pk=need.pk)

    def provider(self, name="مزود مطابق", program=True, region=None, specialization=None):
        item = ServiceProvider.objects.create(name=name, provider_type="government", scope="local", program=self.program if program else None)
        row = ProviderCoverage.objects.create(provider=item, region=region or self.region)
        row.specializations.add(specialization or self.spec)
        return item

    def employer(self, name="جهة توظيف"):
        shape = SponsorshipShape.objects.create(name=name + " شكل", is_employment=True)
        return self.organization(name=name, shapes=[shape], state="capability")

    def save(self, need, provider_ids=(), employer_ids=(), status="new", **changes):
        execution = NeedExecution.objects.filter(need=need).first()
        args = dict(need_id=need.pk, expected_version=execution.version if execution else 0,
                    expected_need_version=need.version, nonce=uuid.uuid4(),
                    data={"providers": list(provider_ids), "employers": list(employer_ids), "status": status, "notes": "متابعة التنفيذ"}, actor=self.user)
        args.update(changes)
        return save_execution(**args)

    def test_only_exactly_funded_cards_and_no_get_side_effects(self):
        need = self.funded(); self.create_need(title="غير ممولة")
        self.assertEqual(list(matching.approved_needs().values_list("pk", flat=True)), [need.pk])
        self.client.get(reverse("program_execution:index"))
        self.client.get(reverse("program_execution:assignment", args=[need.pk]))
        self.assertFalse(NeedExecution.objects.exists())
        Need.objects.filter(pk=need.pk).update(approved_support=Decimal("99.99"))
        self.assertFalse(matching.approved_needs().exists())

    def test_cached_complete_without_real_funding_is_excluded(self):
        need = self.funded(); need.sponsorships.update(amount=Decimal("99.99"))
        self.assertFalse(matching.approved_needs().exists())

    def test_partial_region_match_and_program_foreign_key(self):
        need=self.funded(); item=self.provider()
        found=matching.providers(need).get(pk=item.pk)
        evidence=matching.provider_evidence(need,found)
        self.assertFalse(evidence["full_coverage"])
        self.assertEqual(evidence["regions"][0]["id"],self.region.pk)
        other=TrainingProgram.objects.create(name="برنامج غير مطابق",category="qualifying_program")
        ServiceProvider.objects.filter(pk=item.pk).update(program=other)
        self.assertFalse(matching.providers(need).exists())

    def test_full_region_match_has_explained_coverage(self):
        need=self.funded(); item=self.provider()
        coverage=ProviderCoverage.objects.create(provider=item,region=self.region2);coverage.specializations.add(self.spec)
        self.assertTrue(matching.provider_evidence(need,matching.providers(need).get())["full_coverage"])

    def test_each_inactive_matching_reference_is_excluded(self):
        need = self.funded(); self.provider()
        for record in (self.program, self.sector, self.spec, self.region):
            with self.subTest(model=record._meta.label):
                # Simulate a historical/imported inactive reference. Ordinary
                # deactivation is correctly blocked by dependency protection.
                type(record).objects.filter(pk=record.pk).update(is_active=False)
                current = matching.approved_needs().get(pk=need.pk)
                self.assertFalse(matching.providers(current).exists())
                type(record).objects.filter(pk=record.pk).update(is_active=True)

    def test_assignment_preserves_actor_history_and_blocks_provider_basis_edit(self):
        need = self.funded(); item = self.provider()
        execution = self.save(need, [item.pk], status="running")
        event = need.events.get(action__startswith="تنفيذ البرنامج")
        self.assertEqual(event.actor_id, self.user.pk)
        self.assertEqual(event.after["حالة التنفيذ"], "تحت التنفيذ")
        self.assertEqual(event.after["مزودو التدريب"][0]["name"], item.name)
        payload = {"name": item.name, "representative": "", "email": "", "phone": "", "phone_country": "SA", "provider_type": "government", "scope": "local", "is_active": "1", "program": self.program.pk, "coverage": json.dumps([{"region": self.region2.pk, "specializations": [self.spec.pk], "is_active": True}])}
        form = ProviderForm(payload, instance=item)
        self.assertFalse(form.is_valid())
        self.assertIn("مرتبط بتنفيذ برنامج", str(form.non_field_errors()))
        self.assertEqual(execution.provider_links.count(), 1)

    def test_unknown_program_and_cross_coverage_false_match_are_excluded(self):
        need=self.funded(); self.provider(program=False)
        item=self.provider(name="مزود ارتباطات مختلفة",specialization=self.spec2)
        from regions.models import Region
        other_region=Region.objects.create(name="منطقة خارج البطاقة")
        row=ProviderCoverage.objects.create(provider=item,region=other_region);row.specializations.add(self.spec)
        self.assertFalse(matching.providers(need).exists())

    def test_inactive_coverage_provider_and_region_excluded(self):
        need=self.funded(); item=self.provider()
        item.coverage.update(is_active=False);self.assertFalse(matching.providers(need).exists())
        item.coverage.update(is_active=True);ServiceProvider.objects.filter(pk=item.pk).update(is_active=False)
        self.assertFalse(matching.providers(need).exists())

    def test_training_has_no_employment_results_operational_has_both(self):
        need=self.funded(); self.provider(); self.employer()
        self.assertFalse(matching.employers(need).exists())
        Need.objects.filter(pk=need.pk).update(training_type="تشغيلي")
        need=matching.approved_needs().get(pk=need.pk)
        self.assertEqual(matching.employers(need).count(),1)
        self.assertEqual(matching.providers(need).count(),1)

    def test_employment_uses_boolean_not_name_or_financial_capacity(self):
        need=self.funded(operational=True)
        correct=self.employer(); correct.offerings.first().sponsorship_shape.__class__.objects.filter(pk=correct.offerings.first().sponsorship_shape_id).update(name="اسم آخر بلا كلمة الوظيفة")
        wrong_shape=SponsorshipShape.objects.create(name="توظيف بالاسم فقط",is_employment=False)
        self.organization(name="غير مؤهلة",shapes=[wrong_shape])
        self.assertEqual(list(matching.employers(need).values_list("pk",flat=True)),[correct.pk])
        self.assertIn("غير محددة",matching.employer_evidence(need,matching.employers(need).get())["geography"])

    def test_cross_offering_employment_does_not_match(self):
        need=self.funded(operational=True)
        org=self.organization(shapes=[self.shape]);shape=SponsorshipShape.objects.create(name="توظيف قطاع آخر",is_employment=True)
        row=PartnershipOffering.objects.create(partnership=org,sector=self.sector2,sponsorship_shape=shape);row.specializations.add(self.spec2)
        self.assertFalse(matching.employers(need).exists())

    def test_required_selections_for_running_and_operational(self):
        need=self.funded(operational=True); item=self.provider(); org=self.employer()
        with self.assertRaises(ExecutionConflict):self.save(need,status="running")
        with self.assertRaises(ExecutionConflict):self.save(need,[item.pk],status="running")
        result=self.save(need,[item.pk],[org.pk],status="running")
        self.assertEqual(result.status,"running")

    def test_save_does_not_change_funding_or_organization_state(self):
        need=self.funded(operational=True); item=self.provider(); org=self.employer()
        old_time=org.development_state_at;count=need.sponsorships.count()
        self.save(need,[item.pk],[org.pk],status="running")
        need.refresh_from_db();org.refresh_from_db()
        self.assertEqual(need.approved_support,need.total_cost);self.assertEqual(need.status,"complete")
        self.assertEqual(need.sponsorships.count(),count);self.assertEqual(org.development_state_id,"capability");self.assertEqual(org.development_state_at,old_time)

    def test_completion_locks_even_superuser_and_preserves_time(self):
        need=self.funded(); item=self.provider()
        execution=self.save(need,[item.pk],status="complete")
        entered=execution.completed_at
        with self.assertRaises(ExecutionConflict):self.save(need,[item.pk],status="new")
        execution.refresh_from_db();self.assertEqual(execution.completed_at,entered)
        self.assertEqual(execution.version,1)

    def test_duplicate_submission_and_altered_replay(self):
        need=self.funded(); item=self.provider();nonce=uuid.uuid4()
        result=self.save(need,[item.pk],nonce=nonce)
        repeated=self.save(need,[item.pk],nonce=nonce,expected_version=0)
        self.assertEqual(repeated.pk,result.pk);self.assertEqual(result.provider_links.count(),1)
        self.assertEqual(need.events.filter(action__startswith="تنفيذ").count(),1)
        with self.assertRaises(ExecutionConflict):self.save(need,[item.pk],nonce=nonce,data={"providers":[item.pk],"employers":[],"status":"new","notes":"طلب مختلف"})

    def test_stale_version_candidate_and_atomic_failure(self):
        need=self.funded(); item=self.provider();self.save(need,[item.pk])
        with self.assertRaises(ExecutionConflict):self.save(need,[item.pk],expected_version=0)
        with self.assertRaises(ExecutionConflict):self.save(need,[999999])
        execution=NeedExecution.objects.get(need=need);self.assertEqual(execution.version,1);self.assertEqual(execution.provider_links.get().provider_id,item.pk)

    def test_prior_inactive_reference_can_remain_draft_not_start(self):
        need=self.funded(); item=self.provider(); self.save(need,[item.pk])
        ServiceProvider.objects.filter(pk=item.pk).update(is_active=False)
        self.save(need,[item.pk],status="new")
        with self.assertRaises(ExecutionConflict):self.save(need,[item.pk],status="running")

    def test_selected_reference_deletion_and_deactivation_are_blocked(self):
        need=self.funded(operational=True); item=self.provider(); org=self.employer(); self.save(need,[item.pk],[org.pk])
        for record in (item,org,need):
            with self.subTest(record=record):
                with self.assertRaises(DependencyBlocked):ensure_allowed(record,"delete")
                with self.assertRaises(DependencyBlocked):ensure_allowed(record,"deactivate",False)

    def test_provider_program_requirement_preserves_legacy_unknown(self):
        item=self.provider(program=False)
        self.assertIsNone(item.program_id)
        form=ProviderForm(instance=item)
        self.assertFalse(form.fields["program"].required)
        self.assertTrue(ProviderForm().fields["program"].required)

    def test_unique_execution_and_provider_constraints(self):
        need=self.funded(); item=self.provider();execution=self.save(need,[item.pk])
        with self.assertRaises(IntegrityError),transaction.atomic():
            NeedExecution.objects.create(need=need)
        with self.assertRaises(IntegrityError),transaction.atomic():
            ExecutionProvider.objects.create(execution=execution,provider=item)

    def test_headers_details_and_search_are_rendered(self):
        need=self.funded()
        response=self.client.get(reverse("program_execution:index"),{"q":need.sector.name,"detail":need.pk})
        self.assertEqual(response.status_code,200)
        for text in ("حالة التنفيذ","تكلفة البرنامج","عدد المتدربين","شكل الرعاية","سجل دورة الحياة"):
            self.assertContains(response,text)
        self.assertEqual(response.context["page_obj"].paginator.count,1)

    def test_server_preview_and_confirmation(self):
        need=self.funded();item=self.provider();url=reverse("program_execution:assignment",args=[need.pk])
        response=self.client.get(url)
        response=self.client.post(url,{"action":"preview","snapshot":response.context["snapshot"],"status":"running","notes":"ملاحظات","selection":json.dumps({"providers":[item.pk],"employers":[]})})
        self.assertEqual(response.status_code,200);self.assertFalse(NeedExecution.objects.exists())
        response=self.client.post(url,{"action":"confirm","snapshot":response.context["pending"]["snapshot"]})
        self.assertEqual(response.status_code,302);self.assertEqual(NeedExecution.objects.get().status,"running")

    def grant(self, operations, module="provider_assignments"):
        user=get_user_model().objects.create_user(username="execution-role-"+str(uuid.uuid4()),password="Safe!Test123")
        UserAccess.objects.update_or_create(user=user,defaults={"page_scope":"all"})
        user.user_permissions.add(*Permission.objects.filter(content_type__app_label="access_control",codename__in=[op+"_"+module for op in operations]))
        return user

    def test_watcher_cannot_mutate_and_cannot_open_ungranted_page(self):
        need=self.funded();user=self.grant(["view"]);self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("program_execution:index")).status_code,403)
        url=reverse("program_execution:assignment",args=[need.pk]);response=self.client.get(url)
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.post(url,{"action":"preview","snapshot":response.context["snapshot"],"status":"new","selection":'{"providers":[],"employers":[]}'}).status_code,403)
        with self.assertRaises(PermissionDenied):self.save(need,actor=user)

    def test_edit_without_status_permission_and_explicit_deny(self):
        need=self.funded();item=self.provider();self.save(need,[item.pk])
        user=self.grant(["view","edit"])
        self.save(need,[item.pk],actor=user)
        with self.assertRaises(PermissionDenied):self.save(need,[item.pk],status="running",actor=user)
        PermissionOverride.objects.create(user=user,module_id="provider_assignments",operation="edit",effect="deny")
        with self.assertRaises(PermissionDenied):self.save(need,[item.pk],actor=user)

    def test_format_export_rights_and_unauthorized_candidates(self):
        need=self.funded();user=self.grant(["view"],"approved_programs");self.client.force_login(user)
        url=reverse("program_execution:index")
        self.assertEqual(self.client.get(url,{"_mk_export":"xlsx","_mk_table":"0"}).status_code,403)
        permission=Permission.objects.get(codename="export_xlsx_approved_programs",content_type__app_label="access_control")
        user.user_permissions.add(permission)
        response=self.client.get(url,{"_mk_export":"xlsx","_mk_table":"0"})
        self.assertEqual(response.status_code,200);self.assertTrue(response.content.startswith(b"PK"))
        self.assertEqual(self.client.get(reverse("program_execution:assignment",args=[need.pk]),{"kind":"employer","candidate":need.sponsorships.first().partnership_id}).status_code,403)

    def test_csrf_and_tampered_confirmation(self):
        need=self.funded();url=reverse("program_execution:assignment",args=[need.pk])
        client=Client(enforce_csrf_checks=True);client.force_login(self.user)
        self.assertEqual(client.post(url,{"action":"confirm","snapshot":"bad"}).status_code,403)
        self.assertEqual(self.client.post(url,{"action":"confirm","snapshot":"bad"}).status_code,409)

    def test_new_permissions_exist_without_automatic_grants(self):
        self.assertTrue(Module.objects.filter(pk="provider_assignments").exists())
        permissions=Permission.objects.filter(codename__endswith="_provider_assignments",content_type__app_label="access_control")
        self.assertEqual(permissions.count(),6)
        self.assertFalse(permissions.filter(group__isnull=False).exists())
