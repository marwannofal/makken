# MAKKEN DEPENDENCY TEST POLICY v1
from core.dependencies import DependencyBlocked
import json
import uuid
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from care_states.models import StateColor, DevelopmentState
from entities.models import Entity
from regions.models import Region
from sectors.models import Sector
from specializations.models import Specialization
from expense_items.models import ExpenseItem
from training_programs.models import TrainingProgram
from sponsorship_shapes.models import SponsorshipShape
from partnerships.models import Partnership, PartnershipOffering, DevelopmentHistory
from partnerships.forms import PartnershipForm
from market_needs.models import Need, ExpenseLine, Sponsorship, SupportAttachment, AuditEvent, NeedStatus, SponsorshipStatus
from market_needs.forms import NeedForm, FollowupForm
from market_needs.matching import candidates, explain
from market_needs import services


class MarketFixtures:
    @classmethod
    def setUpTestData(cls):
        from levels.models import Level
        for key, label in [('bronze','برونزي'),('silver','فضي'),('gold','ذهبي'),('strategic','استراتيجي')]:
            Level.objects.get_or_create(funding_key=key, defaults={'name':label})
        cls.user = get_user_model().objects.create_user(username='market-tests', password='Makken!SafeTest930')
        cls.other = get_user_model().objects.create_user(username='market-other', password='Makken!OtherSafe931')
        for state,color in [('capability','#ba1d1d'),('willingness','#fdd2cf'),('care','#1c5d34')]:
            StateColor.objects.update_or_create(state=state, defaults={'color':color})
        cls.region = Region.objects.create(name='منطقة تجريبية الأولى')
        cls.region2 = Region.objects.create(name='منطقة تجريبية الثانية')
        cls.sector = Sector.objects.create(name='قطاع الاختبار')
        cls.sector2 = Sector.objects.create(name='قطاع آخر')
        cls.spec = Specialization.objects.create(name='تخصص الاختبار',sector=cls.sector)
        cls.spec2 = Specialization.objects.create(name='تخصص آخر',sector=cls.sector2)
        cls.expense = ExpenseItem.objects.create(name='تكلفة تدريب تجريبية')
        cls.expense2 = ExpenseItem.objects.create(name='معدات تجريبية')
        cls.shape = SponsorshipShape.objects.create(name='رعاية تدريب اختبار')
        cls.shape2 = SponsorshipShape.objects.create(name='رعاية معدات اختبار')
        cls.program = TrainingProgram.objects.create(name='برنامج تجريبي',category='qualifying_program',is_training=True,is_operational=False)
        cls.program.expense_items.set([cls.expense,cls.expense2])
        cls.entity = Entity.objects.create(name='كيان الاختبار',entity_type='government',branch='')

    def setUp(self):
        self.client.force_login(self.user,backend='accounts.backends.EmailOrUsernameBackend')
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        setting=override_settings(MAKKEN_PRIVATE_UPLOAD_ROOT=self.temp.name);setting.enable();self.addCleanup(setting.disable)

    def data(self,**changes):
        data={'title':'حاجة سوق تجريبية','sector':str(self.sector.pk),'specialization':str(self.spec.pk),'regions':[str(self.region.pk),str(self.region2.pk)],'description':'تدريب وتأهيل المستفيدين','duration':'3','duration_unit':'month','source':'دراسة السوق','beneficiaries':'3','program':str(self.program.pk),'requested_support':'90.00','observed_on':'2026-10-18','is_active':'1','lines':json.dumps([{'expense':self.expense.pk,'shape':self.shape.pk,'amount':'60.00'},{'expense':self.expense2.pk,'shape':self.shape2.pk,'amount':'40.00'}])}
        data.update(changes);return data

    def create_need(self,**changes):
        return services.save_need(self.data(**changes),self.user,nonce=str(uuid.uuid4()))

    def organization(self,name='جهة تجريبية',shapes=None,state='willingness',active=True):
        org=Partnership.objects.create(name=name,representative='الممثل',phone='+966501234567',email='person@example.com',entity=self.entity,scope='local',financial_capacity=1,is_active=active,development_state_id=state)
        for shape in shapes if shapes is not None else [self.shape,self.shape2]:
            row=PartnershipOffering.objects.create(partnership=org,sector=self.sector,sponsorship_shape=shape)
            row.specializations.add(self.spec)
        return org

    def attach(self,need,org):
        need.refresh_from_db();services.add_candidates(need.pk,need.version,[org.pk],{},self.user);need.refresh_from_db()
        return need.sponsorships.get(partnership=org)

    def approve(self,need,record,amount='20.00',files=None):
        need.refresh_from_db();record.refresh_from_db()
        from market_needs.funding import expense_funding
        data={'amount':amount,'notes':'تم التواصل'}
        try:
            remaining=Decimal(amount)
            for line in expense_funding(need):
                value=min(max(remaining,Decimal('0')),line.remaining_amount)
                if value>0:data[f'allocation_{line.pk}']=str(value)
                remaining-=value
        except Exception:
            pass  # Invalid values are intentionally passed through to form validation.
        return services.followup(need.pk,need.version,record.pk,record.version,'approve',data,files or {},self.user)

    def png(self,name='support.png'):
        out=BytesIO();Image.new('RGB',(4,4),'teal').save(out,format='PNG')
        return SimpleUploadedFile(name,out.getvalue(),content_type='image/png')


