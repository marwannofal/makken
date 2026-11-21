"""Comprehensive tests for Makken's site-wide compact filter + table layout & responsive CSS."""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class CompactTableLayoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username='compact_layout_admin',
            email='compact@makken.test',
            password='StrongPassword!2026',
            first_name='Marwan',
            last_name='Admin',
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_all_settings_lookup_pages_render_compact_filter_kicker_and_assets(self):
        settings_routes = [
            'entities:index',
            'levels:index',
            'regions:index',
            'sectors:index',
            'specializations:index',
            'expense_items:index',
            'training_programs:index',
            'sponsorship_shapes:index',
            'agreement_clauses:index',
            'agreement_clauses:classifications',
            'agreement_clauses:references',
            'partnership_types',
            'accounts:departments',
        ]
        for route_name in settings_routes:
            with self.subTest(route=route_name):
                res = self.client.get(reverse(route_name))
                self.assertEqual(res.status_code, 200)
                self.assertContains(res, 'makken-compact-tables.css')
                self.assertContains(res, 'makken-compact-tables.js')
                self.assertContains(res, 'معايير البحث')
                self.assertContains(res, 'label for="settings-filter-q" class="visually-hidden"')
                # Ensure compact script loads BEFORE table-exports.js so .mk-results-end exists first
                html = res.content.decode('utf-8')
                self.assertLess(
                    html.index('makken-compact-tables.js'),
                    html.index('table-exports.js'),
                )

    def test_all_operational_list_and_access_control_pages_load_compact_assets(self):
        operational_routes = [
            'partnerships:capability_index',
            'partnerships:willingness_index',
            'partnerships:agreement_inquiries',
            'partnerships:sponsor_requests',
            'market_needs:index',
            'service_providers:index',
            'access_control:index',
            'access_control:roles',
            'access_control:logs',
            'access_control:activity',
            'makken_mail:work_index',
        ]
        for route_name in operational_routes:
            with self.subTest(route=route_name):
                res = self.client.get(reverse(route_name))
                self.assertEqual(res.status_code, 200)
                self.assertContains(res, 'makken-compact-tables.css')
                self.assertContains(res, 'makken-compact-tables.js')
                html = res.content.decode('utf-8')
                self.assertLess(
                    html.index('makken-compact-tables.js'),
                    html.index('table-exports.js'),
                )

    def test_dashboard_loads_cleanly_without_breaking(self):
        res = self.client.get(reverse('makken_home'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'makken-compact-tables.css')

    def test_static_css_contains_unified_card_eyebrow_hide_and_responsive_breakpoints(self):
        css_path = Path(settings.BASE_DIR) / 'core' / 'static' / 'core' / 'css' / 'makken-compact-tables.css'
        css = css_path.read_text(encoding='utf-8')
        # Eyebrow removed
        self.assertIn('.main-content .page-introduction .eyebrow', css)
        self.assertIn('display: none;', css)
        # Unified card fusion (no gap between filter and table card)
        self.assertIn('.mk-unified-filter-card', css)
        self.assertIn('.mk-unified-table-card', css)
        self.assertIn('border-bottom-left-radius: 0 !important;', css)
        self.assertIn('border-top-left-radius: 0 !important;', css)
        # Single-row results toolbar
        self.assertIn('.mk-results-bar', css)
        self.assertIn('.mk-results-start', css)
        self.assertIn('.mk-results-end', css)
        # Redundant export helper label hidden
        self.assertIn('.mk-export-label', css)
        # All responsive breakpoints present
        for bp in ('@media (max-width: 1024px)', '@media (max-width: 768px)', '@media (max-width: 600px)', '@media (max-width: 480px)'):
            self.assertIn(bp, css)

    def test_static_js_removes_redundant_export_label_and_targets_results_end_slot(self):
        exports_js = (Path(settings.BASE_DIR) / 'core' / 'static' / 'core' / 'exports' / 'table-exports.js').read_text(encoding='utf-8')
        self.assertNotIn('تصدير النتائج حسب الفلاتر', exports_js)
        self.assertIn('[data-mk-results-end]', exports_js)

        compact_js = (Path(settings.BASE_DIR) / 'core' / 'static' / 'core' / 'js' / 'makken-compact-tables.js').read_text(encoding='utf-8')
        self.assertIn('معايير البحث', compact_js)
        self.assertIn('نتائج البحث', compact_js)
        self.assertIn('mk-header-compact-hidden', compact_js)
        self.assertIn('.dash-page', compact_js)

    def test_table_tags_and_bdi_wrap_cleanly_without_overflowing_grid(self):
        css = (Path(settings.BASE_DIR) / 'core' / 'static' / 'core' / 'css' / 'makken-compact-tables.css').read_text(encoding='utf-8')
        self.assertNotIn('table tbody td bdi,', css)
        self.assertIn(':is(.expense_item-tags, .specialization-tags, .program-type-tags)', css)
        self.assertIn('max-width: 260px;', css)
        self.assertIn('max-width: 250px;', css)
        res = self.client.get(reverse('training_programs:index'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'makken-compact-tables.css?v=20261121-cols2')
