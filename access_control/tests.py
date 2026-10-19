import json
from uuid import uuid4
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group,Permission
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.core.management import call_command
from django.db import transaction,IntegrityError
from django.test import TestCase,Client,override_settings,RequestFactory
from django.urls import reverse,resolve
from django.utils import timezone
from access_control.models import UserAccess,RoleProfile,Module,PermissionOverride,SecurityAudit,SecurityLock
from access_control.defaults import initialize
from access_control.policy import AccessPolicy,require
from access_control.registry import MODULES,codename
from access_control import services,views
from access_control.signals import LastAdminError
from regions.models import Region
from entities.models import Entity
from partnerships.models import Partnership
from core.dependencies import DependencyBlocked


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class AccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()
        cls.admin=get_user_model().objects.create_superuser(username='access-root',email='root@example.com',password='Strong!Password834')
        cls.watcher=get_user_model().objects.create_user(username='watcher',email='watcher@example.com',password='Strong!Password835')
        cls.editor=get_user_model().objects.create_user(username='editor',email='editor@example.com',password='Strong!Password836')
        cls.empty=get_user_model().objects.create_user(username='empty',email='empty@example.com',password='Strong!Password837')
        for user,key in [(cls.watcher,'watcher'),(cls.editor,'editor')]:
            UserAccess.objects.update_or_create(user=user,defaults={'page_scope':'all'})
            user.groups.add(RoleProfile.objects.get(system_key=key).group)
        cls.region=Region.objects.create(name='منطقة صلاحيات تجريبية')

    def login(self,user):
        self.client.force_login(user,backend='accounts.backends.EmailOrUsernameBackend')

    def form_data(self,**changes):
        values={'snapshot':'validated','full_name':'مستخدم تجريبي','username':'new-user','email':'new@example.com','is_active':'1','page_scope':'selected','allowed_pages':['regions'],'roles':[str(RoleProfile.objects.get(system_key='watcher').pk)],'new_password1':'Really!Strong9348','new_password2':'Really!Strong9348'}
        values.update(changes);return values

    def user_token(self,pk,action='save',actor=None):
        request=RequestFactory().get('/');request.user=actor or self.admin
        user=get_user_model().objects.get(pk=pk) if pk else None
        return views.token(request,'user',action,user)

    def test_default_roles_are_idempotent_and_editor_status_delete_separate(self):
        before=(Group.objects.count(),RoleProfile.objects.count(),Permission.objects.count())
        call_command('initialize_access_control',verbosity=0);call_command('initialize_access_control',verbosity=0)
        self.assertEqual(before,(Group.objects.count(),RoleProfile.objects.count(),Permission.objects.count()))
        policy=AccessPolicy(self.editor)
        for module in MODULES:
            self.assertTrue(policy.can(module.key))
            self.assertFalse(policy.can(module.key,'delete'));self.assertFalse(policy.can(module.key,'change_status'))
        self.assertTrue(policy.can('regions','create'));self.assertTrue(policy.can('regions','edit'))
        self.assertFalse(AccessPolicy(self.empty).can('regions'))

    def test_all_registered_watcher_pages_are_readable_without_mutating_actions(self):
        self.login(self.watcher)
        for module in MODULES:
            with self.subTest(module=module.key):
                response=self.client.get(reverse(module.route_name))
                self.assertEqual(response.status_code,200)
                self.assertNotContains(response,'href="'+reverse('access_control:index')+'"')
        response=self.client.get(reverse('regions:index'),{'q':self.region.name})
        self.assertNotContains(response,'data-add-region');self.assertNotContains(response,'data-edit-region')
        self.assertNotContains(response,'class="region-action action-delete"')
        self.assertContains(response,'منطقة صلاحيات تجريبية')

    def test_watcher_rejects_all_write_methods_and_signed_confirmations(self):
        from regions import views as region_views
        self.login(self.watcher)
        before=Region.objects.count()
        for method in ['post','put','patch','delete']:
            for module in MODULES:
                response=getattr(self.client,method)(reverse(module.route_name),{'action':'delete'})
                self.assertEqual(response.status_code,403,(module.key,method))
        for operation in ['edit','toggle','delete']:
            snapshot=region_views._snapshot(self.region,operation,self.watcher)
            data={'action':'preview','operation':operation,'snapshot':snapshot,'name':'تعديل ممنوع','is_active':'0'}
            response=self.client.post(reverse('regions:index'),data,HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code,403);self.assertIn('error',response.json())
        self.region.refresh_from_db();self.assertEqual(self.region.name,'منطقة صلاحيات تجريبية');self.assertTrue(self.region.is_active)
        self.assertEqual(Region.objects.count(),before)

    def test_editor_can_create_and_edit_but_cannot_delete_or_toggle(self):
        self.login(self.editor)
        url=reverse('regions:index');page=self.client.get(url)
        response=self.client.post(url,{'action':'preview','operation':'add','snapshot':page.context['add_snapshot'],'name':'منطقة إنشاء محرر','is_active':'1'})
        self.assertEqual(response.status_code,200)
        response=self.client.post(url,{'action':'confirm','token':response.context['pending']['token']});self.assertEqual(response.status_code,302)
        item=Region.objects.get(name='منطقة إنشاء محرر')
        from regions import views as rv
        response=self.client.post(url,{'action':'preview','operation':'edit','snapshot':rv._snapshot(item,'edit',self.editor),'name':'منطقة تعديل محرر','is_active':'1'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.post(url,{'action':'confirm','token':response.context['pending']['token']}).status_code,302)
        for operation in ['toggle','delete']:
            response=self.client.post(url,{'action':'preview','snapshot':rv._snapshot(item,operation,self.editor)})
            self.assertEqual(response.status_code,403)
        item.refresh_from_db();self.assertEqual(item.name,'منطقة تعديل محرر');self.assertTrue(item.is_active)

    def test_editor_cannot_smuggle_status_through_edit_or_create(self):
        from regions import views as rv
        self.login(self.editor);url=reverse('regions:index')
        for operation in ['edit','add']:
            snapshot=rv._snapshot(self.region,'edit',self.editor) if operation=='edit' else self.client.get(url).context['add_snapshot']
            response=self.client.post(url,{'action':'preview','operation':operation,'snapshot':snapshot,'name':'منطقة غير نشطة ممنوعة','is_active':'0'})
            self.assertEqual(response.status_code,403)
        self.region.refresh_from_db();self.assertTrue(self.region.is_active)

    def test_status_permission_can_be_granted_without_delete(self):
        from regions import views as rv
        PermissionOverride.objects.create(user=self.editor,module_id='regions',operation='change_status',effect='grant')
        self.login(self.editor);url=reverse('regions:index')
        response=self.client.post(url,{'action':'preview','snapshot':rv._snapshot(self.region,'toggle',self.editor)})
        self.assertEqual(response.status_code,200)
        self.assertEqual(self.client.post(url,{'action':'confirm','token':response.context['pending']['token']}).status_code,302)
        self.region.refresh_from_db();self.assertFalse(self.region.is_active)
        self.assertFalse(AccessPolicy(self.editor).can('regions','delete'))

    def test_selected_pages_override_global_roles_and_dashboard_redirect(self):
        access=UserAccess.objects.get(user=self.watcher);access.page_scope='selected';access.save();access.allowed_pages.set(['regions'])
        self.login(self.watcher)
        self.assertEqual(self.client.get(reverse('regions:index')).status_code,200)
        self.assertEqual(self.client.get(reverse('training_programs:index')).status_code,403)
        response=self.client.get(reverse('makken_home'));self.assertRedirects(response,reverse('regions:index'))
        response=self.client.get(reverse('regions:index'))
        self.assertNotContains(response,'href="'+reverse('training_programs:index')+'"')
        self.assertContains(response,'href="'+reverse('regions:index')+'"')
        self.assertNotContains(response,'بطاقات حاجة السوق')
        access.allowed_pages.clear()
        self.assertRedirects(self.client.get(reverse('makken_home')),reverse('access_control:no_access'))

    def test_multi_role_union_explicit_denial_view_prerequisite_and_source_labels(self):
        self.watcher.groups.add(RoleProfile.objects.get(system_key='editor').group)
        policy=AccessPolicy(self.watcher);self.assertTrue(policy.can('regions','edit'));self.assertIn('دور:',policy.decision('regions','edit')[1])
        PermissionOverride.objects.create(user=self.watcher,module_id='regions',operation='edit',effect='deny')
        self.assertFalse(AccessPolicy(self.watcher).can('regions','edit'))
        PermissionOverride.objects.create(user=self.watcher,module_id='regions',operation='view',effect='deny')
        PermissionOverride.objects.create(user=self.watcher,module_id='regions',operation='delete',effect='grant')
        policy=AccessPolicy(self.watcher);self.assertFalse(policy.can('regions','delete'));self.assertIn('منع صريح',policy.decision('regions')[1])
        self.assertFalse(policy.can('unknown','view'))

    def test_role_selected_pages_and_direct_grants_do_not_override_user_page_scope(self):
        role=RoleProfile.objects.get(system_key='editor');role.page_scope='selected';role.save();role.allowed_pages.set(['regions'])
        self.assertFalse(AccessPolicy(self.editor).can('entities'))
        PermissionOverride.objects.create(user=self.editor,module_id='entities',operation='view',effect='grant')
        self.assertTrue(AccessPolicy(self.editor).can('entities'))
        access=UserAccess.objects.get(user=self.editor);access.page_scope='selected';access.save();access.allowed_pages.set(['regions'])
        self.assertFalse(AccessPolicy(self.editor).can('entities'))

    def test_superuser_only_panel_and_role_name_never_grants_superuser(self):
        fake=RoleProfile.objects.create(group=Group.objects.create(name='Super Admin'))
        self.watcher.groups.add(fake.group)
        endpoints=['access_control:index','access_control:roles','access_control:logs','access_control:user_create','access_control:role_create']
        self.login(self.watcher)
        for route in endpoints:
            self.assertEqual(self.client.get(reverse(route)).status_code,403)
            self.assertEqual(self.client.post(reverse(route),{}).status_code,403)
        self.assertEqual(self.client.get('/admin/').status_code,403)
        self.login(self.admin)
        for route in endpoints:self.assertEqual(self.client.get(reverse(route)).status_code,200,route)

    def test_unconfigured_routes_fail_closed_and_no_access_page_is_safe(self):
        self.login(self.watcher)
        # Define a real unregistered route independently of the site's URL list.
        from types import ModuleType
        from django.http import HttpResponse
        from django.urls import get_resolver, path
        root = ModuleType('makken_rbac_test_routes')
        root.urlpatterns = [path('rbac-unregistered-test/', lambda request: HttpResponse('UNREGISTERED'), name='rbac_unregistered_test'), *get_resolver().url_patterns]
        with override_settings(ROOT_URLCONF=root):
            self.assertEqual(self.client.get('/rbac-unregistered-test/').status_code,403)
            self.login(self.admin)
            self.assertEqual(self.client.get('/rbac-unregistered-test/').status_code,200)
        self.login(self.empty)
        response=self.client.get(reverse('access_control:no_access'));self.assertEqual(response.status_code,200)
        self.assertContains(response,'لم تُمنح صلاحيات بعد');self.assertNotContains(response,'href="'+reverse('regions:index')+'"')
        self.assertEqual(self.client.get(reverse('accounts:profile')).status_code,200)

    def test_user_creation_hashes_password_and_selected_pages_persist(self):
        self.login(self.admin);url=reverse('access_control:user_create');page=self.client.get(url)
        data=self.form_data(snapshot=page.context['form']['snapshot'].value())
        response=self.client.post(url,data);self.assertEqual(response.status_code,302)
        target=get_user_model().objects.get(username='new-user')
        self.assertTrue(target.check_password(data['new_password1']));self.assertNotEqual(target.password,data['new_password1'])
        self.assertFalse(target.is_superuser);self.assertFalse(target.is_staff)
        self.assertTrue(AccessPolicy(target).can('regions'));self.assertFalse(AccessPolicy(target).can('entities'))
        log=SecurityAudit.objects.get(target_user=target);serialized=json.dumps([log.before,log.after]);self.assertNotIn(data['new_password1'],serialized);self.assertNotIn('snapshot',serialized);self.assertNotIn(target.password,serialized)
        self.client.logout();self.assertTrue(self.client.login(username='new-user',password=data['new_password1']))
        self.assertEqual(self.client.get(reverse('regions:index')).status_code,200)
        self.assertEqual(self.client.get(reverse('entities:index')).status_code,403)
        self.assertEqual(self.client.post(url,data).status_code,403)

    def test_invalid_password_duplicate_identity_and_privilege_fields_rejected(self):
        self.login(self.admin);url=reverse('access_control:user_create')
        for changed in [{'new_password1':'123','new_password2':'123'},{'new_password2':'Mismatch!9348'},{'username':'watcher'},{'email':'watcher@example.com'},{'is_superuser':'1'},{'is_staff':'1'},{'override__regions__view':'unknown'}]:
            page=self.client.get(url);data=self.form_data(snapshot=page.context['form']['snapshot'].value(),**changed)
            response=self.client.post(url,data);self.assertEqual(response.status_code,400,changed)
        self.assertFalse(get_user_model().objects.filter(username='new-user').exists())

    def test_user_edit_revocation_applies_to_existing_session_and_signed_old_actions(self):
        self.login(self.editor)
        from regions import views as rv
        preview=self.client.post(reverse('regions:index'),{'action':'preview','operation':'edit','snapshot':rv._snapshot(self.region,'edit',self.editor),'name':'لا يحفظ بعد الإلغاء','is_active':'1'})
        self.assertEqual(preview.status_code,200)
        self.editor.groups.clear()
        self.assertEqual(self.client.post(reverse('regions:index'),{'action':'confirm','token':preview.context['pending']['token']}).status_code,403)
        self.region.refresh_from_db();self.assertNotEqual(self.region.name,'لا يحفظ بعد الإلغاء')
        self.assertEqual(self.client.get(reverse('regions:index')).status_code,403)

    def test_user_management_updates_roles_overrides_pages_and_stale_posts(self):
        self.login(self.admin);url=reverse('access_control:user_edit',args=[self.watcher.pk]);page=self.client.get(url)
        data=self.form_data(username='watcher',email='watcher@example.com',snapshot=page.context['form']['snapshot'].value(),roles=[str(RoleProfile.objects.get(system_key='editor').pk)],**{'override__regions__edit':'deny'})
        response=self.client.post(url,data);self.assertEqual(response.status_code,302)
        policy=AccessPolicy(self.watcher);self.assertTrue(policy.can('regions','create'));self.assertFalse(policy.can('regions','edit'));self.assertFalse(policy.can('entities'))
        self.assertEqual(self.client.post(url,data).status_code,409)
        event=SecurityAudit.objects.filter(target_user=self.watcher).latest('pk');self.assertEqual(event.actor_id,self.admin.pk);self.assertEqual(event.after['page_scope'],'selected');self.assertEqual(event.after['pages'],['regions'])

    def test_inactive_accounts_existing_sessions_are_denied(self):
        self.login(self.watcher)
        snapshot=services.fingerprint(self.watcher,'user');services.toggle_user(self.admin,self.watcher.pk,snapshot)
        self.assertEqual(self.client.get(reverse('regions:index')).status_code,302)
        self.assertFalse(AccessPolicy(get_user_model().objects.get(pk=self.watcher.pk)).can('regions'))

    def test_last_superuser_cannot_be_disabled_demoted_or_deleted_including_bulk(self):
        with self.assertRaises(services.Conflict):services.toggle_user(self.admin,self.admin.pk,services.fingerprint(self.admin,'user'))
        for field,value in [('is_active',False),('is_superuser',False)]:
            target=get_user_model().objects.get(pk=self.admin.pk);setattr(target,field,value)
            with self.assertRaises(LastAdminError),transaction.atomic():target.save(update_fields=[field])
        with self.assertRaises(LastAdminError),transaction.atomic():get_user_model().objects.filter(pk=self.admin.pk).delete()
        second=get_user_model().objects.create_superuser(username='another-root',email='another@example.com',password='Strong!Second930')
        with self.assertRaises(LastAdminError),transaction.atomic():get_user_model().objects.filter(is_superuser=True).delete()
        self.admin.refresh_from_db();self.assertTrue(self.admin.is_active);self.assertTrue(self.admin.is_superuser)

    def test_password_reset_invalidates_other_sessions_and_never_logs_secret(self):
        target=self.watcher;old=Client();old.force_login(target,backend='accounts.backends.EmailOrUsernameBackend')
        data={'snapshot':'validated','new_password1':'New!Different9634','new_password2':'New!Different9634'}
        services.reset_password(self.admin,target.pk,services.fingerprint(target,'user'),data)
        target.refresh_from_db();self.assertTrue(target.check_password(data['new_password1']))
        self.assertEqual(old.get(reverse('regions:index')).status_code,302)
        event=SecurityAudit.objects.latest('pk');self.assertEqual(event.after,{'password_reset':True});self.assertNotIn(data['new_password1'],json.dumps(event.after))

    def test_role_create_duplicate_assignment_and_safe_deletion(self):
        data={'snapshot':'validated','name':'مدخل مناطق','description':'دور تجريبي','page_scope':'selected','allowed_pages':['regions'],'permissions':['regions:view','regions:create','regions:edit']}
        role=services.save_role(self.admin,data)
        self.empty.groups.add(role.group);UserAccess.objects.update_or_create(user=self.empty,defaults={'page_scope':'all'})
        policy=AccessPolicy(self.empty);self.assertTrue(policy.can('regions','create'));self.assertFalse(policy.can('entities'));self.assertFalse(policy.can('regions','delete'))
        with self.assertRaises(services.Conflict):services.role_action(self.admin,role.pk,services.fingerprint(role,'role'),'delete')
        clone=services.role_action(self.admin,role.pk,services.fingerprint(role,'role'),'duplicate')
        self.assertEqual(set(role.group.permissions.all()),set(clone.group.permissions.all()))
        self.assertEqual(set(role.allowed_pages.all()),set(clone.allowed_pages.all()))
        clone_pk=clone.pk;services.role_action(self.admin,clone.pk,services.fingerprint(clone,'role'),'delete');self.assertFalse(RoleProfile.objects.filter(pk=clone_pk).exists())
        self.assertTrue(SecurityAudit.objects.filter(action='حذف دور',target_role=None).exists())

    def test_role_matrix_rejects_unsupported_and_edit_without_view(self):
        for permissions in [['regions:edit'],['unknown:view'],['dashboard:delete']]:
            with self.assertRaises(services.InvalidForm):services.save_role(self.admin,{'snapshot':'validated','name':'دور غير صالح','page_scope':'all','permissions':permissions})
        with self.assertRaises(services.Conflict):services.role_action(self.admin,RoleProfile.objects.get(system_key='watcher').pk,services.fingerprint(RoleProfile.objects.get(system_key='watcher'),'role'),'delete')

    def test_business_dependency_rule_still_blocks_superuser_and_authorized_editor(self):
        from entities import views as ev
        entity=Entity.objects.create(name='كيان مرتبط بالصلاحيات',entity_type='government')
        partner=Partnership.objects.create(name='شراكة صلاحيات',representative='ممثل',phone='+966501234567',email='dependency@example.com',entity=entity,scope='local')
        for user in [self.admin,self.editor]:
            if not user.is_superuser:
                PermissionOverride.objects.create(user=user,module_id='entities',operation='change_status',effect='grant')
            self.login(user)
            response=self.client.post(reverse('entities:index'),{'action':'preview','snapshot':ev._snapshot(entity,'toggle',user)})
            self.assertEqual(response.status_code,409)
            self.assertContains(response,'id="dependency-block"',status_code=409)
        entity.refresh_from_db();self.assertTrue(entity.is_active);self.assertTrue(Partnership.objects.filter(pk=partner.pk).exists())

    def test_csrf_and_cross_actor_management_tokens(self):
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.admin,backend='accounts.backends.EmailOrUsernameBackend')
        self.assertEqual(secure.post(reverse('access_control:user_create'),{}).status_code,403)
        self.login(self.admin)
        token=self.user_token(self.watcher.pk,'status',actor=self.editor)
        response=self.client.post(reverse('access_control:user_status',args=[self.watcher.pk]),{'snapshot':token},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code,409);self.assertIn('error',response.json())

    def test_direct_service_cannot_bypass_view_permissions(self):
        from market_needs import services as market
        from service_providers import services as providers
        with self.assertRaises(PermissionDenied):market.card_action(1,1,'delete',self.watcher)
        with self.assertRaises(PermissionDenied):providers.row_action({'id':1,'version':1,'operation':'delete'},self.editor)
        with self.assertRaises(PermissionDenied):services.save_user(self.editor,self.form_data())

    def test_navigation_and_action_html_match_effective_permissions(self):
        self.login(self.editor);response=self.client.get(reverse('regions:index'))
        self.assertContains(response,'data-add-region');self.assertContains(response,'data-edit-region')
        self.assertNotContains(response,'value="{{ row.delete_snapshot }}"')
        self.assertNotContains(response,'class="region-action action-delete"')
        self.assertContains(response,'aria-disabled="true"')
        self.assertNotContains(response,'href="'+reverse('access_control:index')+'"')
        self.login(self.admin);self.assertContains(self.client.get(reverse('regions:index')),'href="'+reverse('access_control:index')+'"')

    def test_editor_cannot_replay_delete_or_bulk_tokens_on_any_settings_module(self):
        import importlib
        from access_control.registry import SETTINGS_MODULES
        self.login(self.editor)
        for module in SETTINGS_MODULES:
            view=importlib.import_module(module+'.views')
            payload={'operation':'delete','id':999999,'version':1,'name':'حذف ممنوع','is_active':True}
            signed=view._sign(payload,self.editor,view.CONFIRM_SALT)
            response=self.client.post(reverse(module+':index'),{'action':'confirm','token':signed},HTTP_X_REQUESTED_WITH='XMLHttpRequest')
            self.assertEqual(response.status_code,403,module)
            response=self.client.post(reverse(module+':index'),{'action':'bulk_delete','ids':[self.region.pk]})
            self.assertEqual(response.status_code,403,module)
        self.assertTrue(Region.objects.filter(pk=self.region.pk).exists())

    def test_login_next_respects_page_scope_and_preserves_remember_me(self):
        access=UserAccess.objects.get(user=self.watcher);access.page_scope='selected';access.save();access.allowed_pages.set(['regions'])
        response=self.client.post(reverse('accounts:login'),{'username':'watcher','password':'Strong!Password835','remember_me':'on','next':reverse('training_programs:index')})
        self.assertRedirects(response,reverse('regions:index'))
        self.assertGreater(self.client.session.get_expiry_age(),24*60*60)

    def test_exports_are_separate_and_page_restrictions_still_apply(self):
        from tempfile import TemporaryDirectory
        from io import BytesIO
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        from partnerships.willingness import validate_attachment,save_supporting_files
        self.login(self.watcher)
        entity=Entity.objects.create(name='كيان ملف خاص',entity_type='government')
        partner=Partnership.objects.create(name='جهة ملف خاص',representative='ممثل',phone='+966501234567',email='private@example.com',entity=entity,scope='local')
        with TemporaryDirectory() as folder,override_settings(MAKKEN_PRIVATE_UPLOAD_ROOT=folder):
            content=BytesIO();Image.new('RGB',(4,4),'white').save(content,'PNG')
            upload=validate_attachment(SimpleUploadedFile('proof.png',content.getvalue(),content_type='image/png'))
            save_supporting_files(partner,{'attachments':[upload],'agreement_type':'official_letter'},self.admin,[])
            attachment=partner.willingness_attachments.get()
            url=reverse('partnerships:attachment_download',args=[partner.pk,attachment.pk])
            self.assertEqual(self.client.get(url).status_code,403)
            PermissionOverride.objects.create(user=self.watcher,module_id='partnerships',operation='export',effect='grant')
            response=self.client.get(url);self.assertEqual(response.status_code,200)
            self.assertEqual(sum(map(len,response.streaming_content)),attachment.size)
            access=UserAccess.objects.get(user=self.watcher);access.page_scope='selected';access.save();access.allowed_pages.set(['regions'])
            self.assertEqual(self.client.get(url).status_code,403)
        self.assertEqual(self.client.get(reverse('market_needs:download',args=[999,999])).status_code,403)

    def test_duplicate_role_submission_is_not_replayed(self):
        source=RoleProfile.objects.get(system_key='watcher');fingerprint=services.fingerprint(source,'role')
        clone=services.role_action(self.admin,source.pk,fingerprint,'duplicate')
        with self.assertRaises(services.Conflict):services.role_action(self.admin,source.pk,fingerprint,'duplicate')
        self.assertEqual(RoleProfile.objects.filter(group__name__startswith='Watcher').count(),2)

    def test_direct_group_delete_cannot_remove_assigned_or_default_role(self):
        from access_control.signals import ProtectedRoleError
        role=RoleProfile.objects.get(system_key='watcher')
        with self.assertRaises(ProtectedRoleError),transaction.atomic():role.group.delete()
        self.assertTrue(RoleProfile.objects.filter(pk=role.pk).exists())


