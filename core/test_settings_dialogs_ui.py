"""Tests verifying all 13 إدارة البيانات pages + إدارات الهيكل التنظيمي load the spacious, responsive settings dialogs CSS."""
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse


class SettingsDialogsCssUnitTests(SimpleTestCase):
    def test_settings_dialogs_css_has_balanced_braces_spacious_sizes_and_responsive_rules(self):
        css = (Path(settings.BASE_DIR) / "core" / "static" / "core" / "css" / "makken-settings-dialogs.css").read_text(encoding="utf-8")
        self.assertEqual(css.count("{"), css.count("}"))
        self.assertIn("width: min(640px, calc(100vw - 28px)) !important;", css)
        self.assertIn("width: min(760px, calc(100vw - 28px)) !important;", css)
        self.assertIn("font-size: 26px !important;", css)
        self.assertIn("font-size: 25px !important;", css)
        self.assertIn("min-height: 52px !important;", css)
        self.assertIn("@media (max-width: 640px)", css)


class SettingsDialogsSiteWideRenderTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="settings_dlg_admin",
            email="settings_dlg@makken.test",
            password="StrongPassword123!",
            first_name="Marwan",
        )
        self.client.force_login(self.admin)

    def test_all_13_data_management_pages_and_departments_load_upgraded_dialog_css(self):
        routes = [
            "care_states:index",
            "agreement_clauses:references",
            "agreement_clauses:classifications",
            "partnership_types",
            "levels:index",
            "regions:index",
            "entities:index",
            "specializations:index",
            "sectors:index",
            "expense_items:index",
            "agreement_clauses:index",
            "training_programs:index",
            "sponsorship_shapes:index",
            "accounts:departments",
        ]
        for route in routes:
            with self.subTest(route=route):
                res = self.client.get(reverse(route))
                self.assertEqual(res.status_code, 200)
                self.assertContains(res, "makken-settings-dialogs.css?v=20261126-dlg1")
