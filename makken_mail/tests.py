from datetime import timedelta
from email import policy
from email.parser import BytesParser
import socket
import smtplib
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from access_control.activity_capture import emit
from access_control.activity_history import import_event
from access_control.defaults import initialize
from access_control.models import PermissionOverride, SecurityAudit, UserAccess, UserActivity
from access_control.services import fingerprint, save_user
from entities.models import Entity
from partnerships.models import Partnership
from regions.models import Region

from .events import consume_activity, enqueue
from .models import Delivery, DeliveryStatus as Status, EventRule, RecipientMute, SMTPConfig, WorkAssignment, WorkHistory
from .registry import CATALOG
from .smtp import SendFailure, build_message, decrypt, encrypt, message_link, send, smtp_endpoints
from .views import preview_values, subscriptions
from .work import WorkConflict, WorkInvalid, change_progress, save_work
from .worker import claim, process, run_batch

User = get_user_model()


class MailTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()
        from importlib import import_module
        from django.apps import apps
        from django.db import connection
        seed = import_module('makken_mail.migrations.0002_initial_mail_rules').seed
        class Schema:
            pass
        schema = Schema()
        schema.connection = connection
        seed(apps, schema)
        cls.admin = User.objects.create_superuser('mail-admin', 'admin@example.org', 'Makken!Password337')
        cls.employee = User.objects.create_user('email-employee', 'worker@example.org', 'Makken!Password338')
        cls.manager = User.objects.create_user('email-manager', 'manager@example.org', 'Makken!Password339')
        cls.other = User.objects.create_user('email-other', 'other@example.org', 'Makken!Password340')
        cls.allowed = Region.objects.create(name='منطقة مسموحة')
        cls.hidden = Region.objects.create(name='منطقة أخرى')
        entity = Entity.objects.create(name='كيان اختبار البريد', entity_type='government', branch='')
        cls.partner = Partnership.objects.create(name='شراكة اعتماد البريد', representative='ممثل الشراكة',
            phone='+966501234567', email='external@example.org', entity=entity, scope='local')
        cls.partner.administrative_regions.add(cls.allowed)
        for user in (cls.employee, cls.manager, cls.other):
            access = UserAccess.objects.create(user=user, page_scope='all', region_scope='selected')
            access.allowed_regions.add(cls.hidden if user == cls.other else cls.allowed)
            PermissionOverride.objects.create(user=user, module_id='partnerships', operation='view', effect='grant')

    def enable(self):
        SMTPConfig.objects.filter(pk=1).update(host='smtp.example.org', sender='makken@example.org', enabled=True)

    def login(self, user=None, client=None):
        (client or self.client).force_login(user or self.admin, backend='accounts.backends.EmailOrUsernameBackend')

    def make_work(self, **changes):
        data = {'title': 'متابعة الأعمال البريدية', 'employee': self.employee.pk, 'manager': self.manager.pk}
        data.update(changes)
        return save_work(self.admin, data)

    def self_event(self, **extra):
        fields = dict(actor=self.employee, module='accounts', action='login', description='تسجيل الدخول',
                      source_key='test-login-event', live=True)
        fields.update(extra)
        with self.captureOnCommitCallbacks(execute=True):
            return emit(**fields)

    def admin_user_data(self, **extra):
        data = {'snapshot': 'validated', 'full_name': 'مستخدم اختبار', 'username': 'created-by-admin', 'email': 'created@example.org',
                'is_active': '1', 'page_scope': 'selected', 'allowed_pages': ['regions'],
                'new_password1': 'Test!StrongPassword9246', 'new_password2': 'Test!StrongPassword9246'}
        data.update(extra)
        return data

    def test_seed_catalog_and_smtp_are_blank(self):
        self.assertEqual(set(EventRule.objects.values_list('pk', flat=True)), set(CATALOG))
        config = SMTPConfig.objects.get()
        self.assertEqual((config.host, config.username, config.secret, config.sender), ('', '', '', ''))
        self.assertFalse(config.enabled)
        self.assertTrue(EventRule.objects.get(pk='account.login').enabled)
        self.assertFalse(EventRule.objects.get(pk='dashboard.view').enabled)

    def test_disabled_smtp_does_not_retroactively_queue(self):
        self.self_event()
        self.assertFalse(Delivery.objects.exists())
        self.enable()
        with patch('makken_mail.worker.send') as send_mock:
            self.assertEqual(run_batch(), 0)
        send_mock.assert_not_called()

    def test_actual_successful_login_queues_one_to_actor_failed_login_queues_none(self):
        self.enable()
        with self.captureOnCommitCallbacks(execute=True):
            self.client.post(reverse('accounts:login'), {'username': self.employee.username, 'password': 'bad'})
        self.assertEqual(Delivery.objects.count(), 0)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('accounts:login'), {'username': self.employee.username, 'password': 'Makken!Password338'})
        self.assertEqual(response.status_code, 302)
        row = Delivery.objects.get()
        self.assertEqual((row.rule_id, row.recipient_id), ('account.login', self.employee.pk))

    def test_new_account_notifies_admin_new_account_and_selected_recipient_once(self):
        self.enable()
        rule = EventRule.objects.get(pk='account.created')
        rule.recipients.add(self.admin, self.manager)
        with self.captureOnCommitCallbacks(execute=True):
            user = save_user(self.admin, self.admin_user_data())
        rows = Delivery.objects.filter(rule_id='account.created')
        self.assertCountEqual(rows.values_list('recipient_id', flat=True), [user.pk, self.admin.pk, self.manager.pk])
        with patch('makken_mail.worker.send') as mail:
            run_batch()
        pairs = {call.args[1]: call.args[2] for call in mail.call_args_list}
        self.assertIn('أُنشئ حساب', pairs[user.email]['description'])
        self.assertIn(user.username, str(pairs[self.admin.email]['details']))
        self.assertNotIn(user.username, str(pairs[self.manager.email]))
        self.assertNotIn('Test!StrongPassword9246', str(pairs))

    def test_admin_edit_goes_to_actor_subject_and_selected(self):
        self.enable()
        rule = EventRule.objects.get(pk='account.edited')
        rule.recipients.add(self.manager)
        with self.captureOnCommitCallbacks(execute=True):
            save_user(self.admin, self.admin_user_data(
                username=self.employee.username, email=self.employee.email, full_name='اسم موظف معدل',
                new_password1='', new_password2='',
            ), self.employee.pk, fingerprint(self.employee, 'user'))
        self.assertCountEqual(Delivery.objects.filter(rule=rule).values_list('recipient_id', flat=True),
                              [self.admin.pk, self.employee.pk, self.manager.pk])

    def test_account_noop_edit_does_not_email(self):
        self.enable()
        data = self.admin_user_data()
        user = save_user(self.admin, data)
        with self.captureOnCommitCallbacks(execute=True, using='default'):
            save_user(self.admin, data | {'new_password1': '', 'new_password2': ''}, user.pk, fingerprint(user, 'user'))
        self.assertFalse(Delivery.objects.exists())

    def test_rollback_and_historical_import_do_not_dispatch(self):
        self.enable()
        with self.captureOnCommitCallbacks(execute=True):
            with self.assertRaises(RuntimeError):
                with transaction.atomic():
                    emit(actor=self.admin, module='accounts', action='login', description='test', live=True)
                    raise RuntimeError
        self.assertFalse(Delivery.objects.exists())
        history = SecurityAudit.objects.create(actor=self.admin, actor_name='root', target_user=self.employee,
                                               target_name='employee', action='إنشاء مستخدم', before={}, after={})
        with self.captureOnCommitCallbacks(execute=True):
            import_event(history)
        self.assertFalse(Delivery.objects.exists())

    def test_replaying_same_event_id_is_idempotent(self):
        self.enable()
        event = self.self_event()
        self.assertEqual(consume_activity(event.pk), 0)
        self.assertEqual(Delivery.objects.count(), 1)

    def test_read_events_are_opt_in_and_scope_checked(self):
        self.enable()
        rule = EventRule.objects.get(pk='partnerships.view')
        rule.enabled = True
        rule.save()
        rule.recipients.set([self.manager, self.other])
        self.self_event(module='partnerships', action='view', target_model='partnerships.partnership',
                        target_key=str(self.partner.pk), target_label=self.partner.name,
                        regions={self.allowed.pk: self.allowed.name})
        self.assertEqual(Delivery.objects.get().recipient_id, self.manager.pk)

    def test_revoke_access_cancel_rule_mute_and_address_changes_prevent_delivery(self):
        self.enable()
        rule = EventRule.objects.get(pk='partnerships.view')
        rule.enabled = True
        rule.save()
        rule.recipients.add(self.manager)
        for case in ('scope', 'rule', 'mute', 'address'):
            with self.subTest(case=case):
                self.self_event(module='partnerships', action='view', source_key='revoke:'+case,
                                target_model='partnerships.partnership', target_key=str(self.partner.pk),
                                regions={self.allowed.pk: self.allowed.name})
                if case == 'scope':
                    self.manager.makken_access.allowed_regions.clear()
                elif case == 'rule':
                    EventRule.objects.filter(pk=rule.pk).update(enabled=False)
                elif case == 'mute':
                    RecipientMute.objects.create(rule=rule, user=self.manager)
                else:
                    User.objects.filter(pk=self.manager.pk).update(email='different@example.org')
                with patch('makken_mail.worker.send') as mocked:
                    self.assertEqual(run_batch(), 1)
                mocked.assert_not_called()
                self.assertEqual(Delivery.objects.latest('pk').status, Status.SKIPPED)
                self.manager.makken_access.allowed_regions.set([self.allowed])
                EventRule.objects.filter(pk=rule.pk).update(enabled=True)
                RecipientMute.objects.filter(rule=rule, user=self.manager).delete()
                User.objects.filter(pk=self.manager.pk).update(email=self.manager.email)

    def test_work_progress_queues_to_manager_with_event_snapshot(self):
        self.enable()
        work = self.make_work()
        change_progress(self.employee, work.pk, {'revision': 1, 'status': 'running', 'progress': 45, 'note': 'ملاحظة داخلية'})
        change_progress(self.employee, work.pk, {'revision': 2, 'status': 'complete', 'progress': 100, 'note': ''})
        self.assertEqual(work.history.count(), 3)
        self.assertEqual(Delivery.objects.filter(recipient=self.manager, rule_id='work.progress').count(), 2)
        with patch('makken_mail.worker.send') as mail:
            self.assertEqual(run_batch(), 6)
        manager_messages = [args.args[2] for args in mail.call_args_list if args.args[1] == self.manager.email]
        self.assertEqual([dict(m['details'])['الإنجاز عند التحديث'] for m in manager_messages], ['0%', '45%', '100%'])
        self.assertNotIn('ملاحظة داخلية', str(mail.call_args_list))

    def test_work_reassignment_revokes_old_staff_access_and_mail(self):
        self.enable()
        work = self.make_work()
        save_work(self.admin, {'title': work.title, 'employee': self.other.pk, 'manager': self.manager.pk, 'revision': 1}, work.pk)
        self.login(self.employee)
        self.assertEqual(self.client.get(reverse('makken_mail:work_detail', args=[work.pk])).status_code, 404)
        with patch('makken_mail.worker.send') as mail:
            run_batch()
        self.assertNotIn(self.employee.email, [c.args[1] for c in mail.call_args_list])
        self.assertEqual(Delivery.objects.filter(recipient=self.other, rule_id='work.reassigned', status=Status.SENT).count(), 1)

    def test_work_manager_cannot_write_and_guessed_work_is_hidden(self):
        work = self.make_work()
        self.login(self.manager)
        path = reverse('makken_mail:work_detail', args=[work.pk])
        self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.post(path, {'status': 'running', 'progress': 10, 'revision': 1}).status_code, 403)
        self.login(self.other)
        self.assertNotContains(self.client.get(reverse('makken_mail:work_index')), work.title)
        self.assertEqual(self.client.get(path).status_code, 404)

    def test_work_validates_parent_permission_same_manager_progress_and_staleness(self):
        base = {'target_model': 'partnerships.partnership', 'target_key': self.partner.pk}
        with self.assertRaises(WorkInvalid):
            self.make_work(**base, manager=self.other.pk)
        with self.assertRaises(WorkInvalid):
            self.make_work(manager=self.employee.pk)
        with self.assertRaises(PermissionDenied):
            save_work(self.employee, {'title': 'غير مسموح'})
        work = self.make_work(**base)
        with self.assertRaises(WorkInvalid):
            change_progress(self.employee, work.pk, {'revision': 1, 'status': 'complete', 'progress': 75})
        change_progress(self.employee, work.pk, {'revision': 1, 'status': 'running', 'progress': 35})
        with self.assertRaises(WorkConflict):
            change_progress(self.employee, work.pk, {'revision': 1, 'status': 'running', 'progress': 55})

    def test_work_list_and_details_recheck_regions_after_reassignment(self):
        work = self.make_work(target_model='partnerships.partnership', target_key=self.partner.pk)
        self.login(self.employee)
        self.assertContains(self.client.get(reverse('makken_mail:work_index')), work.title)
        self.employee.makken_access.allowed_regions.set([self.hidden])
        self.assertNotContains(self.client.get(reverse('makken_mail:work_index')), work.title)
        self.assertEqual(self.client.get(reverse('makken_mail:work_detail', args=[work.pk])).status_code, 404)

    def test_linked_business_event_routes_to_employee_manager(self):
        self.enable()
        work = self.make_work(target_model='partnerships.partnership', target_key=self.partner.pk)
        EventRule.objects.filter(pk='partnerships.update').update(enabled=True, to_employee=True, to_manager=True)
        self.self_event(module='partnerships', action='update', target_model='partnerships.partnership',
                        target_key=str(self.partner.pk), regions={self.allowed.pk: self.allowed.name})
        self.assertCountEqual(Delivery.objects.filter(rule_id='partnerships.update', work=work).values_list(
            'recipient_id', flat=True), [self.employee.pk, self.manager.pk])

    def test_admin_routes_are_superadmin_only_and_test_requires_post_csrf(self):
        self.login(self.employee)
        for name, args in [('index', []), ('smtp', []), ('smtp_test', []), ('preview', []), ('deliveries', []),
                           ('rule', ['account.login']), ('preferences', [self.employee.pk]), ('work_targets', [])]:
            self.assertEqual(self.client.get(reverse('makken_mail:'+name, args=args)).status_code, 403)
        self.login()
        self.assertEqual(self.client.get(reverse('makken_mail:smtp_test')).status_code, 405)
        client = Client(enforce_csrf_checks=True)
        self.login(client=client)
        self.assertEqual(client.post(reverse('makken_mail:smtp_test'), {'recipient': 'a@example.org'}).status_code, 403)

    def test_smtp_saves_encrypted_password_and_never_displays_it(self):
        self.login()
        path = reverse('makken_mail:smtp')
        data = {'host': 'smtp.example.org', 'port': 587, 'security': 'starttls', 'username': 'relay',
                'password': 'sensitive-superadmin-credential', 'sender': 'makken@example.org', 'sender_name': 'مكّن', 'revision': 1}
        response = self.client.post(path, data, follow=True)
        self.assertNotContains(response, data['password'])
        config = SMTPConfig.objects.get()
        self.assertNotEqual(config.secret, data['password'])
        self.assertEqual(decrypt(config.secret), data['password'])
        self.assertFalse(config.enabled)
        self.assertNotContains(response, config.secret)
        self.assertEqual(self.client.post(path, data).status_code, 409)
        self.client.post(path, data | {'revision': 2, 'password': '', 'clear_password': 'on'})
        self.assertEqual(SMTPConfig.objects.get().secret, '')
        self.assertNotIn(data['password'], str(list(UserActivity.objects.values('before', 'after'))))

    def test_smtp_test_works_when_globally_disabled_and_is_throttled(self):
        self.login()
        self.enable()
        SMTPConfig.objects.update(enabled=False)
        path = reverse('makken_mail:smtp_test')
        with patch('makken_mail.views.send') as mail:
            response = self.client.post(path, {'recipient': 'test@example.org'}, follow=True)
            self.assertContains(response, 'قبل مزود البريد رسالة الاختبار')
            self.client.post(path, {'recipient': 'test2@example.org'})
        mail.assert_called_once()
        self.assertEqual(mail.call_args.args[1], 'test@example.org')
        self.assertFalse(SMTPConfig.objects.get().enabled)
        self.assertFalse(Delivery.objects.exists())

    def test_smtp_invalid_host_and_unconfigured_test_do_not_contact_network(self):
        self.login()
        response = self.client.post(reverse('makken_mail:smtp'), {'host': '127.0.0.1', 'revision': 1,
            'port': 587, 'security': 'starttls', 'sender_name': 'مكّن'})
        self.assertEqual(response.status_code, 400)
        with patch('makken_mail.views.send') as mail:
            self.client.post(reverse('makken_mail:smtp_test'), {'recipient': 'test@example.org'})
        mail.assert_not_called()

    def test_subscription_editor_and_rule_editor_honor_stale_state(self):
        self.login()
        url = reverse('makken_mail:preferences', args=[self.manager.pk])
        data = subscriptions(self.manager) | {'selected': ['regions.create'], 'muted': ['account.login']}
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertTrue(self.manager.makken_email_rules.filter(pk='regions.create').exists())
        self.assertTrue(self.manager.makken_email_mutes.filter(rule_id='account.login').exists())
        self.assertEqual(self.client.post(url, data).status_code, 409)
        rule = EventRule.objects.get(pk='regions.create')
        route = reverse('makken_mail:rule', args=[rule.pk])
        self.assertEqual(self.client.post(route, {'revision': rule.revision, 'enabled': 'on', 'recipients': [self.manager.pk]}).status_code, 302)
        self.assertEqual(self.client.post(route, {'revision': rule.revision}).status_code, 409)

    def test_outbox_only_claims_once_and_retries_temporary_failures(self):
        self.enable()
        self.self_event()
        now = timezone.now()
        key = claim(now)
        self.assertIsNotNone(key)
        self.assertIsNone(claim(now))
        with patch('makken_mail.worker.send', side_effect=SendFailure('temporary', retry=True)):
            process(key, now)
        row = Delivery.objects.get(pk=key)
        self.assertEqual((row.status, row.attempts), (Status.QUEUED, 1))
        self.assertEqual(row.next_at, now + timedelta(minutes=5))
        self.assertIsNone(claim(now))

    def test_ambiguous_delivery_and_expired_inflight_are_not_replayed(self):
        self.enable()
        self.self_event()
        with patch('makken_mail.worker.send', side_effect=SendFailure('uncertain', unknown=True)):
            run_batch()
        self.assertEqual(Delivery.objects.get().status, Status.UNKNOWN)
        Delivery.objects.update(status=Status.SENDING, last_at=timezone.now()-timedelta(hours=1))
        with patch('makken_mail.worker.send') as mock:
            self.assertEqual(run_batch(), 0)
        self.assertEqual(Delivery.objects.get().reason, 'claim_expired')
        mock.assert_not_called()

    def test_old_pending_notifications_expire(self):
        self.enable()
        self.self_event()
        Delivery.objects.update(created_at=timezone.now()-timedelta(days=3))
        with patch('makken_mail.worker.send') as mock:
            self.assertEqual(run_batch(), 0)
        mock.assert_not_called()
        self.assertEqual(Delivery.objects.get().reason, 'expired')

    def test_django_secret_fallback_can_decode_previous_credential(self):
        with override_settings(SECRET_KEY='old-local-key'):
            protected = encrypt('old-secret')
        with override_settings(SECRET_KEY='new-local-key', SECRET_KEY_FALLBACKS=['old-local-key']):
            self.assertEqual(decrypt(protected), 'old-secret')

    def test_embedded_logo_multipart_and_html_escaping(self):
        cfg = SMTPConfig(sender='makken@example.org')
        ctx = {**preview_values(), 'recipient_name': '<script>alert(1)</script>'}
        msg = build_message(cfg, self.employee.email, ctx, '<a@makken.example.org>')
        decoded = BytesParser(policy=policy.default).parsebytes(msg.as_bytes())
        html = decoded.get_body(preferencelist=('html',)).get_content()
        self.assertTrue(decoded.get_body(preferencelist=('plain',)))
        self.assertIn('dir="rtl"', html)
        self.assertIn('#24B3AF', html)
        self.assertIn('cid:makken-brand', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertNotIn('<script>', html)
        self.assertTrue(any(p['Content-ID'] == '<makken-brand>' and p.get_content_type() == 'image/png' for p in decoded.walk()))
        self.assertFalse(message_link('//attacker.example.org/'))
        self.assertFalse(message_link('http://attacker.example.org/'))

    def test_mixed_public_private_dns_is_blocked(self):
        for address in ['127.0.0.1', '10.12.0.10', '169.254.169.254', '224.0.0.1', '::ffff:8.8.8.8', '64:ff9b::a00:1']:
            with self.subTest(address=address), patch('socket.getaddrinfo', return_value=[
                (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('8.8.8.8', 587)),
                (socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, 587)),
            ]):
                with self.assertRaises(SendFailure) as exc:
                    smtp_endpoints('smtp.example.org', 587)
                self.assertEqual(exc.exception.code, 'network')

    def test_smtp_requires_tls_before_authentication_and_maps_provider_errors(self):
        cfg = SMTPConfig(host='smtp.example.org', port=587, security='starttls', sender='makken@example.org',
                         username='relay', secret=encrypt('not-logged'))
        with patch('makken_mail.smtp.smtp_endpoints', return_value=[('endpoint',)]) as dns, patch('makken_mail.smtp.PublicStartTLS') as transport:
            server = transport.return_value
            server.connect.return_value = (220, b'ok')
            send(cfg, self.employee.email, preview_values(), '<test@makken.example.org>')
            calls = [c[0] for c in server.method_calls]
            self.assertLess(calls.index('starttls'), calls.index('login'))
            self.assertLess(calls.index('login'), calls.index('send_message'))
            self.assertEqual(server.endpoints, [('endpoint',)])
            dns.assert_called_with(cfg.host, cfg.port)
            server.login.side_effect = smtplib.SMTPAuthenticationError(535, b'do not reveal provider diagnostic')
            with self.assertRaises(SendFailure) as err:
                send(cfg, self.employee.email, preview_values(), '<test@makken.example.org>')
            self.assertEqual(str(err.exception), 'auth')

    def test_database_rejects_completion_mismatch(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            WorkAssignment.objects.create(title='invalid', employee=self.employee, manager=self.manager, status='complete', progress=80)


from market_needs.tests.test_market import MarketFixtures


class SponsorshipNotificationTests(MarketFixtures, TestCase):
    def test_real_sponsorship_approval_routes_to_assigned_manager_and_employee(self):
        initialize()
        need = self.create_need(regions=[self.region.pk])
        partner = self.organization()
        partner.administrative_regions.add(self.region)
        sponsor = self.attach(need, partner)
        manager = User.objects.create_user('sponsor-assignment-manager', 'sponsor-manager@example.org')
        employee = User.objects.create_user('sponsor-assignment-employee', 'sponsor-employee@example.org')
        for person in [manager, employee]:
            access = UserAccess.objects.create(user=person, page_scope='all', region_scope='selected')
            access.allowed_regions.add(self.region)
            PermissionOverride.objects.create(user=person, module_id='market_needs', operation='view', effect='grant')
        work = save_work(self.user, {'title': 'متابعة الرعاية', 'target_model': 'market_needs.sponsorship',
            'target_key': sponsor.pk, 'employee': employee.pk, 'manager': manager.pk})
        SMTPConfig.objects.filter(pk=1).update(host='smtp.example.org', sender='mail@example.org', enabled=True)
        with self.captureOnCommitCallbacks(execute=True):
            self.approve(need, sponsor)
        received = Delivery.objects.filter(rule_id='sponsorship.approved', work=work)
        self.assertCountEqual(received.values_list('recipient_id', flat=True), [manager.pk, employee.pk])
        self.assertTrue(all(m == sponsor.pk for m in received.values_list('record_key', flat=True)))
        with patch('makken_mail.worker.send') as mock:
            run_batch()
        self.assertEqual(mock.call_count, 2)
        self.assertTrue(all('تم التواصل' not in str(call) for call in mock.call_args_list))
