# MAKKEN RBAC BUSINESS FIXTURES v1
# MAKKEN RBAC INTEGRATION v1
# MAKKEN DEPENDENCY TEST POLICY v1
import json
import uuid
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from care_states.models import StateColor
from entities.models import Entity
from regions.models import Region
from sectors.models import Sector
from specializations.models import Specialization
from sponsorship_shapes.models import SponsorshipShape
from .forms import ProviderForm
from .models import ServiceProvider, ProviderCoverage, CoverageSpecialization, ProviderAudit
from .services import save_provider, row_action, Conflict


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ProviderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user=get_user_model().objects.create_user(username='provider-tests',password='Provider!Test123', is_superuser=True)
        cls.other=get_user_model().objects.create_user(username='provider-other', is_superuser=True)
        cls.region=Region.objects.create(name='منطقة مزود الأولى')
        cls.region2=Region.objects.create(name='منطقة مزود الثانية')
        cls.sector=Sector.objects.create(name='قطاع مزودي التدريب')
        cls.spec=Specialization.objects.create(name='تخصص مزود أول',sector=cls.sector)
        cls.spec2=Specialization.objects.create(name='تخصص مزود ثان',sector=cls.sector)
        cls.shape=SponsorshipShape.objects.create(name='رعاية مزودي التدريب')
        cls.entity=Entity.objects.create(name='كيان مزود حكومي',entity_type='government',branch='')
        cls.private=Entity.objects.create(name='كيان مزود أهلي',entity_type='non_government',branch='private_large')
        StateColor.objects.update_or_create(state='willingness',defaults={'color':'#24b3af'})

    def setUp(self):
        self.client.force_login(self.user,backend='accounts.backends.EmailOrUsernameBackend')
        self.folder=TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        setting=override_settings(MAKKEN_PRIVATE_UPLOAD_ROOT=self.folder.name);setting.enable();self.addCleanup(setting.disable)

    def data(self,**changes):
        data={'name':'مزود تدريب تجريبي','representative':'ممثل الجهة','phone_country':'SA','phone':'0501234567','email':'provider@example.com','provider_type':'government','scope':'local','is_active':'1','coverage':json.dumps([{'region':self.region.pk,'specializations':[self.spec.pk,self.spec2.pk],'is_active':True},{'region':self.region2.pk,'specializations':[self.spec.pk],'is_active':False}])}
        data.update(changes);return data

    def create(self,**changes):
        return save_provider({'id':None,'nonce':str(uuid.uuid4()),'data':self.data(**changes)},self.user)

    def payload(self,item):
        return {'id':item.pk,'version':item.version,'nonce':str(uuid.uuid4())}

    def attachment(self,name='agreement.png'):
        stream=BytesIO();Image.new('RGB',(4,4),'white').save(stream,'PNG')
        return SimpleUploadedFile(name,stream.getvalue(),content_type='image/png')


    def test_create_edit_roundtrip_and_actor_history(self):
        page=self.client.get(reverse('service_providers:create'))
        data=self.data(action='preview',snapshot=page.context['snapshot'])
        preview=self.client.post(reverse('service_providers:create'),data)
        self.assertEqual(preview.status_code,200)
        confirmation=preview.context['pending']['token']
        response=self.client.post(reverse('service_providers:create'),{'action':'confirm','token':confirmation})
        self.assertEqual(response.status_code,302)
        item=ServiceProvider.objects.get();self.assertEqual(item.phone,'+966501234567')
        self.assertEqual(item.coverage.count(),2);self.assertEqual(item.coverage.first().specializations.count(),2)
        self.assertEqual(item.events.get().actor,self.user)
        same=self.client.post(reverse('service_providers:create'),{'action':'confirm','token':confirmation})
        self.assertEqual(same.status_code,302);self.assertEqual(ServiceProvider.objects.count(),1);self.assertEqual(ProviderAudit.objects.count(),1)
        save_provider({**self.payload(item),'data':self.data(name='مزود بعد التعديل')},self.user)
        item.refresh_from_db();self.assertEqual(item.name,'مزود بعد التعديل');self.assertEqual(item.version,2);self.assertEqual(item.events.count(),2)

    def test_optional_contacts_and_validation(self):
        form=ProviderForm(self.data(representative='',phone='',email=''))
        self.assertTrue(form.is_valid(),form.errors)
        for key,value in [('phone','123'),('email','bad-email'),('phone_country','IL'),('name','<script>bad</script>'),('name','＜script＞bad＜/script＞'),('name','ﷺ'*100)]:
            form=ProviderForm(self.data(**{key:value}));self.assertFalse(form.is_valid(),(key,form.errors))

    def test_coverage_required_unique_and_tampering_rejected(self):
        row={'region':self.region.pk,'specializations':[self.spec.pk],'is_active':True}
        for rows in [[],[row,row],[{**row,'specializations':[]}],[{**row,'specializations':[self.spec.pk,self.spec.pk]}],[{**row,'region':True}],[{**row,'is_active':'1'}],[{**row,'specializations':[999999]}],[{**row,'unexpected':'data'}]]:
            form=ProviderForm(self.data(coverage=json.dumps(rows)));self.assertFalse(form.is_valid(),rows)

    def test_historical_inactive_refs_preserved_but_not_new(self):
        item=self.create();self.region.is_active=False;type(self.region).objects.filter(pk=self.region.pk).update(is_active=False);self.spec.is_active=False;type(self.spec).objects.filter(pk=self.spec.pk).update(is_active=False)
        self.assertTrue(ProviderForm(self.data(),instance=item).is_valid())
        self.assertFalse(ProviderForm(self.data(name='مزود جديد')).is_valid())
        self.sector.is_active=False;type(self.sector).objects.filter(pk=self.sector.pk).update(is_active=False)
        self.assertFalse(ProviderForm(self.data(name='مزود جديد آخر',coverage=json.dumps([{'region':self.region2.pk,'specializations':[self.spec2.pk],'is_active':True}]))).is_valid())

    def test_duplicate_and_stale_update_and_reference_revalidation(self):
        item=self.create()
        self.assertFalse(ProviderForm(self.data(name='  مزود  تدريب تجريبي  ')).is_valid())
        old=self.payload(item)
        row_action({**old,'operation':'toggle'},self.user)
        with self.assertRaises(Conflict):save_provider({**old,'data':self.data()},self.user)
        before=ServiceProvider.objects.count();self.region.is_active=False;type(self.region).objects.filter(pk=self.region.pk).update(is_active=False)
        with self.assertRaises(Conflict):self.create(name='مرجع تغيّر قبل الحفظ')
        self.assertEqual(ServiceProvider.objects.count(),before)

    def test_toggle_delete_and_retained_audit(self):
        item=self.create();key=item.pk
        row_action({**self.payload(item),'operation':'toggle'},self.user);item.refresh_from_db();self.assertFalse(item.is_active)
        row_action({**self.payload(item),'operation':'delete'},self.user)
        self.assertFalse(ServiceProvider.objects.filter(pk=key).exists())
        self.assertEqual(ProviderCoverage.objects.count(),0)
        self.assertEqual(ProviderAudit.objects.filter(provider_key=key).count(),3)
        self.assertTrue(all(event.provider is None for event in ProviderAudit.objects.filter(provider_key=key)))

    def test_database_unique_and_reference_protection(self):
        item=self.create();coverage=item.coverage.first()
        with self.assertRaises(IntegrityError),transaction.atomic():ProviderCoverage.objects.create(provider=item,region=self.region)
        with self.assertRaises(IntegrityError),transaction.atomic():CoverageSpecialization.objects.create(coverage=coverage,specialization=self.spec)
        with self.assertRaises(ProtectedError):self.region.delete()
        with self.assertRaises(ProtectedError):self.spec.delete()

    def test_list_search_status_count_pagination_and_details(self):
        item=self.create()
        for i in range(10):self.create(name=f'مزود إضافي {i}')
        for term in ['مزود','تخصص مزود أول','منطقة مزود الأولى','وحدات تدريبية حكومية','محلي','provider@example.com','+966501234567']:
            response=self.client.get(reverse('service_providers:index'),{'q':term})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.context['page_obj'].paginator.count,11)
        first=self.client.get(reverse('service_providers:index'));second=self.client.get(reverse('service_providers:index'),{'page':2})
        self.assertEqual(len(first.context['page_obj']),10);self.assertEqual(len(second.context['page_obj']),1)
        self.assertContains(first,'عدد السجلات:')
        detail=self.client.get(reverse('service_providers:index'),{'detail':item.pk})
        self.assertContains(detail,'provider-detail');self.assertContains(detail,'ممثل الجهة');self.assertContains(detail,'منطقة مزود الثانية')
        row_action({**self.payload(item),'operation':'toggle'},self.user)
        response=self.client.get(reverse('service_providers:index'),{'status':'inactive'})
        self.assertEqual(response.context['page_obj'].paginator.count,1)

    def test_login_csrf_token_user_binding_and_expiry(self):
        guest=Client();self.assertEqual(guest.get(reverse('service_providers:index')).status_code,302)
        item=self.create();page=self.client.get(reverse('service_providers:create'));snapshot=page.context['snapshot']
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.user)
        self.assertEqual(csrf.post(reverse('service_providers:create'),self.data(action='preview',snapshot=snapshot)).status_code,403)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse('service_providers:create'),self.data(action='preview',snapshot=snapshot)).status_code,400)
        self.client.force_login(self.user)
        with patch('django.core.signing.time.time',return_value=timezone.now().timestamp()+1300):
            self.assertEqual(self.client.post(reverse('service_providers:create'),self.data(action='preview',snapshot=snapshot)).status_code,400)
        self.assertEqual(ServiceProvider.objects.count(),1)









    def test_navigation_list_does_not_expand_management(self):
        response=self.client.get(reverse('service_providers:index'))
        from html.parser import HTMLParser
        class Details(HTMLParser):
            def __init__(self):super().__init__();self.groups=[]
            def handle_starttag(self,tag,attrs):
                if tag=='details' and 'nav-management' in dict(attrs).get('class',''):self.groups.append(dict(attrs))
        parsed=Details();parsed.feed(response.content.decode())
        self.assertTrue(parsed.groups);self.assertTrue(all('open' not in group for group in parsed.groups))
        self.assertContains(response,reverse('service_providers:create'))


    def test_list_queries_do_not_grow_per_provider(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        self.create()
        with CaptureQueriesContext(connection) as first:
            response=self.client.get(reverse("service_providers:index"))
            self.assertEqual(response.status_code,200)
        for number in range(10):
            self.create(name=f"مزود اختبار الأداء {number}")
        with CaptureQueriesContext(connection) as many:
            response=self.client.get(reverse("service_providers:index"))
            self.assertEqual(response.status_code,200)
        self.assertLessEqual(len(many),len(first)+1)

