"""Unit tests for seeding the 64 Saudi capability (قدرة) partner organizations."""
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from care_states.models import DevelopmentState
from entities.models import EntityBranch, EntityType
from partnerships.models import DevelopmentHistory, Partnership


class SeedSaudiCapabilityPartnersTests(TestCase):
    def test_seed_command_creates_all_64_capability_partners_and_is_idempotent(self):
        out1 = StringIO()
        call_command("seed_saudi_capability_partners", stdout=out1)
        self.assertIn("created=64", out1.getvalue())
        self.assertEqual(Partnership.objects.filter(development_state_id=DevelopmentState.CAPABILITY).count(), 64)

        moh = Partnership.objects.get(name="وزارة الصحة")
        self.assertEqual(moh.entity.entity_type, EntityType.GOVERNMENT)
        self.assertEqual(moh.email, "937@moh.gov.sa")
        self.assertEqual(moh.phone, "937")
        self.assertEqual(moh.financial_capacity, Decimal("1000000.00"))
        self.assertTrue(DevelopmentHistory.objects.filter(partnership=moh, state_id=DevelopmentState.CAPABILITY).exists())

        aramco = Partnership.objects.get(name="شركة أرامكو السعودية")
        self.assertEqual(aramco.entity.entity_type, EntityType.NON_GOVERNMENT)
        self.assertEqual(aramco.entity.branch, EntityBranch.PRIVATE_LARGE)
        self.assertEqual(aramco.phone, "+966138720115")
        self.assertEqual(aramco.email, "investor.relations@aramco.com")

        out2 = StringIO()
        call_command("seed_saudi_capability_partners", stdout=out2)
        self.assertIn("created=0, skipped_existing=64", out2.getvalue())
        self.assertEqual(Partnership.objects.count(), 64)
