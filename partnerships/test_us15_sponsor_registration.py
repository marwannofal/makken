"""US-15 tests: public sponsor registration form, new/approved/rejected workflow, RBAC, and regional scoping."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.defaults import initialize
from access_control.models import PermissionOverride, RegionScope, UserAccess
from care_states.models import DevelopmentState
from entities.models import Entity
from regions.models import Region
from sectors.models import Sector
from sponsorship_shapes.models import SponsorshipShape

from .models import Partnership, PartnershipOffering, SponsorRegistrationRequest, SponsorRequestStatus

User = get_user_model()
AUTH_BACKEND = 'accounts.backends.EmailOrUsernameBackend'


class SponsorRegistrationUS15Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()

    def setUp(self):
        self.region_a = Region.objects.create(name='منطقة راعي أ', is_active=True)
        self.region_b = Region.objects.create(name='منطقة راعي ب', is_active=True)
        self.entity = Entity.objects.create(name='شركة مساهمة للرعاة', entity_type='government', is_active=True)
        self.sector = Sector.objects.create(name='قطاع الاتصالات للرعاة', is_active=True)
        self.shape = SponsorshipShape.objects.create(name='رعاية مالية للرعاة', is_active=True)

        self.admin = User.objects.create_superuser('sr_admin', 'sr_admin@example.com', 'StrongPass123!')
        self.reviewer_a = User.objects.create_user('sr_rev_a', 'sr_rev_a@example.com', 'StrongPass123!')
        self.watcher = User.objects.create_user('sr_watch', 'sr_watch@example.com', 'StrongPass123!')
        self.no_perm = User.objects.create_user('sr_noperm', 'sr_noperm@example.com', 'StrongPass123!')

        acc_rev, _ = UserAccess.objects.get_or_create(
            user=self.reviewer_a,
            defaults={'page_scope': 'all', 'region_scope': RegionScope.SELECTED},
        )
        acc_rev.page_scope = 'all'
        acc_rev.region_scope = RegionScope.SELECTED
        acc_rev.save()
        acc_rev.allowed_regions.set([self.region_a])
        PermissionOverride.objects.create(user=self.reviewer_a, module_id='partnerships', operation='view', effect='grant')
        PermissionOverride.objects.create(user=self.reviewer_a, module_id='partnerships', operation='create', effect='grant')

        acc_w, _ = UserAccess.objects.get_or_create(
            user=self.watcher,
            defaults={'page_scope': 'all', 'region_scope': RegionScope.ALL},
        )
        acc_w.page_scope = 'all'
        acc_w.region_scope = RegionScope.ALL
        acc_w.save()
        PermissionOverride.objects.create(user=self.watcher, module_id='partnerships', operation='view', effect='grant')

    def _public_payload(self, name='شركة الراعي الخارجي الأولى', region=None):
        region = region or self.region_a
        return {
            'name': name,
            'representative': 'عبدالله العتيبي',
            'phone': '0551234567',
            'email': 'sponsor@external.test',
            'entity': str(self.entity.pk),
            'scope': 'local',
            'administrative_regions': [str(region.pk)],
            'sector': str(self.sector.pk),
            'sponsorship_shape': str(self.shape.pk),
            'financial_capacity': '250000.00',
            'notes': 'مهتمون برعاية برامج التقنية.',
            'website': '',
        }

    def test_public_submission_creates_new_request_without_touching_partnerships(self):
        reg_url = reverse('partnerships:public_sponsor_register')
        # Anonymous GET works without login
        get_res = self.client.get(reg_url)
        self.assertEqual(get_res.status_code, 200)

        before_partnerships = Partnership.objects.count()
        post_res = self.client.post(reg_url, self._public_payload())
        self.assertRedirects(post_res, reverse('partnerships:public_sponsor_thanks'))

        # Request created with status='new'; Partnership register untouched
        self.assertEqual(Partnership.objects.count(), before_partnerships)
        req = SponsorRegistrationRequest.objects.get(name='شركة الراعي الخارجي الأولى')
        self.assertEqual(req.status, SponsorRequestStatus.NEW)
        self.assertIsNone(req.created_partnership)
        self.assertEqual(list(req.administrative_regions.all()), [self.region_a])

        # Duplicate pending submission rejected cleanly
        dup_res = self.client.post(reg_url, self._public_payload())
        self.assertEqual(dup_res.status_code, 400)
        self.assertEqual(SponsorRegistrationRequest.objects.count(), 1)

        # Honeypot filled by bot -> redirects without creating a DB row
        bot_payload = self._public_payload(name='شركة روبوت')
        bot_payload['website'] = 'https://spam.invalid'
        bot_res = self.client.post(reg_url, bot_payload)
        self.assertRedirects(bot_res, reverse('partnerships:public_sponsor_thanks'))
        self.assertFalse(SponsorRegistrationRequest.objects.filter(name='شركة روبوت').exists())

    def test_approval_creates_partnership_and_prevents_double_approval(self):
        self.client.post(reverse('partnerships:public_sponsor_register'), self._public_payload())
        req = SponsorRegistrationRequest.objects.get(name='شركة الراعي الخارجي الأولى')

        self.client.force_login(self.reviewer_a, backend=AUTH_BACKEND)
        review_url = reverse('partnerships:sponsor_request_review', args=[req.pk])

        # Approve creates Partnership in default CAPABILITY state + regions + offering
        res = self.client.post(review_url, {'operation': 'approve'})
        self.assertRedirects(res, review_url)

        req.refresh_from_db()
        self.assertEqual(req.status, SponsorRequestStatus.APPROVED)
        self.assertEqual(req.reviewed_by, self.reviewer_a)
        self.assertIsNotNone(req.created_partnership)

        p = req.created_partnership
        self.assertEqual(p.name, 'شركة الراعي الخارجي الأولى')
        self.assertEqual(p.development_state_id, DevelopmentState.CAPABILITY)
        self.assertTrue(p.is_active)
        self.assertEqual(list(p.administrative_regions.all()), [self.region_a])
        self.assertTrue(PartnershipOffering.objects.filter(partnership=p, sector=self.sector, sponsorship_shape=self.shape).exists())

        # Second approve attempt returns 409 and does not duplicate Partnership
        res_again = self.client.post(review_url, {'operation': 'approve'})
        self.assertEqual(res_again.status_code, 409)
        self.assertEqual(Partnership.objects.filter(name='شركة الراعي الخارجي الأولى').count(), 1)

    def test_rejection_keeps_request_rejected_and_never_creates_partnership(self):
        self.client.post(reverse('partnerships:public_sponsor_register'), self._public_payload(name='شركة مرفوضة'))
        req = SponsorRegistrationRequest.objects.get(name='شركة مرفوضة')

        self.client.force_login(self.admin, backend=AUTH_BACKEND)
        review_url = reverse('partnerships:sponsor_request_review', args=[req.pk])

        # Reject without reason -> 400 validation error
        bad_rej = self.client.post(review_url, {'operation': 'reject', 'rejection_reason': ''})
        self.assertEqual(bad_rej.status_code, 400)
        req.refresh_from_db()
        self.assertEqual(req.status, SponsorRequestStatus.NEW)

        # Reject with reason -> stays permanently rejected, no Partnership created
        ok_rej = self.client.post(review_url, {'operation': 'reject', 'rejection_reason': 'بيانات ناقصة'})
        self.assertRedirects(ok_rej, review_url)
        req.refresh_from_db()
        self.assertEqual(req.status, SponsorRequestStatus.REJECTED)
        self.assertEqual(req.rejection_reason, 'بيانات ناقصة')
        self.assertIsNone(req.created_partnership)
        self.assertFalse(Partnership.objects.filter(name='شركة مرفوضة').exists())

        # Subsequent approve attempt on rejected request is blocked (409) and stays rejected
        retry = self.client.post(review_url, {'operation': 'approve'})
        self.assertEqual(retry.status_code, 409)
        req.refresh_from_db()
        self.assertEqual(req.status, SponsorRequestStatus.REJECTED)
        self.assertFalse(Partnership.objects.filter(name='شركة مرفوضة').exists())

    def test_rbac_and_regional_scoping_on_review_queue(self):
        self.client.post(reverse('partnerships:public_sponsor_register'), self._public_payload(name='راعي منطقة أ', region=self.region_a))
        self.client.post(reverse('partnerships:public_sponsor_register'), self._public_payload(name='راعي منطقة ب', region=self.region_b))
        req_a = SponsorRegistrationRequest.objects.get(name='راعي منطقة أ')
        req_b = SponsorRegistrationRequest.objects.get(name='راعي منطقة ب')

        queue_url = reverse('partnerships:sponsor_requests')

        # Unauthorized user -> 403
        self.client.force_login(self.no_perm, backend=AUTH_BACKEND)
        self.assertEqual(self.client.get(queue_url).status_code, 403)

        # Read-only watcher -> can view queue (200) but cannot approve/reject (403)
        self.client.force_login(self.watcher, backend=AUTH_BACKEND)
        self.assertEqual(self.client.get(queue_url).status_code, 200)
        self.assertEqual(
            self.client.post(reverse('partnerships:sponsor_request_review', args=[req_a.pk]), {'operation': 'approve'}).status_code,
            403,
        )

        # Regional reviewer A -> sees only req_a in queue, gets 403 on req_b review & approve
        self.client.force_login(self.reviewer_a, backend=AUTH_BACKEND)
        q_res = self.client.get(queue_url)
        self.assertEqual(q_res.status_code, 200)
        self.assertEqual([r.pk for r in q_res.context['rows']], [req_a.pk])
        self.assertEqual(self.client.get(reverse('partnerships:sponsor_request_review', args=[req_b.pk])).status_code, 403)
        self.assertEqual(
            self.client.post(reverse('partnerships:sponsor_request_review', args=[req_b.pk]), {'operation': 'approve'}).status_code,
            403,
        )


    def test_public_register_capability_fields_receipt_email_and_admin_notification_rule(self):
        import json
        from unittest.mock import patch
        from makken_mail.models import Delivery, EventRule, SMTPConfig
        from makken_mail.worker import build_context
        from specializations.models import Specialization

        spec = Specialization.objects.create(name='تخصص الذكاء الاصطناعي للاختبار', sector=self.sector)
        SMTPConfig.objects.update_or_create(
            pk=1,
            defaults={'host': 'smtp.example.org', 'sender': 'makken@example.org', 'enabled': True},
        )
        rule, _ = EventRule.objects.get_or_create(code='sponsor_request.submitted')
        rule.enabled = True
        rule.save()
        rule.recipients.add(self.admin)

        sent_receipts = []
        def fake_send(config, address, context, message_id):
            sent_receipts.append((address, context))

        offerings_payload = json.dumps([
            {'sector': self.sector.pk, 'specializations': [spec.pk], 'shape': self.shape.pk}
        ])
        with patch('makken_mail.smtp.send', side_effect=fake_send):
            res = self.client.post(
                reverse('partnerships:public_sponsor_register'),
                {
                    'name': 'شركة المستقبل للتدريب',
                    'representative': 'عبدالرحمن العتيبي',
                    'phone_country': 'SA',
                    'phone': '0551234567',
                    'email': 'future-sponsor@example.org',
                    'entity_type': self.entity.entity_type,
                    'entity': self.entity.pk,
                    'scope': 'local',
                    'administrative_regions': [self.region_a.pk],
                    'offerings_json': offerings_payload,
                    'financial_capacity': '250000',
                    'notes': 'طلب شراكة تدريبية',
                },
            )
        self.assertEqual(res.status_code, 302)
        req = SponsorRegistrationRequest.objects.get(name='شركة المستقبل للتدريب')
        self.assertEqual(req.phone_country, 'SA')
        self.assertEqual(len(req.offerings), 1)
        self.assertEqual(req.offerings[0]['specializations'], [spec.pk])

        # 1. Sponsor received automatic confirmation receipt at their submitted email
        self.assertEqual(len(sent_receipts), 1)
        self.assertEqual(sent_receipts[0][0], 'future-sponsor@example.org')
        self.assertIn(req.reference_code, dict(sent_receipts[0][1]['details']).values())

        # 2. Admin notification rule queued a Delivery for configured recipients
        delivery = Delivery.objects.get(rule_id='sponsor_request.submitted', recipient=self.admin)
        ctx = build_context(delivery, None)
        self.assertEqual(dict(ctx['details'])['رقم الطلب'], req.reference_code)

        # 3. Approving converts into a قدرة Partnership carrying all offerings & specializations
        self.client.force_login(self.admin, backend='accounts.backends.EmailOrUsernameBackend')
        with patch('makken_mail.smtp.send'):
            app_res = self.client.post(
                reverse('partnerships:sponsor_request_review', args=[req.pk]),
                {'operation': 'approve'},
            )
        self.assertEqual(app_res.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.status, 'approved')
        p = req.created_partnership
        self.assertIsNotNone(p)
        self.assertEqual(p.development_state_id, 'capability')
        off = p.offerings.first()
        self.assertIsNotNone(off)
        self.assertEqual(list(off.specializations.values_list('pk', flat=True)), [spec.pk])


    def test_public_register_partnership_type_and_attachments_prefill_willingness_transition(self):
        import io
        from unittest.mock import patch
        from django.core.files.uploadedfile import SimpleUploadedFile
        from PIL import Image
        from partnerships.models import PartnershipType
        from partnerships.willingness import WillingnessTransitionForm

        ptype, _ = PartnershipType.objects.get_or_create(name='مذكرة تفاهم')
        buf = io.BytesIO()
        Image.new('RGB', (40, 40), color=(36, 179, 175)).save(buf, format='PNG')
        upload = SimpleUploadedFile('sponsor-doc.png', buf.getvalue(), content_type='image/png')

        with patch('makken_mail.smtp.send'):
            res = self.client.post(
                reverse('partnerships:public_sponsor_register'),
                {
                    'name': 'شركة المرفقات الداعمة',
                    'representative': 'خالد الحربي',
                    'phone_country': 'SA',
                    'phone': '0559876543',
                    'email': 'att-sponsor@example.org',
                    'entity_type': self.entity.entity_type,
                    'entity': self.entity.pk,
                    'scope': 'local',
                    'administrative_regions': [self.region_a.pk],
                    'partnership_type': ptype.pk,
                    'attachments': [upload],
                },
            )
        self.assertEqual(res.status_code, 302)
        req = SponsorRegistrationRequest.objects.get(name='شركة المرفقات الداعمة')
        self.assertEqual(req.partnership_type_id, ptype.pk)
        self.assertEqual(req.attachments.count(), 1)

        # Admin downloads attachment & approves request into قدرة
        self.client.force_login(self.admin, backend='accounts.backends.EmailOrUsernameBackend')
        att = req.attachments.first()
        dl = self.client.get(reverse('partnerships:sponsor_request_attachment_download', args=[req.pk, att.pk]))
        self.assertEqual(dl.status_code, 200)
        dl.close()

        with patch('makken_mail.smtp.send'):
            app_res = self.client.post(
                reverse('partnerships:sponsor_request_review', args=[req.pk]),
                {'operation': 'approve'},
            )
        self.assertEqual(app_res.status_code, 302)
        req.refresh_from_db()
        p = req.created_partnership
        self.assertEqual(p.partnership_type_id, ptype.pk)
        self.assertEqual(p.willingness_attachments.count(), 1)

        # Converting that قدرة partnership to رغبة pre-fills partnership_type & satisfies attachments without re-upload
        unbound = WillingnessTransitionForm(partnership=p)
        self.assertEqual(unbound.fields['agreement_type'].initial, ptype.pk)
        self.assertFalse(unbound.fields['attachments'].required)
        bound = WillingnessTransitionForm({'agreement_type': str(ptype.pk)}, {}, partnership=p)
        self.assertTrue(bound.is_valid(), bound.errors)

    def test_sponsor_request_phone_displays_country_code_in_list_and_detail(self):
        req = SponsorRegistrationRequest.objects.create(
            name='جهة الأردن للتدريب',
            representative='محمود',
            phone_country='JO',
            phone='797971718',
            email='jo@example.com',
            entity=self.entity,
            scope='local',
        )
        self.assertEqual(req.formatted_phone, '+962 797971718')
        self.client.force_login(self.admin, backend=AUTH_BACKEND)
        list_res = self.client.get(reverse('partnerships:sponsor_requests'))
        self.assertEqual(list_res.status_code, 200)
        self.assertContains(list_res, '+962 797971718')
        detail_res = self.client.get(reverse('partnerships:sponsor_request_review', args=[req.pk]))
        self.assertEqual(detail_res.status_code, 200)
        self.assertContains(detail_res, '+962 797971718')

    def test_public_register_page_includes_tvtc_logo_and_ltr_phone_row(self):
        res = self.client.get(reverse('partnerships:public_sponsor_register'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'accounts/images/header-logo.svg')
        self.assertContains(res, '<div class="pub-phone-row" dir="ltr">')
        self.assertNotContains(res, 'العودة لتسجيل الدخول')

    def test_public_register_hides_entity_until_non_government_and_auto_resolves_government(self):
        url = reverse('partnerships:public_sponsor_register')
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'data-pub-entity-field hidden')

        gov_res = self.client.post(url, {
            'name': 'جهة حكومية تلقائية',
            'representative': 'خالد',
            'phone_country': 'SA',
            'phone': '0501234567',
            'email': 'govauto@example.com',
            'entity_type': 'government',
            'scope': 'local',
            'administrative_regions': [str(self.region_a.pk)],
        })
        self.assertEqual(gov_res.status_code, 302)
        req = SponsorRegistrationRequest.objects.get(name='جهة حكومية تلقائية')
        self.assertEqual(req.entity.entity_type, 'government')

        non_gov_res = self.client.post(url, {
            'name': 'جهة خاصة بدون كيان',
            'representative': 'سالم',
            'phone_country': 'SA',
            'phone': '0507654321',
            'email': 'nongov@example.com',
            'entity_type': 'non_government',
            'scope': 'local',
            'administrative_regions': [str(self.region_a.pk)],
        })
        self.assertEqual(non_gov_res.status_code, 400)
        self.assertIn('entity', non_gov_res.context['form'].errors)