class NeedCardTests(MarketFixtures,TestCase):
    def test_create_calculations_ignore_client_system_fields(self):
        need=self.create_need(total_cost='1',approved_support='999',status='complete')
        self.assertEqual(need.total_cost,Decimal('100.00'))
        self.assertEqual(need.seat_cost,Decimal('33.33'))
        self.assertEqual(need.status,'new');self.assertEqual(need.approved_support,0)
        self.assertEqual(need.expense_lines.count(),2);self.assertEqual(need.events.count(),1)

    def test_required_range_and_sector_relationship_validation(self):
        for changes in [{'title':''},{'regions':[]},{'beneficiaries':'0'},{'duration':'0'},{'requested_support':'100.01'},{'requested_support':'0'},{'specialization':str(self.spec2.pk)}]:
            with self.subTest(changes=changes):self.assertFalse(NeedForm(self.data(**changes)).is_valid())

    def test_line_validation_duplicate_unrelated_inactive_and_amounts(self):
        base={'expense':self.expense.pk,'shape':self.shape.pk,'amount':'1.00'}
        other=ExpenseItem.objects.create(name='بند خارج البرنامج')
        for rows in [[],[base,base],[dict(base,expense=other.pk)],[dict(base,amount='0')],[dict(base,amount='NaN')],[dict(base,amount='1.001')],[dict(base,expense=True)]]:
            with self.subTest(rows=rows):self.assertFalse(NeedForm(self.data(lines=json.dumps(rows))).is_valid())

    def test_dependencies_need_confirmation(self):
        need=self.create_need();other=TrainingProgram.objects.create(name='برنامج آخر',category='qualifying_course');other.expense_items.set([self.expense,self.expense2])
        form=NeedForm(self.data(program=str(other.pk)),instance=need)
        self.assertFalse(form.is_valid());self.assertIn('dependencies_confirmed',form.errors)
        self.assertTrue(NeedForm(self.data(program=str(other.pk),dependencies_confirmed='true'),instance=need).is_valid())

    def test_historical_inactive_references_preserved_no_new_selection(self):
        need=self.create_need()
        for obj in [self.sector,self.spec,self.region,self.shape,self.expense,self.program]:
            obj.is_active=False;type(obj).objects.filter(pk=obj.pk).update(is_active=False)
        self.assertTrue(NeedForm(self.data(),instance=need).is_valid())
        self.assertFalse(NeedForm(self.data()).is_valid())
        # An inactive shape cannot be moved onto a different line.
        rows=[{'expense':self.expense.pk,'shape':self.shape.pk,'amount':'60'},{'expense':self.expense2.pk,'shape':self.shape.pk,'amount':'40'}]
        self.assertFalse(NeedForm(self.data(lines=json.dumps(rows)),instance=need).is_valid())

    def test_approved_financial_and_matching_basis_locked_but_description_editable(self):
        need=self.create_need();record=self.attach(need,self.organization());self.approve(need,record)
        need.refresh_from_db()
        for changes in [{'requested_support':'99'},{'beneficiaries':'4'},{'regions':[str(self.region.pk)]},{'lines':json.dumps([{'expense':self.expense.pk,'shape':self.shape.pk,'amount':'100'}])}]:
            with self.subTest(changes=changes),self.assertRaises(services.Conflict):services.save_need(self.data(**changes),self.user,need.pk,need.version)
        saved=services.save_need(self.data(description='وصف محدث'),self.user,need.pk,need.version)
        self.assertEqual(saved.description,'وصف محدث');self.assertEqual(saved.approved_support,20)

    def test_stale_edit_replay_and_duplicate_creation_rejected(self):
        nonce=str(uuid.uuid4());need=services.save_need(self.data(),self.user,nonce=nonce)
        with self.assertRaises(services.Conflict):services.save_need(self.data(),self.user,nonce=nonce)
        services.save_need(self.data(title='عنوان معدل'),self.user,need.pk,need.version)
        with self.assertRaises(services.Conflict):services.save_need(self.data(),self.user,need.pk,need.version)

    def test_delete_protection_and_delete_history_retained(self):
        need=self.create_need();record=self.attach(need,self.organization());self.approve(need,record)
        need.refresh_from_db()
        with self.assertRaises(DependencyBlocked):services.card_action(need.pk,need.version,'delete',self.user)
        empty=self.create_need();number=empty.number;services.card_action(empty.pk,empty.version,'delete',self.user)
        self.assertTrue(AuditEvent.objects.filter(need_number=number,action='حذف البطاقة',need__isnull=True).exists())

    def test_database_constraints(self):
        need=self.create_need()
        for change in [{'approved_support':Decimal('100.01')},{'total_cost':0},{'status':'forged'}]:
            with self.subTest(change=change),self.assertRaises(IntegrityError),transaction.atomic():Need.objects.filter(pk=need.pk).update(**change)

    def test_regions_cannot_be_deleted_when_historical_relationships_exist(self):
        need=self.create_need()
        with self.assertRaises(ProtectedError):self.region.delete()
        self.assertEqual(need.regions.count(),2)


