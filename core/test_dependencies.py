"""Business references must block deactivate/delete through every write path."""
import importlib
import json
from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from core.dependencies import DependencyBlocked, ensure_allowed, references_for
from market_needs.tests.test_market import MarketFixtures
from market_needs.models import Need, Sponsorship, SponsorshipStatus, AuditEvent
from market_needs import services as market_services
from partnerships.models import Partnership, DevelopmentHistory
from partnerships import views as partnership_views
from service_providers.models import ServiceProvider, ProviderCoverage, CoverageSpecialization, ProviderAudit
from service_providers import services as provider_services
from levels.models import Level
from regions.models import Region
from sectors.models import Sector
from specializations.models import Specialization
from expense_items.models import ExpenseItem
from training_programs.models import TrainingProgram
from sponsorship_shapes.models import SponsorshipShape
from entities.models import Entity


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DependencyTests(MarketFixtures, TestCase):
    def linked_records(self):
        need = self.create_need()
        org = self.organization()
        level = Level.objects.get(funding_key='bronze')
        record = Sponsorship.objects.create(need=need, partnership=org, level=level)
        return need, org, level, record

    def assert_blocked_unchanged(self, item):
        model = type(item);pk = item.pk
        for operation in ('delete', 'toggle', 'edit'):
            with self.subTest(model=model._meta.label, operation=operation):
                with self.assertRaises(DependencyBlocked) as raised:
                    ensure_allowed(item, operation, active=False)
                self.assertTrue(raised.exception.references)
                self.assertIn('لارتباطه بسجلات أخرى', str(raised.exception))
                self.assertTrue(model.objects.get(pk=pk).is_active)
        item.is_active = False
        with self.assertRaises(DependencyBlocked):
            item.save()
        self.assertTrue(model.objects.get(pk=pk).is_active)
        item.refresh_from_db()

    def test_all_reference_types_block_and_keep_inactive_or_rejected_links(self):
        need, org, level, record = self.linked_records()
        for item in [self.sector, self.spec, self.expense, self.shape, self.program, self.region, self.entity, need, org, level]:
            self.assert_blocked_unchanged(item)
        record.status = SponsorshipStatus.REJECTED;record.rejection_reason = 'اختبار رفض نهائي';record.save()
        # Rejection does not erase the historical association.
        self.assert_blocked_unchanged(need);self.assert_blocked_unchanged(org)
        Partnership.objects.filter(pk=org.pk).update(is_active=False)
        self.assert_blocked_unchanged(self.entity)

    def test_provider_regions_and_specialties_and_historical_link_protected_both_ways(self):
        provider = ServiceProvider.objects.create(name='مزود مرتبط',provider_type='government',scope='local')
        coverage = ProviderCoverage.objects.create(provider=provider,region=self.region,is_active=False)
        coverage.specializations.add(self.spec)
        self.assert_blocked_unchanged(self.region);self.assert_blocked_unchanged(self.spec)
        org = self.organization()
        provider.converted_partnership = org;provider.converted_at = timezone.now();provider.save()
        self.assert_blocked_unchanged(provider)
        self.assertIn('مزودو الخدمات المرتبطون سابقًا',references_for(org))
        for operation in ['toggle', 'delete']:
            with self.assertRaises(DependencyBlocked):
                provider_services.row_action({'id':provider.pk,'version':provider.version,'operation':operation},self.user)
        self.assertFalse(ProviderAudit.objects.filter(provider=provider).exists())
        self.assertEqual(provider.converted_at,ServiceProvider.objects.get(pk=provider.pk).converted_at)

    def test_unlinked_records_still_toggle_reactivate_edit_and_delete_owned_rows(self):
        items = [Region.objects.create(name='منطقة غير مستخدمة'), Sector.objects.create(name='قطاع غير مستخدم'),
                 Specialization.objects.create(name='تخصص غير مستخدم'), ExpenseItem.objects.create(name='بند غير مستخدم'),
                 SponsorshipShape.objects.create(name='شكل غير مستخدم'), Entity.objects.create(name='كيان غير مستخدم',entity_type='government'),
                 Level.objects.create(name='مستوى غير مستخدم'), TrainingProgram.objects.create(name='برنامج غير مستخدم',category='qualifying_program',is_training=True,is_operational=False)]
        # The program's own expense membership is not use by another record.
        items[-1].expense_items.add(self.expense)
        for item in items:
            with self.subTest(model=item._meta.label):
                item.is_active=False;item.save();item.refresh_from_db();self.assertFalse(item.is_active)
                item.is_active=True;item.save();ensure_allowed(item,'delete');item.delete()
        provider=ServiceProvider.objects.create(name='مزود مستقل',provider_type='government',scope='local')
        coverage=ProviderCoverage.objects.create(provider=provider,region=self.region);coverage.specializations.add(self.spec)
        provider_services.row_action({'id':provider.pk,'version':provider.version,'operation':'toggle'},self.user)
        provider.refresh_from_db();self.assertFalse(provider.is_active)
        provider_services.row_action({'id':provider.pk,'version':provider.version,'operation':'delete'},self.user)
        self.assertFalse(ProviderCoverage.objects.filter(pk=coverage.pk).exists())
        self.assertTrue(ProviderAudit.objects.filter(action='delete').exists())
        need=self.create_need();need.expense_lines.exists()
        market_services.card_action(need.pk,need.version,'delete',self.user)
        self.assertFalse(Need.objects.filter(pk=need.pk).exists())
        self.assertTrue(AuditEvent.objects.filter(action='حذف البطاقة').exists())

    def test_settings_preview_all_eight_pages_show_same_arabic_dialog(self):
        need, org, level, record=self.linked_records()
        cases=[('levels',level),('regions',self.region),('entities',self.entity),('specializations',self.spec),('sectors',self.sector),('expense_items',self.expense),('training_programs',self.program),('sponsorship_shapes',self.shape)]
        for app,item in cases:
            view=importlib.import_module(app+'.views')
            for operation in ['delete','toggle']:
                with self.subTest(app=app,operation=operation):
                    response=self.client.post(reverse(app+':index'),{'action':'preview','snapshot':view._snapshot(item,operation,self.user)})
                    self.assertEqual(response.status_code,409)
                    self.assertContains(response,'id="dependency-block"',status_code=409)
                    self.assertTrue(response.context['dependency_block']['references'])
                    self.assertIsNone(response.context.get('pending'))
                    item.refresh_from_db();self.assertTrue(item.is_active)

    def test_edit_previews_use_shared_rule_and_keep_metadata_edit_available(self):
        need,org,level,record=self.linked_records()
        cases=[('levels',level),('regions',self.region),('specializations',self.spec),('expense_items',self.expense)]
        for app,item in cases:
            view=importlib.import_module(app+'.views')
            response=self.client.post(reverse(app+':index'),{'action':'preview','operation':'edit','snapshot':view._snapshot(item,'edit',self.user),'name':item.name,'is_active':'0'})
            self.assertEqual(response.status_code,409,app)
            response=self.client.post(reverse(app+':index'),{'action':'preview','operation':'edit','snapshot':view._snapshot(item,'edit',self.user),'name':item.name+' معدل','is_active':'1'})
            self.assertEqual(response.status_code,200,app)
            self.assertIsNotNone(response.context['pending'])

    def test_relationship_added_after_preview_is_rechecked_on_confirmation(self):
        from entities import views
        fresh=Entity.objects.create(name='كيان قبل الربط',entity_type='government')
        for operation in ['toggle','delete']:
            preview=self.client.post(reverse('entities:index'),{'action':'preview','snapshot':views._snapshot(fresh,operation,self.user)})
            self.assertEqual(preview.status_code,200)
            pending=preview.context['pending']
            org=Partnership.objects.create(name='جهة بعد المعاينة '+operation,representative='ممثل',phone='+966501234567',email='x@example.com',entity=fresh,scope='local')
            response=self.client.post(reverse('entities:index'),{'action':'confirm','token':pending['token']})
            self.assertEqual(response.status_code,409)
            self.assertContains(response,'سجل الشراكات',status_code=409)
            fresh.refresh_from_db();self.assertTrue(fresh.is_active)
            # Remove only this test's association before the next independent preview.
            org.delete()

    def test_sector_delete_does_not_release_specializations_before_checking(self):
        from sectors import views
        snapshot=views._snapshot(self.sector,'delete',self.user)
        response=self.client.post(reverse('sectors:index'),{'action':'preview','snapshot':snapshot})
        self.assertEqual(response.status_code,409)
        self.spec.refresh_from_db();self.assertEqual(self.spec.sector_id,self.sector.pk)
        with self.assertRaises(DependencyBlocked), transaction.atomic():
            Sector.objects.filter(pk=self.sector.pk).delete()
        self.spec.refresh_from_db();self.assertEqual(self.spec.sector_id,self.sector.pk)

    def test_partnership_list_and_editor_reject_deactivation_without_affecting_history(self):
        need,org,level,record=self.linked_records()
        original=(org.version,org.development_state_id,org.development_state_at)
        for operation in ['toggle','delete']:
            signed=partnership_views._sign({'kind':'row','id':org.pk,'version':org.version,'operation':operation},self.user)
            response=self.client.post(reverse('partnerships:index'),{'action':'preview','token':signed})
            self.assertEqual(response.status_code,409)
            self.assertContains(response,'id="dependency-block"',status_code=409)
            response=self.client.post(reverse('partnerships:index'),{'action':'preview','token':signed},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code,409);self.assertIn('متابعة الرعاية',response.json()['error'])
        data=partnership_views._initial(org);data['is_active']='0'
        snapshot=partnership_views._sign({'kind':'editor','id':org.pk,'version':org.version,'nonce':'unused'},self.user)
        response=self.client.post(reverse('partnerships:edit',args=[org.pk]),{**data,'action':'preview','snapshot':snapshot})
        self.assertEqual(response.status_code,409)
        org.refresh_from_db();self.assertTrue(org.is_active)
        self.assertEqual((org.version,org.development_state_id,org.development_state_at),original)
        self.assertEqual(need.sponsorships.count(),1)

    def test_need_editor_list_and_services_cannot_bypass_linked_candidate_rule(self):
        from market_needs import views
        from django.test import RequestFactory
        need,org,level,record=self.linked_records()
        previous=(need.version,need.total_cost,need.status,need.updated_at)
        for operation in ['toggle','delete']:
            request=RequestFactory().post('/');request.user=self.user
            snapshot=views.token(request,need,operation)
            response=self.client.post(reverse('market_needs:index'),{'card':str(need.pk),'snapshot':snapshot})
            self.assertEqual(response.status_code,409)
            self.assertContains(response,'id="dependency-block"',status_code=409)
            with self.assertRaises(DependencyBlocked):market_services.card_action(need.pk,need.version,operation,self.user)
        with self.assertRaises(DependencyBlocked):market_services.save_need(self.data(is_active='0'),self.user,need.pk,need.version)
        need.refresh_from_db();self.assertTrue(need.is_active)
        self.assertEqual((need.version,need.total_cost,need.status,need.updated_at),previous)
        self.assertEqual(need.expense_lines.count(),2)

    def test_existing_inactive_records_keep_state_and_allow_reactivation(self):
        need,org,level,record=self.linked_records()
        Entity.objects.filter(pk=self.entity.pk).update(is_active=False)  # Legacy fixture, not an application action.
        self.entity.refresh_from_db();self.entity.name='كيان تاريخي';self.entity.save()
        self.entity.is_active=True;self.entity.save();self.entity.refresh_from_db();self.assertTrue(self.entity.is_active)

    def test_anonymous_csrf_and_safe_escaping(self):
        need,org,level,record=self.linked_records()
        from entities import views
        from django.test import Client
        response=Client().post(reverse('entities:index'),{'action':'preview'})
        self.assertEqual(response.status_code,302)
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.user,backend='accounts.backends.EmailOrUsernameBackend')
        self.assertEqual(secure.post(reverse('entities:index'),{'action':'preview'}).status_code,403)
        Entity.objects.filter(pk=self.entity.pk).update(name='<img src=x onerror=alert(1)>')
        self.entity.refresh_from_db()
        response=self.client.post(reverse('entities:index'),{'action':'preview','snapshot':views._snapshot(self.entity,'toggle',self.user)})
        self.assertEqual(response.status_code,409)
        self.assertContains(response,'&lt;img src=x onerror=alert(1)&gt;',status_code=409)
        self.assertNotContains(response,'<img src=x onerror=alert(1)>',status_code=409)

    def test_every_dependency_label_is_reported(self):
        need,org,level,record=self.linked_records()
        provider=ServiceProvider.objects.create(name='مزود فحص الروابط',provider_type='government',scope='local',converted_partnership=org,converted_at=timezone.now())
        coverage=ProviderCoverage.objects.create(provider=provider,region=self.region)
        coverage.specializations.add(self.spec)
        expected=[(level,['متابعة الرعاية']), (self.region,['بطاقات حاجة السوق','مزودو الخدمات']),
                  (self.entity,['سجل الشراكات']), (self.spec,['بنود الشراكات','بطاقات حاجة السوق','تخصصات مزودي الخدمات']),
                  (self.sector,['التخصصات','بنود الشراكات','بطاقات حاجة السوق']),
                  (self.expense,['برامج التدريب','بنود بطاقات حاجة السوق']), (self.program,['بطاقات حاجة السوق']),
                  (self.shape,['بنود الشراكات','بنود بطاقات حاجة السوق']),
                  (org,['متابعة الرعاية','مزودو الخدمات المرتبطون سابقًا']), (need,['الجهات المرشحة ومتابعة الرعاية']),
                  (provider,['سجل الشراكات المرتبط سابقًا'])]
        for item,labels in expected:
            with self.subTest(model=item._meta.label):
                self.assertEqual(set(references_for(item)),set(labels))

    def test_provider_editor_and_confirm_recheck_historical_link(self):
        from service_providers import views
        import uuid
        provider=ServiceProvider.objects.create(name='مزود تأكيد الربط',provider_type='government',scope='local')
        coverage=ProviderCoverage.objects.create(provider=provider,region=self.region);coverage.specializations.add(self.spec)
        page=self.client.get(reverse('service_providers:index'))
        pending=self.client.post(reverse('service_providers:index'),{'action':'preview','operation':'toggle','token':views.token({'id':provider.pk,'version':provider.version,'operation':'row'},self.user)})
        self.assertEqual(pending.status_code,200)
        org=self.organization();provider.converted_partnership=org;provider.converted_at=timezone.now();provider.save()
        response=self.client.post(reverse('service_providers:index'),{'action':'confirm','token':pending.context['pending']['token']})
        self.assertEqual(response.status_code,409)
        path=reverse('service_providers:edit',args=[provider.pk]);page=self.client.get(path)
        data=views.initial(provider);data.update(action='preview',snapshot=page.context['snapshot'],is_active='0')
        response=self.client.post(path,data)
        self.assertEqual(response.status_code,409)
        self.assertContains(response,'id="dependency-block"',status_code=409)
        provider.refresh_from_db();self.assertTrue(provider.is_active)
        self.assertFalse(ProviderAudit.objects.filter(provider=provider).exists())

    def test_commit_checks_settings_changes_after_preview_with_no_partial_update(self):
        from regions import views
        region=Region.objects.create(name='منطقة قبل المعاينة')
        for operation in ['toggle','delete','edit']:
            snapshot=views._snapshot(region,operation,self.user)
            response=self.client.post(reverse('regions:index'),{'action':'preview','operation':operation,'snapshot':snapshot,'name':region.name+' معدل','is_active':'0'})
            self.assertEqual(response.status_code,200)
            provider=ServiceProvider.objects.create(name='مزود بعد المعاينة '+operation,provider_type='government',scope='local')
            coverage=ProviderCoverage.objects.create(provider=provider,region=region)
            response=self.client.post(reverse('regions:index'),{'action':'confirm','token':response.context['pending']['token']})
            self.assertEqual(response.status_code,409)
            region.refresh_from_db();self.assertTrue(region.is_active);self.assertEqual(region.name,'منطقة قبل المعاينة')
            provider.delete()


