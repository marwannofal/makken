"""Tests for Makken's platform-wide DD/MM/YYYY date format (inputs, displays, settings)."""
from datetime import date
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class PlatformDateFormatTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username='date_format_admin',
            email='datefmt@makken.test',
            password='StrongPassword!2026',
            first_name='Marwan',
            last_name='Admin',
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_django_settings_configure_dmy_format_and_dual_input_formats(self):
        self.assertEqual(settings.DATE_FORMAT, 'd/m/Y')
        self.assertEqual(settings.SHORT_DATE_FORMAT, 'd/m/Y')
        self.assertEqual(settings.DATETIME_FORMAT, 'd/m/Y H:i')
        self.assertIn('%d/%m/%Y', settings.DATE_INPUT_FORMATS)
        self.assertIn('%Y-%m-%d', settings.DATE_INPUT_FORMATS)

    def test_date_format_assets_loaded_globally_on_date_bearing_pages(self):
        routes = [
            'makken_home',
            'partnerships:create',
            'partnerships:create_willingness',
            'partnerships:willingness_index',
            'partnerships:agreement_inquiries',
            'market_needs:create',
            'access_control:activity',
            'makken_mail:work_stats',
        ]
        for route_name in routes:
            with self.subTest(route=route_name):
                res = self.client.get(reverse(route_name))
                self.assertEqual(res.status_code, 200)
                self.assertContains(res, 'makken-date-format.css')
                self.assertContains(res, 'makken-date-format.js')

    def test_date_format_js_supports_dmy_placeholder_conversion_and_calendar_picker(self):
        js_path = Path(settings.BASE_DIR) / 'core' / 'static' / 'core' / 'js' / 'makken-date-format.js'
        js = js_path.read_text(encoding='utf-8')
        self.assertIn("placeholder = 'DD/MM/YYYY'", js)
        self.assertIn('isoToDmy', js)
        self.assertIn('dmyToIso', js)
        self.assertIn('showPicker', js)

    def test_live_expiry_js_outputs_dmy_format(self):
        wc_js = (Path(settings.BASE_DIR) / 'partnerships' / 'static' / 'partnerships' / 'willingness_clauses.js').read_text(encoding='utf-8')
        self.assertIn('${pad(targetDay)}/${pad(targetMonth)}/${targetYear}', wc_js)

        rec_js = (Path(settings.BASE_DIR) / 'agreement_clauses' / 'static' / 'agreement_clauses' / 'record.js').read_text(encoding='utf-8')
        self.assertIn('.join("/")', rec_js)

    def test_forms_accept_both_dmy_and_iso_date_strings(self):
        from market_needs.forms import NeedForm
        from partnerships.forms import PartnershipForm

        for field_name in ('starts_on', 'ends_on'):
            field = PartnershipForm().fields[field_name]
            self.assertEqual(field.clean('30/06/2027'), date(2027, 6, 30))
            self.assertEqual(field.clean('2027-06-30'), date(2027, 6, 30))

        obs_field = NeedForm().fields['observed_on']
        self.assertEqual(obs_field.clean('30/06/2027'), date(2027, 6, 30))
        self.assertEqual(obs_field.clean('2027-06-30'), date(2027, 6, 30))
