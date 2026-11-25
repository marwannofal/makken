"""Comprehensive tests for the site-wide circular scroll-progress indicator on Makken."""
from pathlib import Path
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse


class ScrollProgressStaticAssetTests(SimpleTestCase):
    """Validates CSS, JS, template partial, Ocean-Blue theme, sidebar responsiveness, and strict CSP."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        base = Path(settings.BASE_DIR)
        cls.css_path = base / "core" / "static" / "core" / "css" / "makken-scroll-progress.css"
        cls.js_path = base / "core" / "static" / "core" / "js" / "makken-scroll-progress.js"
        cls.partial_path = base / "core" / "templates" / "core" / "partials" / "scroll_progress_assets.html"
        cls.base_tpl_path = base / "core" / "templates" / "core" / "makken_base.html"
        cls.css = cls.css_path.read_text(encoding="utf-8")
        cls.js = cls.js_path.read_text(encoding="utf-8")
        cls.partial = cls.partial_path.read_text(encoding="utf-8")
        cls.base_tpl = cls.base_tpl_path.read_text(encoding="utf-8")

    def test_css_has_balanced_braces_and_makken_ocean_blue_palette(self):
        self.assertEqual(self.css.count("{"), self.css.count("}"))
        self.assertIn("#005b85", self.css)
        self.assertIn("#003b5c", self.css)
        self.assertIn("border-radius: 50%", self.css)
        self.assertIn("stroke-linecap: round", self.css)

    def test_css_positions_beside_sidebar_and_moves_to_right_corner_when_collapsed_or_mobile(self):
        self.assertIn("right: calc(var(--sidebar-width, 280px) - 27px);", self.css)
        self.assertIn("body.mk-sidebar-collapsed .mk-scroll-progress {", self.css)
        self.assertIn("right: 16px;", self.css)
        self.assertIn("width: 54px;", self.css)
        self.assertIn("width: 48px;", self.css)
        self.assertIn("width: 42px;", self.css)
        self.assertIn("height: 54px;", self.css)
        self.assertIn("bottom: 20px;", self.css)
        a11y_css = (Path(settings.BASE_DIR) / "core" / "static" / "core" / "css" / "makken-accessibility.css").read_text(encoding="utf-8")
        self.assertIn("width: 54px;", a11y_css)
        self.assertIn("width: 48px;", a11y_css)
        self.assertIn("width: 42px;", a11y_css)
        self.assertIn("height: 54px;", a11y_css)
        self.assertIn("bottom: 20px;", a11y_css)
        self.assertIn("@media (max-width: 900px)", self.css)
        self.assertIn("right: 14px;", self.css)

    def test_css_starts_hidden_and_reveals_with_is_visible_class(self):
        self.assertIn("opacity: 0;", self.css)
        self.assertIn(".mk-scroll-progress.is-visible {", self.css)
        self.assertIn("opacity: 1;", self.css)
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.css)
        self.assertIn("@media print", self.css)

    def test_css_never_collides_with_left_accessibility_button(self):
        self.assertNotIn("left: 20px", self.css)
        self.assertNotIn("left: 14px", self.css)

    def test_js_uses_csp_safe_svg_attributes_and_zero_inline_styles_or_innerhtml(self):
        self.assertIn('setAttribute("stroke-dashoffset"', self.js)
        self.assertIn('setAttribute("stroke-dasharray"', self.js)
        self.assertIn("requestAnimationFrame", self.js)
        self.assertIn("window.scrollTo", self.js)
        self.assertIn('addEventListener("scroll"', self.js)
        self.assertIn('addEventListener("resize"', self.js)
        self.assertIn("SHOW_THRESHOLD_PX", self.js)
        self.assertNotIn("innerHTML", self.js)
        self.assertNotIn("eval(", self.js)
        self.assertNotIn(".style.", self.js)

    def test_partial_and_base_template_inclusion_are_csp_clean(self):
        self.assertIn("makken-scroll-progress.css", self.partial)
        self.assertIn("makken-scroll-progress.js", self.partial)
        self.assertNotIn("<style", self.partial.lower())
        self.assertNotIn("style=", self.partial.lower())
        self.assertNotIn("onclick=", self.partial.lower())
        self.assertEqual(
            self.base_tpl.count('{% include "core/partials/scroll_progress_assets.html" %}'),
            1,
        )


class ScrollProgressEndToEndPageTests(TestCase):
    """Verifies the scroll-progress assets load on every major authenticated Makken page."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="scroll_progress_tester",
            email="scroll_progress@makken.test",
            password="StrongPassword123!",
            first_name="Marwan",
        )
        self.client.force_login(self.user)

    def test_scroll_progress_loads_across_all_major_makken_pages(self):
        routes = [
            "/",
            "regions:index",
            "sectors:index",
            "entities:index",
            "levels:index",
            "specializations:index",
            "expense_items:index",
            "sponsorship_shapes:index",
            "training_programs:index",
            "partnerships:index",
            "market_needs:index",
            "service_providers:index",
            "accounts:profile",
            "access_control:index",
        ]
        for route in routes:
            with self.subTest(route=route):
                res = self.client.get(route if route.startswith("/") else reverse(route))
                self.assertEqual(res.status_code, 200)
                self.assertContains(res, "makken-scroll-progress.css")
                self.assertContains(res, "makken-scroll-progress.js")

    def test_no_inline_script_or_style_tags_introduced_on_home_page(self):
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.content.decode("utf-8")
        inline_script_re = re.compile(
            r"<script(?![^>]*\bsrc=)(?![^>]*type=['\"]application/json['\"])[^>]*>",
            re.I,
        )
        self.assertIsNone(inline_script_re.search(html))
        self.assertIsNone(re.search(r"<style\b", html, re.I))