class MatchingTests(MarketFixtures,TestCase):
    def test_program_required_shapes_full_and_partial_matches_unique_small_capacity(self):
        need=self.create_need();full=self.organization();partial=self.organization('جهة جزئية',shapes=[self.shape])
        found=explain(need,candidates(need));self.assertEqual({m.organization.pk for m in found},{full.pk,partial.pk})
        self.assertTrue(next(m for m in found if m.organization.pk==full.pk).full)
        row=next(m for m in found if m.organization.pk==partial.pk);self.assertFalse(row.full);self.assertEqual(len(row.lines),1)
        self.assertEqual(candidates(need).count(),2)

    def test_cross_offering_false_matches_blocked(self):
        need=self.create_need();org=self.organization(shapes=[])
        one=PartnershipOffering.objects.create(partnership=org,sector=self.sector,sponsorship_shape=self.shape);one.specializations.add(self.spec2)
        two=PartnershipOffering.objects.create(partnership=org,sector=self.sector2,sponsorship_shape=self.shape2);two.specializations.add(self.spec)
        self.assertFalse(candidates(need).filter(pk=org.pk).exists())

    def test_regions_do_not_affect_matching_or_require_partnership_data(self):
        need=self.create_need();org=self.organization()
        self.assertFalse(hasattr(org,'coverage_regions'))
        self.assertTrue(candidates(need).filter(pk=org.pk).exists())
        need.regions.set([self.region]);self.region.is_active=False;type(self.region).objects.filter(pk=self.region.pk).update(is_active=False)
        self.assertTrue(candidates(need).filter(pk=org.pk).exists())
        org.scope='global';org.save()
        self.assertTrue(candidates(need).filter(pk=org.pk).exists())

    def test_all_states_with_active_shared_data_are_eligible(self):
        need=self.create_need();willing=self.organization()
        capability=self.organization('قدرة غير مؤهلة',state='capability')
        care=self.organization('رعاية غير مؤهلة',state='care')
        inactive=self.organization('جهة غير نشطة',active=False)
        wrong=self.organization('عرض غير نشط');wrong.offerings.update(is_active=False)
        wrong_spec=self.organization('تخصص مختلف');wrong_spec.offerings.first().specializations.set([self.spec2]);wrong_spec.offerings.last().specializations.set([self.spec2])
        unrelated_shape=SponsorshipShape.objects.create(name='شكل خارج حاجة البرنامج')
        wrong_shape=self.organization('شكل غير مطلوب',shapes=[unrelated_shape])
        self.assertEqual(set(candidates(need)),{willing,capability,care})
        for org in [inactive,wrong,wrong_spec,wrong_shape]:
            self.assertFalse(candidates(need,{'states':['capability','willingness','care']}).filter(pk=org.pk).exists())
        for obj in [self.program,self.entity,self.sector,self.spec,self.shape,self.shape2]:
            with self.subTest(reference=type(obj).__name__):
                obj.is_active=False;type(obj).objects.filter(pk=obj.pk).update(is_active=False)
                if obj in [self.shape,self.shape2]:
                    # One remaining required shape still yields a partial match.
                    self.shape.is_active=False;type(self.shape).objects.filter(pk=self.shape.pk).update(is_active=False);self.shape2.is_active=False;type(self.shape2).objects.filter(pk=self.shape2.pk).update(is_active=False)
                self.assertFalse(candidates(need).filter(pk=willing.pk).exists())
                obj.is_active=True;obj.save()
                self.shape.is_active=True;self.shape.save();self.shape2.is_active=True;self.shape2.save()

    def test_scope_and_state_filters_support_single_multiple_and_all(self):
        need=self.create_need();local=self.organization();other=self.organization('جهة عالمية');other.scope='global';other.save()
        self.assertEqual(candidates(need,{'states':['capability','willingness'],'scopes':['global']}).get(),other)
        self.assertFalse(candidates(need,{'states':['capability','care']}).exists())
        self.attach(need,local);self.assertFalse(candidates(need).filter(pk=local.pk).exists())
        from market_needs.forms import MatchFilterForm
        self.assertTrue(MatchFilterForm({'states':['capability']}).is_valid())
        self.assertTrue(MatchFilterForm({'states':['care']}).is_valid())
        self.assertFalse(MatchFilterForm({'states':['invented']}).is_valid())
        self.assertTrue(MatchFilterForm({'states':['willingness']}).is_valid())

    def test_every_state_filter_or_and_scope_intersection(self):
        need=self.create_need();organizations={state:self.organization('جهة '+state,state=state) for state in DevelopmentState.values}
        self.assertEqual(set(candidates(need).values_list('pk',flat=True)),{o.pk for o in organizations.values()})
        for state,org in organizations.items():
            with self.subTest(state=state):
                self.assertEqual(list(candidates(need,{'states':[state]})),[org])
        self.assertEqual(set(candidates(need,{'states':['capability','care']}).values_list('pk',flat=True)),{organizations['capability'].pk,organizations['care'].pk})
        org=organizations['care'];org.scope='global';org.save()
        self.assertEqual(list(candidates(need,{'states':['capability','care'],'scopes':['global']})),[org])
        self.assertFalse(candidates(need,{'states':['willingness'],'scopes':['global']}).exists())

    def test_candidate_addition_revalidates_selected_states(self):
        need=self.create_need();org=self.organization(state='capability')
        with self.assertRaises(services.Conflict):services.add_candidates(need.pk,need.version,[org.pk],{'states':['willingness']},self.user)
        services.add_candidates(need.pk,need.version,[org.pk],{'states':['capability','care']},self.user)
        self.assertTrue(need.sponsorships.filter(partnership=org).exists())

    def test_unrelated_program_expense_shapes_are_not_used(self):
        need=self.create_need();org=self.organization(shapes=[self.shape2])
        self.assertTrue(candidates(need).filter(pk=org.pk).exists())
        different=TrainingProgram.objects.create(name='برنامج ببند آخر',category='qualifying_course')
        different.expense_items.add(self.expense)
        updated=services.save_need(self.data(program=str(different.pk),dependencies_confirmed='true',lines=json.dumps([{'expense':self.expense.pk,'shape':self.shape.pk,'amount':'100'}])),self.user,need.pk,need.version)
        self.assertFalse(candidates(updated).filter(pk=org.pk).exists())
        self.assertEqual(list(updated.expense_lines.values_list('expense_item_id',flat=True)),[self.expense.pk])

    def test_search_read_only_and_duplicate_addition(self):
        need=self.create_need();org=self.organization();url=reverse('market_needs:followup',args=[need.pk])
        before=AuditEvent.objects.count();response=self.client.get(url)
        self.assertEqual(response.status_code,200);need.refresh_from_db();self.assertEqual(need.status,'new');self.assertEqual(need.version,1);self.assertEqual(before,AuditEvent.objects.count())
        self.assertFalse(need.sponsorships.exists());self.attach(need,org)
        with self.assertRaises(services.Conflict):services.add_candidates(need.pk,need.version,[org.pk],{},self.user)
        with self.assertRaises(IntegrityError),transaction.atomic():Sponsorship.objects.create(need=need,partnership=org)

    def test_revalidation_after_results_change(self):
        need=self.create_need();org=self.organization();self.assertTrue(candidates(need).exists());org.is_active=False;type(org).objects.filter(pk=org.pk).update(is_active=False)
        with self.assertRaises(services.Conflict):services.add_candidates(need.pk,need.version,[org.pk],{},self.user)
        self.assertFalse(need.sponsorships.exists())


