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
