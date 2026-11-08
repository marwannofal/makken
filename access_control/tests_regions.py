"""Regional isolation through real MVT views, service callers and exports."""
import json
import uuid
from io import BytesIO
from zipfile import ZipFile
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase, Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.urls import reverse
from access_control.defaults import initialize
from access_control.models import UserAccess, UserRegion, RegionScope, RoleProfile, Module, PermissionOverride, SecurityAudit
from access_control.policy import AccessPolicy
from access_control.regions import RegionalPolicy, scoped, can_write, safe_event
from access_control import services as administration
from access_control.forms import UserForm
from market_needs.tests.test_market import MarketFixtures
from market_needs.models import Need, Sponsorship, SupportAttachment, AuditEvent, NeedExecution
from market_needs import services as market_services, execution_matching
from market_needs.matching import candidates
from market_needs.forms import NeedForm
from market_needs.execution_services import save_execution
from service_providers.models import ServiceProvider, ProviderCoverage
from service_providers.forms import ProviderForm
from service_providers import services as provider_services, views as provider_views
from partnerships.models import Partnership, PartnershipRegion, WillingnessAttachment
from partnerships.forms import PartnershipForm
from partnerships import views as partner_views
from regions.models import Region
from core.dependencies import DependencyBlocked, ensure_allowed


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class RegionalAccessTests(MarketFixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        initialize()
        cls.editor=get_user_model().objects.create_user('regional-editor',email='regional@example.com',password='Regional!Password832')
        cls.watcher=get_user_model().objects.create_user('regional-watcher',email='watcher@example.com',password='Regional!Password833')
        for user,key in [(cls.editor,'editor'),(cls.watcher,'watcher')]:
            user.groups.add(RoleProfile.objects.get(system_key=key).group)
            access=UserAccess.objects.create(user=user,page_scope='all',region_scope='selected')
            access.allowed_regions.add(cls.region)
        # Give the editor explicit extra operations to test region checks on all
        # mutation types without confusing them with the ordinary editor role.
        for module in Module.objects.all():
            for op in module.operations:
                PermissionOverride.objects.create(user=cls.editor,module=module,operation=op,effect='grant')

    def setUp(self):
        super().setUp()
        self.own=self.create_need(title='VISIBLE_RIYADH_CARD',regions=[str(self.region.pk)])
        self.hidden=self.create_need(title='PRIVATE_OTHER_CARD',regions=[str(self.region2.pk)])
        self.shared=self.create_need(title='SHARED_CARD',regions=[str(self.region.pk),str(self.region2.pk)])
        self.org=self.organization(name='VISIBLE_RIYADH_ORG');self.org.administrative_regions.add(self.region)
        self.other_org=self.organization(name='PRIVATE_OTHER_ORG');self.other_org.administrative_regions.add(self.region2)
        self.shared_org=self.organization(name='SHARED_ORG');self.shared_org.administrative_regions.add(self.region,self.region2)
        self.legacy_org=self.organization(name='PRIVATE_UNASSIGNED_ORG')
        self.provider=self.make_provider('VISIBLE_RIYADH_PROVIDER',[self.region])
        self.other_provider=self.make_provider('PRIVATE_OTHER_PROVIDER',[self.region2])
        self.shared_provider=self.make_provider('SHARED_PROVIDER',[self.region,self.region2])
        self.login(self.editor)

    def login(self,user):
        self.client.force_login(user,backend='accounts.backends.EmailOrUsernameBackend')

    def make_provider(self,name,regions):
        provider=ServiceProvider.objects.create(name=name,program=self.program,provider_type='government',scope='local')
        for region in regions:
            row=ProviderCoverage.objects.create(provider=provider,region=region);row.specializations.add(self.spec)
        return provider

    def regions_for(self,user,*regions):
        access=UserAccess.objects.get(user=user);access.region_scope='selected';access.save();access.allowed_regions.set(regions)

    def ids(self,model,writable=False,user=None):
        return set(scoped(model.objects.all(),user or self.editor,writable=writable).values_list('pk',flat=True))

    def provider_data(self,provider=None,regions=None,name='NEW_PROVIDER'):
        return {'program':str(self.program.pk),'name':provider.name if provider else name,'representative':'ممثل المزود','phone_country':'SA','phone':'','email':'','provider_type':'government','scope':'local','is_active':'1','coverage':json.dumps([{'region':r.pk,'specializations':[self.spec.pk],'is_active':True} for r in (regions or [self.region])])}

    def partnership_data(self,instance=None,regions=None,name='NEW_PARTNER'):
        return {'name':instance.name if instance else name,'representative':'ممثل الجهة','phone_country':'SA','phone':'0501234567','email':'person@example.com','financial_capacity':'1000','entity_type':'government','entity':str(self.entity.pk),'scope':'local','is_active':'1','administrative_regions':[str(r.pk) for r in (regions if regions is not None else [self.region])],'offerings':json.dumps([{'sector':self.sector.pk,'specializations':[self.spec.pk],'shape':self.shape.pk,'is_active':True}])}

    def user_data(self,target,**changes):
        access=UserAccess.objects.get(user=target)
        data={'snapshot':'validated','username':target.username,'full_name':'مستخدم إقليمي','email':target.email,'is_active':'1','roles':[str(RoleProfile.objects.get(system_key='editor').pk)],'page_scope':'all','region_scope':'selected','allowed_regions':[str(self.region2.pk)]}
        data.update(changes);return data

    def funded(self,need):
        Sponsorship.objects.create(need=need,partnership=self.org,status='approved',amount=need.total_cost)
        need.approved_support=need.total_cost;need.status='complete';need.save()
        return need

    def test_scope_uses_overlap_for_read_and_all_regions_for_write(self):
        self.assertEqual(self.ids(Need),{self.own.pk,self.shared.pk})
        self.assertEqual(self.ids(Need,True),{self.own.pk})
        self.assertEqual(self.ids(Partnership),{self.org.pk,self.shared_org.pk})
        self.assertEqual(self.ids(Partnership,True),{self.org.pk})
        self.assertEqual(self.ids(ServiceProvider),{self.provider.pk,self.shared_provider.pk})
        self.assertEqual(self.ids(ServiceProvider,True),{self.provider.pk})

    def test_multiple_regions_allow_shared_mutations(self):
        self.regions_for(self.editor,self.region,self.region2)
        self.assertTrue(can_write(self.editor,self.shared))
        self.assertTrue(can_write(self.editor,self.shared_org))
        self.assertTrue(can_write(self.editor,self.shared_provider))

    def test_empty_selected_scope_does_not_mean_all_regions(self):
        self.regions_for(self.editor)
        for model in [Need,Partnership,ServiceProvider,Region]:self.assertFalse(scoped(model.objects.all(),self.editor).exists())

    def test_existing_unrestricted_access_and_superuser_are_preserved(self):
        access=UserAccess.objects.get(user=self.editor);access.region_scope='all';access.save()
        self.assertEqual(self.ids(Partnership),set(Partnership.objects.values_list('pk',flat=True)))
        self.assertTrue(RegionalPolicy(self.user).unrestricted)
        self.assertEqual(self.ids(Need,user=self.user),{self.own.pk,self.hidden.pk,self.shared.pk})

    def test_no_configuration_inactive_and_anonymous_fail_closed(self):
        from django.contrib.auth.models import AnonymousUser
        empty=get_user_model().objects.create_user('unconfigured')
        self.assertFalse(scoped(Need.objects.all(),empty).exists())
        self.assertFalse(scoped(Need.objects.all(),AnonymousUser()).exists())
        with self.assertRaises(PermissionDenied):market_services.card_action(self.own.pk,self.own.version,'toggle',AnonymousUser())
        self.editor.is_active=False;self.editor.save()
        self.assertFalse(scoped(Need.objects.all(),self.editor).exists())

    def test_all_lists_and_counts_are_scoped_before_pagination(self):
        cases=[('market_needs:index',self.own.title,self.hidden.title,2),('partnerships:index',self.org.name,self.other_org.name,2),('service_providers:index',self.provider.name,self.other_provider.name,2)]
        for route,visible,hidden,count in cases:
            with self.subTest(route=route):
                response=self.client.get(reverse(route));self.assertEqual(response.status_code,200)
                self.assertContains(response,visible);self.assertNotContains(response,hidden)
                self.assertEqual(response.context['page_obj'].paginator.count,count)

    def test_search_cannot_escape_scope_or_reveal_hidden_counts(self):
        for route,term in [('market_needs:index',self.hidden.title),('partnerships:index',self.other_org.name),('service_providers:index',self.other_provider.name)]:
            response=self.client.get(reverse(route),{'q':term});self.assertEqual(response.status_code,200)
            self.assertEqual(response.context['page_obj'].paginator.count,0)

    def test_detail_and_direct_editor_urls_do_not_leak_hidden_records(self):
        for route,item in [('market_needs:index',self.hidden),('partnerships:index',self.other_org),('service_providers:index',self.other_provider)]:
            self.assertEqual(self.client.get(reverse(route),{'detail':item.pk}).status_code,404)
        for route,item in [('market_needs:edit',self.hidden),('partnerships:edit',self.other_org),('service_providers:edit',self.other_provider),('market_needs:followup',self.hidden)]:
            self.assertEqual(self.client.get(reverse(route,args=[item.pk])).status_code,404)

    def test_shared_records_have_read_only_details_and_no_edit_links(self):
        for route,edit,item in [('market_needs:index','market_needs:edit',self.shared),('partnerships:index','partnerships:edit',self.shared_org),('service_providers:index','service_providers:edit',self.shared_provider)]:
            response=self.client.get(reverse(route),{'detail':item.pk});self.assertEqual(response.status_code,200)
            self.assertContains(response,'عرض فقط')
            self.assertNotContains(response,'href="'+reverse(edit,args=[item.pk])+'"')
            self.assertEqual(self.client.get(reverse(edit,args=[item.pk])).status_code,403)

    def test_watcher_region_does_not_grant_mutation_permissions(self):
        self.login(self.watcher)
        self.assertEqual(self.client.get(reverse('market_needs:index')).status_code,200)
        self.assertEqual(self.client.get(reverse('market_needs:edit',args=[self.own.pk])).status_code,403)
        with self.assertRaises(PermissionDenied):market_services.card_action(self.own.pk,self.own.version,'toggle',self.watcher)

    def test_page_scope_and_explicit_denials_still_apply(self):
        access=UserAccess.objects.get(user=self.editor);access.page_scope='selected';access.save();access.allowed_pages.set(['regions'])
        self.assertEqual(self.client.get(reverse('market_needs:index')).status_code,403)
        access.page_scope='all';access.save()
        PermissionOverride.objects.update_or_create(user=self.editor,module_id='market_needs',operation='view',defaults={'effect':'deny'})
        self.assertEqual(self.client.get(reverse('market_needs:index')).status_code,403)

    def test_need_form_choices_and_forged_create_regions(self):
        form=NeedForm(actor=self.editor)
        self.assertEqual(set(form.fields['regions'].queryset.values_list('pk',flat=True)),{self.region.pk})
        count=Need.objects.count()
        with self.assertRaises(PermissionDenied):market_services.save_need(self.data(regions=[str(self.region2.pk)]),self.editor,nonce=uuid.uuid4())
        self.assertEqual(Need.objects.count(),count)

    def test_need_create_edit_and_attempted_region_transfer(self):
        saved=market_services.save_need(self.data(title='NEW_LOCAL',regions=[str(self.region.pk)]),self.editor,nonce=uuid.uuid4())
        saved=market_services.save_need(self.data(title='EDIT_LOCAL',regions=[str(self.region.pk)]),self.editor,saved.pk,saved.version)
        with self.assertRaises(PermissionDenied):market_services.save_need(self.data(title='ATTACK',regions=[str(self.region2.pk)]),self.editor,saved.pk,saved.version)
        saved.refresh_from_db();self.assertEqual(saved.title,'EDIT_LOCAL')

    def test_direct_card_services_cannot_write_hidden_or_shared(self):
        for need in [self.hidden,self.shared]:
            for op in ['toggle','delete']:
                with self.assertRaises(PermissionDenied):market_services.card_action(need.pk,need.version,op,self.editor)
            with self.assertRaises(PermissionDenied):market_services.save_need(self.data(),self.editor,need.pk,need.version)
        self.assertEqual(Need.objects.count(),3)

    def test_provider_catalog_and_payload_reject_outside_regions(self):
        response=self.client.get(reverse('service_providers:create'))
        self.assertEqual({row['id'] for row in response.context['catalog']['regions']},{self.region.pk})
        form=ProviderForm(self.provider_data(regions=[self.region2]),actor=self.editor)
        self.assertFalse(form.is_valid());self.assertIn('coverage',form.errors)
        count=ServiceProvider.objects.count()
        with self.assertRaises(provider_services.Conflict):provider_services.save_provider({'nonce':str(uuid.uuid4()),'data':self.provider_data(regions=[self.region2])},self.editor)
        self.assertEqual(ServiceProvider.objects.count(),count)

    def test_provider_services_and_preview_reject_shared_rows(self):
        for provider in [self.other_provider,self.shared_provider]:
            with self.assertRaises(PermissionDenied):provider_services.row_action({'id':provider.pk,'version':provider.version,'operation':'toggle'},self.editor)
            with self.assertRaises(PermissionDenied):provider_services.save_provider({'id':provider.pk,'version':provider.version,'data':self.provider_data(provider)},self.editor)
        token=provider_views.token({'operation':'row','id':self.shared_provider.pk,'version':self.shared_provider.version},self.editor)
        self.assertEqual(self.client.post(reverse('service_providers:index'),{'action':'preview','operation':'toggle','token':token},HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code,403)

    def test_partnership_form_creates_scoped_administrative_regions(self):
        response=self.client.get(reverse('partnerships:create'))
        self.assertEqual(set(response.context['form'].fields['administrative_regions'].queryset.values_list('pk',flat=True)),{self.region.pk})
        response=self.client.post(reverse('partnerships:create'),{**self.partnership_data(),'snapshot':response.context['snapshot'],'action':'preview'})
        self.assertEqual(response.status_code,200,response.context['form'].errors)
        response=self.client.post(reverse('partnerships:create'),{'action':'confirm','token':response.context['pending']['token']})
        self.assertEqual(response.status_code,302)
        self.assertEqual(set(Partnership.objects.get(name='NEW_PARTNER').administrative_regions.values_list('pk',flat=True)),{self.region.pk})

    def test_partnership_forged_regions_and_empty_selected_are_invalid(self):
        for regions in [[],[self.region2]]:
            form=PartnershipForm(self.partnership_data(regions=regions),actor=self.editor)
            self.assertFalse(form.is_valid());self.assertIn('administrative_regions',form.errors)

    def test_legacy_partnerships_stay_hidden_until_explicit_assignment(self):
        self.assertNotIn(self.legacy_org.pk,self.ids(Partnership))
        self.legacy_org.administrative_regions.add(self.region)
        self.assertIn(self.legacy_org.pk,self.ids(Partnership))

    def test_scope_change_invalidates_open_partnership_confirmation(self):
        page=self.client.get(reverse('partnerships:edit',args=[self.org.pk]))
        preview=self.client.post(reverse('partnerships:edit',args=[self.org.pk]),{**self.partnership_data(self.org),'action':'preview','snapshot':page.context['snapshot']})
        self.assertEqual(preview.status_code,200)
        self.regions_for(self.editor,self.region2)
        response=self.client.post(reverse('partnerships:edit',args=[self.org.pk]),{'action':'confirm','token':preview.context['pending']['token']})
        self.assertIn(response.status_code,[403,404]);self.org.refresh_from_db();self.assertEqual(self.org.version,1)

    def test_valid_row_token_is_not_a_regional_authorization(self):
        token=partner_views._sign({'kind':'row','id':self.shared_org.pk,'version':self.shared_org.version,'operation':'toggle'},self.editor)
        response=self.client.post(reverse('partnerships:index'),{'action':'preview','token':token})
        self.assertEqual(response.status_code,403);self.shared_org.refresh_from_db();self.assertTrue(self.shared_org.is_active)

    def test_candidate_search_is_intersection_not_new_geographic_matching(self):
        self.assertEqual(set(candidates(self.own,actor=self.editor).values_list('pk',flat=True)),{self.org.pk,self.shared_org.pk})
        self.assertEqual(set(candidates(self.own).values_list('pk',flat=True)),{self.org.pk,self.other_org.pk,self.shared_org.pk,self.legacy_org.pk})
        self.assertFalse(Sponsorship.objects.exists())

    def test_add_candidates_rechecks_scope_and_prevents_shared_mutation(self):
        for org in [self.other_org,self.shared_org,self.legacy_org]:
            with self.assertRaises(PermissionDenied):market_services.add_candidates(self.own.pk,self.own.version,[org.pk],{},self.editor)
        market_services.add_candidates(self.own.pk,self.own.version,[self.org.pk],{},self.editor)
        self.assertEqual(Sponsorship.objects.get().partnership_id,self.org.pk)

    def test_followup_hidden_partnership_and_shared_need_are_protected(self):
        record=Sponsorship.objects.create(need=self.own,partnership=self.other_org)
        response=self.client.get(reverse('market_needs:followup',args=[self.own.pk]),{'record':record.pk,'operation':'details'})
        self.assertEqual(response.status_code,404)
        with self.assertRaises(PermissionDenied):market_services.followup(self.own.pk,self.own.version,record.pk,record.version,'notes',{'notes':'ATTACK'},{},self.editor)
        shared_record=Sponsorship.objects.create(need=self.shared,partnership=self.org)
        response=self.client.get(reverse('market_needs:followup',args=[self.shared.pk]),{'record':shared_record.pk,'operation':'notes'})
        self.assertEqual(response.status_code,403)

    def test_funding_totals_remain_correct_without_exposing_hidden_funders(self):
        Sponsorship.objects.create(need=self.own,partnership=self.org,status='approved',amount=40)
        hidden=Sponsorship.objects.create(need=self.own,partnership=self.other_org,status='approved',amount=60)
        self.own.approved_support=100;self.own.status='complete';self.own.save()
        AuditEvent.objects.create(need=self.own,need_number=self.own.number,sponsorship=hidden,action='hidden audit',after={'organization':self.other_org.name})
        for route in ['market_needs:index','market_needs:followup']:
            response=self.client.get(reverse(route,args=[self.own.pk]) if 'followup' in route else reverse(route),{} if 'followup' in route else {'detail':self.own.pk})
            self.assertEqual(response.status_code,200);self.assertNotContains(response,self.other_org.name)
        self.own.refresh_from_db();self.assertEqual(self.own.approved_support,100)

    def test_approved_and_assignment_lists_and_direct_links_are_scoped(self):
        for need in [self.own,self.hidden,self.shared]:self.funded(need)
        for route in ['program_execution:index','program_execution:assignments']:
            response=self.client.get(reverse(route));self.assertEqual(response.status_code,200)
            self.assertEqual(response.context['page_obj'].paginator.count,2);self.assertNotContains(response,self.hidden.title)
        self.assertEqual(self.client.get(reverse('program_execution:assignment',args=[self.hidden.pk])).status_code,404)
        response=self.client.get(reverse('program_execution:assignment',args=[self.shared.pk]));self.assertEqual(response.status_code,200);self.assertFalse(response.context['writable'])

    def test_execution_candidate_results_and_unknown_candidate_ids_are_scoped(self):
        self.funded(self.own)
        response=self.client.get(reverse('program_execution:assignment',args=[self.own.pk]))
        self.assertEqual(response.status_code,200);self.assertNotContains(response,self.other_provider.name)
        self.assertEqual(self.client.get(reverse('program_execution:assignment',args=[self.own.pk]),{'candidate':self.other_provider.pk,'kind':'provider'}).status_code,404)

    def test_direct_execution_write_cannot_add_foreign_or_shared_candidates(self):
        self.funded(self.own)
        for provider in [self.other_provider,self.shared_provider]:
            with self.assertRaises(PermissionDenied):save_execution(need_id=self.own.pk,expected_version=0,expected_need_version=self.own.version,nonce=uuid.uuid4(),data={'providers':[provider.pk],'employers':[],'status':'new','notes':''},actor=self.editor)
        self.assertFalse(NeedExecution.objects.exists())
        saved=save_execution(need_id=self.own.pk,expected_version=0,expected_need_version=self.own.version,nonce=uuid.uuid4(),data={'providers':[self.provider.pk],'employers':[],'status':'new','notes':''},actor=self.editor)
        self.assertEqual(saved.provider_links.get().provider_id,self.provider.pk)

    def test_saved_hidden_execution_links_cannot_be_silently_removed(self):
        from market_needs.models import ExecutionProvider
        self.funded(self.own)
        saved=save_execution(need_id=self.own.pk,expected_version=0,expected_need_version=self.own.version,nonce=uuid.uuid4(),data={'providers':[self.provider.pk],'employers':[],'status':'new','notes':''},actor=self.user)
        self.provider.coverage.update(region=self.region2)
        response=self.client.get(reverse('program_execution:assignment',args=[self.own.pk]))
        self.assertFalse(response.context['writable']);self.assertNotContains(response,self.provider.name)
        with self.assertRaises(PermissionDenied):save_execution(need_id=self.own.pk,expected_version=saved.version,expected_need_version=self.own.version,nonce=uuid.uuid4(),data={'providers':[],'employers':[],'status':'new','notes':''},actor=self.editor)
        self.assertTrue(ExecutionProvider.objects.filter(execution=saved,provider=self.provider).exists())

    def test_execution_history_evidence_is_redacted_without_modifying_history(self):
        event=AuditEvent.objects.create(need=self.own,need_number=self.own.number,action='تنفيذ البرنامج',after={'مزودو التدريب':[{'name':self.provider.name},{'name':self.other_provider.name}],'جهات التوظيف':[{'name':self.other_org.name}]})
        safe=safe_event(event,self.editor)
        self.assertEqual(safe.after['مزودو التدريب'],[{'name':self.provider.name}]);self.assertEqual(safe.after['جهات التوظيف'],[])
        event.refresh_from_db();self.assertEqual(len(event.after['مزودو التدريب']),2)

    def test_private_willingness_and_support_downloads_check_owner_scope(self):
        own=WillingnessAttachment.objects.create(partnership=self.org,file='regional/own.pdf',original_name='own.pdf',size=4,content_type='application/pdf',uploaded_by=self.user)
        own.file.save('own.pdf',ContentFile(b'test'),save=True)
        hidden=WillingnessAttachment.objects.create(partnership=self.other_org,file='regional/hidden.pdf',original_name='hidden.pdf',size=4,content_type='application/pdf',uploaded_by=self.user)
        response=self.client.get(reverse('partnerships:attachment_download',args=[self.org.pk,own.pk]));self.assertEqual(response.status_code,200);self.assertEqual(b''.join(response.streaming_content),b'test')
        self.assertEqual(self.client.get(reverse('partnerships:attachment_download',args=[self.other_org.pk,hidden.pk])).status_code,404)
        record=Sponsorship.objects.create(need=self.own,partnership=self.other_org)
        attachment=SupportAttachment.objects.create(sponsorship=record,file='hidden.pdf',original_name='hidden.pdf',size=4,content_type='application/pdf')
        self.assertEqual(self.client.get(reverse('market_needs:download',args=[self.own.pk,attachment.pk])).status_code,404)

    def test_xlsx_all_pages_use_scope_and_pdf_is_protected(self):
        for i in range(16):
            org=self.organization(name=f'EXPORT_VISIBLE_{i:02}');org.administrative_regions.add(self.region)
        response=self.client.get(reverse('partnerships:index'),{'_mk_export':'xlsx'})
        self.assertEqual(response.status_code,200)
        data=b''.join(response.streaming_content) if response.streaming else response.content
        with ZipFile(BytesIO(data)) as archive:text=''.join(archive.read(name).decode() for name in archive.namelist() if name.endswith('.xml'))
        self.assertIn('EXPORT_VISIBLE_15',text);self.assertNotIn(self.other_org.name,text);self.assertNotIn(self.legacy_org.name,text)
        self.login(self.watcher)
        self.assertEqual(self.client.get(reverse('partnerships:index'),{'_mk_export':'pdf'}).status_code,403)

    def test_scoped_list_query_count_does_not_grow_per_row(self):
        with CaptureQueriesContext(connection) as first:self.client.get(reverse('partnerships:index'))
        for i in range(10):
            org=self.organization(name=f'QUERY_VISIBLE_{i}');org.administrative_regions.add(self.region)
        with CaptureQueriesContext(connection) as many:self.client.get(reverse('partnerships:index'))
        self.assertLessEqual(len(many),len(first)+1)

    def test_regions_page_only_assigned_and_new_region_not_allowed(self):
        response=self.client.get(reverse('regions:index'))
        self.assertEqual(response.context['page_obj'].paginator.count,1)
        self.assertNotContains(response,self.region2.name)
        self.assertEqual(self.client.get(reverse('regions:index'),{'edit':self.region2.pk}).status_code,404)
        self.assertEqual(self.client.get(reverse('regions:index'),{'edit':'new'}).status_code,403)
        self.assertFalse(AccessPolicy(self.editor).can('regions','create'))

    def test_global_reference_settings_remain_governed_by_rbac(self):
        self.assertTrue(AccessPolicy(self.editor).can('sectors','edit'))
        self.assertEqual(self.client.get(reverse('sectors:index')).status_code,200)

    def test_assigned_or_partnership_region_cannot_be_deleted_or_deactivated(self):
        with self.assertRaises(DependencyBlocked):ensure_allowed(self.region,'delete')
        with self.assertRaises(DependencyBlocked):ensure_allowed(self.region,'toggle',False)
        with self.assertRaises(ProtectedError):self.region.delete()

    def test_inactive_region_history_access_is_retained_but_not_newly_selected(self):
        Region.objects.filter(pk=self.region.pk).update(is_active=False)
        self.assertIn(self.own.pk,self.ids(Need));self.assertTrue(can_write(self.editor,self.own))
        self.assertNotIn(self.region.pk,set(NeedForm(actor=self.editor).fields['regions'].queryset.values_list('pk',flat=True)))
        self.assertIn(self.region.pk,set(NeedForm(instance=self.own,actor=self.editor).fields['regions'].queryset.values_list('pk',flat=True)))

    def test_region_admin_ui_is_superuser_only_and_requires_nonempty_selection(self):
        self.assertEqual(self.client.get(reverse('access_control:user_edit',args=[self.editor.pk])).status_code,403)
        form=UserForm(self.user_data(self.editor,allowed_regions=[]),target=self.editor)
        self.assertFalse(form.is_valid());self.assertIn('allowed_regions',form.errors)
        self.login(self.user);response=self.client.get(reverse('access_control:user_edit',args=[self.editor.pk]))
        self.assertContains(response,'نطاق المناطق');self.assertContains(response,'data-ac-regions')

    def test_scope_admin_save_audits_and_changes_existing_session_immediately(self):
        expected=administration.fingerprint(self.editor,'user')
        saved=administration.save_user(self.user,self.user_data(self.editor),self.editor.pk,expected)
        event=SecurityAudit.objects.filter(target_user=self.editor).first()
        self.assertEqual(event.before['regions'],[self.region.pk]);self.assertEqual(event.after['regions'],[self.region2.pk])
        response=self.client.get(reverse('market_needs:index'))
        self.assertNotContains(response,self.own.title);self.assertContains(response,self.hidden.title)
        self.assertEqual(saved.makken_access.region_scope,'selected')

    def test_omitted_scope_fields_preserve_existing_restrictions(self):
        data=self.user_data(self.editor);data.pop('region_scope');data.pop('allowed_regions')
        administration.save_user(self.user,data,self.editor.pk,administration.fingerprint(self.editor,'user'))
        self.assertEqual(self.ids(Need),{self.own.pk,self.shared.pk})

    def test_stale_admin_form_cannot_restore_old_region_grants(self):
        expected=administration.fingerprint(self.editor,'user')
        self.regions_for(self.editor,self.region2)
        with self.assertRaises(administration.Conflict):administration.save_user(self.user,self.user_data(self.editor,allowed_regions=[str(self.region.pk)]),self.editor.pk,expected)

    def test_region_constraints_prevent_duplicate_links(self):
        for model,values in [(UserRegion,{'access':UserAccess.objects.get(user=self.editor),'region':self.region}),(PartnershipRegion,{'partnership':self.org,'region':self.region})]:
            with self.assertRaises(IntegrityError),transaction.atomic():model.objects.create(**values)


    def test_restricted_need_editor_http_submission_is_valid(self):
        page=self.client.get(reverse('market_needs:create'))
        response=self.client.post(reverse('market_needs:create'),{**self.data(title='HTTP_LOCAL_NEED',regions=[str(self.region.pk)]),'snapshot':page.context['snapshot']})
        self.assertEqual(response.status_code,302)
        self.assertEqual(set(Need.objects.get(title='HTTP_LOCAL_NEED').regions.values_list('pk',flat=True)),{self.region.pk})

    def test_restricted_provider_http_preview_and_confirmation(self):
        page=self.client.get(reverse('service_providers:create'))
        response=self.client.post(reverse('service_providers:create'),{**self.provider_data(name='HTTP_LOCAL_PROVIDER'),'action':'preview','snapshot':page.context['snapshot']})
        self.assertEqual(response.status_code,200,response.context['form'].errors)
        response=self.client.post(reverse('service_providers:create'),{'action':'confirm','token':response.context['pending']['token']})
        self.assertEqual(response.status_code,302)
        self.assertEqual(ServiceProvider.objects.get(name='HTTP_LOCAL_PROVIDER').coverage.get().region_id,self.region.pk)

    def test_authorized_regional_followup_notes_are_saved(self):
        record=Sponsorship.objects.create(need=self.own,partnership=self.org)
        market_services.followup(self.own.pk,self.own.version,record.pk,record.version,'notes',{'notes':'متابعة ضمن المنطقة'},{},self.editor)
        record.refresh_from_db();self.assertEqual(record.notes,'متابعة ضمن المنطقة');self.assertEqual(record.status,'new')

    def test_pdf_export_does_not_include_hidden_organizations(self):
        from pypdf import PdfReader
        response=self.client.get(reverse('partnerships:index'),{'_mk_export':'pdf'})
        self.assertEqual(response.status_code,200)
        data=b''.join(response.streaming_content) if response.streaming else response.content
        self.assertTrue(data.startswith(b'%PDF'))
        text=''.join(''.join(page.extract_text() for page in PdfReader(BytesIO(data)).pages).split())
        self.assertIn(self.org.name,text)
        self.assertNotIn(self.other_org.name,text)
        self.assertNotIn(self.legacy_org.name,text)
