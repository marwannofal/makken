"""Tests for decoupled clauses_progress RBAC and assigned-employee read-only partnership view."""
import json
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from access_control.defaults import initialize
from access_control.models import PageScope, RegionScope, RoleProfile, UserAccess
from agreement_clauses.models import AgreementClause, ClauseAssignment, Responsibility
from care_states.models import DevelopmentState
from entities.models import Entity
from makken_mail.models import WorkAssignment
from regions.models import Region

from .models import Partnership

User = get_user_model()
AUTH_BACKEND = "accounts.backends.EmailOrUsernameBackend"

PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


class ClausesProgressRBACAndEmployeeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()
        cls.region = Region.objects.create(name="منطقة الرياض اختبار", is_active=True)
        cls.entity = Entity.objects.create(name="جهة اختبار البنود", entity_type="government", is_active=True)
        cls.clause = AgreementClause.objects.create(name="بند اختبار الصلاحيات", is_active=True)
        cls.manager = User.objects.create_user("mgr_cp", "mgr_cp@example.com", "StrongPass123!", first_name="مدير", last_name="التجربة")
        cls.assigned_emp = User.objects.create_user("emp_assigned", "emp_a@example.com", "StrongPass123!", first_name="عبدالله", last_name="شبيب")
        cls.other_emp = User.objects.create_user("emp_other", "emp_o@example.com", "StrongPass123!", first_name="موظف", last_name="آخر")
        cls.cp_only_user = User.objects.create_user("cp_only", "cp_only@example.com", "StrongPass123!", first_name="محدث", last_name="البنود")
        cls.view_only_user = User.objects.create_user("view_only", "view_only@example.com", "StrongPass123!", first_name="عارض", last_name="فقط")

        for u in (cls.assigned_emp, cls.other_emp):
            UserAccess.objects.update_or_create(
                user=u,
                defaults={"page_scope": PageScope.ALL, "region_scope": RegionScope.ALL},
            )

        p_view = Permission.objects.get(codename="view_partnerships")
        p_cp = Permission.objects.get(codename="clauses_progress_partnerships")

        g_cp = Group.objects.create(name="تحديث بنود فقط")
        RoleProfile.objects.create(group=g_cp, page_scope=PageScope.ALL)
        g_cp.permissions.add(p_view, p_cp)
        cls.cp_only_user.groups.add(g_cp)
        UserAccess.objects.update_or_create(
            user=cls.cp_only_user,
            defaults={"page_scope": PageScope.ALL, "region_scope": RegionScope.ALL},
        )

        g_view = Group.objects.create(name="عرض الشراكات فقط")
        RoleProfile.objects.create(group=g_view, page_scope=PageScope.ALL)
        g_view.permissions.add(p_view)
        cls.view_only_user.groups.add(g_view)
        UserAccess.objects.update_or_create(
            user=cls.view_only_user,
            defaults={"page_scope": PageScope.ALL, "region_scope": RegionScope.ALL},
        )

        cls.partnership = Partnership.objects.create(
            name="شركة اختبار متابعة البنود",
            representative="ممثل",
            phone_country="SA",
            phone="+966501112233",
            email="cp_test@example.com",
            entity=cls.entity,
            scope="local",
            development_state_id=DevelopmentState.WILLINGNESS,
            created_by=cls.manager,
        )
        cls.partnership.administrative_regions.add(cls.region)
        cls.assignment = ClauseAssignment.objects.create(
            partnership=cls.partnership,
            clause=cls.clause,
            responsibility=Responsibility.SHARED,
            progress=0,
        )
        cls.work = WorkAssignment.objects.create(
            title="متابعة الشراكة",
            target_model="partnerships.partnership",
            target_key=cls.partnership.pk,
            employee=cls.assigned_emp,
            manager=cls.manager,
        )
        cls.work.assignees.add(cls.assigned_emp)

    def test_clauses_progress_permission_is_decoupled_from_partnership_edit(self):
        self.client.force_login(self.view_only_user, backend=AUTH_BACKEND)
        list_res = self.client.get(reverse("partnerships:willingness_index"))
        self.assertEqual(list_res.status_code, 200)
        cp_url = reverse("partnerships:clauses_progress", args=[self.partnership.pk])
        self.assertNotContains(list_res, cp_url)
        self.assertEqual(self.client.get(cp_url).status_code, 403)
        self.assertEqual(self.client.post(cp_url, {"items_json": "[]"}).status_code, 403)

        self.client.force_login(self.cp_only_user, backend=AUTH_BACKEND)
        list_res2 = self.client.get(reverse("partnerships:willingness_index"))
        self.assertEqual(list_res2.status_code, 200)
        self.assertContains(list_res2, cp_url)
        self.assertEqual(self.client.get(cp_url).status_code, 200)
        post_res = self.client.post(
            cp_url,
            {"items_json": json.dumps([{"id": self.assignment.pk, "progress": 50, "notes": "تقدم 50%"}])},
        )
        self.assertEqual(post_res.status_code, 200)
        self.assignment.refresh_from_db()
        self.assertEqual(self.assignment.progress, 50)
        self.assertEqual(
            self.client.post(reverse("partnerships:edit", args=[self.partnership.pk]), {"action": "preview"}).status_code,
            403,
        )

    def test_assigned_employee_from_my_work_opens_clauses_first_and_readonly_rest(self):
        self.client.force_login(self.assigned_emp, backend=AUTH_BACKEND)
        my_work = self.client.get(reverse("makken_mail:work_index"))
        self.assertEqual(my_work.status_code, 200)
        expected_url = reverse("partnerships:edit", args=[self.partnership.pk]) + "?from=my_work"
        self.assertContains(my_work, expected_url)

        edit_page = self.client.get(expected_url)
        self.assertEqual(edit_page.status_code, 200)
        html = edit_page.content.decode()
        self.assertIn("01 · بنود الاتفاقية ونسب الإنجاز", html)
        self.assertIn('class="mk-readonly-fieldset" disabled', html)
        self.assertNotIn("data-save-partnership", html)
        self.assertLess(html.index("01 · بنود الاتفاقية ونسب الإنجاز"), html.index("01 · معلومات الجهة والبيانات الأساسية"))

        cp_url = reverse("partnerships:clauses_progress", args=[self.partnership.pk])
        up_res = self.client.post(
            cp_url,
            {
                "items_json": json.dumps([{"id": self.assignment.pk, "progress": 75, "notes": "تم التنفيذ"}]),
                f"evidence_{self.assignment.pk}": SimpleUploadedFile("proof.png", PNG_BYTES, content_type="image/png"),
            },
        )
        self.assertEqual(up_res.status_code, 200)
        data = up_res.json()
        self.assertEqual(data["overall_display"], "75%")
        self.assertEqual(len(data["clauses"][0]["evidences"]), 1)

        dl_url = data["clauses"][0]["evidences"][0]["download_url"]
        self.assertEqual(self.client.get(dl_url).status_code, 200)

        self.assertEqual(self.client.post(expected_url, {"action": "preview"}).status_code, 403)

    def test_unassigned_employee_remains_denied(self):
        self.client.force_login(self.other_emp, backend=AUTH_BACKEND)
        self.assertEqual(
            self.client.get(reverse("partnerships:edit", args=[self.partnership.pk]) + "?from=my_work").status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("partnerships:clauses_progress", args=[self.partnership.pk])).status_code,
            403,
        )
