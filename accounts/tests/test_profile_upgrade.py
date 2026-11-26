"""Comprehensive tests for profile photo upload, topbar greeting dropdown, separate password page, and read-only email/username."""
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts.models import UserProfile

TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


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

    def test_profile_and_password_are_two_separate_pages_with_topbar_dropdown(self):
        res_prof = self.client.get(reverse("accounts:profile"))
        self.assertEqual(res_prof.status_code, 200)
        self.assertContains(res_prof, "data-account-menu-trigger")
        self.assertContains(res_prof, reverse("accounts:profile_password"))
        self.assertContains(res_prof, 'id="mk-readonly-username"')
        self.assertContains(res_prof, 'id="mk-readonly-email"')
        # No password confirmation or email confirmation on profile details page
        self.assertNotContains(res_prof, 'name="current_password"')
        self.assertNotContains(res_prof, 'name="email_confirm"')
        self.assertNotContains(res_prof, 'name="new_password1"')

        res_pw = self.client.get(reverse("accounts:profile_password"))
        self.assertEqual(res_pw.status_code, 200)
        self.assertContains(res_pw, 'name="old_password"')
        self.assertContains(res_pw, 'name="new_password1"')
        self.assertContains(res_pw, 'name="new_password2"')
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

    def test_avatar_upload_serves_image_and_rejects_invalid_files(self):
        page = self.client.get(reverse("accounts:profile"))
        snap = page.context["detail_form"]["snapshot"].value()

        # Reject non-image file
        bad = SimpleUploadedFile("bad.png", b"not-a-real-image", content_type="image/png")
        res_bad = self.client.post(
            reverse("accounts:profile"),
            {"snapshot": snap, "first_name": "Marwan", "last_name": "Nofal", "phone_country": "SA", "phone": "", "avatar": bad},
        )
        self.assertEqual(res_bad.status_code, 400)

        # Upload valid PNG
        good = SimpleUploadedFile("me.png", TINY_PNG, content_type="image/png")
        res_ok = self.client.post(
            reverse("accounts:profile"),
            {"snapshot": snap, "first_name": "Marwan", "last_name": "Nofal", "phone_country": "SA", "phone": "", "avatar": good},
        )
        self.assertEqual(res_ok.status_code, 302)
        prof = UserProfile.objects.get(user=self.user)
        self.assertTrue(bool(prof.avatar))

        av_res = self.client.get(reverse("accounts:profile_avatar"))
        self.assertEqual(av_res.status_code, 200)
        self.assertEqual(av_res["Content-Type"], "image/png")
        av_res.close()

        # Topbar & sidebar now render avatar image
        home_res = self.client.get("/")
        self.assertContains(home_res, reverse("accounts:profile_avatar"))

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