from django.test import skipUnlessDBFeature


@skipUnlessDBFeature('has_select_for_update')
@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class DependencyConcurrencyTests(MarketFixtures, TransactionTestCase):
    def setUp(self):
        self.setUpTestData()
        super().setUp()

    def payload(self):
        import uuid
        from partnerships.forms import PartnershipForm
        data={'name':'جهة ربط متزامن','representative':'ممثل','phone_country':'SA','phone':'0501234567','email':'race@example.com','entity_type':'government','entity':str(self.entity.pk),'scope':'local','is_active':'1','financial_capacity':'100','offerings':json.dumps([{'sector':self.sector.pk,'specializations':[self.spec.pk],'shape':self.shape.pk,'is_active':True}])}
        form=PartnershipForm(data);self.assertTrue(form.is_valid(),form.errors)
        values=partnership_views._serialized(form.cleaned_data)
        return {'id':None,'nonce':str(uuid.uuid4()),'data':values,'catalog':partnership_views._fingerprint(values)}

    def test_deactivation_wins_before_new_link_and_link_is_revalidated(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from django.db import close_old_connections
        payload=self.payload();locked=Event();writer_started=Event();pk=self.entity.pk;actor=self.user
        def deactivate():
            close_old_connections()
            try:
                with transaction.atomic():
                    item=Entity.objects.select_for_update().get(pk=pk)
                    locked.set()
                    if not writer_started.wait(timeout=10):raise AssertionError('writer did not start')
                    ensure_allowed(item,'toggle',False)
                    item.is_active=False;item.save()
                return 'deactivated'
            finally:close_old_connections()
        def create_link():
            close_old_connections()
            try:
                if not locked.wait(timeout=10):raise AssertionError('deactivation did not lock')
                writer_started.set()
                try:partnership_views._save(payload,actor)
                except partnership_views.Conflict:return 'blocked'
                return 'created'
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            first=executor.submit(deactivate);second=executor.submit(create_link)
            self.assertEqual(first.result(timeout=25),'deactivated');self.assertEqual(second.result(timeout=25),'blocked')
        self.entity.refresh_from_db();self.assertFalse(self.entity.is_active)
        self.assertFalse(Partnership.objects.filter(entity=self.entity).exists())

    def test_new_link_wins_and_deactivation_sees_committed_dependency(self):
        from concurrent.futures import ThreadPoolExecutor
        from threading import Event
        from django.db import close_old_connections
        payload=self.payload();linked=Event();deactivation_started=Event();pk=self.entity.pk;actor=self.user
        def create_link():
            close_old_connections()
            try:
                with transaction.atomic():
                    partnership_views._save(payload,actor)
                    linked.set()
                    if not deactivation_started.wait(timeout=10):raise AssertionError('deactivation did not start')
                return 'created'
            finally:close_old_connections()
        def deactivate():
            close_old_connections()
            try:
                if not linked.wait(timeout=10):raise AssertionError('link was not created')
                deactivation_started.set()
                try:
                    with transaction.atomic():
                        item=Entity.objects.select_for_update().get(pk=pk)
                        ensure_allowed(item,'toggle',False)
                        item.is_active=False;item.save()
                except DependencyBlocked:return 'blocked'
                return 'deactivated'
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            first=executor.submit(create_link);second=executor.submit(deactivate)
            self.assertEqual(first.result(timeout=25),'created');self.assertEqual(second.result(timeout=25),'blocked')
        self.entity.refresh_from_db();self.assertTrue(self.entity.is_active)
        self.assertEqual(Partnership.objects.filter(entity=self.entity).count(),1)
