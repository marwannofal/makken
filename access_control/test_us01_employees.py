import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from accounts.models import Department, UserProfile
from agreement_clauses.models import (
    Agreement,
    AgreementClause,
    AgreementDetails,
    AgreementFollowupState,
    AgreementOption,
    ClauseAssignment,
    DepartmentType,
    OptionKind,
)
from entities.models import Entity
from makken_mail.models import Delivery, EventRule, SMTPConfig
from makken_mail.worker import build_context
from partnerships.models import Partnership
from regions.models import Region

from .defaults import initialize
from .models import RoleProfile, SecurityAudit

User = get_user_model()


class EmployeeManagementUS01Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()
        cls.admin = User.objects.create_superuser('us01-admin', 'us01-admin@makken.test', 'AdminPass!9876')
        cls.riyadh = Region.objects.create(name='منطقة الرياض للموظفين')
        cls.jeddah = Region.objects.create(name='منطقة مكة للموظفين')
        cls.city_riyadh = AgreementOption.objects.create(kind=OptionKind.CITY, name='الرياض للاختبار')
        cls.dept_training = Department.objects.create(name='إدارة التدريب للموظفين')
        cls.watcher_role = RoleProfile.objects.get(system_key='watcher')
        cls.entity = Entity.objects.create(name='جهة اختبار الموظفين', entity_type='government')
        cls.partner_riyadh = Partnership.objects.create(name='شراكة الرياض للموظف', entity=cls.entity, scope='local')
        cls.partner_riyadh.administrative_regions.add(cls.riyadh)
        cls.partner_jeddah = Partnership.objects.create(name='شراكة مكة للموظف', entity=cls.entity, scope='local')
        cls.partner_jeddah.administrative_regions.add(cls.jeddah)

    def setUp(self):
        self.client.force_login(self.admin, backend='accounts.backends.EmailOrUsernameBackend')
        EventRule.objects.update_or_create(code='account.regions_assigned', defaults={'to_subject': True, 'enabled': True})
        SMTPConfig.objects.update_or_create(
            pk=1,
            defaults={
                'enabled': True,
                'host': 'smtp.example.com',
                'port': 587,
                'security': 'starttls',
                'sender': 'noreply@makken.menatech.edu.jo',
                'sender_name': 'منصة مكّن',
                'username': '',
                'secret': '',
            },
        )

    def _create_payload(self, snapshot, **overrides):
        data = {
            'snapshot': snapshot,
            'full_name': 'سعود العتيبي',
            'username': 'saud.emp',
            'email': 'saud@makken.test',
            'is_active': '1',
            'city': str(self.city_riyadh.pk),
            'department': str(self.dept_training.pk),
            'must_change_password': '1',
            'send_welcome_email': '1',
            'new_password1': 'TempPass!2026',
            'new_password2': 'TempPass!2026',
            'roles': [str(self.watcher_role.pk)],
            'page_scope': 'all',
            'region_scope': 'selected',
            'allowed_regions': [str(self.riyadh.pk)],
        }
        data.update(overrides)
        return data

    def test_create_employee_with_city_dept_regions_welcome_email_and_forced_password_change(self):
        create_url = reverse('access_control:user_create')
        page = self.client.get(create_url)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context['form'].initial['must_change_password'], '1')
        self.assertEqual(page.context['form'].initial['send_welcome_email'], '1')

        payload = self._create_payload(page.context['form']['snapshot'].value())
        sent_messages = []

        def fake_send(config, address, context, message_id):
            sent_messages.append((address, context))

        with patch('access_control.employee_agreements.send', side_effect=fake_send):
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(create_url, payload)

        self.assertEqual(response.status_code, 302)
        employee = User.objects.get(username='saud.emp')
        profile = UserProfile.objects.get(user=employee)
        self.assertEqual(profile.city_id, self.city_riyadh.pk)
        self.assertEqual(profile.department_id, self.dept_training.pk)
        self.assertTrue(profile.must_change_password)
        self.assertEqual(list(employee.makken_access.allowed_regions.values_list('pk', flat=True)), [self.riyadh.pk])

        # Welcome email sent with credentials and forced-change notice; password never stored in audit or Delivery
        self.assertEqual(len(sent_messages), 1)
        addr, ctx = sent_messages[0]
        self.assertEqual(addr, 'saud@makken.test')
        details_dict = dict(ctx['details'])
        self.assertEqual(details_dict['البريد الإلكتروني'], 'saud@makken.test')
        self.assertEqual(details_dict['اسم المستخدم'], 'saud.emp')
        self.assertEqual(details_dict['كلمة المرور الأولية'], 'TempPass!2026')
        self.assertIn('تغيير كلمة المرور', ctx['description'])

        audit_log = SecurityAudit.objects.filter(target_user=employee).first()
        self.assertNotIn('TempPass!2026', json.dumps([audit_log.before, audit_log.after]))

        # Regional assignment email queued in makken_mail Delivery and renders assigned regions
        delivery = Delivery.objects.get(rule_id='account.regions_assigned', recipient=employee)
        mail_ctx = build_context(delivery, None)
        self.assertIn(self.riyadh.name, dict(mail_ctx['details'])['المناطق المعينة'])

        # Log in as employee -> forced redirect to /profile/ with persistent toaster until password is changed
        self.client.logout()
        self.assertEqual(self.client.post('/login', {'username': 'saud.emp', 'password': 'TempPass!2026'}).status_code, 302)
        blocked = self.client.get(reverse('partnerships:index'))
        self.assertEqual(blocked.status_code, 302)
        self.assertEqual(blocked.url, reverse('accounts:profile'))

        profile_page = self.client.get(reverse('accounts:profile'))
        self.assertEqual(profile_page.status_code, 200)
        self.assertContains(profile_page, 'data-must-change-password-toast')

        # Changing password clears must_change_password and restores RBAC-scoped access
        pw_snap = profile_page.context['password_form']['snapshot'].value()
        pw_res = self.client.post(reverse('accounts:profile'), {
            'action': 'password',
            'snapshot': pw_snap,
            'old_password': 'TempPass!2026',
            'new_password1': 'NewSecure!2026',
            'new_password2': 'NewSecure!2026',
        })
        self.assertEqual(pw_res.status_code, 302)
        profile.refresh_from_db()
        self.assertFalse(profile.must_change_password)

        # Toaster is gone and RBAC regional scoping works (sees Riyadh partnership, not Jeddah)
        after_profile = self.client.get(reverse('accounts:profile'))
        self.assertNotContains(after_profile, 'data-must-change-password-toast')
        partnerships_res = self.client.get(reverse('partnerships:index'))
        self.assertEqual(partnerships_res.status_code, 200)
        self.assertContains(partnerships_res, self.partner_riyadh.name)
        self.assertNotContains(partnerships_res, self.partner_jeddah.name)

    def test_admin_can_disable_forced_password_change_and_welcome_email(self):
        create_url = reverse('access_control:user_create')
        page = self.client.get(create_url)
        payload = self._create_payload(
            page.context['form']['snapshot'].value(),
            username='nora.emp',
            email='nora@makken.test',
            must_change_password='0',
            send_welcome_email='0',
        )
        with patch('access_control.employee_agreements.send') as mocked_send:
            with self.captureOnCommitCallbacks(execute=True):
                res = self.client.post(create_url, payload)
        self.assertEqual(res.status_code, 302)
        mocked_send.assert_not_called()

        employee = User.objects.get(username='nora.emp')
        self.assertFalse(UserProfile.objects.get(user=employee).must_change_password)

        # Immediately accesses authorized page without redirect to /profile/
        self.client.logout()
        self.assertEqual(self.client.post('/login', {'username': 'nora.emp', 'password': 'TempPass!2026'}).status_code, 302)
        self.assertEqual(self.client.get(reverse('partnerships:index')).status_code, 200)

    def test_employee_agreements_progress_and_last_followup_shown_on_account_page(self):
        emp = User.objects.create_user('agreements-emp', 'agr-emp@makken.test', 'EmpPass!2026', first_name='فهد')
        UserProfile.objects.create(user=emp, city=self.city_riyadh, department=self.dept_training)
        agr = Agreement.objects.create(partnership=self.partner_riyadh, title='اتفاقية الموظف الرئيسية', created_by=self.admin)
        AgreementDetails.objects.create(agreement=agr, responsible_employee=emp)
        c1 = AgreementClause.objects.create(name='بند الموظف 1')
        c2 = AgreementClause.objects.create(name='بند الموظف 2')
        ClauseAssignment.objects.create(agreement=agr, clause=c1, responsibility='shared', progress=50, updated_by=self.admin)
        ClauseAssignment.objects.create(agreement=agr, clause=c2, responsibility='shared', progress=75, updated_by=self.admin)
        AgreementFollowupState.objects.create(agreement=agr, updated_by=self.admin)

        edit_page = self.client.get(reverse('access_control:user_edit', args=[emp.pk]))
        self.assertEqual(edit_page.status_code, 200)
        self.assertContains(edit_page, 'اتفاقيات الموظف')
        self.assertContains(edit_page, agr.number)
        self.assertContains(edit_page, 'اتفاقية الموظف الرئيسية')
        self.assertContains(edit_page, '62.50%')
        self.assertContains(edit_page, 'الموظف المسؤول')

        list_page = self.client.get(reverse('access_control:index'))
        self.assertContains(list_page, self.city_riyadh.name)
        self.assertContains(list_page, self.dept_training.name)

    def test_unified_willingness_partnership_progress_and_followup_shown_for_employee(self):
        from django.utils import timezone
        from makken_mail.models import WorkAssignment
        from partnerships.models import PartnershipTeamMember, TeamMemberRole, TeamSide

        emp = User.objects.create_user('unified-emp', 'unified-emp@makken.test', 'EmpPass!2026', first_name='سارة')
        extra = User.objects.create_user('unified-extra', 'unified-extra@makken.test', 'EmpPass!2026', first_name='خالد')
        UserProfile.objects.create(user=emp, city=self.city_riyadh, department=self.dept_training)
        UserProfile.objects.create(user=extra, city=self.city_riyadh, department=self.dept_training)

        self.partner_riyadh.agreement_number = '202611999'
        self.partner_riyadh.followup_updated_at = timezone.now()
        self.partner_riyadh.followup_updated_by = self.admin
        self.partner_riyadh.save(update_fields=['agreement_number', 'followup_updated_at', 'followup_updated_by'])

        work = WorkAssignment.objects.create(
            title='متابعة شراكة الرياض',
            target_model='partnerships.partnership',
            target_key=self.partner_riyadh.pk,
            employee=emp,
            manager=self.admin,
            created_by=self.admin,
        )
        work.assignees.add(emp, extra)
        PartnershipTeamMember.objects.create(
            partnership=self.partner_riyadh,
            side=TeamSide.INSTITUTION,
            name='خالد',
            email='unified-extra@makken.test',
            role=TeamMemberRole.LIAISON,
        )

        c1 = AgreementClause.objects.create(name='بند موحد 1')
        c2 = AgreementClause.objects.create(name='بند موحد 2')
        ClauseAssignment.objects.create(partnership=self.partner_riyadh, clause=c1, responsibility='shared', progress=40, updated_by=self.admin)
        ClauseAssignment.objects.create(partnership=self.partner_riyadh, clause=c2, responsibility='institution', progress=80, updated_by=self.admin)

        edit_page = self.client.get(reverse('access_control:user_edit', args=[emp.pk]))
        self.assertEqual(edit_page.status_code, 200)
        self.assertContains(edit_page, '202611999')
        self.assertContains(edit_page, self.partner_riyadh.name)
        self.assertContains(edit_page, '60%')
        self.assertContains(edit_page, 'الموظف المسؤول')

        extra_page = self.client.get(reverse('access_control:user_edit', args=[extra.pk]))
        self.assertEqual(extra_page.status_code, 200)
        self.assertContains(extra_page, '202611999')
        self.assertContains(extra_page, 'ضابط اتصال')

        list_page = self.client.get(reverse('access_control:index'), {'q': 'unified-emp'})
        self.assertEqual(list_page.status_code, 200)
        self.assertContains(list_page, f'/access-control/users/{emp.pk}/#employee-agreements')

    def test_regions_assigned_email_includes_regional_partnership_info(self):
        from makken_mail.models import Delivery, EventRule
        from makken_mail.worker import mail_content

        emp = User.objects.create_user('region-mail-emp', 'region-mail@makken.test', 'EmpPass!2026', first_name='ريم')
        self.partner_riyadh.agreement_number = '202611888'
        self.partner_riyadh.save(update_fields=['agreement_number'])
        self.partner_riyadh.administrative_regions.add(self.riyadh)

        access, _ = UserAccess.objects.get_or_create(user=emp, defaults={'region_scope': 'selected'})
        access.region_scope = 'selected'
        access.save()
        access.allowed_regions.set([self.riyadh])

        rule, _ = EventRule.objects.get_or_create(code='account.regions_assigned', defaults={'to_subject': True, 'enabled': True})
        delivery = Delivery.objects.create(
            rule=rule,
            recipient=emp,
            recipient_key=emp.pk,
            email_digest='test',
            actor=self.admin,
            subject_user=emp,
            source=f'regions:{emp.pk}:test',
        )
        content = mail_content(delivery, emp)
        details_dict = dict(content['details'])
        self.assertIn('عدد الشراكات والاتفاقيات في النطاق', details_dict)
        self.assertIn(self.partner_riyadh.name, details_dict.get('أبرز الشراكات والاتفاقيات', ''))
        self.assertIn('202611888', details_dict.get('أبرز الشراكات والاتفاقيات', ''))
