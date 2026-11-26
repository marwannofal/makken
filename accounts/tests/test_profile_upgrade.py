"""Tests for separate Profile and Change Password pages, topbar dropdown, and read-only username/email."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class ProfileAndTopbarMenuTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="prof_upgrade_user",
            email="original@makken.test",
            password="OldStrongPassword123!",
            first_name="Marwan",
            last_name="Nofal",
        )
        self.client.force_login(self.user)

    def test_profile_and_password_are_clean_separate_pages_without_upload_or_shortcut_buttons(self):
        res_prof = self.client.get(reverse("accounts:profile"))
        self.assertEqual(res_prof.status_code, 200)
        self.assertContains(res_prof, "data-account-menu-trigger")
        self.assertContains(res_prof, 'id="mk-readonly-username"')
        self.assertContains(res_prof, 'id="mk-readonly-email"')
        self.assertNotContains(res_prof, 'name="avatar"')
        self.assertNotContains(res_prof, 'name="remove_avatar"')
        self.assertNotContains(res_prof, 'class="mk-prof-head-actions"')
        self.assertNotContains(res_prof, 'name="current_password"')
        self.assertNotContains(res_prof, 'name="email_confirm"')
        self.assertNotContains(res_prof, 'name="new_password1"')

        res_pw = self.client.get(reverse("accounts:profile_password"))
        self.assertEqual(res_pw.status_code, 200)
        self.assertContains(res_pw, 'name="old_password"')
        self.assertContains(res_pw, 'name="new_password1"')
        self.assertContains(res_pw, 'name="new_password2"')
        self.assertNotContains(res_pw, 'class="mk-prof-head-actions"')
        self.assertNotContains(res_pw, 'name="first_name"')

    def test_profile_updates_without_password_and_ignores_email_or_username_tampering(self):
        page = self.client.get(reverse("accounts:profile"))
        snap = page.context["detail_form"]["snapshot"].value()
        res = self.client.post(
            reverse("accounts:profile"),
            {
                "snapshot": snap,
                "first_name": "مروان",
                "last_name": "نوفل",
                "phone_country": "SA",
                "phone": "0501234567",
                "email": "hacked@evil.test",
                "username": "hacked_user",
            },
        )
        self.assertEqual(res.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "مروان")
        self.assertEqual(self.user.last_name, "نوفل")
        self.assertEqual(self.user.email, "original@makken.test")
        self.assertEqual(self.user.username, "prof_upgrade_user")

    def test_dedicated_change_password_page_updates_password(self):
        page = self.client.get(reverse("accounts:profile_password"))
        snap = page.context["password_form"]["snapshot"].value()
        res = self.client.post(
            reverse("accounts:profile_password"),
            {
                "snapshot": snap,
                "old_password": "OldStrongPassword123!",
                "new_password1": "NewSuperStrong#2026!",
                "new_password2": "NewSuperStrong#2026!",
            },
        )
        self.assertEqual(res.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NewSuperStrong#2026!"))
