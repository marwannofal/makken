from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.defaults import initialize
from access_control.models import PermissionOverride, UserAccess
from agreement_clauses.models import Agreement
from entities.models import Entity
from partnerships.models import Partnership
from regions.models import Region

from .models import Delivery, EventRule, SMTPConfig, WorkAssignment, WorkHistory

User = get_user_model()


class WorkAssignmentsUS04US05Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()
        cls.admin = User.objects.create_superuser('work-admin', 'work-admin@makken.test', 'AdminPass!9876')
        cls.riyadh = Region.objects.create(name='منطقة الرياض للمهام')
        cls.jeddah = Region.objects.create(name='منطقة مكة للمهام')

        cls.entity = Entity.objects.create(name='جهة اختبار المهام', entity_type='government')
        cls.partner_riyadh = Partnership.objects.create(name='شراكة الرياض للمهام', entity=cls.entity, scope='local')
        cls.partner_riyadh.administrative_regions.add(cls.riyadh)
        cls.partner_jeddah = Partnership.objects.create(name='شراكة مكة للمهام', entity=cls.entity, scope='local')
        cls.partner_jeddah.administrative_regions.add(cls.jeddah)

        cls.agr_riyadh = Agreement.objects.create(
            partnership=cls.partner_riyadh,
            title='اتفاقية مهام الرياض',
            created_by=cls.admin,
        )
        cls.agr_jeddah = Agreement.objects.create(
            partnership=cls.partner_jeddah,
            title='اتفاقية مهام مكة',
            created_by=cls.admin,
        )

    def setUp(self):
        self.manager = self._user('task-manager', self.riyadh, ('partnerships', 'view'), ('work_assignments', 'view'), ('work_assignments', 'create'), ('work_assignments', 'edit'))
        self.emp1 = self._user('task-emp1', self.riyadh, ('partnerships', 'view'))
        self.emp2 = self._user('task-emp2', self.riyadh, ('partnerships', 'view'))
        self.emp3 = self._user('task-emp3', self.riyadh, ('partnerships', 'view'))
        self.jeddah_emp = self._user('task-jeddah', self.jeddah, ('partnerships', 'view'))
        self.plain_user = self._user('task-plain', self.riyadh, ('partnerships', 'view'))

        SMTPConfig.objects.update_or_create(
            pk=1,
            defaults={
                'enabled': True, 'host': 'smtp.example.com', 'port': 587, 'security': 'starttls',
                'sender': 'noreply@makken.menatech.edu.jo', 'sender_name': 'منصة مكّن',
            },
        )
        for code in ('work.created', 'work.reassigned'):
            EventRule.objects.update_or_create(code=code, defaults={'enabled': True, 'to_employee': True, 'to_manager': True})

    def _user(self, username, region, *grants):
        user = User.objects.create_user(username, f'{username}@makken.test', 'UserPass!2026', first_name=username)
        access = UserAccess.objects.create(user=user, page_scope='all', region_scope='selected')
        access.allowed_regions.add(region)
        for module_id, op in grants:
            PermissionOverride.objects.create(user=user, module_id=module_id, operation=op, effect='grant')
        return user

    def test_authorized_manager_assigns_multi_employee_agreement_task_and_reassigns(self):
        self.client.force_login(self.manager, backend='accounts.backends.EmailOrUsernameBackend')

        # Target search returns Riyadh agreement (supports AGR- number), never Jeddah agreement
        search_res = self.client.get(reverse('makken_mail:work_targets'), {
            'model': 'agreement_clauses.agreement',
            'q': self.agr_riyadh.number,
        })
        self.assertEqual(search_res.status_code, 200)
        ids = [row['id'] for row in search_res.json()['results']]
        self.assertEqual(ids, [str(self.agr_riyadh.pk)])

        search_jeddah = self.client.get(reverse('makken_mail:work_targets'), {
            'model': 'agreement_clauses.agreement',
            'q': self.agr_jeddah.title,
        })
        self.assertEqual(search_jeddah.json()['results'], [])

        # Manager creates a task assigned to BOTH emp1 and emp2, linked to agr_riyadh
        create_res = self.client.post(reverse('makken_mail:work_create'), {
            'title': 'مراجعة بنود اتفاقية الرياض',
            'instructions': 'متابعة تسليم الشواهد خلال الأسبوع',
            'assignees': [str(self.emp1.pk), str(self.emp2.pk)],
            'manager': str(self.manager.pk),
            'target_model': 'agreement_clauses.agreement',
            'target_key': str(self.agr_riyadh.pk),
        })
        self.assertEqual(create_res.status_code, 302)
        work = WorkAssignment.objects.get(title='مراجعة بنود اتفاقية الرياض')
        self.assertEqual(set(work.assignees.values_list('pk', flat=True)), {self.emp1.pk, self.emp2.pk})
        self.assertEqual(work.target_model, 'agreement_clauses.agreement')
        self.assertEqual(work.target_key, self.agr_riyadh.pk)

        # Both assignees + manager receive work.created notifications
        notified_ids = set(Delivery.objects.filter(rule_id='work.created', work=work).values_list('recipient_id', flat=True))
        self.assertEqual(notified_ids, {self.emp1.pk, self.emp2.pk, self.manager.pk})

        # Detail page links directly to US-17 agreement follow-up card and shows reassign button
        detail = self.client.get(reverse('makken_mail:work_detail', args=[work.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, reverse('partnerships:agreement', args=[self.partner_riyadh.pk, self.agr_riyadh.pk]))
        self.assertContains(detail, reverse('makken_mail:work_edit', args=[work.pk]))

        # Secondary assignee (emp2) can view and update progress
        self.client.force_login(self.emp2, backend='accounts.backends.EmailOrUsernameBackend')
        self.assertContains(self.client.get(reverse('makken_mail:work_index')), work.title)
        prog_res = self.client.post(reverse('makken_mail:work_detail', args=[work.pk]), {
            'revision': str(work.revision),
            'status': 'running',
            'progress': '45',
            'note': 'تمت مراجعة البند الأول',
        })
        self.assertEqual(prog_res.status_code, 302)
        work.refresh_from_db()
        self.assertEqual(work.progress, 45)

        # Manager reassigns task from (emp1, emp2) to (emp2, emp3) -> logs 'reassigned' history & notifies
        self.client.force_login(self.manager, backend='accounts.backends.EmailOrUsernameBackend')
        edit_res = self.client.post(reverse('makken_mail:work_edit', args=[work.pk]), {
            'revision': str(work.revision),
            'title': work.title,
            'instructions': work.instructions,
            'assignees': [str(self.emp2.pk), str(self.emp3.pk)],
            'manager': str(self.manager.pk),
            'target_model': 'agreement_clauses.agreement',
            'target_key': str(self.agr_riyadh.pk),
        })
        self.assertEqual(edit_res.status_code, 302)
        work.refresh_from_db()
        self.assertEqual(set(work.assignees.values_list('pk', flat=True)), {self.emp2.pk, self.emp3.pk})
        self.assertTrue(WorkHistory.objects.filter(assignment=work, action='reassigned').exists())

    def test_cross_region_and_unauthorized_assignment_blocked(self):
        # Plain user without work_assignments permission is denied 403
        self.client.force_login(self.plain_user, backend='accounts.backends.EmailOrUsernameBackend')
        self.assertEqual(self.client.get(reverse('makken_mail:work_create')).status_code, 403)
        self.assertEqual(self.client.get(reverse('makken_mail:work_targets'), {'model': 'agreement_clauses.agreement'}).status_code, 403)

        # Riyadh manager cannot link Jeddah agreement or assign Jeddah-only employee
        self.client.force_login(self.manager, backend='accounts.backends.EmailOrUsernameBackend')
        bad_target = self.client.post(reverse('makken_mail:work_create'), {
            'title': 'محاولة ربط مكة',
            'assignees': [str(self.emp1.pk)],
            'manager': str(self.manager.pk),
            'target_model': 'agreement_clauses.agreement',
            'target_key': str(self.agr_jeddah.pk),
        })
        self.assertEqual(bad_target.status_code, 400)

        bad_emp = self.client.post(reverse('makken_mail:work_create'), {
            'title': 'محاولة إسناد موظف مكة',
            'assignees': [str(self.jeddah_emp.pk)],
            'manager': str(self.manager.pk),
            'target_model': 'agreement_clauses.agreement',
            'target_key': str(self.agr_riyadh.pk),
        })
        self.assertEqual(bad_emp.status_code, 400)
        self.assertFalse(WorkAssignment.objects.filter(title__startswith='محاولة').exists())
