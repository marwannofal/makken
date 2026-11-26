"""Unit and end-to-end tests for live sidebar counter badges (Sponsor Requests & Work Log)."""
from pathlib import Path
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from core.templatetags.sidebar_badges import format_badge_count, get_sidebar_new_counts
from entities.models import Entity
from makken_mail.models import WorkAssignment, WorkStatus
from partnerships.models import SponsorRegistrationRequest, SponsorRequestStatus


class SidebarBadgeFormattingAndCssTests(SimpleTestCase):
    """Validates badge formatting helpers, CSS rules, active inversion, and collapsed-parent behavior."""

    def test_format_badge_count_handles_zero_normal_and_99_plus(self):
        self.assertEqual(format_badge_count(0), "")
        self.assertEqual(format_badge_count(-3), "")
        self.assertEqual(format_badge_count(1), "1")
        self.assertEqual(format_badge_count(42), "42")
        self.assertEqual(format_badge_count(99), "99")
        self.assertEqual(format_badge_count(100), "99+")
        self.assertEqual(format_badge_count(250), "99+")

    def test_sidebar_badge_css_has_balanced_braces_and_required_rules(self):
        css = (Path(settings.BASE_DIR) / "core" / "static" / "core" / "css" / "makken-sidebar-management.css").read_text(encoding="utf-8")
        self.assertEqual(css.count("{"), css.count("}"))
        self.assertIn(".nav-count-badge {", css)
        self.assertIn("background: #ffffff;", css)
        self.assertIn("color: #005b85;", css)
        self.assertIn(".nav-management[open] > .nav-management-toggle .nav-group-badge {", css)
        self.assertIn(".sidebar .nav-link.is-active .nav-count-badge {", css)


class SidebarBadgeEndToEndTests(TestCase):
    """Verifies live count updates, disappearance at 0, RBAC/visibility scoping, and request caching."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser(
            username="badge_admin",
            email="badge_admin@makken.test",
            password="StrongPassword123!",
            first_name="Marwan",
        )
        self.employee = User.objects.create_user(
            username="badge_emp",
            email="badge_emp@makken.test",
            password="StrongPassword123!",
            first_name="Employee",
        )
        self.other_emp = User.objects.create_user(
            username="badge_other",
            email="badge_other@makken.test",
            password="StrongPassword123!",
            first_name="Other",
        )
        self.entity = Entity.objects.create(name="جهة اختبار الشارات", entity_type="government", is_active=True)

    def _create_sponsor_request(self, name, status=SponsorRequestStatus.NEW):
        return SponsorRegistrationRequest.objects.create(
            name=name,
            representative="ممثل اختبار",
            phone="+966501234567",
            email="sponsor@test.local",
            entity=self.entity,
            scope="global",
            status=status,
        )

    def _create_work(self, title, employee, status=WorkStatus.NEW):
        return WorkAssignment.objects.create(
            title=title,
            employee=employee,
            manager=self.admin,
            created_by=self.admin,
            status=status,
        )

    def test_sponsor_requests_badge_counts_new_and_disappears_at_zero(self):
        self.client.force_login(self.admin)

        # 0 new -> no sponsor badge rendered
        res0 = self.client.get("/")
        self.assertEqual(res0.status_code, 200)
        self.assertNotContains(res0, 'data-badge-kind="sponsor_requests"')

        # 2 new -> badge shows 2 on both parent group and inner link
        r1 = self._create_sponsor_request("شركة اختبار الشارة 1", SponsorRequestStatus.NEW)
        r2 = self._create_sponsor_request("شركة اختبار الشارة 2", SponsorRequestStatus.NEW)
        res2 = self.client.get("/")
        self.assertContains(res2, 'data-badge-kind="sponsor_requests">2</span>')
        self.assertContains(res2, 'data-badge-group="partnerships">2</span>')

        # Move 1 to approved -> drops to 1
        r1.status = SponsorRequestStatus.APPROVED
        r1.save(update_fields=["status"])
        res1 = self.client.get("/")
        self.assertContains(res1, 'data-badge-kind="sponsor_requests">1</span>')
        self.assertContains(res1, 'data-badge-group="partnerships">1</span>')

        # Move last to rejected -> disappears completely
        r2.status = SponsorRequestStatus.REJECTED
        r2.save(update_fields=["status"])
        res_gone = self.client.get("/")
        self.assertNotContains(res_gone, 'data-badge-kind="sponsor_requests"')
        self.assertNotContains(res_gone, 'data-badge-group="partnerships"')

    def test_work_assignments_badge_counts_new_and_disappears_at_zero(self):
        self.client.force_login(self.admin)

        # 0 new -> no work badge
        res0 = self.client.get("/")
        self.assertNotContains(res0, 'data-badge-kind="work_assignments"')

        # 2 new -> badge shows 2 on both parent group and inner link
        w1 = self._create_work("مهمة اختبار شارة 1", self.employee, WorkStatus.NEW)
        w2 = self._create_work("مهمة اختبار شارة 2", self.other_emp, WorkStatus.NEW)
        res2 = self.client.get("/")
        self.assertContains(res2, 'data-badge-kind="work_assignments">2</span>')
        self.assertContains(res2, 'data-badge-group="work">2</span>')

        # Move 1 to running -> drops to 1
        w1.status = WorkStatus.RUNNING
        w1.save(update_fields=["status"])
        res1 = self.client.get("/")
        self.assertContains(res1, 'data-badge-kind="work_assignments">1</span>')
        self.assertContains(res1, 'data-badge-group="work">1</span>')

        # Move last to complete -> disappears completely
        w2.status = WorkStatus.COMPLETE
        w2.progress = 100
        w2.save(update_fields=["status", "progress"])
        res_gone = self.client.get("/")
        self.assertNotContains(res_gone, 'data-badge-kind="work_assignments"')
        self.assertNotContains(res_gone, 'data-badge-group="work"')

    def test_non_superuser_only_counts_visible_new_work_and_hides_unpermitted_sponsor_badge(self):
        self._create_sponsor_request("شركة غير مرئية للموظف", SponsorRequestStatus.NEW)
        self._create_work("مهمة للموظف", self.employee, WorkStatus.NEW)
        self._create_work("مهمة لموظف آخر", self.other_emp, WorkStatus.NEW)

        req = RequestFactory().get("/")
        req.user = self.employee
        counts = get_sidebar_new_counts(req)
        self.assertEqual(counts["sponsor_requests_new"], 0)
        self.assertEqual(counts["work_assignments_new"], 1)
        self.assertEqual(counts["work_assignments_display"], "1")

    def test_counts_are_cached_per_request_and_csp_clean(self):
        self._create_work("مهمة كاش", self.employee, WorkStatus.NEW)
        req = RequestFactory().get("/")
        req.user = self.admin
        first = get_sidebar_new_counts(req)
        second = get_sidebar_new_counts(req)
        self.assertIs(first, second)

        self.client.force_login(self.admin)
        res = self.client.get(reverse("makken_mail:work_index"))
        self.assertEqual(res.status_code, 200)
        html = res.content.decode("utf-8")
        self.assertIn('data-badge-kind="work_assignments">1</span>', html)
        self.assertIsNone(re.search(r"<style\b", html, re.I))
