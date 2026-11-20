"""Tests for Partnership.partnership_date (month and year only, YYYY-MM)."""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.defaults import initialize
from entities.models import Entity
from regions.models import Region
from sectors.models import Sector
from specializations.models import Specialization
from sponsorship_shapes.models import SponsorshipShape

from .forms import PartnershipForm
from .models import Partnership

User = get_user_model()
AUTH_BACKEND = 'accounts.backends.EmailOrUsernameBackend'


class PartnershipDateMonthYearTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()

    def setUp(self):
        self.admin = User.objects.create_superuser('pdate_admin', 'pdate_admin@example.com', 'StrongPass123!')
        self.region = Region.objects.create(name='منطقة تاريخ الشراكة', is_active=True)
        self.entity = Entity.objects.create(name='جهة تاريخ الشراكة', entity_type='government', is_active=True)
        self.sector = Sector.objects.create(name='قطاع تاريخ الشراكة', is_active=True)
        self.spec = Specialization.objects.create(name='تخصص تاريخ الشراكة', sector=self.sector, is_active=True)
        self.shape = SponsorshipShape.objects.create(name='رعاية تاريخ الشراكة', is_active=True)

    def _form_data(self, partnership_date='2026-11'):
        return {
            'name': 'شراكة اختبار الشهر والسنة',
            'representative': 'خالد الحربي',
            'phone_country': 'SA',
            'phone': '0501234567',
            'email': 'partner@example.com',
            'financial_capacity': '100000.00',
            'entity_type': 'government',
            'entity': str(self.entity.pk),
            'scope': 'local',
            'administrative_regions': [str(self.region.pk)],
            'partnership_date': partnership_date,
            'is_active': '1',
            'offerings': json.dumps([{
                'sector': self.sector.pk,
                'shape': self.shape.pk,
                'specializations': [self.spec.pk],
                'is_active': True,
            }]),
        }

    def test_valid_month_year_accepted_and_day_or_bad_month_rejected(self):
        ok_form = PartnershipForm(self._form_data('2026-11'), actor=self.admin)
        self.assertTrue(ok_form.is_valid(), ok_form.errors)
        self.assertEqual(ok_form.cleaned_data['partnership_date'], '2026-11')

        blank_form = PartnershipForm(self._form_data(''), actor=self.admin)
        self.assertTrue(blank_form.is_valid(), blank_form.errors)
        self.assertEqual(blank_form.cleaned_data['partnership_date'], '')

        with_day = PartnershipForm(self._form_data('2026-11-20'), actor=self.admin)
        self.assertFalse(with_day.is_valid())
        self.assertIn('partnership_date', with_day.errors)

        bad_month = PartnershipForm(self._form_data('2026-13'), actor=self.admin)
        self.assertFalse(bad_month.is_valid())
        self.assertIn('partnership_date', bad_month.errors)

    def test_editor_renders_month_input_and_saves_partnership_date(self):
        self.client.force_login(self.admin, backend=AUTH_BACKEND)
        url = reverse('partnerships:create')
        get_res = self.client.get(url)
        self.assertEqual(get_res.status_code, 200)
        self.assertContains(get_res, 'type="month"')
        self.assertContains(get_res, 'تاريخ الشراكة')

        snapshot = get_res.context['snapshot']
        preview_res = self.client.post(url, {'action': 'preview', 'snapshot': snapshot, **self._form_data('2026-11')})
        self.assertEqual(preview_res.status_code, 200)
        token = preview_res.context['pending']['token']
        self.assertEqual(preview_res.context['pending']['partnership_date'], '2026-11')

        confirm_res = self.client.post(url, {'action': 'confirm', 'token': token})
        self.assertEqual(confirm_res.status_code, 302)

        saved = Partnership.objects.get(name='شراكة اختبار الشهر والسنة')
        self.assertEqual(saved.partnership_date, '2026-11')
