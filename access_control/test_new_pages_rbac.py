"""Tests verifying RBAC enforcement for Home, Dashboard, and all new partnership pages."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.defaults import initialize
from access_control.models import Module, PermissionOverride, PageScope, RegionScope, UserAccess

User = get_user_model()
AUTH_BACKEND = 'accounts.backends.EmailOrUsernameBackend'


class NewPagesRBACTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()

    def setUp(self):
        self.user = User.objects.create_user('rbac_tester', 'rbac_tester@makken.test', 'StrongPass!2026')
        UserAccess.objects.update_or_create(
            user=self.user,
            defaults={'page_scope': PageScope.ALL, 'region_scope': RegionScope.ALL},
        )
        self.client.force_login(self.user, backend=AUTH_BACKEND)

    def test_all_new_modules_are_registered_in_rbac_matrix(self):
        expected = {
            'home': 'الرئيسية',
            'dashboard': 'مركز المؤشرات والتحليلات',
            'partnerships_all': 'جميع الشراكات',
            'agreement_inquiries': 'الاستعلامات',
            'partnership_achievement': 'إنجاز الشراكات',
            'sponsor_requests': 'طلبات الرعاة الخارجيين',
        }
        for key, title in expected.items():
            mod = Module.objects.get(pk=key)
            self.assertEqual(mod.title, title)

    def test_home_dashboard_and_all_new_pages_enforce_dedicated_rbac_modules(self):
        cases = [
            ('home', 'makken_home', 302),
            ('dashboard', 'core:dashboard', 403),
            ('partnerships_all', 'partnerships:all_index', 403),
            ('agreement_inquiries', 'partnerships:agreement_inquiries', 403),
            ('partnership_achievement', 'partnerships:achievement_report', 403),
            ('sponsor_requests', 'partnerships:sponsor_requests', 403),
        ]
        for module_key, route_name, denied_status in cases:
            with self.subTest(module=module_key):
                url = reverse(route_name)
                self.assertEqual(self.client.get(url).status_code, denied_status)
                override = PermissionOverride.objects.create(
                    user=self.user, module_id=module_key, operation='view', effect='grant'
                )
                self.assertEqual(self.client.get(url).status_code, 200)
                override.delete()

    def test_sidebar_hides_work_stats_without_work_assignments_permission(self):
        res = self.client.get(reverse('makken_mail:work_index'))
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, reverse('makken_mail:work_stats'))
        self.assertNotContains(res, 'إحصائيات المهام')

        ov = PermissionOverride.objects.create(
            user=self.user, module_id='work_assignments', operation='view', effect='grant'
        )
        res2 = self.client.get(reverse('makken_mail:work_index'))
        self.assertEqual(res2.status_code, 200)
        self.assertContains(res2, reverse('makken_mail:work_stats'))
        ov.delete()

    def test_willingness_editor_locks_section_04_for_users_without_work_assignments_edit(self):
        from care_states.models import DevelopmentState
        from entities.models import Entity
        from makken_mail.models import WorkAssignment, WorkStatus
        from partnerships.models import Partnership

        ent = Entity.objects.create(name='جهة صلاحية المهام', entity_type='government', is_active=True)
        p = Partnership.objects.create(
            name='شراكة رغبة مقيدة المهام',
            representative='ممثل',
            phone='+966501112299',
            email='lock_work@example.com',
            entity=ent,
            scope='local',
            development_state_id=DevelopmentState.WILLINGNESS,
        )
        mgr = User.objects.create_user('lock_mgr', 'lock_mgr@makken.test', 'StrongPass!2026')
        wk = WorkAssignment.objects.create(
            title='مهمة مقيدة',
            target_model='partnerships.partnership',
            target_key=p.pk,
            employee=self.user,
            manager=mgr,
            created_by=mgr,
            status=WorkStatus.NEW,
            progress=0,
        )
        wk.assignees.set([self.user])

        PermissionOverride.objects.create(user=self.user, module_id='partnerships', operation='view', effect='grant')
        PermissionOverride.objects.create(user=self.user, module_id='partnerships', operation='edit', effect='grant')

        edit_url = reverse('partnerships:edit', args=[p.pk]) + '?from=willingness'
        res = self.client.get(edit_url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'مهمة مقيدة')
        self.assertNotContains(res, 'data-edit-work-url=')
        self.assertNotContains(res, 'name="work-title"')

        api_url = reverse('partnerships:work_edit', args=[p.pk, wk.pk])
        self.assertEqual(self.client.get(api_url).status_code, 403)
        self.assertEqual(self.client.post(api_url, {'title': 'محاولة تعديل'}).status_code, 403)

    def test_all_registered_modules_appear_in_rbac_assignment_matrix_and_empty_action_cols_hide(self):
        from pathlib import Path
        from access_control.registry import MODULES

        admin = User.objects.create_superuser('matrix_admin', 'matrix_admin@makken.test', 'StrongPass!2026')
        self.client.force_login(admin, backend=AUTH_BACKEND)
        role_res = self.client.get(reverse('access_control:roles'))
        self.assertEqual(role_res.status_code, 200)
        user_edit_res = self.client.get(reverse('access_control:user_edit', args=[self.user.pk]))
        self.assertEqual(user_edit_res.status_code, 200)
        for mod in MODULES:
            self.assertTrue(Module.objects.filter(pk=mod.key).exists(), f'Missing Module {mod.key}')
            self.assertContains(user_edit_res, mod.title)

        self.client.force_login(self.user, backend=AUTH_BACKEND)
        ov = PermissionOverride.objects.create(
            user=self.user, module_id='care_states', operation='view', effect='grant'
        )
        cs_res = self.client.get(reverse('care_states:index'))
        self.assertEqual(cs_res.status_code, 200)
        self.assertNotContains(cs_res, 'الإجراء')
        ov.delete()

        js_txt = Path('core/static/core/js/makken-row-actions-menu.js').read_text(encoding='utf-8')
        self.assertIn('function hideEmptyActionColumns', js_txt)
