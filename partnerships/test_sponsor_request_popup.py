"""Tests verifying /partnerships/requests/<id>/ and ?detail=<id> use the Ocean-Blue detail-dialog popup."""
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from entities.models import Entity
from partnerships.models import SponsorRegistrationRequest, SponsorRequestStatus


class SponsorRequestPopupDesignTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_superuser(
            username="sr_popup_admin",
            email="sr_popup@makken.test",
            password="StrongPassword123!",
            first_name="Marwan",
        )
        self.entity = Entity.objects.create(name="جهة اختبار النافذة", entity_type="government", is_active=True)
        self.req = SponsorRegistrationRequest.objects.create(
            name="شركة المدار للاختبار",
            representative="م. خالد العتيبي",
            phone="+966501234567",
            email="almadar@test.local",
            entity=self.entity,
            scope="global",
            status=SponsorRequestStatus.NEW,
            notes="ملاحظات اختبار للنافذة المنبثقة",
        )
        self.client.force_login(self.admin)

    def test_direct_review_url_renders_ocean_blue_detail_dialog_popup(self):
        res = self.client.get(reverse("partnerships:sponsor_request_review", args=[self.req.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'id="sponsor-request-detail"')
        self.assertContains(res, 'class="partnership-dialog detail-dialog sr-detail-dialog"')
        self.assertContains(res, 'data-server-dialog')
        self.assertContains(res, 'class="detail-grid"')
        self.assertContains(res, 'class="detail-offerings"')
        self.assertContains(res, self.req.name)
        self.assertContains(res, "اعتماد وإنشاء الشراكة")
        self.assertContains(res, "رفض الطلب نهائيًا")

    def test_queue_detail_query_param_also_opens_popup(self):
        res = self.client.get(reverse("partnerships:sponsor_requests") + f"?detail={self.req.pk}")
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'id="sponsor-request-detail"')
        self.assertContains(res, self.req.name)
