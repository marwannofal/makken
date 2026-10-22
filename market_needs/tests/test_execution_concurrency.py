"""Actual InnoDB lock checks; deliberately skipped on SQLite."""
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections, OperationalError
from django.test import TransactionTestCase, skipUnlessDBFeature
from access_control.defaults import initialize
from .test_market import MarketFixtures
from . import test_execution
from market_needs.execution_services import save_execution, ExecutionConflict
from market_needs.models import NeedExecution


@skipUnlessDBFeature("has_select_for_update")
class ExecutionConcurrencyTests(MarketFixtures, TransactionTestCase):
    funded = test_execution.ExecutionTests.funded
    provider = test_execution.ExecutionTests.provider

    def setUp(self):
        initialize()
        self.setUpTestData()
        super().setUp()

    def test_simultaneous_creation_completion_and_stale_update(self):
        need = self.funded()
        provider = self.provider()
        barrier = Barrier(2)
        def worker(status):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                save_execution(need_id=need.pk, expected_version=0, expected_need_version=need.version,
                    nonce=uuid.uuid4(), data={"providers": [provider.pk], "employers": [], "status": status}, actor=self.user)
                return "saved"
            except (ExecutionConflict, OperationalError):
                return "conflict"
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, ["complete", "running"]))
        self.assertEqual(results.count("saved"), 1)
        execution = NeedExecution.objects.get(need=need)
        self.assertEqual(execution.version, 1)
        self.assertEqual(execution.provider_links.count(), 1)
        self.assertEqual(need.events.filter(action__startswith="تنفيذ البرنامج").count(), 1)
