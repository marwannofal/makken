from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import translation

from agreement_clauses.models import AgreementOption
from care_states.models import DevelopmentState
from entities.models import Entity
from partnerships.models import Partnership, SponsorRegistrationRequest
from partnerships.templatetags.partnership_states import sar_money


class WillingnessColumnsAndMoneyFormattingTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser("admin_money_cols", "admin@example.com", "StrongPass!123")
        self.client.force_login(self.user)
        self.entity = Entity.objects.create(name="كيان اختبار", entity_type="non_government", branch="private_large", is_active=True)
        self.status_active = AgreementOption.objects.filter(kind="status", name="مستمرة").first() or AgreementOption.objects.create(kind="status", name="مستمرة", is_active=True)

        self.p_cap = Partnership.objects.create(
            name="شركة القدرة للاختبار",
            representative="ممثل القدرة",
            phone_country="SA",
            phone="+966550001111",
            email="cap@demo.sa",
            entity=self.entity,
            scope="local",
            development_state_id=DevelopmentState.CAPABILITY,
            financial_capacity=Decimal("1500000.00"),
        )
        self.p_will = Partnership.objects.create(
            name="شركة الرغبة للاختبار",
            representative="ممثل الرغبة",
            phone_country="SA",
            phone="+966550002222",
            email="will@demo.sa",
            entity=self.entity,
            scope="global",
            development_state_id=DevelopmentState.WILLINGNESS,
            financial_capacity=Decimal("1800000.00"),
            starts_on=date(2026, 1, 15),
            ends_on=date(2027, 1, 15),
            partnership_status=self.status_active,
        )

    def test_sar_money_formats_with_commas_in_arabic_locale(self):
        with translation.override("ar"):
            self.assertEqual(sar_money(Decimal("1500000.00")), "1,500,000.00")
            self.assertEqual(sar_money(Decimal("355550000.00")), "355,550,000.00")

    def test_willingness_table_shows_dates_status_tooltip_and_formatted_money(self):
        with translation.override("ar"):
            res = self.client.get(reverse("partnerships:willingness_index"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "تاريخ البداية")
        self.assertContains(res, "تاريخ النهاية")
        self.assertContains(res, "حالة الشراكة")
        self.assertContains(res, "15/01/2026")
        self.assertContains(res, "15/01/2027")
        self.assertContains(res, "mk-pstatus-pill is-active")
        self.assertContains(res, "مستمرة")
        self.assertContains(res, "mk-contact-tip-box")
        self.assertContains(res, "+966550002222")
        self.assertContains(res, "will@demo.sa")
        self.assertContains(res, "1,800,000.00")
        self.assertNotContains(res, '<th scope="col">هاتف التواصل</th>')
        self.assertNotContains(res, '<th scope="col">البريد الإلكتروني</th>')

    def test_capability_and_all_keep_contact_columns_and_format_money(self):
        with translation.override("ar"):
            cap = self.client.get(reverse("partnerships:capability_index"))
            all_res = self.client.get(reverse("partnerships:all_index"))
        for res in (cap, all_res):
            self.assertEqual(res.status_code, 200)
            self.assertContains(res, '<th scope="col">هاتف التواصل</th>')
            self.assertContains(res, '<th scope="col">البريد الإلكتروني</th>')
            self.assertContains(res, "1,500,000.00")

    def test_sponsor_request_detail_formats_financial_capacity(self):
        req = SponsorRegistrationRequest.objects.create(
            name="شركة طلب خارجي",
            representative="م. خالد",
            phone="+962798700954",
            email="ext@demo.sa",
            entity=self.entity,
            scope="local",
            financial_capacity=Decimal("1000000.00"),
        )
        with translation.override("ar"):
            res = self.client.get(reverse("partnerships:sponsor_request_review", args=[req.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "1,000,000.00")
