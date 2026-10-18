"""Exercise the real forward upgrade with existing organizations and funding."""
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

from partnerships.models import Partnership, DevelopmentHistory
from regions.models import Region
from market_needs.models import Need, Sponsorship, AuditEvent, SupportAttachment
from market_needs.tests.test_market import MarketFixtures


class CoverageRemovalMigrationTests(MarketFixtures, TransactionTestCase):
    def setUp(self):
        # Only the new removal migration is rolled back. Market data tables and
        # all other migrations stay in place. This class must not use TestCase's
        # enclosing transaction because MySQL DDL cannot be rolled back.
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([("partnerships", "0004_coverage_regions")])
        self.addCleanup(self.restore_latest_schema)
        self.setUpTestData()
        super().setUp()

    def restore_latest_schema(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_forward_removal_keeps_partnerships_card_regions_funding_and_history(self):
        need = self.create_need()
        organization = self.organization()
        record = self.attach(need, organization)
        self.approve(need, record, "25.00")
        evidence = SupportAttachment.objects.create(
            sponsorship=record, file="market-support/historical-evidence.pdf",
            original_name="historical-evidence.pdf", size=123,
            content_type="application/pdf", uploaded_by=self.user,
        )
        old_apps = self.executor.loader.project_state(
            [("partnerships", "0004_coverage_regions")]
        ).apps
        old_partnership = old_apps.get_model("partnerships", "Partnership")
        old_partnership.objects.get(pk=organization.pk).coverage_regions.add(self.region.pk)
        models = [Partnership, Need, Sponsorship, DevelopmentHistory, AuditEvent, SupportAttachment]
        snapshots = {model: list(model.objects.order_by("pk").values()) for model in models}
        region_ids = set(need.regions.values_list("pk", flat=True))

        self.restore_latest_schema()

        for model, before in snapshots.items():
            with self.subTest(model=model.__name__):
                self.assertEqual(list(model.objects.order_by("pk").values()), before)
        self.assertEqual(set(need.regions.values_list("pk", flat=True)), region_ids)
        self.assertTrue(Region.objects.filter(pk=self.region.pk).exists())
        self.assertTrue(SupportAttachment.objects.filter(pk=evidence.pk).exists())
        self.assertNotIn("partnerships_partnership_coverage_regions", connection.introspection.table_names())
        self.assertNotIn("coverage_regions", {field.name for field in Partnership._meta.get_fields()})
