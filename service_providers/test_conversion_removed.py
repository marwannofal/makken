# MAKKEN RBAC BUSINESS FIXTURES v1
# MAKKEN RBAC INTEGRATION v1
# MAKKEN DEPENDENCY TEST POLICY v1
from core.dependencies import DependencyBlocked
"""Conversion is unavailable; previous records and private evidence remain valid."""
from io import BytesIO
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs,urlparse
import uuid
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase,override_settings
from django.urls import NoReverseMatch,reverse
from django.utils import timezone
from PIL import Image
from entities.models import Entity
from care_states.models import StateColor
from partnerships.models import Partnership,DevelopmentHistory,WillingnessAttachment
from partnerships.willingness import save_supporting_files,validate_attachment
from . import forms,services,views
from .models import ServiceProvider,ProviderAudit


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ConversionRemovalTests(TestCase):
    def setUp(self):
        self.user=get_user_model().objects.create_user(username='provider-conversion-removed', is_superuser=True)
        self.client.force_login(self.user,backend='accounts.backends.EmailOrUsernameBackend')
        self.item=ServiceProvider.objects.create(name='مزود اختبار إلغاء التحويل',provider_type='government',scope='local')
        folder=TemporaryDirectory();self.addCleanup(folder.cleanup)
        setting=override_settings(MAKKEN_PRIVATE_UPLOAD_ROOT=folder.name);setting.enable();self.addCleanup(setting.disable)

    def test_entry_points_and_get_post_ajax_are_removed_without_side_effects(self):
        self.assertFalse(hasattr(forms,'ConversionForm'));self.assertFalse(hasattr(services,'convert_provider'));self.assertFalse(hasattr(views,'convert'))
        with self.assertRaises(NoReverseMatch):reverse('service_providers:convert',args=[self.item.pk])
        before=(ServiceProvider.objects.count(),Partnership.objects.count(),ProviderAudit.objects.count(),DevelopmentHistory.objects.count(),WillingnessAttachment.objects.count())
        url=f'/service-providers/{self.item.pk}/convert/'
        token=views.token({'operation':'convert','id':self.item.pk,'version':1,'nonce':str(uuid.uuid4())},self.user)
        self.assertEqual(self.client.get(url).status_code,404)
        self.assertEqual(self.client.post(url,{'snapshot':token}).status_code,404)
        self.assertEqual(self.client.post(url,{'snapshot':token},HTTP_X_REQUESTED_WITH='XMLHttpRequest').status_code,404)
        self.assertEqual(before,(ServiceProvider.objects.count(),Partnership.objects.count(),ProviderAudit.objects.count(),DevelopmentHistory.objects.count(),WillingnessAttachment.objects.count()))

    def test_controls_removed_from_list_details_editor_and_javascript(self):
        for url in [reverse('service_providers:index'),reverse('service_providers:index')+f'?detail={self.item.pk}',reverse('service_providers:create'),reverse('service_providers:edit',args=[self.item.pk])]:
            response=self.client.get(url);self.assertEqual(response.status_code,200)
            for text in ['تحويلها لراغبة','data-provider-conversion','/convert/','تُستكمل عند التحويل']:self.assertNotContains(response,text)
        from pathlib import Path
        source=Path(__file__).parent.joinpath('static/service_providers/providers.js').read_text()
        self.assertNotIn('data-provider-conversion',source);self.assertNotIn('XMLHttpRequest',source)

    def test_old_actions_cannot_create_a_partnership(self):
        for url in [reverse('service_providers:index'),reverse('service_providers:edit',args=[self.item.pk])]:
            self.assertEqual(self.client.post(url,{'action':'convert','operation':'convert','id':self.item.pk}).status_code,400)
        self.assertFalse(Partnership.objects.exists());self.item.refresh_from_db();self.assertIsNone(self.item.converted_partnership_id)

    def test_historical_relationship_evidence_timestamps_and_history_preserved(self):
        entity=Entity.objects.create(name='كيان شراكة سابقة',entity_type='government',branch='')
        StateColor.objects.update_or_create(state='willingness',defaults={'color':'#24b3af'})
        now=timezone.now()
        partner=Partnership.objects.create(name='شراكة سابقة محفوظة',representative='ممثل الجهة',phone='+966501234567',email='old@example.test',entity=entity,scope='local',development_state_id='willingness',development_state_at=now)
        history=DevelopmentHistory.objects.create(partnership=partner,state_id='willingness',entered_at=now)
        self.item.converted_partnership=partner;self.item.converted_at=now;self.item.save()
        event=ProviderAudit.objects.create(provider=self.item,provider_key=self.item.pk,provider_name=self.item.name,action='convert',actor=self.user,actor_name=self.user.username,after={'partnership':partner.pk})
        stream=BytesIO();Image.new('RGB',(4,4),'white').save(stream,'PNG')
        upload=validate_attachment(SimpleUploadedFile('old.png',stream.getvalue(),content_type='image/png'))
        save_supporting_files(partner,{'attachments':[upload],'agreement_type':'official_letter'},self.user,[])
        attachment=partner.willingness_attachments.get()
        for url in [reverse('service_providers:index'),reverse('service_providers:index')+f'?detail={self.item.pk}',reverse('service_providers:edit',args=[self.item.pk])]:
            response=self.client.get(url);self.assertEqual(response.status_code,200);self.assertNotContains(response,'/convert/');self.assertNotContains(response,'تحويلها لراغبة')
        self.item.refresh_from_db();partner.refresh_from_db();history.refresh_from_db();event.refresh_from_db()
        self.assertEqual(self.item.converted_partnership_id,partner.pk);self.assertEqual(self.item.converted_at,now)
        self.assertEqual(partner.development_state_id,'willingness');self.assertEqual(partner.development_state_at,now)
        self.assertEqual(history.entered_at,now);self.assertEqual(event.after,{'partnership':partner.pk})
        with self.assertRaises(DependencyBlocked):services.row_action({'id':self.item.pk,'version':self.item.version,'operation':'delete'},self.user)
        url=reverse('partnerships:attachment_download',args=[partner.pk,attachment.pk]);response=self.client.get(url)
        self.assertEqual(response.status_code,200);self.assertEqual(sum(map(len,response.streaming_content)),attachment.size)
        self.client.logout();self.assertEqual(self.client.get(url).status_code,302)

    def test_toggle_preserves_filters_and_has_no_conversion_side_effect(self):
        url=reverse('service_providers:index')+'?q='+self.item.name+'&status=active&page=1'
        token=views.token({'operation':'row','id':self.item.pk,'version':self.item.version},self.user)
        preview=self.client.post(url,{'action':'preview','operation':'toggle','token':token})
        response=self.client.post(url,{'action':'confirm','token':preview.context['pending']['token']})
        self.assertEqual(response.status_code,302)
        params=parse_qs(urlparse(response.url).query);self.assertEqual(params['q'],[self.item.name]);self.assertEqual(params['status'],['active'])
        self.item.refresh_from_db();self.assertFalse(self.item.is_active);self.assertFalse(Partnership.objects.exists())
