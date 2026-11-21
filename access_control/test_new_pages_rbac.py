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
