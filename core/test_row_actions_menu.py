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
        self.assertIn('moveRowStatusTogglesIntoMenu', js)
        self.assertIn('إيقاف التفعيل', js)
        self.assertIn('تفعيل السجل', js)

    def test_row_click_navigation_is_removed_across_all_site_scripts(self):
        base = Path(settings.BASE_DIR)
        partnerships_js = (base / 'partnerships' / 'static' / 'partnerships' / 'partnerships.js').read_text(encoding='utf-8')
        self.assertNotIn("$$('[data-partnership-row]')", partnerships_js)
        self.assertNotIn('row.dataset.rowUrl', partnerships_js)

        market_js = (base / 'market_needs' / 'static' / 'market_needs' / 'market.js').read_text(encoding='utf-8')
        self.assertNotIn("$$('[data-market-row]')", market_js)

        providers_js = (base / 'service_providers' / 'static' / 'service_providers' / 'providers.js').read_text(encoding='utf-8')
        self.assertNotIn("$$('[data-provider-row]')", providers_js)

        execution_js = (base / 'market_needs' / 'static' / 'market_needs' / 'execution.js').read_text(encoding='utf-8')
        self.assertIn('[data-execution-dialog]:not(tr)', execution_js)

    def test_dots_menu_adds_view_action_with_eye_icon_and_resets_row_cursor(self):
        base = Path(settings.BASE_DIR)
        js = (base / 'core' / 'static' / 'core' / 'js' / 'makken-row-actions-menu.js').read_text(encoding='utf-8')
        self.assertIn('EYE_SVG', js)
        self.assertIn('moveRowDetailLinksIntoMenu', js)
        self.assertIn('مشاهدة', js)
        self.assertIn('mk-view-action', js)
        self.assertIn('data-row-url', js)
        self.assertIn('data-url', js)
        self.assertIn('data-execution-dialog', js)
        self.assertIn('existingView', js)
        self.assertIn('resolvedTarget', js)

        css = (base / 'core' / 'static' / 'core' / 'css' / 'makken-row-actions-menu.css').read_text(encoding='utf-8')
        self.assertIn('cursor: default !important;', css)
        self.assertIn('.mk-view-action', css)

    def test_operational_tables_expose_detail_urls_for_dots_menu_view_action(self):
        from entities.models import Entity
        from partnerships.models import Partnership
        from service_providers.models import ServiceProvider

        entity = Entity.objects.create(name='جهة اختبار المشاهدة', entity_type='government', is_active=True)
        p = Partnership.objects.create(
            name='شراكة اختبار المشاهدة',
            representative='ممثل',
            phone_country='SA',
            phone='+966501234567',
            email='viewtest@makken.test',
            entity=entity,
            scope='local',
            development_state_id='capability',
            is_active=True,
        )
        sp = ServiceProvider.objects.create(
            name='مزود اختبار المشاهدة',
            phone='+966501234568',
            email='spview@makken.test',
            provider_type='government',
            scope='local',
            is_active=True,
        )

        p_res = self.client.get(reverse('partnerships:capability_index'))
        self.assertEqual(p_res.status_code, 200)
        self.assertContains(p_res, f'detail={p.pk}')
        self.assertContains(p_res, 'makken-row-actions-menu.js')

        sp_res = self.client.get(reverse('service_providers:index'))
        self.assertEqual(sp_res.status_code, 200)
        self.assertContains(sp_res, f'detail={sp.pk}')
        self.assertContains(sp_res, 'makken-row-actions-menu.js')

    def test_mobile_action_labels_are_never_hidden_in_any_stylesheet(self):
        import re
        base = Path(settings.BASE_DIR)
        menu_css = (base / 'core' / 'static' / 'core' / 'css' / 'makken-row-actions-menu.css').read_text(encoding='utf-8')
        self.assertIn(':root .mk-actions-dropdown :is(a, button) > span:not([aria-hidden="true"])', menu_css)
        self.assertIn('display: inline !important;', menu_css)

        hide_span_re = re.compile(r'\.[a-z0-9_-]+-action\s*>\s*span\s*\{[^}]*display\s*:\s*none', re.I)
        offenders = []
        for css_file in sorted(base.rglob('*.css')):
            if 'staticfiles' in css_file.parts or '.git' in css_file.parts:
                continue
            if hide_span_re.search(css_file.read_text(encoding='utf-8', errors='ignore')):
                offenders.append(str(css_file.relative_to(base)))
        self.assertEqual(offenders, [], f'Found stylesheets hiding action button text on mobile: {offenders}')

        res = self.client.get(reverse('agreement_clauses:references'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'makken-row-actions-menu.css')
