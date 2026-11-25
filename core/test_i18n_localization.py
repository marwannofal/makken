"""Comprehensive unit and integration tests for Makken Arabic/English UI localization."""
from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from access_control.registry import PUBLIC_ROUTES
from core.i18n_catalog import AR_TO_EN, get_js_catalog, translate_ui_text
from core.middleware import localize_html_to_english

User = get_user_model()


class I18nSettingsAndRoutingTests(SimpleTestCase):
    def test_settings_enable_arabic_and_english_with_arabic_default(self):
        self.assertTrue(settings.USE_I18N)
        self.assertEqual(settings.LANGUAGE_CODE, "ar")
        lang_codes = [code for code, _ in settings.LANGUAGES]
        self.assertIn("ar", lang_codes)
        self.assertIn("en", lang_codes)

        mw = list(settings.MIDDLEWARE)
        self.assertIn("django.middleware.locale.LocaleMiddleware", mw)
        self.assertIn("core.middleware.MakkenLocalizationMiddleware", mw)
        self.assertLess(
            mw.index("django.contrib.sessions.middleware.SessionMiddleware"),
            mw.index("django.middleware.locale.LocaleMiddleware"),
        )

        ctx_processors = settings.TEMPLATES[0]["OPTIONS"]["context_processors"]
        self.assertIn("django.template.context_processors.i18n", ctx_processors)

    def test_i18n_routes_are_public_and_reverse_cleanly(self):
        self.assertEqual(reverse("set_language"), "/i18n/setlang/")
        self.assertEqual(reverse("makken_i18n_catalog"), "/i18n/catalog.js")
        self.assertIn("set_language", PUBLIC_ROUTES)
        self.assertIn("makken_i18n_catalog", PUBLIC_ROUTES)

    def test_csp_compliance_zero_inline_scripts_or_styles_in_i18n_assets(self):
        base = Path(settings.BASE_DIR)
        switcher = (base / "core" / "templates" / "core" / "partials" / "lang_switcher.html").read_text(encoding="utf-8")
        self.assertNotIn("<script", switcher.lower())
        self.assertNotIn("<style", switcher.lower())
        self.assertNotIn("style=", switcher.lower())
        self.assertNotIn("onclick=", switcher.lower())

        css = (base / "core" / "static" / "core" / "css" / "makken-i18n.css").read_text(encoding="utf-8")
        self.assertEqual(css.count("{"), css.count("}"))
        self.assertIn('html[dir="ltr"]', css)
        self.assertIn(".mk-lang-btn", css)

        js = (base / "core" / "static" / "core" / "js" / "makken-i18n.js").read_text(encoding="utf-8")
        self.assertIn("MutationObserver", js)
        self.assertIn("MAKKEN_I18N_EN", js)


class TranslationCatalogUnitTests(SimpleTestCase):
    def test_exact_ui_translations_cover_navigation_actions_and_statuses(self):
        expected = {
            "الرئيسية": "Home",
            "الشراكات": "Partnerships",
            "بطاقات حاجة السوق": "Market Need Cards",
            "المؤشرات والتحليلات المرنة": "Flexible Analytics & KPIs",
            "المستخدمون والصلاحيات": "Users & Permissions",
            "تسجيل الخروج": "Sign Out",
            "تعديل": "Edit",
            "حذف": "Delete",
            "مشاهدة": "View",
            "إيقاف التفعيل": "Deactivate",
            "تفعيل السجل": "Activate",
            "نشط": "Active",
            "غير نشط": "Inactive",
            "تصدير Excel": "Export Excel",
            "تصدير PDF": "Export PDF",
        }
        for ar, en in expected.items():
            with self.subTest(ar=ar):
                self.assertEqual(translate_ui_text(ar), en)

    def test_preserves_outer_whitespace_and_punctuation_variants(self):
        self.assertEqual(translate_ui_text("  تعديل  "), "  Edit  ")
        self.assertEqual(translate_ui_text("\nحذف\n"), "\nDelete\n")
        self.assertEqual(translate_ui_text("البريد الإلكتروني *"), "Email Address *")
        self.assertEqual(translate_ui_text("حالة السجل:"), "Record Status:")

    def test_dynamic_parameterized_patterns_translate_cleanly(self):
        self.assertEqual(translate_ui_text("عدد السجلات: 42"), "Total Records: 42")
        self.assertEqual(translate_ui_text("نسبة إنجاز الشراكة: 85%"), "Partnership Completion: 85%")
        self.assertEqual(translate_ui_text("عدد البنود: 4"), "Clauses: 4")
        self.assertEqual(translate_ui_text("مرحبًا، Marwan"), "Welcome, Marwan")
        self.assertEqual(translate_ui_text("إدارة المناطق | مكّن"), "Regions Management | Makken")
        self.assertEqual(translate_ui_text("تعديل الرياض"), "Edit الرياض")
        self.assertEqual(translate_ui_text("حذف سجل تجريبي"), "Delete سجل تجريبي")
        self.assertEqual(translate_ui_text("المسؤولية: المؤسسة"), "Responsibility: TVTC")
        self.assertEqual(translate_ui_text("3 بند"), "3 clause(s)")
        self.assertEqual(translate_ui_text("عرض 1 إلى 10 من 50"), "Showing 1–10 of 50")

    def test_non_ui_arabic_database_records_and_english_text_remain_untouched(self):
        self.assertEqual(translate_ui_text("شركة أرامكو السعودية"), "شركة أرامكو السعودية")
        self.assertEqual(translate_ui_text("Already English"), "Already English")
        self.assertEqual(translate_ui_text("12345"), "12345")
        self.assertEqual(translate_ui_text(""), "")

    def test_js_catalog_is_non_empty_and_matches_dictionary(self):
        catalog = get_js_catalog()
        self.assertGreaterEqual(len(catalog), 250)
        self.assertEqual(catalog["تعديل"], "Edit")
        self.assertEqual(len(catalog), len(AR_TO_EN))


