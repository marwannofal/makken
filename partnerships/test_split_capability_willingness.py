"""Tests for dedicated capability and willingness partnership pages and creating directly in willingness."""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.defaults import initialize
from care_states.models import DevelopmentState
from entities.models import Entity
from regions.models import Region
from sectors.models import Sector
from specializations.models import Specialization
from sponsorship_shapes.models import SponsorshipShape

from .models import DevelopmentHistory, Partnership

User = get_user_model()
AUTH_BACKEND = 'accounts.backends.EmailOrUsernameBackend'


class SplitCapabilityWillingnessPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()

    def setUp(self):
        self.admin = User.objects.create_superuser('split_admin', 'split_admin@example.com', 'StrongPass123!')
        self.region = Region.objects.create(name='منطقة فصل الشراكات', is_active=True)
        self.entity = Entity.objects.create(name='جهة فصل الشراكات', entity_type='government', is_active=True)
        self.sector = Sector.objects.create(name='قطاع فصل الشراكات', is_active=True)
        self.spec = Specialization.objects.create(name='تخصص فصل الشراكات', sector=self.sector, is_active=True)
        self.shape = SponsorshipShape.objects.create(name='رعاية فصل الشراكات', is_active=True)

        self.p_cap = Partnership.objects.create(
            name='جهة قدرة مستقلة',
            representative='أحمد',
            phone='0501111111',
            email='cap@example.com',
            entity=self.entity,
            scope='local',
            development_state_id=DevelopmentState.CAPABILITY,
        )
        self.p_will = Partnership.objects.create(
            name='جهة رغبة مستقلة',
            representative='سالم',
            phone='0502222222',
            email='will@example.com',
            entity=self.entity,
            scope='local',
            development_state_id=DevelopmentState.WILLINGNESS,
        )

    def test_capability_and_willingness_pages_are_separate_and_titled(self):
        self.client.force_login(self.admin, backend=AUTH_BACKEND)

        cap_res = self.client.get(reverse('partnerships:capability_index'))
        self.assertEqual(cap_res.status_code, 200)
        self.assertContains(cap_res, 'إدارة سجل شراكات القدرة')
        self.assertContains(cap_res, 'جهة قدرة مستقلة')
        self.assertNotContains(cap_res, 'جهة رغبة مستقلة')

        will_res = self.client.get(reverse('partnerships:willingness_index'))
        self.assertEqual(will_res.status_code, 200)
        self.assertContains(will_res, 'إدارة سجل شراكات الرغبة')
        self.assertContains(will_res, 'جهة رغبة مستقلة')
        self.assertContains(will_res, 'جهة قدرة مستقلة')

    def test_can_create_partnership_directly_in_willingness_state(self):
        self.client.force_login(self.admin, backend=AUTH_BACKEND)
        url = reverse('partnerships:create_willingness')
        get_res = self.client.get(url)
        self.assertEqual(get_res.status_code, 200)
        self.assertContains(get_res, 'إضافة جهة لسجل الشراكات المحتملة التي لها الرغبة')

        payload = {
            'action': 'preview',
            'snapshot': get_res.context['snapshot'],
            'name': 'جهة جديدة من الرغبة مباشرة',
            'representative': 'فيصل',
            'phone_country': 'SA',
            'phone': '0503333333',
            'email': 'newwill@example.com',
            'financial_capacity': '50000.00',
            'entity_type': 'government',
            'entity': str(self.entity.pk),
            'scope': 'local',
            'administrative_regions': [str(self.region.pk)],
            'partnership_date': '2026-11',
            'is_active': '1',
            'offerings': json.dumps([{
                'sector': self.sector.pk,
                'shape': self.shape.pk,
                'specializations': [self.spec.pk],
                'is_active': True,
            }]),
        }
        prev = self.client.post(url, payload)
        self.assertEqual(prev.status_code, 200)
        token = prev.context['pending']['token']

        conf = self.client.post(url, {'action': 'confirm', 'token': token})
        self.assertEqual(conf.status_code, 302)

        created = Partnership.objects.get(name='جهة جديدة من الرغبة مباشرة')
        self.assertEqual(created.development_state_id, DevelopmentState.WILLINGNESS)
        self.assertTrue(
            DevelopmentHistory.objects.filter(partnership=created, state_id=DevelopmentState.WILLINGNESS).exists()
        )

    def test_capability_and_willingness_detail_modals_show_only_corner_close_button(self):
        self.client.force_login(self.admin, backend=AUTH_BACKEND)
        for route, obj in (
            ('partnerships:capability_index', self.p_cap),
            ('partnerships:willingness_index', self.p_will),
        ):
            with self.subTest(route=route):
                res = self.client.get(reverse(route), {'detail': str(obj.pk)})
                self.assertEqual(res.status_code, 200)
                self.assertNotContains(res, '>تعديل بيانات الجهة</a>')
                self.assertContains(res, 'detail-dialog-actions')
                self.assertContains(res, 'detail-close-btn')
                self.assertContains(res, 'إغلاق')

    def test_partnerships_table_displays_only_entity_branch_column(self):
        self.client.force_login(self.admin, backend=AUTH_BACKEND)
        res = self.client.get(reverse('partnerships:capability_index'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '<th scope="col">فرع الكيان</th>', html=True)
        self.assertNotContains(res, '<th scope="col">الكيان / فرعه</th>', html=True)

    def test_all_partnerships_page_lists_all_states_and_statuses_read_only(self):
        p_care = Partnership.objects.create(
            name='جهة رعاية مستقلة',
            representative='عمر',
            phone='0503333333',
            email='care@example.com',
            entity=self.entity,
            scope='local',
            development_state_id=DevelopmentState.CARE,
            is_active=True,
        )
        p_inactive = Partnership.objects.create(
            name='جهة غير نشطة مستقلة',
            representative='فيصل',
            phone='0504444444',
            email='inactive@example.com',
            entity=self.entity,
            scope='local',
            development_state_id=DevelopmentState.CAPABILITY,
            is_active=False,
        )
        self.client.force_login(self.admin, backend=AUTH_BACKEND)
        url = reverse('partnerships:all_index')
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'جميع الشراكات')
        for obj in (self.p_cap, self.p_will, p_care, p_inactive):
            self.assertContains(res, obj.name)
        self.assertNotContains(res, 'إضافة جهة جديدة')
        self.assertNotContains(res, 'delete-action')
        self.assertNotContains(res, 'تحويل إلى رغبة')
        self.assertContains(res, 'مشاهدة')
        self.assertEqual(self.client.post(url, {'action': 'preview'}).status_code, 405)
        will_only = self.client.get(url, {'development_state': 'رغبة'})
        self.assertEqual(will_only.status_code, 200)
        self.assertContains(will_only, self.p_will.name)
        self.assertNotContains(will_only, self.p_cap.name)
        self.assertNotContains(will_only, p_care.name)

    def test_capability_and_willingness_show_rule_scoped_development_state_filter(self):
        self.client.force_login(self.admin, backend=AUTH_BACKEND)

        cap_res = self.client.get(reverse('partnerships:capability_index'))
        self.assertEqual(cap_res.status_code, 200)
        cap_choices = [c[0] for c in cap_res.context['development_filter_form'].fields['development_state'].choices]
        self.assertEqual(cap_choices, ['', 'قدرة'])

        will_url = reverse('partnerships:willingness_index')
        will_res = self.client.get(will_url)
        self.assertEqual(will_res.status_code, 200)
        will_choices = [c[0] for c in will_res.context['development_filter_form'].fields['development_state'].choices]
        self.assertEqual(will_choices, ['', 'قدرة', 'رغبة'])

        only_will = self.client.get(will_url, {'development_state': 'رغبة'})
        self.assertEqual(only_will.status_code, 200)
        self.assertContains(only_will, self.p_will.name)
        self.assertNotContains(only_will, self.p_cap.name)

        only_cap = self.client.get(will_url, {'development_state': 'قدرة'})
        self.assertEqual(only_cap.status_code, 200)
        self.assertContains(only_cap, self.p_cap.name)
        self.assertNotContains(only_cap, self.p_will.name)
