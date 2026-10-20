"""Format-specific export rights, real roles/overrides, real document downloads."""
from io import BytesIO
import json
from unittest.mock import patch
from zipfile import ZipFile

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError,transaction
from django.template import Context, Template
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import resolve, reverse

from .defaults import initialize
from .enforcement import module_view, requested_operations
from .exports import export_access
from .forms import RoleForm, UserForm
from .models import Module, Operation, PageScope, PermissionOverride, RoleProfile, SecurityAudit, UserAccess
from .policy import AccessPolicy
from .registry import MODULES, codename
from . import services, views


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ExportAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()
        User=get_user_model()
        cls.admin=User.objects.create_superuser(username='export-rbac-root',email='root-export@example.test',password='Safe!Export123')
        cls.user=User.objects.create_user(username='export-rbac-user',email='user-export@example.test',password='Safe!Export124')
        cls.role=RoleProfile.objects.create(group=Group.objects.create(name='تصدير تجريبي'),page_scope=PageScope.ALL)
        cls.user.groups.add(cls.role.group)
        UserAccess.objects.update_or_create(user=cls.user,defaults={'page_scope':PageScope.ALL})
        cls.role.group.permissions.add(*Permission.objects.filter(content_type__app_label='access_control',content_type__model='module',codename__in=['view_regions','view_sectors']))
        from regions.models import Region
        for number in range(1,34):Region.objects.create(name='منطقة اختبار التصدير '+str(number))

    def login(self,user=None):self.client.force_login(user or self.user,backend='accounts.backends.EmailOrUsernameBackend')
    def permit(self,module,operation):
        self.role.group.permissions.add(Permission.objects.get(content_type__app_label='access_control',content_type__model='module',codename=codename(module,operation)))
    def get(self,module='regions',format=None,**params):
        if format:params.update(_mk_export=format,_mk_table='0')
        return self.client.get(reverse(module+':index'),params)
    def rights(self,response):
        import re
        m=re.search(r'<script id="makken-table-export-access" type="application/json">(.*?)</script>',response.content.decode(),re.S)
        self.assertIsNotNone(m)
        return json.loads(m.group(1))

    def test_catalog_registers_both_formats_without_automatically_granting_roles(self):
        for definition in MODULES:
            if definition.key=='dashboard':continue
            for format in ['export_xlsx','export_pdf']:
                self.assertIn(format,Module.objects.get(pk=definition.key).operations)
                self.assertTrue(Permission.objects.filter(codename=codename(definition.key,format),content_type__app_label='access_control',content_type__model='module').exists())
                self.assertFalse(RoleProfile.objects.get(system_key='watcher').group.permissions.filter(codename=codename(definition.key,format)).exists())
        counts=(Permission.objects.count(),self.role.group.permissions.count())
        initialize();self.assertEqual(counts,(Permission.objects.count(),self.role.group.permissions.count()))

    def test_view_only_has_no_buttons_and_direct_download_is_403(self):
        self.login();page=self.get()
        self.assertEqual(page.status_code,200)
        self.assertEqual(self.rights(page),{'xlsx':False,'pdf':False})
        for format in ['xlsx','pdf']:
            response=self.get(format=format)
            self.assertEqual(response.status_code,403)
            self.assertEqual(response['Content-Type'],'application/json')
            self.assertIn('صلاحية',response.json()['error'])

    def test_excel_only_full_pagination_and_pdf_separate(self):
        self.permit('regions','export_xlsx');self.login()
        self.assertEqual(self.rights(self.get()),{'xlsx':True,'pdf':False})
        response=self.get(format='xlsx',page=2,q='منطقة اختبار التصدير')
        self.assertEqual(response.status_code,200)
        with ZipFile(BytesIO(response.content)) as z:
            xml=z.read('xl/worksheets/sheet1.xml').decode()
            self.assertIn('منطقة اختبار التصدير 1',xml)
            self.assertIn('منطقة اختبار التصدير 33',xml)
            self.assertNotIn('csrfmiddlewaretoken',xml)
        self.assertEqual(self.get(format='pdf').status_code,403)

    def test_pdf_only_download_and_excel_denial(self):
        self.permit('regions','export_pdf');self.login()
        self.assertEqual(self.rights(self.get()),{'xlsx':False,'pdf':True})
        response=self.get(format='pdf',q='منطقة اختبار التصدير 33')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.content.startswith(b'%PDF-'))
        self.assertEqual(self.get(format='xlsx').status_code,403)

    def test_both_formats_and_per_page_isolation(self):
        for op in ['export_xlsx','export_pdf']:self.permit('regions',op)
        self.login();self.assertEqual(self.rights(self.get()),{'xlsx':True,'pdf':True})
        self.assertEqual(self.rights(self.get('sectors')),{'xlsx':False,'pdf':False})
        for format in ['xlsx','pdf']:self.assertEqual(self.get('sectors',format).status_code,403)
        # A forged module hint cannot change which route owns the permission.
        self.assertEqual(self.get('sectors','xlsx',_mk_module='regions').status_code,403)

    def test_user_explicit_deny_overrides_role_grant(self):
        self.permit('regions','export_xlsx');self.permit('regions','export_pdf')
        PermissionOverride.objects.create(user=self.user,module_id='regions',operation='export_pdf',effect='deny')
        self.login();self.assertEqual(self.rights(self.get()),{'xlsx':True,'pdf':False})
        self.assertEqual(self.get(format='pdf').status_code,403)

    def test_direct_grant_works_without_format_role_grant(self):
        PermissionOverride.objects.create(user=self.user,module_id='regions',operation='export_xlsx',effect='grant')
        self.login();self.assertEqual(self.get(format='xlsx').status_code,200)
        self.assertEqual(self.get(format='pdf').status_code,403)

    def test_export_right_without_view_cannot_grant_page_access(self):
        self.role.group.permissions.clear();self.permit('regions','export_xlsx')
        self.login();self.assertEqual(self.get().status_code,403);self.assertEqual(self.get(format='xlsx').status_code,403)

    def test_user_selected_pages_restrict_all_exports(self):
        self.permit('regions','export_xlsx')
        access=UserAccess.objects.get(user=self.user);access.page_scope='selected';access.save();access.allowed_pages.set(['sectors'])
        self.login();self.assertEqual(self.get(format='xlsx').status_code,403)

    def test_role_selected_pages_restrict_export_grants(self):
        self.permit('regions','export_xlsx');self.role.page_scope='selected';self.role.save();self.role.allowed_pages.set(['sectors'])
        self.login();self.assertEqual(self.get(format='xlsx').status_code,403)

    def test_revocation_takes_effect_on_next_request_without_logout(self):
        self.permit('regions','export_xlsx');self.login()
        self.assertEqual(self.get(format='xlsx').status_code,200)
        self.role.group.permissions.remove(Permission.objects.get(codename='export_xlsx_regions',content_type__app_label='access_control',content_type__model='module'))
        self.assertEqual(self.get(format='xlsx').status_code,403)
        self.assertEqual(self.get().status_code,200)

    def test_legacy_attachment_export_does_not_grant_document_formats(self):
        PermissionOverride.objects.create(user=self.user,module_id='partnerships',operation='export',effect='grant')
        PermissionOverride.objects.create(user=self.user,module_id='partnerships',operation='view',effect='grant')
        self.login()
        for format in ['xlsx','pdf']:self.assertEqual(self.get('partnerships',format).status_code,403)
        self.assertTrue(AccessPolicy(self.user).can('partnerships','export'))

    def test_document_right_does_not_grant_attachment_download(self):
        self.permit('regions','export_xlsx')
        PermissionOverride.objects.create(user=self.user,module_id='partnerships',operation='view',effect='grant')
        PermissionOverride.objects.create(user=self.user,module_id='partnerships',operation='export_xlsx',effect='grant')
        policy=AccessPolicy(self.user)
        self.assertTrue(policy.can('partnerships','export_xlsx'));self.assertFalse(policy.can('partnerships','export'))

    def test_superuser_keeps_both_formats_and_managed_pages_remain_superuser_only(self):
        self.login(self.admin)
        self.assertEqual(self.rights(self.get()),{'xlsx':True,'pdf':True})
        self.assertEqual(self.get(format='xlsx').status_code,200)
        page=self.client.get(reverse('access_control:roles'));self.assertEqual(page.status_code,200)
        self.assertEqual(self.rights(page),{'xlsx':True,'pdf':True})
        self.login();self.assertEqual(self.client.get(reverse('access_control:roles'),{'_mk_export':'xlsx'}).status_code,403)

    def test_role_and_user_editors_show_independent_columns(self):
        self.login(self.admin)
        for name,args in [('access_control:role_edit',[self.role.pk]),('access_control:user_edit',[self.user.pk])]:
            page=self.client.get(reverse(name,args=args));self.assertEqual(page.status_code,200)
            self.assertContains(page,'تصدير Excel');self.assertContains(page,'تصدير PDF');self.assertContains(page,'تنزيل المرفقات')
            self.assertContains(page,'data-export-permission-note');self.assertContains(page,'data-ac-matrix data-no-export')
        page=self.client.get(reverse('access_control:role_edit',args=[self.role.pk]))
        self.assertContains(page,'value="regions:export_xlsx"');self.assertContains(page,'value="regions:export_pdf"')

    def test_role_save_persists_format_right_and_audits_it(self):
        data={'snapshot':'validated','name':'دور Excel فقط','description':'اختبار','page_scope':'selected','allowed_pages':['regions'],'permissions':['regions:view','regions:export_xlsx']}
        role=services.save_role(self.admin,data)
        self.assertTrue(role.group.permissions.filter(codename='export_xlsx_regions').exists())
        self.assertFalse(role.group.permissions.filter(codename='export_pdf_regions').exists())
        audit=SecurityAudit.objects.filter(target_role=role).first()
        self.assertIn('export_xlsx_regions',audit.after['permissions'])
        bad=dict(data,name='بدون عرض',permissions=['regions:export_xlsx'])
        with self.assertRaises(services.InvalidForm):services.save_role(self.admin,bad)

    def test_user_override_save_persists_new_choices_and_audits(self):
        data=views.initial_user(self.user)
        data.update(snapshot='validated',override__regions__export_pdf='grant',override__regions__export_xlsx='deny')
        expected=services.fingerprint(self.user,'user')
        services.save_user(self.admin,data,self.user.pk,expected)
        rules=dict(PermissionOverride.objects.filter(user=self.user,module_id='regions').values_list('operation','effect'))
        self.assertEqual(rules['export_pdf'],'grant');self.assertEqual(rules['export_xlsx'],'deny')
        audit=SecurityAudit.objects.filter(target_user=self.user).first()
        self.assertTrue(any(rule['operation']=='export_pdf' for rule in audit.after['overrides']))

    def test_module_view_checks_format_permission_even_without_export_middleware(self):
        from django.http import HttpResponse
        @module_view('regions')
        def sample(request):return HttpResponse('view')
        request=RequestFactory().get(reverse('regions:index'),{'_mk_export':'xlsx'});request.user=self.user
        request.resolver_match=resolve(reverse('regions:index'))
        response=sample(request)
        self.assertEqual(response.status_code,403)

    def test_unauthenticated_export_remains_login_redirect(self):
        response=self.get(format='xlsx');self.assertEqual(response.status_code,302)

    def test_server_rejects_unknown_formats_and_template_fails_closed_without_request(self):
        self.login();self.assertEqual(self.get(format='csv').status_code,400)
        result=Template('{% load export_tags %}{% table_export_access as rights %}{{ rights|json_script:"test-rights" }}').render(Context())
        self.assertIn('"xlsx": false',result);self.assertIn('"pdf": false',result)

    def test_new_override_check_constraint_rejects_invalid_operation(self):
        with self.assertRaises(IntegrityError),transaction.atomic():
            PermissionOverride.objects.create(user=self.user,module_id='regions',operation='export_invalid',effect='grant')