class HtmlLocalizerUnitTests(SimpleTestCase):
    def test_html_localizer_translates_text_and_ui_attributes_only(self):
        raw = (
            '<div aria-label="القائمة الرئيسية">'
            '<input type="text" name="q" value="شركة سابك" placeholder="ابحث هنا…">'
            '<input type="submit" value="بحث">'
            '<button type="button" title="إغلاق">حفظ</button>'
            '</div>'
        )
        out = localize_html_to_english(raw)
        self.assertIn('aria-label="Main Menu"', out)
        self.assertIn('placeholder="Search here…"', out)
        self.assertIn('value="شركة سابك"', out)
        self.assertIn('value="Search"', out)
        self.assertIn('title="Close"', out)
        self.assertIn(">Save</button>", out)

    def test_html_localizer_skips_script_style_textarea_and_lang_switcher(self):
        raw = (
            '<script>var x = "تعديل";</script>'
            '<style>.a { content: "حذف"; }</style>'
            '<textarea name="notes">تعديل</textarea>'
            '<form data-lang-switcher><button type="submit">العربية</button></form>'
            '<p>تعديل</p>'
        )
        out = localize_html_to_english(raw)
        self.assertIn('var x = "تعديل";', out)
        self.assertIn('.a { content: "حذف"; }', out)
        self.assertIn("<textarea name=\"notes\">تعديل</textarea>", out)
        self.assertIn(">العربية</button>", out)
        self.assertIn("<p>Edit</p>", out)


class LanguageSwitcherEndToEndTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="i18n_admin_test",
            email="i18nadmin@makken.test",
            password="StrongPassword!2026",
            first_name="Marwan",
            last_name="Admin",
        )
        cls.regular_user = User.objects.create_user(
            username="i18n_user_test",
            email="i18nuser@makken.test",
            password="StrongPassword!2026",
            first_name="Noura",
            last_name="Staff",
        )

    def test_no_pending_database_migrations_for_ui_only_localization(self):
        # Raises SystemExit if any unmigrated model changes exist
        call_command("makemigrations", "core", check=True, dry_run=True, verbosity=0)

    def test_default_arabic_renders_rtl_and_english_switch_button_in_topbar(self):
        self.client.force_login(self.admin)
        res = self.client.get(reverse("makken_home"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '<html lang="ar" dir="rtl">')
        self.assertContains(res, 'action="/i18n/setlang/"')
        self.assertContains(res, 'name="language" value="en"')
        self.assertContains(res, "<span>English</span>")
        self.assertContains(res, "makken-i18n.css")
        self.assertNotContains(res, "makken-i18n.js")

    def test_switching_to_english_uses_clean_url_sets_cookie_and_renders_ltr(self):
        self.client.force_login(self.admin)
        target_url = reverse("regions:index")
        post_res = self.client.post(
            reverse("set_language"),
            {"language": "en", "next": target_url},
        )
        self.assertEqual(post_res.status_code, 302)
        self.assertEqual(post_res["Location"], target_url)
        self.assertEqual(post_res.cookies[settings.LANGUAGE_COOKIE_NAME].value, "en")

        res = self.client.get(target_url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '<html lang="en" dir="ltr">')
        self.assertContains(res, 'name="language" value="ar"')
        self.assertContains(res, "<span>العربية</span>")
        self.assertContains(res, "/i18n/catalog.js")
        self.assertContains(res, "makken-i18n.js")
        self.assertContains(res, "Regions Management")
        self.assertContains(res, "Sign Out")

    def test_switching_back_to_arabic_restores_rtl_and_skips_english_js(self):
        self.client.force_login(self.admin)
        target_url = reverse("levels:index")
        self.client.post(reverse("set_language"), {"language": "en", "next": target_url})
        en_res = self.client.get(target_url)
        self.assertContains(en_res, '<html lang="en" dir="ltr">')

        self.client.post(reverse("set_language"), {"language": "ar", "next": target_url})
        ar_res = self.client.get(target_url)
        self.assertEqual(ar_res.status_code, 200)
        self.assertContains(ar_res, '<html lang="ar" dir="rtl">')
        self.assertNotContains(ar_res, "makken-i18n.js")

    def test_query_string_is_preserved_across_language_switch(self):
        self.client.force_login(self.admin)
        target_with_qs = f"{reverse('regions:index')}?q=Riyadh&status=active"
        res = self.client.post(
            reverse("set_language"),
            {"language": "en", "next": target_with_qs},
        )
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res["Location"], target_with_qs)

    def test_anonymous_user_can_switch_language_on_login_page(self):
        login_url = reverse("accounts:login")
        ar_res = self.client.get(login_url)
        self.assertEqual(ar_res.status_code, 200)
        self.assertContains(ar_res, '<html lang="ar" dir="rtl">')
        self.assertContains(ar_res, "data-lang-switcher")

        switch_res = self.client.post(
            reverse("set_language"),
            {"language": "en", "next": login_url},
        )
        self.assertEqual(switch_res.status_code, 302)
        self.assertEqual(switch_res["Location"], login_url)

        en_res = self.client.get(login_url)
        self.assertEqual(en_res.status_code, 200)
        self.assertContains(en_res, '<html lang="en" dir="ltr">')
        self.assertContains(en_res, "Welcome Back")
        self.assertContains(en_res, "Sign In")

    def test_non_superuser_can_switch_language_and_fetch_js_catalog(self):
        self.client.force_login(self.regular_user)
        profile_url = reverse("accounts:profile")
        res = self.client.post(
            reverse("set_language"),
            {"language": "en", "next": profile_url},
        )
        self.assertEqual(res.status_code, 302)
        self.assertEqual(res["Location"], profile_url)

        js_res = self.client.get(reverse("makken_i18n_catalog"))
        self.assertEqual(js_res.status_code, 200)
        self.assertIn("javascript", js_res["Content-Type"].lower())

    def test_js_catalog_endpoint_returns_valid_json_payload_without_login(self):
        res = self.client.get(reverse("makken_i18n_catalog"))
        self.assertEqual(res.status_code, 200)
        body = res.content.decode("utf-8")
        self.assertTrue(body.startswith("window.MAKKEN_I18N_EN = "))
        json_str = body[len("window.MAKKEN_I18N_EN = ") :].strip().rstrip(";")
        parsed = json.loads(json_str)
        self.assertEqual(parsed["تعديل"], "Edit")
        self.assertEqual(parsed["إيقاف التفعيل"], "Deactivate")

    def test_major_makken_pages_render_200_in_both_arabic_and_english(self):
        self.client.force_login(self.admin)
        routes = [
            "makken_home",
            "partnerships:capability_index",
            "partnerships:willingness_index",
            "partnerships:agreement_inquiries",
            "market_needs:index",
            "service_providers:index",
            "flex_analytics:index",
            "levels:index",
            "regions:index",
            "sectors:index",
            "entities:index",
            "specializations:index",
            "expense_items:index",
            "training_programs:index",
            "sponsorship_shapes:index",
            "agreement_clauses:index",
            "agreement_clauses:references",
            "accounts:profile",
            "access_control:index",
            "access_control:roles",
        ]
        # Verify Arabic (RTL)
        self.client.post(reverse("set_language"), {"language": "ar", "next": "/"})
        for route_name in routes:
            with self.subTest(lang="ar", route=route_name):
                res = self.client.get(reverse(route_name))
                self.assertEqual(res.status_code, 200)
                self.assertContains(res, '<html lang="ar" dir="rtl">')

        # Verify English (LTR)
        self.client.post(reverse("set_language"), {"language": "en", "next": "/"})
        for route_name in routes:
            with self.subTest(lang="en", route=route_name):
                res = self.client.get(reverse(route_name))
                self.assertEqual(res.status_code, 200)
                self.assertContains(res, '<html lang="en" dir="ltr">')
                self.assertContains(res, "data-lang-switcher")
                self.assertContains(res, "Sign Out")
