from datetime import date, datetime, timezone as dt_timezone
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from access_control.defaults import initialize
from access_control.models import Module, PageScope, PermissionOverride, RegionScope, UserAccess
from entities.models import Entity
from partnerships.models import Partnership
from regions.models import Region

from .models import Delivery, DeliveryStatus, EventRule, RecipientMute, SMTPConfig, WorkAssignment, WorkStatus
from .registry import PARTNERSHIP_EXPIRY
from .reminders import business_date, queue_due_reminders, shifted_month
from .smtp import build_message
from .worker import process

User = get_user_model()
NOW = datetime(2026, 11, 18, 8, tzinfo=dt_timezone.utc)


class PartnershipReminderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()
        cls.admin = User.objects.create_superuser('reminder-admin', 'admin@example.org', 'TestPassword')
        cls.employee = User.objects.create_user('responsible', 'employee@example.org')
        cls.manager = User.objects.create_user('responsible-manager', 'manager@example.org')
        cls.outside = User.objects.create_user('another-region', 'outside@example.org')
        cls.denied = User.objects.create_user('no-module', 'denied@example.org')
        cls.inactive = User.objects.create_user('inactive', 'inactive@example.org', is_active=False)
        cls.region = Region.objects.create(name='منطقة التذكير')
        other_region = Region.objects.create(name='منطقة خارجية')
        cls.entity = Entity.objects.create(name='جهة اختبار الإشعار', entity_type='government')
        for user in (cls.employee, cls.manager, cls.outside, cls.denied, cls.inactive):
            access = UserAccess.objects.create(user=user, page_scope='all', region_scope='selected')
            access.allowed_regions.add(other_region if user == cls.outside else cls.region)
            if user != cls.denied:
                PermissionOverride.objects.create(user=user, module_id='partnerships', operation='view', effect='grant')

    def setUp(self):
        self.rule = EventRule.objects.get(pk=PARTNERSHIP_EXPIRY)

    def enable(self, manager=False):
        SMTPConfig.objects.filter(pk=1).update(host='smtp.example.org', sender='makken@example.org', enabled=True)
        EventRule.objects.filter(pk=PARTNERSHIP_EXPIRY).update(enabled=True, to_manager=manager)

    def partner(self, name='شراكة تذكير تجريبية', end=date(2027, 1, 18), active=True):
        item = Partnership.objects.create(
            name=name, representative='ممثل', phone='+966501234567', email='partner@example.org',
            entity=self.entity, scope='local', is_active=active,
            starts_on=date(2026, 1, 1) if end else None, ends_on=end,
        )
        item.administrative_regions.add(self.region)
        return item

    def assign(self, item, employee=None, manager=None, status=WorkStatus.NEW, model='partnerships.partnership'):
        return WorkAssignment.objects.create(
            title='متابعة الشراكة', target_model=model, target_key=item.pk if model else None,
            employee=employee or self.employee, manager=manager or self.manager,
            status=status, progress=100 if status == WorkStatus.COMPLETE else 0,
        )

    def deliver(self, now=NOW):
        row = Delivery.objects.latest('pk')
        Delivery.objects.filter(pk=row.pk).update(status=DeliveryStatus.SENDING, created_at=NOW, attempts=1)
        with patch('makken_mail.worker.send') as send:
            process(row.pk, now)
        row.refresh_from_db()
        return row, send

    def test_calendar_months_clamp_and_riyadh_midnight(self):
        self.assertEqual(shifted_month(date(2026, 4, 30), -2), date(2026, 2, 28))
        self.assertEqual(shifted_month(date(2028, 4, 30), -2), date(2028, 2, 29))
        self.assertEqual(shifted_month(date(2027, 1, 31), -2), date(2026, 11, 30))
        before = datetime(2026, 2, 27, 20, 59, tzinfo=dt_timezone.utc)
        after = datetime(2026, 2, 27, 21, 0, tzinfo=dt_timezone.utc)
        self.assertEqual(business_date(before), date(2026, 2, 27))
        self.assertEqual(business_date(after), date(2026, 2, 28))
        self.enable()
        self.assign(self.partner(end=date(2026, 4, 30)))
        self.assertEqual(queue_due_reminders(before), 0)
        self.assertEqual(queue_due_reminders(after), 1)

    def test_default_rule_stays_off_until_enabled_and_smtp_ready(self):
        self.assertFalse(self.rule.enabled)
        self.assertTrue(self.rule.to_employee)
        self.assertFalse(self.rule.to_manager)
        self.assign(self.partner())
        self.assertEqual(queue_due_reminders(NOW), 0)
        EventRule.objects.filter(pk=PARTNERSHIP_EXPIRY).update(enabled=True)
        self.assertEqual(queue_due_reminders(NOW), 0)
        self.enable()
        self.assertEqual(queue_due_reminders(NOW), 1)

    def test_command_queues_catch_up_once_per_person_and_end_date(self):
        self.enable(manager=True)
        item = self.partner(end=date(2026, 12, 1))
        self.assign(item)
        self.assign(item, status=WorkStatus.RUNNING)
        self.assign(item, employee=self.manager, manager=self.employee)
        for expected in (2, 0):
            output = StringIO()
            with patch('makken_mail.reminders.timezone.now', return_value=NOW):
                call_command('queue_partnership_expiry_reminders', stdout=output)
            self.assertIn(f'queued: {expected}', output.getvalue())
        rows = Delivery.objects.filter(rule=self.rule)
        self.assertCountEqual(rows.values_list('recipient_id', flat=True), [self.employee.pk, self.manager.pk])
        self.assertEqual(set(rows.values_list('source', flat=True)), {f'partnership-expiry:{item.pk}:2026-12-01'})
        Partnership.objects.filter(pk=item.pk).update(ends_on=date(2027, 1, 17))
        self.assertEqual(queue_due_reminders(NOW), 2)
        self.assertEqual(rows.count(), 4)

    def test_requires_eligible_open_direct_assignment_and_available_end_date(self):
        self.enable()
        item = self.partner()
        self.assign(item, status=WorkStatus.COMPLETE)
        self.assign(item, status=WorkStatus.CANCELLED)
        self.assign(item, employee=self.outside)
        self.assign(item, employee=self.denied)
        self.assign(item, employee=self.inactive)
        self.assign(item, model='market_needs.sponsorship')
        self.assign(item, model='')
        for name, end, active in (
            ('شراكة خارج المهلة', date(2027, 1, 19), True),
            ('شراكة تنتهي اليوم', date(2026, 11, 18), True),
            ('شراكة منتهية', date(2026, 11, 17), True),
            ('شراكة غير نشطة', date(2026, 12, 1), False),
            ('شراكة بلا فترة', None, True),
        ):
            self.assign(self.partner(name, end, active))
        self.rule.recipients.add(self.admin)
        self.assertEqual(queue_due_reminders(NOW), 0)
        self.assign(item)
        RecipientMute.objects.create(rule=self.rule, user=self.employee)
        self.assertEqual(queue_due_reminders(NOW), 0)
        RecipientMute.objects.filter(rule=self.rule, user=self.employee).delete()
        self.assertEqual(queue_due_reminders(NOW), 1)
        self.assertEqual(Delivery.objects.get().recipient_id, self.employee.pk)

    def test_delivery_checks_date_assignment_and_permissions_again(self):
        self.enable()
        item = self.partner()
        work = self.assign(item)
        self.assertEqual(queue_due_reminders(NOW), 1)
        Partnership.objects.filter(pk=item.pk).update(ends_on=date(2027, 1, 17))
        row, send = self.deliver()
        self.assertEqual((row.status, row.reason), (DeliveryStatus.SKIPPED, 'reminder_obsolete'))
        send.assert_not_called()

        self.assertEqual(queue_due_reminders(NOW), 1)
        WorkAssignment.objects.filter(pk=work.pk).update(employee=self.outside)
        row, send = self.deliver()
        self.assertEqual((row.status, row.reason), (DeliveryStatus.SKIPPED, 'eligibility'))
        send.assert_not_called()

        WorkAssignment.objects.filter(pk=work.pk).update(employee=self.employee)
        Partnership.objects.filter(pk=item.pk).update(ends_on=date(2027, 1, 16))
        self.assertEqual(queue_due_reminders(NOW), 1)
        self.employee.makken_access.allowed_regions.clear()
        row, send = self.deliver()
        self.assertEqual((row.status, row.reason), (DeliveryStatus.SKIPPED, 'eligibility'))
        send.assert_not_called()

    def test_email_uses_date_and_authenticated_partnership_link(self):
        self.enable()
        item = self.partner()
        self.assign(item)
        self.assertEqual(queue_due_reminders(NOW), 1)
        row, send = self.deliver()
        self.assertEqual(row.status, DeliveryStatus.SENT)
        config, address, values, message_id = send.call_args.args
        self.assertEqual(address, self.employee.email)
        self.assertIn(('تاريخ نهاية الشراكة', '2027-01-18'), values['details'])
        self.assertTrue(values['link'].endswith(reverse('partnerships:index') + f'?detail={item.pk}'))
        message = build_message(config, address, values, message_id)
        self.assertIn('تذكير بقرب انتهاء الشراكة', message['Subject'])
        self.assertIn('dir="rtl"', message.get_body(preferencelist=('html',)).get_content())
        self.assertIn('2027-01-18', message.get_body(preferencelist=('plain',)).get_content())

    def test_arabic_rule_is_configurable_and_not_available_as_fixed_subscription(self):
        self.client.force_login(self.admin, backend='accounts.backends.EmailOrUsernameBackend')
        url = reverse('makken_mail:rule', args=[PARTNERSHIP_EXPIRY])
        page = self.client.get(url)
        self.assertContains(page, 'تذكير بقرب انتهاء الشراكة')
        self.assertContains(page, 'شهرين تقويميين')
        self.assertNotContains(page, 'name="recipients"')
        response = self.client.post(url, {'revision': self.rule.revision, 'enabled': '1', 'to_employee': '1',
                                          'to_manager': '1', 'recipients': [self.outside.pk]})
        self.assertEqual(response.status_code, 302)
        self.rule.refresh_from_db()
        self.assertTrue(self.rule.enabled and self.rule.to_employee and self.rule.to_manager)
        self.assertFalse(self.rule.recipients.exists())
        preferences = self.client.get(reverse('makken_mail:preferences', args=[self.employee.pk])).context['form']
        self.assertIn(PARTNERSHIP_EXPIRY, dict(preferences.fields['muted'].choices))
        self.assertNotIn(PARTNERSHIP_EXPIRY, dict(preferences.fields['selected'].choices))

    def test_calculated_expiry_without_ends_on_triggers_reminder_for_all_assignees(self):
        self.enable()
        extra = User.objects.create_user('reminder-extra', 'extra@example.org', 'TestPassword')
        access = UserAccess.objects.create(user=extra, page_scope=PageScope.SELECTED, region_scope=RegionScope.SELECTED)
        access.allowed_pages.add(Module.objects.get(pk='partnerships'))
        access.allowed_regions.add(self.region)

        # signed_on=2026-01-18 + 12 months => calculated_expiry=2027-01-18 (exactly 2 months from NOW=2026-11-18)
        item = self.partner()
        Partnership.objects.filter(pk=item.pk).update(signed_on=date(2026, 1, 18), duration_months=12, ends_on=None)
        item.refresh_from_db()
        self.assertIsNone(item.ends_on)
        self.assertEqual(item.calculated_expiry, date(2027, 1, 18))

        work = self.assign(item)
        work.assignees.add(self.employee, extra)

        self.assertEqual(queue_due_reminders(NOW), 2)
        rows = list(Delivery.objects.filter(rule_id=PARTNERSHIP_EXPIRY).order_by('pk'))
        self.assertEqual({r.recipient_id for r in rows}, {self.employee.pk, extra.pk})

        row, send = self.deliver()
        self.assertEqual(row.status, DeliveryStatus.SENT)
        _, _, values, _ = send.call_args.args
        self.assertIn(('تاريخ نهاية الشراكة', '2027-01-18'), values['details'])
