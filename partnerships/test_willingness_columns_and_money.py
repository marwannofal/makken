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

    def test_unified_dates_removed_from_section1_and_computed_from_starts_on(self):
        from partnerships.willingness_workflow import WillingnessDetailsForm, apply_willingness_details
        cap_create = self.client.get(reverse("partnerships:create"))
        self.assertEqual(cap_create.status_code, 200)
        self.assertNotContains(cap_create, "مدة الشراكة")
        self.assertNotContains(cap_create, "id_partnership_date")
        self.assertNotContains(cap_create, "mk-term-row-4")

        will_edit = self.client.get(reverse("partnerships:edit", args=[self.p_will.pk]))
        self.assertEqual(will_edit.status_code, 200)
        self.assertNotContains(will_edit, "<h3>مدة الشراكة</h3>")
        self.assertNotContains(will_edit, "id_partnership_date")
        self.assertContains(will_edit, "mk-term-row-4")
        self.assertContains(will_edit, "تاريخ توقيع الشراكة")
        self.assertContains(will_edit, "تاريخ بداية الشراكة")
        self.assertContains(will_edit, "مدة الشراكة بالأشهر")

        # Separate signed_on vs starts_on + auto ends_on
        form = WillingnessDetailsForm(
            data={"signed_on": "2026-03-10", "starts_on": "2026-02-01", "duration_months": "18"},
            partnership=self.p_will,
        )
        self.assertTrue(form.is_valid(), form.errors)
        apply_willingness_details(self.p_will, form.cleaned_data)
        self.p_will.save()
        self.p_will.refresh_from_db()
        self.assertEqual(self.p_will.signed_on, date(2026, 3, 10))
        self.assertEqual(self.p_will.starts_on, date(2026, 2, 1))
        self.assertEqual(self.p_will.ends_on, date(2027, 8, 1))

        # starts_on without duration_months is rejected cleanly
        bad = WillingnessDetailsForm(data={"starts_on": "2026-02-01", "duration_months": ""}, partnership=self.p_will)
        self.assertFalse(bad.is_valid())
        self.assertIn("duration_months", bad.errors)
