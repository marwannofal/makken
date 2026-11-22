"""Comprehensive site-wide responsiveness, ⋮ portal menu, greeting pill, and table layout tests."""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.defaults import initialize

User = get_user_model()
AUTH_BACKEND = "accounts.backends.EmailOrUsernameBackend"


def _read_static(rel_path):
    return (Path(settings.BASE_DIR) / rel_path).read_text(encoding="utf-8")


def _check_balanced_braces(css_text):
    depth = 0
    for ch in css_text:
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


class SiteWideResponsivenessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()

    def setUp(self):
        self.admin = User.objects.create_superuser("resp_admin", "resp_admin@makken.test", "StrongPass!2026")
        self.client.force_login(self.admin, backend=AUTH_BACKEND)

    def test_all_core_responsive_stylesheets_have_balanced_braces(self):
        for rel in (
            "core/static/core/css/makken-home.css",
            "core/static/core/css/makken-compact-tables.css",
            "core/static/core/css/makken-row-actions-menu.css",
            "core/static/core/css/makken-dropdowns.css",
        ):
            with self.subTest(stylesheet=rel):
                self.assertTrue(_check_balanced_braces(_read_static(rel)), f"Unbalanced CSS braces in {rel}")

    def test_row_actions_menu_js_portals_to_body_and_supports_mobile_sheet(self):
        js = _read_static("core/static/core/js/makken-row-actions-menu.js")
        self.assertIn("document.body.append(dropdown)", js)
        self.assertIn("is-portaled", js)
        self.assertIn("is-mobile-sheet", js)
        self.assertIn("function isMobileSheet()", js)
        self.assertIn("function positionOpenMenu(", js)
        self.assertIn("window.matchMedia('(max-width: 640px)')", js)
        self.assertIn("setTimeout(() => closeOpenMenu(false), 0)", js)
        self.assertIn("!openMenu.dropdown.contains(event.target)", js)
        self.assertIn("function hideEmptyActionColumns(", js)

    def test_row_actions_menu_css_styles_portaled_body_dropdowns_and_sticky_mobile_column(self):
        css = _read_static("core/static/core/css/makken-row-actions-menu.css")
        self.assertNotIn(":root .main-content .mk-actions-dropdown", css)
        self.assertIn(":root .mk-actions-dropdown a", css)
        self.assertIn(".mk-actions-dropdown.is-portaled", css)
        self.assertIn("position: fixed !important;", css)
        self.assertIn(".mk-actions-dropdown.is-mobile-sheet", css)
        self.assertIn("min-height: 48px !important;", css)
        self.assertIn("position: sticky;", css)
        self.assertIn("th[hidden], td[hidden]", css)

    def test_topbar_and_greeting_pill_responsive_rules_prevent_mobile_collision(self):
        css = _read_static("core/static/core/css/makken-home.css")
        self.assertIn("Responsive Topbar & Greeting Pill Hardening", css)
        self.assertIn("overflow-x: clip;", css)
        self.assertIn(".account-chip-sep", css)
        self.assertIn(".account-chip-clock", css)
        self.assertIn("text-overflow: ellipsis;", css)
        self.assertIn("max-width: none !important;", css)

    def test_compact_tables_css_enforces_readable_mobile_scroll_and_dialog_clamping(self):
        css = _read_static("core/static/core/css/makken-compact-tables.css")
        self.assertIn("-webkit-overflow-scrolling: touch;", css)
        self.assertIn("min-width: 680px !important;", css)
        self.assertIn("min-width: 96px !important;", css)
        self.assertIn(":not(.states-table)", css)
        self.assertIn("calc(100vw - 24px)", css)
        self.assertIn("grid-template-columns: 1fr !important;", css)

    def test_major_pages_render_200_with_responsive_assets_and_strict_csp(self):
        routes = [
            "makken_home",
            "core:dashboard",
            "partnerships:all_index",
            "partnerships:capability_index",
            "partnerships:willingness_index",
            "partnerships:agreement_inquiries",
            "partnerships:achievement_report",
            "partnerships:sponsor_requests",
            "care_states:index",
            "sectors:index",
            "training_programs:index",
            "makken_mail:work_index",
            "makken_mail:work_stats",
            "access_control:index",
        ]
        for route_name in routes:
            with self.subTest(route=route_name):
                res = self.client.get(reverse(route_name))
                self.assertEqual(res.status_code, 200)
                self.assertContains(res, 'name="viewport"')
                self.assertContains(res, "makken-home.css")
                self.assertContains(res, "makken-compact-tables.css")
                self.assertContains(res, "makken-row-actions-menu.js")
                self.assertContains(res, "makken-row-actions-menu.css")
                self.assertContains(res, "account-chip-name")
                csp = res.get("Content-Security-Policy", "")
                self.assertNotIn("unsafe-inline", csp)
                self.assertNotIn("unsafe-eval", csp)

    def test_public_sponsor_register_is_responsive_and_csp_clean(self):
        self.client.logout()
        res = self.client.get(reverse("partnerships:public_sponsor_register"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'name="viewport"')
        csp = res.get("Content-Security-Policy", "")
        self.assertNotIn("unsafe-inline", csp)

    def test_detail_dialogs_css_uses_ocean_blue_palette_bold_typography_and_balanced_braces(self):
        css = _read_static("core/static/core/css/makken-detail-dialogs.css")
        self.assertTrue(_check_balanced_braces(css))
        self.assertIn("#005b85", css)
        self.assertIn("font-weight: 800 !important;", css)
        self.assertIn("font-weight: 700 !important;", css)
        self.assertIn("font-size: 12.5px !important;", css)
        self.assertIn("font-size: 14.5px !important;", css)
        self.assertIn("border-inline-start: 3.5px solid #005b85;", css)
        self.assertIn(".detail-dialog-actions .detail-close-btn:hover", css)
        self.assertIn("color: #ffffff !important;", css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr)) !important;", css)
        self.assertIn("grid-template-columns: 1fr !important;", css)

    def test_no_duplicate_core_css_or_js_links_in_base_template(self):
        base_html = (Path(settings.BASE_DIR) / "core/templates/core/makken_base.html").read_text(encoding="utf-8")
        for asset in (
            "makken-home.css",
            "makken-detail-dialogs.css",
            "makken-dropdowns.css",
            "makken-dropdowns.js",
            "compact_tables_assets.html",
            "table_actions_assets.html",
        ):
            with self.subTest(asset=asset):
                self.assertEqual(base_html.count(asset), 1, f"Duplicate or missing {asset} in makken_base.html")

    def test_partnership_detail_view_modal_loads_ocean_blue_detail_css_and_strict_csp(self):
        from care_states.models import DevelopmentState
        from entities.models import Entity
        from partnerships.models import Partnership

        ent = Entity.objects.create(name="جهة عرض تفاصيل اختبارية", entity_type="government", is_active=True)
        p = Partnership.objects.create(
            name="شركة تفاصيل العرض الاختبارية",
            representative="ممثل التفاصيل",
            phone="+966501234999",
            email="detail_view@example.com",
            entity=ent,
            scope="local",
            development_state_id=DevelopmentState.WILLINGNESS,
        )
        res = self.client.get(reverse("partnerships:willingness_index"), {"detail": str(p.pk)})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "makken-detail-dialogs.css")
        self.assertContains(res, "detail-dialog")
        self.assertContains(res, "detail-grid")
        self.assertContains(res, "شركة تفاصيل العرض الاختبارية")
        self.assertEqual(res.content.decode("utf-8").count("makken-detail-dialogs.css"), 1)
        csp = res.get("Content-Security-Policy", "")
        self.assertNotIn("unsafe-inline", csp)

    def test_inquiries_detail_modal_is_view_only_with_compact_close_button(self):
        from care_states.models import DevelopmentState
        from entities.models import Entity
        from partnerships.models import Partnership

        ent = Entity.objects.create(name="جهة استعلامات تفاصيل", entity_type="government", is_active=True)
        p = Partnership.objects.create(
            name="شراكة استعلامات تفاصيل",
            representative="ممثل الاستعلامات",
            phone="+966501234888",
            email="inq_detail@example.com",
            entity=ent,
            scope="local",
            development_state_id=DevelopmentState.WILLINGNESS,
        )
        res = self.client.get(reverse("partnerships:agreement_inquiries"), {"detail": str(p.pk)})
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, "تعديل الشراكة")
        self.assertContains(res, "detail-dialog-actions")
        self.assertContains(res, "detail-close-btn")
        self.assertContains(res, "<span>مشاهدة</span>")
        self.assertContains(res, "<span>تعديل</span>")
        self.assertContains(res, "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z")
        self.assertContains(res, "m16 4 4 4M4 20l5-1L20 8a2.8 2.8 0 0 0-4-4L5 15Z")
        self.assertNotContains(res, ">عرض التفاصيل<")
