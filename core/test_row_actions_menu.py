"""Tests for Makken's site-wide three-dots (⋮) row actions popover menu."""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class RowActionsMenuTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username='row_menu_admin',
            email='rowmenu@makken.test',
            password='StrongPassword!2026',
            first_name='Marwan',
            last_name='Admin',
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_row_actions_menu_assets_load_across_all_table_pages(self):
        routes = [
            'entities:index',
            'levels:index',
            'regions:index',
            'sectors:index',
            'specializations:index',
            'care_states:index',
            'accounts:departments',
            'partnerships:capability_index',
            'partnerships:willingness_index',
            'partnerships:agreement_inquiries',
            'market_needs:index',
            'service_providers:index',
            'access_control:index',
            'access_control:roles',
        ]
        for route_name in routes:
            with self.subTest(route=route_name):
                res = self.client.get(reverse(route_name))
                self.assertEqual(res.status_code, 200)
                self.assertContains(res, 'makken-row-actions-menu.css')
                self.assertContains(res, 'makken-row-actions-menu.js')

    def test_css_and_js_cover_desktop_dropup_mobile_sheet_and_all_action_containers(self):
        css = (Path(settings.BASE_DIR) / 'core' / 'static' / 'core' / 'css' / 'makken-row-actions-menu.css').read_text(encoding='utf-8')
        self.assertIn('.mk-actions-trigger', css)
        self.assertIn('.mk-actions-dropdown', css)
        self.assertIn('.mk-actions-dropdown.is-dropup', css)
        self.assertIn('@media (max-width: 640px)', css)
        self.assertIn('.mk-actions-backdrop.is-open', css)

        js = (Path(settings.BASE_DIR) / 'core' / 'static' / 'core' / 'js' / 'makken-row-actions-menu.js').read_text(encoding='utf-8')
        for cls in ('.row-actions', '.level-row-actions', '.entity-row-actions', '.region-row-actions', '.sector-row-actions', 'td.action-cell'):
            self.assertIn(cls, js)
        self.assertIn('MutationObserver', js)
        self.assertIn("event.key === 'Escape'", js)
        self.assertIn('stopPropagation()', js)
