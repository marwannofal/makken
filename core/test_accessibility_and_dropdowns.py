"""Comprehensive unit and integration tests for Makken's Accessibility Drawer and Site-wide Dropdowns."""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

User = get_user_model()


class AccessibilityAndDropdownsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username='a11y_admin',
            email='a11y@makken.test',
            password='StrongPassword!2026',
            first_name='Marwan',
            last_name='Admin',
        )

    def test_accessibility_assets_present_on_public_login_and_register_pages(self):
        for route_name in ('accounts:login', 'partnerships:public_sponsor_register'):
            with self.subTest(route=route_name):
                res = self.client.get(reverse(route_name))
                self.assertEqual(res.status_code, 200)
                self.assertContains(res, 'makken-accessibility.css')
                self.assertContains(res, 'makken-accessibility.js')
                # Strict CSP compliance: no unsafe-inline
                csp = res.get('Content-Security-Policy', '')
                if csp:
                    self.assertNotIn("'unsafe-inline'", csp)

    def test_accessibility_and_dropdown_assets_present_across_authenticated_pages(self):
        self.client.force_login(self.admin)
        routes = [
            'makken_home',
            'partnerships:capability_index',
            'partnerships:willingness_index',
            'partnerships:create_willingness',
            'market_needs:index',
            'market_needs:create',
            'entities:index',
            'access_control:index',
            'accounts:departments',
        ]
        for route_name in routes:
            with self.subTest(route=route_name):
                res = self.client.get(reverse(route_name))
                self.assertEqual(res.status_code, 200)
                self.assertContains(res, 'makken-accessibility.css')
                self.assertContains(res, 'makken-accessibility.js')
                self.assertContains(res, 'makken-dropdowns.css')

    def test_accessibility_js_implements_all_profiles_content_color_and_orientation_features(self):
        js = (Path(settings.BASE_DIR) / 'core' / 'static' / 'core' / 'js' / 'makken-accessibility.js').read_text(encoding='utf-8')
        # Header & footer controls
        for label in ('إعادة تعيين الإعدادات', 'إغلاق', 'مساعدة', 'makken_a11y_v1'):
            self.assertIn(label, js)
        # 4 collapsible sections
        for section in ('ملفات تعريف إمكانية الوصول', 'تعديلات المحتوى', 'تعديلات الألوان', 'تعديلات الاتجاه'):
            self.assertIn(section, js)
        # All 6 profiles
        for prof in ('ضعف البصر', 'النوبات والصرع', 'ضعف رؤية الألوان', 'ADHD', 'عسر القراءة', 'التعلم'):
            self.assertIn(prof, js)
        # All 8 content toggles + 3 steppers
        for item in (
            'خط قابل للقراءة', 'خط مناسب لعسر القراءة', 'تمييز العناوين', 'تمييز الروابط',
            'تمييز الأزرار', 'إخفاء الصور', 'التلميحات', 'إيقاف الرسوم المتحركة',
            'حجم النص', 'ارتفاع السطر', 'تباعد النص',
        ):
            self.assertIn(item, js)
        # All 7 color adjustments
        for color in ('تباين داكن', 'تباين فاتح', 'عكس الألوان', 'تغيير الألوان', 'تشبع عالي', 'تشبع منخفض', 'أحادي اللون'):
            self.assertIn(color, js)
        # All 4 orientation tools
        for orient in ('دليل القراءة', 'قناع القراءة', 'مؤشر أسود كبير', 'مؤشر أبيض كبير'):
            self.assertIn(orient, js)
        # Keyboard accessibility
        self.assertIn("event.key === 'Escape'", js)
        self.assertIn('event.altKey', js)

    def test_accessibility_css_uses_makken_brand_palette_bottom_left_fab_and_responsive_rules(self):
        css = (Path(settings.BASE_DIR) / 'core' / 'static' / 'core' / 'css' / 'makken-accessibility.css').read_text(encoding='utf-8')
        # Floating circular bottom-left button in brand #24b3af
        self.assertIn('.mk-a11y-fab', css)
        self.assertIn('left: 20px;', css)
        self.assertIn('bottom: 20px;', css)
        self.assertIn('border-radius: 50%;', css)
        self.assertIn('#24b3af', css)
        # All mode classes defined
        for cls in (
            'mk-a11y-readable-font', 'mk-a11y-dyslexia-font', 'mk-a11y-highlight-headings',
            'mk-a11y-highlight-links', 'mk-a11y-highlight-buttons', 'mk-a11y-hide-images',
            'mk-a11y-stop-animations', 'mk-a11y-font-1', 'mk-a11y-font-2', 'mk-a11y-font-3',
            'mk-a11y-line-1', 'mk-a11y-line-2', 'mk-a11y-line-3',
            'mk-a11y-space-1', 'mk-a11y-space-2', 'mk-a11y-space-3',
            'mk-a11y-dark-contrast', 'mk-a11y-light-contrast', 'mk-a11y-invert',
            'mk-a11y-color-shift', 'mk-a11y-high-saturation', 'mk-a11y-low-saturation',
            'mk-a11y-monochrome', 'mk-a11y-cursor-black', 'mk-a11y-cursor-white',
            'mk-a11y-reading-guide', 'mk-a11y-reading-mask',
        ):
            self.assertIn(cls, css)
        self.assertIn('@media (max-width: 600px)', css)
        self.assertIn('@media print', css)

    def test_dropdowns_css_and_multiselect_stay_open_fix(self):
        css = (Path(settings.BASE_DIR) / 'core' / 'static' / 'core' / 'css' / 'makken-dropdowns.css').read_text(encoding='utf-8')
        self.assertIn('font-size: 15px !important;', css)
        self.assertIn('font-weight: 700 !important;', css)
        self.assertIn('min-height: 44px !important;', css)
        self.assertIn('.mk-multi-footer', css)
        self.assertIn('.mk-multi-done', css)

        mjs = (Path(settings.BASE_DIR) / 'market_needs' / 'static' / 'market_needs' / 'market.js').read_text(encoding='utf-8')
        self.assertIn('e.stopPropagation();', mjs)
        self.assertIn('e.target.isConnected', mjs)
        self.assertIn('mk-multi-footer', mjs)
        self.assertIn('مسح التحديد', mjs)

    def test_global_dropdowns_never_duplicate_custom_pickers(self):
        base = Path(settings.BASE_DIR)
        dd_js = (base / 'core' / 'static' / 'core' / 'js' / 'makken-dropdowns.js').read_text(encoding='utf-8')
        self.assertIn('function hasCustomPicker(select)', dd_js)
        self.assertIn('function unwrapSelect(select)', dd_js)
        self.assertIn("select.classList.contains('native-enhanced')", dd_js)
        self.assertIn('window.MakkenDropdowns = { unwrap: unwrapSelect, scan };', dd_js)

        for rel in (
            'partnerships/static/partnerships/partnerships.js',
            'market_needs/static/market_needs/market.js',
            'service_providers/static/service_providers/provider-selects.js',
        ):
            src = (base / rel).read_text(encoding='utf-8')
            self.assertIn('MakkenDropdowns?.unwrap?.(select)', src, f'{rel} must unwrap global dropdown before enhancing')
