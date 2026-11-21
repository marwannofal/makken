"""Tests for automatic WorkAssignment progress & status sync from agreement clause progress (Option A)."""
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.defaults import initialize
from agreement_clauses.models import AgreementClause, ClauseAssignment, Responsibility
from care_states.models import DevelopmentState
from entities.models import Entity
from partnerships.models import Partnership
from .clause_sync import is_work_overdue, riyadh_today
from .models import WorkAssignment, WorkStatus

User = get_user_model()
AUTH_BACKEND = "accounts.backends.EmailOrUsernameBackend"


class WorkClauseProgressSyncTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()

    def setUp(self):
        self.admin = User.objects.create_superuser("sync_admin", "sync_admin@example.com", "StrongPass123!")
        self.emp = User.objects.create_user("sync_emp", "sync_emp@example.com", "StrongPass123!")
        self.mgr = User.objects.create_user("sync_mgr", "sync_mgr@example.com", "StrongPass123!")
        self.entity = Entity.objects.create(name="جهة مزامنة اختبارية", entity_type="government", is_active=True)
        self.partnership = Partnership.objects.create(
            name="شراكة مزامنة البنود",
            representative="ممثل",
            phone="+966501112233",
            email="sync@example.com",
            entity=self.entity,
            scope="local",
            development_state_id=DevelopmentState.WILLINGNESS,
        )
        self.cl1 = AgreementClause.objects.create(name="بند مزامنة 1", is_active=True)
        self.cl2 = AgreementClause.objects.create(name="بند مزامنة 2", is_active=True)
        self.work = WorkAssignment.objects.create(
            title="متابعة شراكة المزامنة",
            target_model="partnerships.partnership",
            target_key=self.partnership.pk,
            employee=self.emp,
            manager=self.mgr,
            created_by=self.admin,
            status=WorkStatus.NEW,
            progress=0,
            due_on=riyadh_today() + timedelta(days=5),
        )
        self.work.assignees.set([self.emp])

    def test_status_and_progress_auto_transition_with_clause_changes(self):
        ca1 = ClauseAssignment.objects.create(clause=self.cl1, partnership=self.partnership, responsibility=Responsibility.INSTITUTION, progress=0)
        ca2 = ClauseAssignment.objects.create(clause=self.cl2, partnership=self.partnership, responsibility=Responsibility.PARTNER, progress=0)
        self.work.refresh_from_db()
        self.assertEqual((self.work.status, self.work.progress), (WorkStatus.NEW, 0))

        ca1.progress = 50
        ca1.save()
        self.work.refresh_from_db()
        self.assertEqual((self.work.status, self.work.progress), (WorkStatus.RUNNING, 25))

        ca1.progress = 100
        ca1.save()
        ca2.progress = 99
        ca2.save()
        self.work.refresh_from_db()
        self.assertEqual((self.work.status, self.work.progress), (WorkStatus.RUNNING, 99))

        ca2.progress = 100
        ca2.save()
        self.work.refresh_from_db()
        self.assertEqual((self.work.status, self.work.progress), (WorkStatus.COMPLETE, 100))

        ca2.progress = 60
        ca2.save()
        self.work.refresh_from_db()
        self.assertEqual((self.work.status, self.work.progress), (WorkStatus.RUNNING, 80))

        ca1.delete()
        ca2.delete()
        self.work.refresh_from_db()
        self.assertEqual((self.work.status, self.work.progress), (WorkStatus.NEW, 0))

    def test_cancelled_work_is_never_overwritten_by_clause_sync(self):
        self.work.status = WorkStatus.CANCELLED
        self.work.progress = 10
        self.work.save(update_fields=["status", "progress"])
        ClauseAssignment.objects.create(clause=self.cl1, partnership=self.partnership, responsibility=Responsibility.SHARED, progress=100)
        self.work.refresh_from_db()
        self.assertEqual((self.work.status, self.work.progress), (WorkStatus.CANCELLED, 10))

    def test_overdue_badge_and_filter_on_work_list_clears_at_100(self):
        self.work.due_on = riyadh_today() - timedelta(days=2)
        self.work.save(update_fields=["due_on"])
        ca1 = ClauseAssignment.objects.create(clause=self.cl1, partnership=self.partnership, responsibility=Responsibility.INSTITUTION, progress=40)
        self.work.refresh_from_db()
        self.assertTrue(is_work_overdue(self.work))

        self.client.force_login(self.admin, backend=AUTH_BACKEND)
        res = self.client.get(reverse("makken_mail:work_index"), {"status": "overdue"})
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "متابعة شراكة المزامنة")
        self.assertContains(res, "is-danger")

        ca1.progress = 100
        ca1.save()
        self.work.refresh_from_db()
        self.assertFalse(is_work_overdue(self.work))
        res2 = self.client.get(reverse("makken_mail:work_index"), {"status": "overdue"})
        self.assertNotContains(res2, "متابعة شراكة المزامنة")