class FundingTests(MarketFixtures,TestCase):
    def test_approval_willingness_to_care_preserves_history(self):
        need=self.create_need();org=self.organization();entered=org.development_state_at;record=self.attach(need,org);self.approve(need,record,'25')
        org.refresh_from_db();need.refresh_from_db();self.assertEqual(org.development_state_id,'care');self.assertEqual(need.funding_percent,Decimal('25.00'));self.assertEqual(need.status,'working')
        self.assertEqual(org.development_history.get(state_id='willingness').entered_at,entered);self.assertFalse(org.development_history.filter(state_id='capability').exists())

    def test_care_timestamp_preserved_for_previously_linked_other_card(self):
        org=self.organization();one=self.create_need();two=self.create_need()
        first=self.attach(one,org);second=self.attach(two,org)
        self.approve(one,first)
        org.refresh_from_db();entered=org.development_state_at
        self.assertTrue(candidates(self.create_need()).filter(pk=org.pk).exists())
        self.approve(two,second)
        org.refresh_from_db();self.assertEqual(org.development_state_at,entered);self.assertEqual(org.development_history.filter(state_id='care').count(),1)

    def test_capability_approval_goes_directly_to_care_without_fake_agreement(self):
        need=self.create_need();org=self.organization(state='capability');entered=org.development_state_at
        record=self.attach(need,org);self.approve(need,record)
        record.refresh_from_db();org.refresh_from_db()
        self.assertEqual(record.status,'approved');self.assertEqual(org.development_state_id,'care')
        self.assertEqual(org.development_history.get(state_id='capability').entered_at,entered)
        self.assertFalse(org.development_history.filter(state_id='willingness').exists())
        self.assertEqual(org.preliminary_agreement_type,'')

    def test_new_care_candidate_approval_preserves_original_timestamp(self):
        org=self.organization(state='care');entered=org.development_state_at
        DevelopmentHistory.objects.create(partnership=org,state_id='care',entered_at=entered)
        need=self.create_need();record=self.attach(need,org);self.approve(need,record)
        org.refresh_from_db();self.assertEqual(org.development_state_at,entered)
        self.assertEqual(org.development_history.filter(state_id='care').count(),1)

    def test_alliance_total_complete_and_overfunding(self):
        need=self.create_need();one=self.attach(need,self.organization());two=self.attach(need,self.organization('الجهة الثانية'))
        self.approve(need,one,'40.01');need.refresh_from_db();self.assertEqual(need.arrangement,'مساهمة واحدة جزئية')
        with self.assertRaises(services.Conflict):self.approve(need,two,'60')
        self.approve(need,two,'59.99');need.refresh_from_db();self.assertEqual(need.status,'complete');self.assertEqual(need.approved_support,100);self.assertEqual(need.remaining,0);self.assertEqual(need.arrangement,'تحالف')

    def test_single_full_contribution_individual(self):
        need=self.create_need();row=self.attach(need,self.organization());self.approve(need,row,'100');need.refresh_from_db();self.assertEqual(need.arrangement,'فردي')

    def test_rejection_required_final_card_rejected_and_other_card_allowed(self):
        need=self.create_need();org=self.organization();record=self.attach(need,org)
        with self.assertRaises(services.InvalidForm):services.followup(need.pk,need.version,record.pk,record.version,'reject',{'rejection_reason':'   '},{},self.user)
        services.followup(need.pk,need.version,record.pk,record.version,'reject',{'rejection_reason':'لا تتوفر ميزانية'},{},self.user)
        need.refresh_from_db();record.refresh_from_db();self.assertEqual(need.status,'rejected')
        with self.assertRaises(services.Conflict):self.approve(need,record)
        other=self.create_need();self.assertTrue(candidates(other).filter(pk=org.pk).exists())

    def test_pending_or_partial_support_keeps_card_working(self):
        need=self.create_need();one=self.attach(need,self.organization());two=self.attach(need,self.organization('جهة أخرى'))
        self.approve(need,one);need.refresh_from_db();services.followup(need.pk,need.version,two.pk,two.version,'reject',{'rejection_reason':'اعتذار'},{},self.user)
        need.refresh_from_db();self.assertEqual(need.status,'working');self.assertEqual(need.approved_support,20)

    def test_stale_second_approval_and_terminal_replay(self):
        need=self.create_need();one=self.attach(need,self.organization());two=self.attach(need,self.organization('جهة أخرى'));old=need.version
        self.approve(need,one,'75')
        with self.assertRaises(services.Conflict):services.followup(need.pk,old,two.pk,two.version,'approve',{'amount':'75'},{},self.user)
        with self.assertRaises(services.Conflict):self.approve(need,one,'75')
        self.assertEqual(Sponsorship.objects.filter(need=need,status='approved').count(),1)

    def test_approval_requires_amount_and_current_eligibility(self):
        need=self.create_need();org=self.organization();row=self.attach(need,org)
        for value in ['', '0','-1','1.001','Infinity']:
            with self.subTest(value=value),self.assertRaises(services.InvalidForm):self.approve(need,row,value)
        org.is_active=False;type(org).objects.filter(pk=org.pk).update(is_active=False)
        with self.assertRaises(services.Conflict):self.approve(need,row)

    def test_optional_real_private_attachments_and_authenticated_download(self):
        need=self.create_need();record=self.attach(need,self.organization());self.approve(need,record,files={'attachments':[self.png()]})
        attachment=SupportAttachment.objects.get(sponsorship=record);self.assertTrue(attachment.file.name.startswith('market-support/'))
        with self.assertRaises(ValueError):_ = attachment.file.url
        url=reverse('market_needs:download',args=[need.pk,attachment.pk]);response=self.client.get(url);self.assertEqual(response.status_code,200);self.assertIn('attachment',response['Content-Disposition']);self.assertIn('no-store',response['Cache-Control']);self.assertEqual(len(b"".join(response.streaming_content)), attachment.size)
        # Consuming Client's streaming iterator closes the response through its
        # connection-safe wrapper. Direct close() ends TestCase's MySQL session.
        self.assertTrue(response.closed)
        self.assertTrue(SupportAttachment.objects.filter(pk=attachment.pk).exists())
        self.assertEqual(Client().get(url).status_code,302);self.assertEqual(self.client.get(reverse('market_needs:download',args=[999999,attachment.pk])).status_code,404)

    def test_invalid_files_no_state_or_partial_save(self):
        need=self.create_need();org=self.organization();record=self.attach(need,org);before=org.development_state_at
        with self.assertRaises(services.InvalidForm):self.approve(need,record,files={'attachments':[SimpleUploadedFile('fake.pdf',b'not a PDF')]})
        org.refresh_from_db();record.refresh_from_db();self.assertEqual(record.status,'new');self.assertEqual(org.development_state_at,before);self.assertFalse(SupportAttachment.objects.exists())

    def test_storage_failure_rolls_back_and_cleans_files(self):
        need=self.create_need();org=self.organization();record=self.attach(need,org)
        with patch.object(SupportAttachment.objects,'create',side_effect=IntegrityError('storage metadata failure')):
            with self.assertRaises(IntegrityError):self.approve(need,record,files={'attachments':[self.png()]})
        record.refresh_from_db();org.refresh_from_db();need.refresh_from_db();self.assertEqual(record.status,'new');self.assertEqual(org.development_state_id,'willingness');self.assertEqual(need.approved_support,0)
        self.assertFalse([p for p in Path(self.temp.name).rglob('*') if p.is_file()])

    @override_settings(MAKKEN_SUPPORT_MAX_FILES=1,MAKKEN_SUPPORT_MAX_FILE_SIZE=32)
    def test_configurable_limits(self):
        self.assertFalse(FollowupForm({'amount':'1'},{'attachments':[self.png(),self.png('second.png')]},operation='approve').is_valid())
        self.assertFalse(FollowupForm({'amount':'1'},{'attachments':[self.png()]},operation='approve').is_valid())


