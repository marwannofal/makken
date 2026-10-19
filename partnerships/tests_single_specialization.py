# MAKKEN RBAC BUSINESS FIXTURES v1
# MAKKEN RBAC INTEGRATION v1
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from entities.models import Entity
from sectors.models import Sector
from specializations.models import Specialization
from sponsorship_shapes.models import SponsorshipShape
from .forms import PartnershipForm
from .models import Partnership, PartnershipOffering


class SingleSpecializationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username="single-specialty-user", is_superuser=True)
        cls.entity = Entity.objects.create(name="كيان الاختيار الفردي", entity_type="government")
        cls.sector = Sector.objects.create(name="قطاع الاختيار الفردي")
        cls.specs = [Specialization.objects.create(name=f"تخصص فردي {i}", sector=cls.sector) for i in range(3)]
        cls.shape = SponsorshipShape.objects.create(name="رعاية الاختيار الفردي")
        cls.other_shape = SponsorshipShape.objects.create(name="شكل رعاية آخر")
        cls.item = Partnership.objects.create(name="جهة سابقة متعددة التخصصات", representative="ممثل سابق", phone_country="SA", phone="+966501234567", email="legacy@example.com", entity=cls.entity, scope="local")
        cls.offering = PartnershipOffering.objects.create(partnership=cls.item, sector=cls.sector, sponsorship_shape=cls.shape)
        cls.offering.specializations.set(cls.specs[:2])

    def row(self, specs=None, **changes):
        row = {"sector": self.sector.pk, "specializations": [self.specs[0].pk] if specs is None else specs, "shape": self.shape.pk, "is_active": True}
        row.update(changes)
        return row

    def data(self, rows):
        return {"name": "جهة اختيار واحد", "representative": "ممثل الاختبار", "phone_country": "SA", "phone": "0501234567", "email": "single@example.com", "entity_type": "government", "entity": self.entity.pk, "scope": "local", "is_active": "1", "financial_capacity": "1000", "offerings": json.dumps(rows)}

    def test_one_required_and_multiple_rejected_for_new_records(self):
        self.assertTrue(PartnershipForm(self.data([self.row()])).is_valid())
        for specs in [[], [self.specs[0].pk, self.specs[1].pk], [True], [str(self.specs[0].pk)]]:
            with self.subTest(specs=specs):
                form = PartnershipForm(self.data([self.row(specs)]))
                self.assertFalse(form.is_valid())
                self.assertIn("offerings", form.errors)

    def test_unchanged_legacy_preserved_including_status_change(self):
        for active in [True, False]:
            form = PartnershipForm(self.data([self.row([s.pk for s in self.specs[:2]], is_active=active)]), instance=self.item)
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(len(form.cleaned_data["offerings"][0]["specializations"]), 2)

    def test_legacy_cannot_add_or_substitute_multiple_specialties(self):
        for row in [self.row([s.pk for s in self.specs]), self.row([self.specs[0].pk, self.specs[2].pk]), self.row([s.pk for s in self.specs[:2]], shape=self.other_shape.pk)]:
            self.assertFalse(PartnershipForm(self.data([row]), instance=self.item).is_valid())

    def test_separate_single_specialty_rows_allowed(self):
        form = PartnershipForm(self.data([self.row([s.pk]) for s in self.specs]))
        self.assertTrue(form.is_valid(), form.errors)

    def test_confirmed_legacy_edit_and_explicit_reduction(self):
        self.client.force_login(self.user)
        path = f"/partnerships/{self.item.pk}/edit/"
        before = self.item.development_state_at
        for specs in [[s.pk for s in self.specs[:2]], [self.specs[0].pk]]:
            snapshot = self.client.get(path).context["snapshot"]
            response = self.client.post(path, {**self.data([self.row(specs)]), "action": "preview", "snapshot": snapshot})
            self.assertEqual(response.status_code, 200)
            response = self.client.post(path, {"action": "confirm", "token": response.context["pending"]["token"]})
            self.assertEqual(response.status_code, 302)
            self.item.refresh_from_db()
            self.assertEqual(set(self.item.offerings.get().specializations.values_list("pk", flat=True)), set(specs))
            self.assertEqual(self.item.development_state_at, before)

    def test_forged_multiple_preview_rejected_without_database_write(self):
        self.client.force_login(self.user)
        path = "/partnerships/new/"
        snapshot = self.client.get(path).context["snapshot"]
        response = self.client.post(path, {**self.data([self.row([s.pk for s in self.specs[:2]])]), "action": "preview", "snapshot": snapshot})
        self.assertEqual(response.status_code, 400)
        self.assertIsNone(response.context["pending"])
        self.assertEqual(Partnership.objects.count(), 1)

    def test_editor_uses_required_single_selection(self):
        self.client.force_login(self.user)
        response = self.client.get("/partnerships/new/")
        self.assertContains(response, '<select id="offering-specializations" required>')
        self.assertNotContains(response, 'id="offering-specializations" required multiple')
        self.assertContains(response, "اختر تخصصًا واحدًا فقط")
