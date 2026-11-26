"""Site-wide regression tests ensuring clicking a <label> never opens a native OS <select> popup."""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse


class DropdownLabelFixStaticTests(SimpleTestCase):
    def test_css_hides_native_selects_with_visibility_hidden_and_balanced_braces(self):
        css = (Path(settings.BASE_DIR) / "core" / "static" / "core" / "css" / "makken-dropdowns.css").read_text(encoding="utf-8")
        self.assertEqual(css.count("{"), css.count("}"))
        self.assertIn("select.mk-ss-native,", css)
        self.assertIn("select.native-enhanced {", css)
        self.assertIn("visibility: hidden !important;", css)
        self.assertIn("opacity: 0 !important;", css)
        self.assertIn("pointer-events: none !important;", css)

    def test_js_intercepts_label_clicks_in_capture_phase_for_all_custom_pickers(self):
        js = (Path(settings.BASE_DIR) / "core" / "static" / "core" / "js" / "makken-dropdowns.js").read_text(encoding="utf-8")
        self.assertIn("bindGlobalLabelInterceptor", js)
        self.assertIn("e.preventDefault();", js)
        self.assertIn(".mk-ss-trigger", js)
        self.assertIn(".search-select-trigger", js)
        self.assertIn(".market-select-trigger", js)
        self.assertIn("}, true);", js)


class DropdownLabelFixSiteWidePageTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="dd_label_tester",
            email="dd_label@makken.test",
            password="StrongPassword123!",
            first_name="Marwan",
        )
        self.client.force_login(self.admin)

    def test_all_major_select_pages_load_hardened_dropdown_assets(self):
        routes = [
            "access_control:index",
            "partnerships:capability_index",
            "partnerships:willingness_index",
            "partnerships:sponsor_requests",
            "market_needs:index",
            "service_providers:index",
            "accounts:profile",
            "makken_mail:work_index",
            "regions:index",
            "partnerships:public_sponsor_register",
        ]
        for route in routes:
            with self.subTest(route=route):
                res = self.client.get(reverse(route))
                self.assertEqual(res.status_code, 200)
                self.assertContains(res, "makken-dropdowns.css?v=20261126-label1")
                self.assertContains(res, "makken-dropdowns.js?v=20261126-label1")
