"""One-time, confirmed capability -> willingness transitions."""
from datetime import datetime, timezone as utc
from io import BytesIO
from tempfile import TemporaryDirectory
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from pypdf import PdfWriter
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
from django.db import IntegrityError
from django.test import Client, TestCase
from care_states.models import StateColor
from . import tests as fixtures
from .models import Partnership
from .views import _sign


class DevelopmentTransitionTests(TestCase):
    setUpTestData = classmethod(fixtures.PartnershipTests.setUpTestData.__func__)
    data = fixtures.PartnershipTests.data
    preview = fixtures.PartnershipTests.preview
    save = fixtures.PartnershipTests.save

    def setUp(self):
        private = TemporaryDirectory()
        self.addCleanup(private.cleanup)
        settings_override = override_settings(MAKKEN_PRIVATE_UPLOAD_ROOT=private.name)
        settings_override.enable()
        self.addCleanup(settings_override.disable)
        self.client.force_login(self.user)
        self.item, _ = self.save()
        self.original = self.item.development_state_at
        self.url = '/partnerships/?status=1&capacity_min=100&capacity_max=200000'

    def transition_preview(self):
        row = self.client.get(self.url).context['rows'][0]
        self.assertTrue(row['advance'])
        response = self.client.post(self.url, {'action':'preview','token':row['advance']})
        self.assertEqual(response.status_code,200)
        return response.context['pending']['token']

    def confirm(self, token=None):
        writer = PdfWriter(); writer.add_blank_page(width=100,height=100)
        data = BytesIO(); writer.write(data)
        return self.client.post(self.url, {'action':'confirm','token':token or self.transition_preview(), 'agreement_type':'official_letter', 'attachments':[SimpleUploadedFile('agreement.pdf',data.getvalue(),content_type='application/pdf')]})

    def test_preview_cancel_and_get_do_not_write(self):
        token = self.transition_preview()
        self.client.get(self.url+'&action=confirm&token='+token)
        self.item.refresh_from_db()
        self.assertEqual(self.item.development_state_id,'capability')
        self.assertEqual(self.item.development_state_at,self.original)
        self.assertEqual(self.item.development_history.count(),1)

    def test_confirm_exact_date_original_history_and_filters(self):
        token = self.transition_preview()
        entered = datetime(2026,10,17,7,15,45,tzinfo=utc.utc)
        with patch('partnerships.views.timezone.now',return_value=entered):
            response = self.confirm(token)
        self.assertEqual(response.status_code,302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.development_state_id,'willingness')
        self.assertEqual(self.item.development_state_at,entered)
        self.assertEqual(self.item.version,2)
        self.assertEqual(self.item.development_history.get(state_id='willingness').entered_at,entered)
        self.assertEqual(self.item.development_history.get(state_id='capability').entered_at,self.original)
        self.assertEqual(parse_qs(urlparse(response.url).query)['capacity_min'],['100'])
        detail = self.client.get('/partnerships/',{'detail':self.item.pk})
        self.assertContains(detail,'2026/10/17 10:15:45')
        self.assertEqual(next(s for s in detail.context['history'] if s['current'])['label'],'رغبة')

    def test_replay_and_fresh_willingness_request_are_rejected(self):
        token = self.transition_preview()
        self.assertEqual(self.confirm(token).status_code,302)
        self.assertEqual(self.confirm(token).status_code,409)
        self.item.refresh_from_db()
        fresh = _sign({'kind':'row','id':self.item.pk,'version':self.item.version,'operation':'advance'},self.user)
        self.assertEqual(self.client.post(self.url,{'action':'preview','token':fresh}).status_code,409)
        self.assertIsNone(self.client.get(self.url).context['rows'][0]['advance'])
        self.assertEqual(self.item.development_history.filter(state_id='willingness').count(),1)

    def test_stale_confirmation_rejected(self):
        token = self.transition_preview()
        Partnership.objects.filter(pk=self.item.pk).update(version=2)
        self.assertEqual(self.confirm(token).status_code,409)
        self.assertFalse(self.item.development_history.filter(state_id='willingness').exists())

    def test_forged_cross_user_and_wrong_phase_rejected(self):
        token = self.transition_preview()
        self.assertEqual(self.confirm(token+'tamper').status_code,400)
        self.client.force_login(self.other)
        self.assertEqual(self.confirm(token).status_code,400)
        self.client.force_login(self.user)
        row = self.client.get(self.url).context['rows'][0]
        self.assertEqual(self.confirm(row['advance']).status_code,400)

    def test_other_state_and_missing_target_rejected(self):
        token = self.transition_preview()
        Partnership.objects.filter(pk=self.item.pk).update(development_state_id='care')
        self.assertEqual(self.confirm(token).status_code,409)
        Partnership.objects.filter(pk=self.item.pk).update(development_state_id='capability')
        StateColor.objects.filter(pk='willingness').delete()
        self.assertEqual(self.confirm(token).status_code,409)
        self.assertFalse(self.item.development_history.filter(state_id='willingness').exists())

    def test_atomic_rollback_on_state_save_failure(self):
        token = self.transition_preview()
        with patch.object(Partnership,'save',side_effect=IntegrityError('simulated conflict')):
            self.assertEqual(self.confirm(token).status_code,409)
        self.item.refresh_from_db()
        self.assertEqual(self.item.development_state_id,'capability')
        self.assertFalse(self.item.development_history.filter(state_id='willingness').exists())

    def test_legacy_original_date_is_preserved(self):
        self.item.development_history.all().delete()
        self.assertEqual(self.confirm().status_code,302)
        self.assertEqual(self.item.development_history.get(state_id='capability').entered_at,self.original)

    def test_login_and_csrf_required(self):
        self.assertEqual(Client().post(self.url,{'action':'confirm','token':'x'}).status_code,302)
        secure = Client(enforce_csrf_checks=True)
        secure.force_login(self.user)
        self.assertEqual(secure.post(self.url,{'action':'preview','token':'x'}).status_code,403)

    def test_editor_save_preserves_both_entry_dates(self):
        self.assertEqual(self.confirm().status_code,302)
        self.item.refresh_from_db()
        entered = self.item.development_state_at
        dates = list(self.item.development_history.values_list('state_id','entered_at'))
        path = f'/partnerships/{self.item.pk}/edit/'
        preview = self.preview(path,representative='ممثل جديد')
        self.assertEqual(preview.status_code,200,preview.context['form'].errors)
        self.assertEqual(self.client.post(path,{'action':'confirm','token':preview.context['pending']['token']}).status_code,302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.development_state_id,'willingness')
        self.assertEqual(self.item.development_state_at,entered)
        self.assertEqual(list(self.item.development_history.values_list('state_id','entered_at')),dates)