from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest import skipUnless
from django.db import connection,connections
from django.test import TransactionTestCase


@skipUnless(connection.vendor == 'mysql', 'Requires real MySQL row locks.')
@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ConcurrentAdministrationTests(TransactionTestCase):
    def test_simultaneous_admin_deactivation_keeps_an_active_superuser(self):
        initialize()
        User=get_user_model()
        first=User.objects.create_superuser(username='race-admin-1',email='race1@example.com',password='Strong!Password834')
        second=User.objects.create_superuser(username='race-admin-2',email='race2@example.com',password='Strong!Password835')
        first_stamp=services.fingerprint(first,'user');second_stamp=services.fingerprint(second,'user')
        barrier=Barrier(2)
        def attempt(actor_id,target_id,stamp):
            connections.close_all()
            try:
                actor=User.objects.get(pk=actor_id)
                barrier.wait(timeout=10)
                try:
                    services.toggle_user(actor,target_id,stamp)
                    return 'saved'
                except (PermissionDenied,services.Conflict):
                    return 'blocked'
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            one=pool.submit(attempt,first.pk,second.pk,second_stamp)
            two=pool.submit(attempt,second.pk,first.pk,first_stamp)
            outcomes=[one.result(timeout=30),two.result(timeout=30)]
        self.assertEqual(sorted(outcomes),['blocked','saved'])
        self.assertEqual(User.objects.filter(is_superuser=True,is_active=True).count(),1)
