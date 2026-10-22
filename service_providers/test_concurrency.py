# MAKKEN RBAC BUSINESS FIXTURES v1
# MAKKEN RBAC INTEGRATION v1
from concurrent.futures import ThreadPoolExecutor
import json
from tempfile import TemporaryDirectory
from threading import Barrier
import uuid
from unittest import skipUnless
from django.contrib.auth import get_user_model
from django.db import connection, close_old_connections
from django.test import TransactionTestCase, override_settings
from care_states.models import StateColor
from entities.models import Entity
from regions.models import Region
from sectors.models import Sector
from specializations.models import Specialization
from sponsorship_shapes.models import SponsorshipShape
from .models import ProviderAudit
from .services import save_provider, row_action, Conflict


@skipUnless(connection.vendor == 'mysql', 'Requires real MySQL row locks; run compose.providers-tests.yaml.')
class ProviderConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user(username='provider-concurrency', is_superuser=True)
        self.region=Region.objects.create(name='منطقة اختبار التزامن')
        sector=Sector.objects.create(name='قطاع اختبار التزامن')
        self.spec=Specialization.objects.create(name='تخصص اختبار التزامن',sector=sector)
        self.shape=SponsorshipShape.objects.create(name='شكل رعاية اختبار التزامن')
        self.entity=Entity.objects.create(name='كيان اختبار التزامن',entity_type='government',branch='')
        StateColor.objects.update_or_create(state='willingness',defaults={'color':'#24b3af'})
        from training_programs.models import TrainingProgram
        program=TrainingProgram.objects.create(name='برنامج اختبار التزامن',category='qualifying_program')
        data={'program':program.pk,'name':'مزود اختبار التزامن','representative':'ممثل المزود','phone_country':'SA','phone':'0501234567','email':'parallel@example.com','provider_type':'government','scope':'local','is_active':'1','coverage':json.dumps([{'region':self.region.pk,'specializations':[self.spec.pk],'is_active':True}])}
        self.item=save_provider({'id':None,'nonce':str(uuid.uuid4()),'data':data},self.user)
        self.folder=TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        setting=override_settings(MAKKEN_PRIVATE_UPLOAD_ROOT=self.folder.name);setting.enable();self.addCleanup(setting.disable)

    def parallel(self, action):
        barrier=Barrier(2)
        def run():
            close_old_connections()
            try:
                user=get_user_model().objects.get(pk=self.user.pk)
                barrier.wait(timeout=15)
                return action(user)
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks=[pool.submit(run),pool.submit(run)]
            return [task.result(timeout=40) for task in tasks]

    def test_simultaneous_status_updates_allow_only_one_version(self):
        def action(user):
            try:
                row_action({'id':self.item.pk,'version':1,'operation':'toggle'},user)
                return 'saved'
            except Conflict:
                return 'stale'
        self.assertCountEqual(self.parallel(action),['saved','stale'])
        self.item.refresh_from_db();self.assertEqual(self.item.version,2);self.assertFalse(self.item.is_active)
        self.assertEqual(ProviderAudit.objects.filter(action='toggle').count(),1)

