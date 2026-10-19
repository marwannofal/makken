import json
import uuid
from decimal import Decimal
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import ValidationError
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
from partnerships.models import Partnership, DevelopmentHistory, WillingnessAttachment
from .forms import ProviderForm
from .models import ServiceProvider, ProviderCoverage, CoverageSpecialization, ProviderAudit
from .services import save_provider, row_action, convert_provider, Conflict
from .views import token, SALT


@override_settings(PASSWORD_HASHERS=['django.contrib.auth.hashers.MD5PasswordHasher'])
class ProviderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user=get_user_model().objects.create_user(username='provider-tests',password='Provider!Test123')
        cls.other=get_user_model().objects.create_user(username='provider-other')
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

    def conversion(self,**changes):
        values={'representative':'ممثل جهة التدريب','phone_country':'SA','phone':'0501234567','email':'converted@example.com','financial_capacity':'1,234,567.89','entity':'','sponsorship_shape':str(self.shape.pk),'agreement_type':'official_letter'}
        values.update(changes);return values

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
        item=self.create();self.region.is_active=False;self.region.save();self.spec.is_active=False;self.spec.save()
        self.assertTrue(ProviderForm(self.data(),instance=item).is_valid())
        self.assertFalse(ProviderForm(self.data(name='مزود جديد')).is_valid())
        self.sector.is_active=False;self.sector.save()
        self.assertFalse(ProviderForm(self.data(name='مزود جديد آخر',coverage=json.dumps([{'region':self.region2.pk,'specializations':[self.spec2.pk],'is_active':True}]))).is_valid())

    def test_duplicate_and_stale_update_and_reference_revalidation(self):
        item=self.create()
        self.assertFalse(ProviderForm(self.data(name='  مزود  تدريب تجريبي  ')).is_valid())
        old=self.payload(item)
        row_action({**old,'operation':'toggle'},self.user)
        with self.assertRaises(Conflict):save_provider({**old,'data':self.data()},self.user)
        before=ServiceProvider.objects.count();self.region.is_active=False;self.region.save()
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

    def test_conversion_creates_one_willing_partner_and_private_evidence(self):
        item=self.create();payload=self.payload(item)
        partner=convert_provider(payload,self.conversion(),{'attachments':[self.attachment()]},self.user)
        self.assertEqual(partner.development_state_id,'willingness');self.assertEqual(partner.financial_capacity,Decimal('1234567.89'))
        self.assertEqual(partner.development_history.count(),1);self.assertEqual(partner.development_history.get().state_id,'willingness')
        self.assertEqual(partner.offerings.count(),2)
        self.assertTrue(all(offering.specializations.count()==1 for offering in partner.offerings.all()))
        self.assertEqual(partner.preliminary_agreement_type,'official_letter')
        item.refresh_from_db();self.assertEqual(item.converted_partnership_id,partner.pk)
        self.assertEqual(convert_provider(payload,self.conversion(),{},self.user).pk,partner.pk)
        attachment=partner.willingness_attachments.get()
        response=self.client.get(reverse('partnerships:attachment_download',args=[partner.pk,attachment.pk]))
        self.assertEqual(response.status_code,200);self.assertEqual(sum(map(len,response.streaming_content)),attachment.size)
        self.client.logout();self.assertEqual(self.client.get(reverse('partnerships:attachment_download',args=[partner.pk,attachment.pk])).status_code,302)

    def test_conversion_requires_contacts_agreement_and_files(self):
        item=self.create()
        for values,files in [(self.conversion(agreement_type=''),{'attachments':[self.attachment()]}),(self.conversion(),{}),(self.conversion(email='bad'),{'attachments':[self.attachment()]}),(self.conversion(),{'attachments':[SimpleUploadedFile('fake.pdf',b'not a PDF')]})]:
            with self.assertRaises(ValidationError):convert_provider(self.payload(item),values,files,self.user)
        item.refresh_from_db();self.assertIsNone(item.converted_partnership_id);self.assertEqual(Partnership.objects.count(),0)

    def test_conversion_filters_inactive_rows_specs_and_regions(self):
        item=self.create();self.spec.is_active=False;self.spec.save()
        partner=convert_provider(self.payload(item),self.conversion(),{'attachments':[self.attachment()]},self.user)
        self.assertEqual(partner.offerings.count(),1);self.assertEqual(partner.offerings.get().specializations.get(),self.spec2)
        item2=self.create(name='مزود دون تغطية نشطة',coverage=json.dumps([{'region':self.region2.pk,'specializations':[self.spec2.pk],'is_active':True}]));item2.coverage.update(is_active=False)
        with self.assertRaises(Conflict):convert_provider(self.payload(item2),self.conversion(),{'attachments':[self.attachment()]},self.user)

    def test_private_conversion_requires_non_government_entity(self):
        item=self.create(provider_type='private')
        with self.assertRaises(ValidationError):convert_provider(self.payload(item),self.conversion(),{'attachments':[self.attachment()]},self.user)
        partner=convert_provider(self.payload(item),self.conversion(entity=str(self.private.pk)),{'attachments':[self.attachment()]},self.user)
        self.assertEqual(partner.entity,self.private)

    def test_conversion_conflicts_and_converted_delete_protection(self):
        item=self.create();payload=self.payload(item)
        row_action({**payload,'operation':'toggle'},self.user);item.refresh_from_db()
        with self.assertRaises(Conflict):convert_provider(payload,self.conversion(),{'attachments':[self.attachment()]},self.user)
        with self.assertRaises(Conflict):convert_provider(self.payload(item),self.conversion(),{'attachments':[self.attachment()]},self.user)
        row_action({**self.payload(item),'operation':'toggle'},self.user);item.refresh_from_db()
        partner=convert_provider(self.payload(item),self.conversion(),{'attachments':[self.attachment()]},self.user);item.refresh_from_db()
        with self.assertRaises(Conflict):row_action({**self.payload(item),'operation':'delete'},self.user)
        with self.assertRaises(ProtectedError):partner.delete()

    def test_conversion_duplicate_name_never_rewrites_existing_partner(self):
        item=self.create();partner=Partnership.objects.create(name=item.name,representative='existing',phone='+966501234567',email='existing@example.com',entity=self.entity,scope='local')
        with self.assertRaises(Conflict):convert_provider(self.payload(item),self.conversion(),{'attachments':[self.attachment()]},self.user)
        partner.refresh_from_db();self.assertEqual(partner.development_state_id,'capability');self.assertEqual(Partnership.objects.count(),1)

    def test_failed_file_save_rolls_back_database_and_cleans_files(self):
        item=self.create()
        from . import services
        original=services.save_supporting_files
        def fail(*args):original(*args);raise OSError('simulated disk error')
        with patch('service_providers.services.save_supporting_files',side_effect=fail):
            with self.assertRaises(OSError):convert_provider(self.payload(item),self.conversion(),{'attachments':[self.attachment()]},self.user)
        from pathlib import Path
        self.assertFalse(any(path.is_file() for path in Path(self.folder.name).rglob('*')))
        self.assertFalse(Partnership.objects.exists());self.assertFalse(WillingnessAttachment.objects.exists());item.refresh_from_db();self.assertIsNone(item.converted_partnership_id)

    def test_conversion_ajax_validation_and_success(self):
        item=self.create();url=reverse('service_providers:convert',args=[item.pk]);page=self.client.get(url)
        self.assertContains(page,'provider-conversion')
        data=self.conversion(snapshot=page.context['conversion_snapshot'])
        response=self.client.post(url,data,HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code,400);self.assertIn('attachments',response.json()['fields'])
        data['attachments']=[self.attachment()]
        response=self.client.post(url,data,HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code,200);self.assertIn('redirect',response.json())

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

    def test_converted_provider_participates_in_existing_market_matching(self):
        from expense_items.models import ExpenseItem
        from training_programs.models import TrainingProgram
        from market_needs.models import Need, ExpenseLine
        from market_needs.matching import candidates
        expense=ExpenseItem.objects.create(name="بند صرف مزود التدريب")
        program=TrainingProgram.objects.create(name="برنامج مزود التدريب",category="qualifying_program",is_training=True,is_operational=False)
        program.expense_items.set([expense])
        need=Need.objects.create(title="حاجة اختبار المزود",sector=self.sector,specialization=self.spec,description="وصف حاجة التدريب",duration=1,duration_unit="day",source="اختبار",beneficiaries=1,program=program,program_name=program.name,program_category=program.get_category_display(),training_type="تدريبي",total_cost=Decimal("100"),requested_support=Decimal("100"))
        need.regions.set([self.region])
        ExpenseLine.objects.create(need=need,expense_item=expense,sponsorship_shape=self.shape,amount=Decimal("100"))
        item=self.create()
        partner=convert_provider(self.payload(item),self.conversion(),{"attachments":[self.attachment()]},self.user)
        self.assertTrue(candidates(need).filter(pk=partner.pk).exists())

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

    def test_inactive_conversion_and_row_filter_preservation(self):
        from urllib.parse import urlencode, urlparse, parse_qs
        item=self.create()
        row_action({**self.payload(item),"operation":"toggle"},self.user)
        item.refresh_from_db()
        response=self.client.get(reverse("service_providers:convert",args=[item.pk]))
        self.assertEqual(response.status_code,409)
        self.assertContains(response,"فعّل سجل المزود",status_code=409)
        url=reverse("service_providers:index")+"?"+urlencode({"q":item.name,"status":"inactive"})
        row_token=token({"operation":"row","id":item.pk,"version":item.version},self.user)
        preview=self.client.post(url,{"action":"preview","operation":"toggle","token":row_token})
        confirmed=self.client.post(url,{"action":"confirm","token":preview.context["pending"]["token"]})
        parameters=parse_qs(urlparse(confirmed.url).query)
        self.assertEqual(parameters["q"],[item.name]);self.assertEqual(parameters["status"],["inactive"])
