"""Tests for the new 'إدارة المستخدمين' sidebar group, removal of ac-tabs, and hiding /access-control/logs/."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse


class UserManagementSidebarAndHiddenLogsTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="um_sidebar_admin",
            email="um_sidebar@makken.test",
            password="StrongPassword123!",
            first_name="Marwan",
        )
        self.regular = get_user_model().objects.create_user(
            username="um_sidebar_user",
            email="um_regular@makken.test",
            password="StrongPassword123!",
            first_name="User",
        )

    def test_superuser_sees_user_management_sidebar_group_with_all_7_links_and_no_logs(self):
        self.client.force_login(self.admin)
        res = self.client.get(reverse("access_control:index"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "data-user-management-group")
        self.assertContains(res, "<span>إدارة المستخدمين</span>")
        for label in [
            "<span>المستخدمون</span>",
            "<span>الأدوار</span>",
            "<span>الصلاحيات</span>",
            "<span>صلاحيات الصفحات</span>",
            "<span>إشعارات البريد</span>",
            "<span>نشاط المستخدمين</span>",
            "<span>إدارات الهيكل التنظيمي</span>",
        ]:
            with self.subTest(label=label):
                self.assertContains(res, label)
        # Horizontal tabs bar removed completely
        self.assertNotContains(res, 'class="ac-tabs"')
        # No links to /access-control/logs/ anywhere
        self.assertNotContains(res, reverse("access_control:logs"))
        # Old duplicate footer links removed
        self.assertNotContains(res, "<span>المستخدمون والصلاحيات</span>")
        self.assertNotContains(res, "<span>سجل نشاط المستخدمين</span>")

    def test_access_control_logs_page_is_completely_hidden_404(self):
        self.client.force_login(self.admin)
        res = self.client.get(reverse("access_control:logs"))
        self.assertEqual(res.status_code, 404)

    def test_all_7_user_management_pages_render_200_without_tabs_bar(self):
        self.client.force_login(self.admin)
        urls = [
            reverse("access_control:index"),
            reverse("access_control:roles"),
            reverse("access_control:index") + "?tab=permissions",
            reverse("access_control:index") + "?tab=pages",
            reverse("makken_mail:index"),
            reverse("access_control:activity"),
            reverse("accounts:departments"),
        ]
        for url in urls:
            with self.subTest(url=url):
                res = self.client.get(url)
                self.assertEqual(res.status_code, 200)
                self.assertNotContains(res, 'class="ac-tabs"')
                self.assertContains(res, "data-user-management-group")

    def test_regular_user_without_permissions_does_not_see_user_management_group(self):
        self.client.force_login(self.regular)
        res = self.client.get(reverse("accounts:profile"))
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, "data-user-management-group")
