"""Real InnoDB checks: a region revocation and a business write serialize."""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from threading import Event
import uuid
from django.db import connections, close_old_connections, transaction
from django.core.exceptions import PermissionDenied
from django.test import TransactionTestCase, skipUnlessDBFeature
from django.contrib.auth import get_user_model
from access_control.models import UserAccess, RoleProfile
from access_control.defaults import initialize
from access_control.services import save_user, fingerprint
from access_control.regions import regional_transaction
from market_needs.tests.test_market import MarketFixtures
from market_needs import services
from market_needs.models import Need


@skipUnlessDBFeature('has_select_for_update')
class RegionalRevocationConcurrencyTests(MarketFixtures, TransactionTestCase):
    def setUp(self):
        initialize()
        MarketFixtures.setUpTestData.__func__(type(self))
        MarketFixtures.setUp(self)
        self.editor=get_user_model().objects.create_user('regional-concurrent',email='region-concurrent@example.com')
        self.role=RoleProfile.objects.get(system_key='editor')
        self.editor.groups.add(self.role.group)
        self.access=UserAccess.objects.create(user=self.editor,page_scope='all',region_scope='selected')
        self.access.allowed_regions.add(self.region)
        self.expected=fingerprint(self.editor,'user')
        self.new_scope={'snapshot':'checked','username':self.editor.username,'full_name':'مستخدم المناطق','email':self.editor.email,'is_active':'1','page_scope':'all','roles':[str(self.role.pk)],'region_scope':'selected','allowed_regions':[str(self.region2.pk)]}

    def worker(self,function):
        close_old_connections()
        try:return function()
        finally:connections.close_all()

    def write(self,title):
        return services.save_need(self.data(title=title,regions=[str(self.region.pk)]),get_user_model().objects.get(pk=self.editor.pk),nonce=uuid.uuid4())

    def test_revocation_commits_first_and_queued_write_is_denied(self):
        locked, release, attempted = Event(),Event(),Event()
        def revoke():
            with transaction.atomic():
                UserAccess.objects.select_for_update().get(pk=self.access.pk)
                save_user(self.user,self.new_scope,self.editor.pk,self.expected)
                locked.set()
                if not release.wait(10):raise AssertionError('Timed out waiting to release revocation')
        def business():
            attempted.set()
            try:self.write('MUST_NOT_EXIST')
            except PermissionDenied:return 'denied'
            return 'unexpected-write'
        with ThreadPoolExecutor(max_workers=2) as pool:
            admin=pool.submit(self.worker,revoke)
            try:
                self.assertTrue(locked.wait(10))
                write=pool.submit(self.worker,business);self.assertTrue(attempted.wait(5))
                with self.assertRaises(TimeoutError):write.result(timeout=.25)
            finally:release.set()
            admin.result(timeout=10);self.assertEqual(write.result(timeout=10),'denied')
        self.assertFalse(Need.objects.filter(title='MUST_NOT_EXIST').exists())

    def test_authorized_write_commits_first_then_new_requests_lose_access(self):
        locked,release,attempted=Event(),Event(),Event()
        def business():
            with regional_transaction(self.editor):
                self.write('AUTHORIZED_BEFORE_REVOCATION')
                locked.set()
                if not release.wait(10):raise AssertionError('Timed out waiting to release writer')
        def revoke():
            attempted.set()
            save_user(self.user,self.new_scope,self.editor.pk,self.expected)
        with ThreadPoolExecutor(max_workers=2) as pool:
            write=pool.submit(self.worker,business)
            try:
                self.assertTrue(locked.wait(10))
                admin=pool.submit(self.worker,revoke);self.assertTrue(attempted.wait(5))
                with self.assertRaises(TimeoutError):admin.result(timeout=.25)
            finally:release.set()
            write.result(timeout=10);admin.result(timeout=10)
        self.assertTrue(Need.objects.filter(title='AUTHORIZED_BEFORE_REVOCATION').exists())
        with self.assertRaises(PermissionDenied):self.write('DENIED_AFTER_REVOCATION')
