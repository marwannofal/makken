from decimal import Decimal
from django.test import SimpleTestCase
from core.templatetags.dashboard_tags import progress_tone


class ProgressToneFilterTests(SimpleTestCase):
    def test_thresholds(self):
        self.assertEqual(progress_tone(0), "mk-pct-low")
        self.assertEqual(progress_tone(Decimal("49.99")), "mk-pct-low")
        self.assertEqual(progress_tone("49.5%"), "mk-pct-low")
        self.assertEqual(progress_tone(50), "mk-pct-high")
        self.assertEqual(progress_tone(Decimal("50.00")), "mk-pct-high")
        self.assertEqual(progress_tone(100), "mk-pct-high")
        self.assertEqual(progress_tone(None), "")