class ViewSecurityTests(MarketFixtures,TestCase):
    def test_authentication_csrf_tokens_and_cross_user(self):
        for url in ['/market-needs/','/market-needs/new/']:
            self.assertEqual(Client().get(url).status_code,302)
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.user,backend='accounts.backends.EmailOrUsernameBackend');self.assertEqual(secure.post('/market-needs/new/',self.data()).status_code,403)
        response=self.client.get('/market-needs/new/');self.assertEqual(response.status_code,200);snapshot=response.context['snapshot']
        self.assertEqual(self.client.post('/market-needs/new/',self.data(snapshot=snapshot+'bad')).status_code,409)
        self.client.force_login(self.other,backend='accounts.backends.EmailOrUsernameBackend');self.assertEqual(self.client.post('/market-needs/new/',self.data(snapshot=snapshot)).status_code,409)

    def test_render_list_details_editor_followup_filters_and_xhr_errors(self):
        need=self.create_need();org=self.organization();record=self.attach(need,org)
        for path in ['/market-needs/',f'/market-needs/?detail={need.pk}',f'/market-needs/{need.pk}/edit/',f'/market-needs/{need.pk}/sponsors/']:
            response=self.client.get(path);self.assertEqual(response.status_code,200,path);self.assertIn('no-store',response['Cache-Control'])
        response=self.client.get('/market-needs/',{'q':need.number,'state':'working','active':'1'});self.assertEqual(response.context['page_obj'].paginator.count,1)
        url=reverse('market_needs:followup',args=[need.pk]);response=self.client.get(url);snap=response.context['records'][0]['approve_token']
        bad=self.client.post(url,{'snapshot':snap,'amount':'0'},HTTP_X_REQUESTED_WITH='XMLHttpRequest');self.assertEqual(bad.status_code,400);self.assertIn('amount',bad.json()['fields'])

    def test_nojs_followup_link_and_post(self):
        need=self.create_need();record=self.attach(need,self.organization());url=reverse('market_needs:followup',args=[need.pk]);response=self.client.get(url,{'record':record.pk,'operation':'notes'})
        self.assertTrue(response.context['reopen_followup']);snap=response.context['followup_snapshot'];saved=self.client.post(url,{'snapshot':snap,'notes':'متابعة بدون جافاسكربت'});self.assertEqual(saved.status_code,302)
        record.refresh_from_db();self.assertEqual(record.notes,'متابعة بدون جافاسكربت')

    def test_partnership_editor_and_details_no_longer_request_or_show_coverage(self):
        org=self.organization();response=self.client.get('/partnerships/',{'detail':org.pk})
        self.assertNotContains(response,'مناطق التغطية');self.assertNotContains(response,'بيانات التغطية غير مكتملة')
        editor=self.client.get(reverse('partnerships:edit',args=[org.pk]))
        self.assertNotContains(editor,'id_coverage_regions')
        self.assertNotIn('coverage_regions',PartnershipForm().fields)
        self.assertFalse(hasattr(org,'coverage_regions'))

    def test_state_filter_ui_and_search_are_read_only(self):
        need=self.create_need();organizations={state:self.organization('عرض '+state,state=state) for state in DevelopmentState.values}
        url=reverse('market_needs:followup',args=[need.pk]);before=AuditEvent.objects.count()
        for states in [[],['capability'],['willingness'],['care'],['capability','care']]:
            response=self.client.get(url,{'states':states});self.assertEqual(response.status_code,200)
            found={match.organization.pk for match in response.context['matches']}
            self.assertEqual(found,{organizations[state].pk for state in states or DevelopmentState.values})
            self.assertContains(response,'name="states"',count=3)
            self.assertNotContains(response,'حالة الشراكات المؤهلة · ثابتة')
        self.assertEqual(AuditEvent.objects.count(),before);self.assertFalse(need.sponsorships.exists())
        self.assertEqual(self.client.get(url,{'states':['invalid']}).status_code,400)

    def test_escaping_user_content(self):
        need=self.create_need();Need.objects.filter(pk=need.pk).update(title='<script>alert(1)</script>')
        response=self.client.get('/market-needs/');self.assertContains(response,'&lt;script&gt;');self.assertNotContains(response,'<script>alert(1)</script>')
