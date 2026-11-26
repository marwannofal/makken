from django.contrib.auth import get_user_model
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.urls import reverse

from access_control.defaults import initialize
from access_control.models import PermissionOverride, RegionScope, UserAccess
from accounts.departments import _snapshot
from accounts.models import Department, UserProfile

User = get_user_model()


class DepartmentLookupTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()
        cls.admin = User.objects.create_superuser('dept-admin', 'dept-admin@makken.test', 'AdminPass!9876')
        cls.reader = User.objects.create_user('dept-reader', 'dept-reader@makken.test', 'ReaderPass!9876')
        cls.no_access = User.objects.create_user('dept-none', 'dept-none@makken.test', 'NonePass!9876')
        UserAccess.objects.update_or_create(
            user=cls.reader, defaults={'page_scope': 'all', 'region_scope': RegionScope.ALL}
        )
        PermissionOverride.objects.create(
            user=cls.reader, module_id='departments', operation='view', effect='grant'
        )
        cls.url = reverse('accounts:departments')

    def test_initial_seeded_departments_exist(self):
        names = set(Department.objects.values_list('name', flat=True))
        for expected in ('الإدارة العامة للتشاركية', 'الكليات', 'المعاهد'):
            self.assertIn(expected, names)

    def test_rbac_enforcement_for_view_and_mutations(self):
        self.client.force_login(self.no_access, backend='accounts.backends.EmailOrUsernameBackend')
        self.assertEqual(self.client.get(self.url).status_code, 403)

        self.client.force_login(self.reader, backend='accounts.backends.EmailOrUsernameBackend')
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'إدارة الهيكل التنظيمي')
        self.assertNotContains(res, 'إضافة إدارة')
        self.assertEqual(self.client.get(f'{self.url}?edit=new').status_code, 403)

    def test_crud_popup_search_filter_and_duplicate_guard(self):
        self.client.force_login(self.admin, backend='accounts.backends.EmailOrUsernameBackend')

        # Open add pop-up dialog
        add_page = self.client.get(f'{self.url}?edit=new')
        self.assertEqual(add_page.status_code, 200)
        self.assertContains(add_page, 'id="department-editor"')
        token = add_page.context['token']

        # Create new department
        res = self.client.post(self.url, {'operation': 'add', 'snapshot': token, 'name': 'إدارة الجودة والتطوير', 'kind': 'department'})
        self.assertEqual(res.status_code, 302)
        dept = Department.objects.get(name='إدارة الجودة والتطوير')
        self.assertTrue(dept.is_active)

        # Duplicate name rejected
        add_page2 = self.client.get(f'{self.url}?edit=new')
        dup = self.client.post(self.url, {'operation': 'add', 'snapshot': add_page2.context['token'], 'name': 'إدارة الجودة والتطوير', 'kind': 'department'})
        self.assertEqual(dup.status_code, 400)

        # Edit via pop-up
        edit_page = self.client.get(f'{self.url}?edit={dept.pk}')
        self.assertEqual(edit_page.status_code, 200)
        res = self.client.post(self.url, {
            'operation': 'edit',
            'snapshot': edit_page.context['token'],
            'name': 'إدارة الجودة المؤسسية',
            'kind': 'department',
        })
        self.assertEqual(res.status_code, 302)
        dept.refresh_from_db()
        self.assertEqual(dept.name, 'إدارة الجودة المؤسسية')

        # Toggle inactive (unlinked succeeds)
        res = self.client.post(self.url, {'operation': 'toggle', 'snapshot': _snapshot(self.admin, 'toggle', dept)})
        self.assertEqual(res.status_code, 302)
        dept.refresh_from_db()
        self.assertFalse(dept.is_active)

        # Search and status filter
        filtered = self.client.get(self.url, {'q': 'الجودة', 'status': '0'})
        self.assertContains(filtered, 'إدارة الجودة المؤسسية')
        filtered_active = self.client.get(self.url, {'q': 'الجودة', 'status': '1'})
        self.assertNotContains(filtered_active, 'إدارة الجودة المؤسسية')

        # Delete unlinked succeeds
        res = self.client.post(self.url, {'operation': 'delete', 'snapshot': _snapshot(self.admin, 'delete', dept)})
        self.assertEqual(res.status_code, 302)
        self.assertFalse(Department.objects.filter(pk=dept.pk).exists())

    def test_linked_department_blocks_both_deactivation_and_deletion_no_cascade(self):
        self.client.force_login(self.admin, backend='accounts.backends.EmailOrUsernameBackend')
        dept = Department.objects.create(name='إدارة الموارد البشرية')
        employee = User.objects.create_user('dept-emp', 'dept-emp@makken.test', 'EmpPass!9876')
        UserProfile.objects.create(user=employee, department=dept)

        # Deactivation blocked by core.dependencies
        toggle_res = self.client.post(self.url, {'operation': 'toggle', 'snapshot': _snapshot(self.admin, 'toggle', dept)})
        self.assertEqual(toggle_res.status_code, 409)
        self.assertIn('dependency_block', toggle_res.context)
        dept.refresh_from_db()
        self.assertTrue(dept.is_active)

        # Deletion blocked by core.dependencies
        delete_res = self.client.post(self.url, {'operation': 'delete', 'snapshot': _snapshot(self.admin, 'delete', dept)})
        self.assertEqual(delete_res.status_code, 409)
        self.assertIn('dependency_block', delete_res.context)
        self.assertTrue(Department.objects.filter(pk=dept.pk).exists())

        # ORM-level delete also protected (never cascade deletes UserProfile)
        with self.assertRaises(ProtectedError):
            dept.delete()
        self.assertTrue(UserProfile.objects.filter(user=employee, department=dept).exists())

    def test_user_creation_form_loads_active_departments_from_database(self):
        self.client.force_login(self.admin, backend='accounts.backends.EmailOrUsernameBackend')
        active_dept = Department.objects.create(name='إدارة التحول الرقمي', is_active=True)
        inactive_dept = Department.objects.create(name='إدارة متوقفة', is_active=False)

        page = self.client.get(reverse('access_control:user_create'))
        self.assertEqual(page.status_code, 200)
        dept_qs = list(page.context['form'].fields['department'].queryset)
        self.assertIn(active_dept, dept_qs)
        self.assertNotIn(inactive_dept, dept_qs)

    def test_departments_tab_in_access_control_and_removed_from_sidebar(self):
        self.client.force_login(self.admin)
        ac_page = self.client.get(reverse('access_control:index'))
        self.assertEqual(ac_page.status_code, 200)
        self.assertContains(ac_page, 'إدارة الهيكل التنظيمي')
        self.assertContains(ac_page, self.url)
        dept_page = self.client.get(self.url)
        self.assertEqual(dept_page.status_code, 200)
        self.assertEqual(dept_page.context['active_page'], 'access_control')
        self.assertEqual(dept_page.context['access_tab'], 'departments')
        self.assertContains(dept_page, 'class="ac-tabs"')
        self.assertNotContains(dept_page, 'data-management-group" open')
