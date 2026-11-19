"""US-07 tests: per-employee task statistics over date range, RBAC, regional scope, and exports."""
from datetime import datetime, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from access_control.defaults import initialize
from access_control.models import PermissionOverride, RegionScope, UserAccess
from agreement_clauses.models import Agreement
from entities.models import Entity
from partnerships.models import Partnership
from regions.models import Region

from .models import WorkAssignment, WorkStatus

User = get_user_model()
AUTH_BACKEND = 'accounts.backends.EmailOrUsernameBackend'


class TaskStatisticsUS07Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()

    def setUp(self):
        self.region_a = Region.objects.create(name='منطقة الإحصائيات أ', is_active=True)
        self.region_b = Region.objects.create(name='منطقة الإحصائيات ب', is_active=True)

        self.admin = User.objects.create_superuser('stats_admin', 'stats_admin@example.com', 'StrongPass123!')
        self.manager = User.objects.create_user(
            'stats_mgr', 'stats_mgr@example.com', 'StrongPass123!', first_name='مدير', last_name='الإحصائيات'
        )
        self.emp_a1 = User.objects.create_user(
            'emp_a1', 'emp_a1@example.com', 'StrongPass123!', first_name='أحمد', last_name='الأول'
        )
        self.emp_a2 = User.objects.create_user(
            'emp_a2', 'emp_a2@example.com', 'StrongPass123!', first_name='سارة', last_name='الثانية'
        )
        self.emp_b = User.objects.create_user(
            'emp_b', 'emp_b@example.com', 'StrongPass123!', first_name='خالد', last_name='الآخر'
        )

        # Regional access setup
        for person, reg in [
            (self.manager, self.region_a),
            (self.emp_a1, self.region_a),
            (self.emp_a2, self.region_a),
            (self.emp_b, self.region_b),
        ]:
            acc, _ = UserAccess.objects.get_or_create(
                user=person,
                defaults={'page_scope': 'all', 'region_scope': RegionScope.SELECTED},
            )
            acc.page_scope = 'all'
            acc.region_scope = RegionScope.SELECTED
            acc.save()
            acc.allowed_regions.set([reg])

        # Grant manager work_assignments.view + partnerships.view (not export_xlsx yet)
        PermissionOverride.objects.create(user=self.manager, module_id='work_assignments', operation='view', effect='grant')
        PermissionOverride.objects.create(user=self.manager, module_id='partnerships', operation='view', effect='grant')

        # Create an agreement in region_b to verify cross-region target exclusion
        entity = Entity.objects.create(name='جهة اختبار إحصائيات', entity_type='government', is_active=True)
        partnership_b = Partnership.objects.create(
            name='شراكة منطقة ب',
            entity=entity,
            scope='local',
            is_active=True,
        )
        partnership_b.administrative_regions.set([self.region_b])
        self.agreement_b = Agreement.objects.create(
            partnership=partnership_b,
            title='اتفاقية منطقة ب',
            created_by=self.admin,
        )

        tz = timezone.get_current_timezone()
        today = timezone.localdate()

        # Task 1: Multi-assignee (emp_a1 + emp_a2), COMPLETE, inside Jan 2026
        self.task_jan = WorkAssignment.objects.create(
            title='مهمة مشتركة يناير',
            employee=self.emp_a1,
            manager=self.manager,
            created_by=self.manager,
            status=WorkStatus.COMPLETE,
            progress=100,
        )
        self.task_jan.assignees.set([self.emp_a1, self.emp_a2])
        WorkAssignment.objects.filter(pk=self.task_jan.pk).update(
            created_at=timezone.make_aware(datetime(2026, 1, 15, 10, 0), tz)
        )

        # Task 2: Single assignee (emp_a1), RUNNING & overdue, inside Feb 2026
        self.task_feb = WorkAssignment.objects.create(
            title='مهمة متأخرة فبراير',
            employee=self.emp_a1,
            manager=self.manager,
            created_by=self.manager,
            status=WorkStatus.RUNNING,
            progress=40,
            due_on=today - timedelta(days=3),
        )
        self.task_feb.assignees.set([self.emp_a1])
        WorkAssignment.objects.filter(pk=self.task_feb.pk).update(
            created_at=timezone.make_aware(datetime(2026, 2, 10, 12, 0), tz)
        )

        # Task 3: Region B employee & agreement, inside Jan 2026
        self.task_b = WorkAssignment.objects.create(
            title='مهمة منطقة ب',
            employee=self.emp_b,
            manager=self.admin,
            created_by=self.admin,
            target_model='agreement_clauses.agreement',
            target_key=self.agreement_b.pk,
            status=WorkStatus.NEW,
            progress=0,
        )
        self.task_b.assignees.set([self.emp_b])
        WorkAssignment.objects.filter(pk=self.task_b.pk).update(
            created_at=timezone.make_aware(datetime(2026, 1, 20, 9, 0), tz)
        )

    def test_unauthorized_employee_and_write_methods_denied(self):
        self.client.force_login(self.emp_a1, backend=AUTH_BACKEND)
        resp = self.client.get(reverse('makken_mail:work_stats'))
        self.assertEqual(resp.status_code, 403)

        self.client.force_login(self.manager, backend=AUTH_BACKEND)
        self.assertEqual(self.client.post(reverse('makken_mail:work_stats')).status_code, 403)

    def test_date_range_and_multi_assignee_counts_for_superuser(self):
        self.client.force_login(self.admin, backend=AUTH_BACKEND)
        # Filter to January 2026 only -> task_jan (emp_a1 + emp_a2) and task_b (emp_b)
        resp = self.client.get(reverse('makken_mail:work_stats'), {
            'date_from': '2026-01-01',
            'date_to': '2026-01-31',
        })
        self.assertEqual(resp.status_code, 200)
        stats = resp.context['stats']
        self.assertEqual(stats['totals']['distinct_tasks'], 2)
        self.assertEqual(stats['totals']['total_assignments'], 3)
        by_user = {r['username']: r for r in stats['rows']}
        self.assertEqual(by_user['emp_a1']['total'], 1)
        self.assertEqual(by_user['emp_a1']['complete'], 1)
        self.assertEqual(by_user['emp_a2']['total'], 1)
        self.assertEqual(by_user['emp_b']['total'], 1)
        self.assertEqual(by_user['emp_b']['new'], 1)

        # Full range -> emp_a1 has 2 tasks (1 complete 100%, 1 running overdue 40% -> avg 70%)
        resp_all = self.client.get(reverse('makken_mail:work_stats'))
        by_user_all = {r['username']: r for r in resp_all.context['stats']['rows']}
        self.assertEqual(by_user_all['emp_a1']['total'], 2)
        self.assertEqual(by_user_all['emp_a1']['overdue'], 1)
        self.assertEqual(by_user_all['emp_a1']['avg_progress'], 70)

    def test_regional_manager_scoping_and_invalid_filters(self):
        self.client.force_login(self.manager, backend=AUTH_BACKEND)
        resp = self.client.get(reverse('makken_mail:work_stats'))
        self.assertEqual(resp.status_code, 200)
        usernames = {r['username'] for r in resp.context['stats']['rows']}
        self.assertEqual(usernames, {'emp_a1', 'emp_a2'})
        self.assertNotIn('emp_b', usernames)

        # Attempting to filter by unauthorized region_b returns validation error and zero rows
        resp_bad_reg = self.client.get(reverse('makken_mail:work_stats'), {'region': str(self.region_b.pk)})
        self.assertEqual(resp_bad_reg.status_code, 200)
        self.assertTrue(resp_bad_reg.context['stats']['errors'])
        self.assertEqual(resp_bad_reg.context['stats']['rows'], [])

        # Reversed date range returns validation error
        resp_bad_dates = self.client.get(reverse('makken_mail:work_stats'), {
            'date_from': '2026-03-01',
            'date_to': '2026-01-01',
        })
        self.assertEqual(resp_bad_dates.status_code, 200)
        self.assertTrue(resp_bad_dates.context['stats']['errors'])

    def test_export_permissions_enforced_on_work_stats(self):
        self.client.force_login(self.manager, backend=AUTH_BACKEND)
        # Without export_xlsx permission -> 403
        denied_export = self.client.get(reverse('makken_mail:work_stats'), {'_mk_export': 'xlsx'})
        self.assertEqual(denied_export.status_code, 403)

        # Grant export_xlsx -> 200 with Excel payload
        PermissionOverride.objects.create(
            user=self.manager, module_id='work_assignments', operation='export_xlsx', effect='grant'
        )
        ok_export = self.client.get(reverse('makken_mail:work_stats'), {'_mk_export': 'xlsx'})
        self.assertEqual(ok_export.status_code, 200)
        self.assertIn('spreadsheetml', ok_export['Content-Type'])