from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class ExportPermissionMigrationTests(TransactionTestCase):
    """Verify the upgrade preserves pre-existing permission assignments."""
    def test_upgrade_preserves_legacy_grants_and_overrides(self):
        before=[('access_control','0002_default_roles')]
        after=[('access_control','0003_table_export_permissions')]
        try:
            MigrationExecutor(connection).migrate(before)
            state=MigrationExecutor(connection).loader.project_state(before).apps
            Group=state.get_model('auth','Group')
            Permission=state.get_model('auth','Permission')
            User=state.get_model('auth','User')
            Override=state.get_model('access_control','PermissionOverride')
            user=User.objects.create(username='migration-export-preserve',is_active=True)
            group=Group.objects.create(name='دور محفوظ قبل التحديث')
            permission=Permission.objects.get(content_type__app_label='access_control',content_type__model='module',codename='export_partnerships')
            group.permissions.add(permission);user.groups.add(group)
            rule=Override.objects.create(user_id=user.pk,module_id='regions',operation='view',effect='deny')
            original_permissions=set(group.permissions.values_list('pk',flat=True))
            original_groups=set(user.groups.values_list('pk',flat=True))
            MigrationExecutor(connection).migrate(after)
            self.assertEqual(set(Group.objects.get(pk=group.pk).permissions.values_list('pk',flat=True)),original_permissions)
            self.assertEqual(set(User.objects.get(pk=user.pk).groups.values_list('pk',flat=True)),original_groups)
            self.assertEqual(Override.objects.get(pk=rule.pk).effect,'deny')
            self.assertFalse(group.permissions.filter(codename__startswith='export_xlsx_').exists())
            self.assertFalse(Override.objects.filter(operation__in=['export_xlsx','export_pdf']).exists())
            self.assertEqual(Permission.objects.filter(content_type__app_label='access_control',content_type__model='module',codename__startswith='export_xlsx_').count(),12)
        finally:
            MigrationExecutor(connection).migrate(after)
