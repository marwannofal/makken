"""Run against MySQL 8.4, not SQLite, to exercise actual row locks."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.db import close_old_connections, connection, OperationalError
from django.test import TransactionTestCase, skipUnlessDBFeature
from market_needs.tests.test_market import MarketFixtures
from market_needs import services
from market_needs.models import Need, Sponsorship, SponsorshipAllocation


@skipUnlessDBFeature('has_select_for_update')
class ApprovalConcurrencyTests(MarketFixtures,TransactionTestCase):
    # TransactionTestCase does not invoke setUpTestData.
    def setUp(self):
        self.setUpTestData();super().setUp()

    def test_simultaneous_approvals_cannot_overfund(self):
        need=self.create_need();one=self.attach(need,self.organization());two=self.attach(need,self.organization('جهة متزامنة'))
        version=need.version;actor=self.user;barrier=Barrier(2)
        def worker(record):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                lines=list(need.expense_lines.order_by('position'))
                services.followup(need.pk,version,record.pk,record.version,'approve',{'amount':'75',f'allocation_{lines[0].pk}':'60',f'allocation_{lines[1].pk}':'15'}, {},actor)
                return 'saved'
            except (services.Conflict,OperationalError):
                return 'conflict'
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(worker,[one,two]))
        self.assertEqual(results.count('saved'),1)
        need.refresh_from_db();self.assertEqual(need.approved_support,75);self.assertLessEqual(need.approved_support,need.total_cost)
        self.assertEqual(Sponsorship.objects.filter(need=need,status='approved').count(),1)

    def test_simultaneous_partial_approvals_cannot_overfund_one_expense(self):
        need=self.create_need();one=self.attach(need,self.organization());two=self.attach(need,self.organization('جهة متزامنة لبند'))
        version=need.version;actor=self.user;barrier=Barrier(2);line=need.expense_lines.first()
        def worker(record):
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                services.followup(need.pk,version,record.pk,record.version,'approve',{'support_percent':'40',f'allocation_{line.pk}':'40'}, {},actor)
                return 'saved'
            except (services.Conflict,OperationalError):
                return 'conflict'
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results=list(executor.map(worker,[one,two]))
        self.assertEqual(results.count('saved'),1)
        need.refresh_from_db();self.assertEqual(need.approved_support,40)
        self.assertEqual(sum(SponsorshipAllocation.objects.filter(expense_line=line).values_list('amount',flat=True)),40)
