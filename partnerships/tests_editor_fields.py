import json
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.test import TestCase
from entities.models import Entity, EntityType
from sectors.models import Sector
from specializations.models import Specialization
from sponsorship_shapes.models import SponsorshipShape
from .forms import PartnershipForm
from .models import Partnership


class EditorFieldTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="editor-field-user")
        cls.government = Entity.objects.filter(entity_type=EntityType.GOVERNMENT, is_active=True).first()
        cls.private = Entity.objects.filter(branch="private_large").first()
        cls.sector = Sector.objects.create(name="قطاع فحص حقول الجهة")
        cls.spec = Specialization.objects.create(name="تخصص فحص حقول الجهة", sector=cls.sector)
        cls.shape = SponsorshipShape.objects.create(name="رعاية فحص حقول الجهة")

    def data(self, **changes):
        data = {"name": "جهة فحص الحقول", "representative": "ممثل الجهة", "phone_country": "SA", "phone": "0501234567", "email": "fields@example.com", "financial_capacity": "1,000,000", "entity_type": "government", "scope": "local", "is_active": "1", "offerings": json.dumps([{"sector": self.sector.pk, "specializations": [self.spec.pk], "shape": self.shape.pk, "is_active": True}])}
        data.update(changes)
        return data

    def test_government_works_without_entity_input(self):
        form = PartnershipForm(self.data())
        self.assertFalse(form.show_entity)
        self.assertFalse(form.fields["entity"].required)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["entity"], self.government)
        self.assertEqual(form.cleaned_data["financial_capacity"], Decimal("1000000"))

    def test_private_entity_required_and_correct_type(self):
        for value in ["", self.government.pk, "999999999"]:
            form = PartnershipForm(self.data(entity_type="non_government", entity=value))
            self.assertTrue(form.show_entity)
            self.assertFalse(form.is_valid())
            self.assertIn("entity", form.errors)
        form = PartnershipForm(self.data(entity_type="non_government", entity=self.private.pk))
        self.assertTrue(form.is_valid(), form.errors)

    def test_missing_active_government_is_clear_error_without_creating_entities(self):
        Entity.objects.filter(entity_type="government").update(is_active=False)
        count = Entity.objects.count()
        form = PartnershipForm(self.data())
        self.assertFalse(form.is_valid())
        self.assertIn("entity_type", form.errors)
        self.assertEqual(Entity.objects.count(), count)

    def test_existing_inactive_government_reference_is_preserved(self):
        legacy = Entity.objects.create(name="كيان حكومي سابق", entity_type="government", is_active=False)
        item = Partnership.objects.create(name="جهة سابقة للفحص", representative="ممثل", phone_country="SA", phone="+966501234567", email="old@example.com", entity=legacy, scope="local")
        form = PartnershipForm(self.data(), instance=item)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["entity"], legacy)

    def test_new_inactive_private_selection_is_rejected(self):
        self.private.is_active = False; self.private.save()
        self.assertFalse(PartnershipForm(self.data(entity_type="non_government", entity=self.private.pk)).is_valid())

    def test_comma_grouping_and_decimal_integrity_remain_server_validated(self):
        for raw, expected in [("125,000", "125000"), ("999,999,999,999.99", "999999999999.99"), ("١٬٢٥٠٫٥٠", "1250.50")]:
            form = PartnershipForm(self.data(financial_capacity=raw))
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data["financial_capacity"], Decimal(expected))
        for raw in ["1,20", "1,000.001", "-1", "1e6"]:
            self.assertFalse(PartnershipForm(self.data(financial_capacity=raw)).is_valid())

    def test_preview_confirm_without_government_entity_saves_exact_amount_and_replay_safe(self):
        self.client.force_login(self.user)
        snapshot = self.client.get("/partnerships/new/").context["snapshot"]
        preview = self.client.post("/partnerships/new/", {**self.data(), "action": "preview", "snapshot": snapshot})
        self.assertEqual(preview.status_code, 200)
        token = preview.context["pending"]["token"]
        result = self.client.post("/partnerships/new/", {"action": "confirm", "token": token})
        self.assertEqual(result.status_code, 302)
        item = Partnership.objects.get(name="جهة فحص الحقول")
        self.assertEqual(item.entity_id, self.government.pk)
        self.assertEqual(item.financial_capacity, Decimal("1000000.00"))
        before = item.development_state_at
        self.client.post("/partnerships/new/", {"action": "confirm", "token": token})
        item.refresh_from_db()
        self.assertEqual(item.development_state_at, before)
        self.assertEqual(Partnership.objects.filter(pk=item.pk).count(), 1)
