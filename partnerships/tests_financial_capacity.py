from regions.models import Region
import json
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit
from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.utils.translation import override
from entities.models import Entity
from sectors.models import Sector
from specializations.models import Specialization
from sponsorship_shapes.models import SponsorshipShape
from .models import Partnership
from .forms import PartnershipForm
from .financial import MoneyField, FinancialRangeForm


class FinancialCapacityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user=get_user_model().objects.create_user(username='financial-user',password='Testing!123456')
        cls.entity=Entity.objects.create(name='هيئة اختبار مالي',entity_type='government')
        cls.sector=Sector.objects.create(name='قطاع الاختبار المالي')
        cls.spec=Specialization.objects.create(name='تخصص الاختبار المالي',sector=cls.sector)
        cls.shape=SponsorshipShape.objects.create(name='رعاية الاختبار المالي',description='وصف الرعاية')
    def setUp(self):self.client.force_login(self.user)
    def data(self,**changes):
        data={'name':'جهة اختبار مالي','representative':'الممثل التجريبي','phone_country':'SA','phone':'0501234567','email':'financial@example.com','entity_type':'government','entity':self.entity.pk,'scope':'local','is_active':'1','financial_capacity':'125000.50','offerings':json.dumps([{'sector':self.sector.pk,'specializations':[self.spec.pk],'shape':self.shape.pk,'is_active':True}])}
        data["coverage_regions"] = [str(Region.objects.get_or_create(name="منطقة اختبار الشراكة")[0].pk)]
        data.update(changes);return data
    def preview(self,path='/partnerships/new/',**changes):
        snapshot=self.client.get(path).context['snapshot']
        return self.client.post(path,{**self.data(**changes),'action':'preview','snapshot':snapshot})
    def save(self,**changes):
        response=self.preview(**changes);self.assertEqual(response.status_code,200,response.context['form'].errors)
        token=response.context['pending']['token']
        response=self.client.post('/partnerships/new/',{'action':'confirm','token':token});self.assertEqual(response.status_code,302)
        return Partnership.objects.latest('pk')
    def record(self,name,amount,is_active=True):
        return Partnership.objects.create(name=name,representative='ممثل جهة',phone_country='SA',phone='+966501234567',email='a@example.com',entity=self.entity,scope='local',financial_capacity=amount,is_active=is_active)
    def ids(self,response):return {r['item'].pk for r in response.context['rows']}

    def test_required_nonnegative_exact_amount_and_normalization(self):
        self.assertIsNone(MoneyField(required=False).clean('   '))
        for raw,expected in [('0',Decimal('0')),('1,250.50',Decimal('1250.50')),('١٬٢٥٠٫٥٠',Decimal('1250.50')),('۱۲۵۰٫۵۰',Decimal('1250.50')),('999999999999.99',Decimal('999999999999.99'))]:
            with self.subTest(raw=raw):self.assertEqual(MoneyField().clean(raw),expected)
        for raw in ['', '-0.01','1.999','1000000000000','NaN','Infinity','1e6','abc','1,20.00','9'*100]:
            with self.subTest(raw=raw):
                form=PartnershipForm(self.data(financial_capacity=raw));self.assertFalse(form.is_valid());self.assertIn('financial_capacity',form.errors)

    def test_confirmed_create_and_replay_keep_exact_decimal(self):
        preview=self.preview(financial_capacity='1,250.50')
        self.assertFalse(Partnership.objects.exists())
        self.assertContains(preview,'القدرة المالية')
        token=preview.context['pending']['token']
        self.client.post('/partnerships/new/',{'action':'confirm','token':token})
        item=Partnership.objects.get();self.assertEqual(item.financial_capacity,Decimal('1250.50'))
        self.client.post('/partnerships/new/',{'action':'confirm','token':token})
        self.assertEqual(Partnership.objects.count(),1)

    def test_edit_amount_preserves_care_timestamp_and_history(self):
        item=self.save();date=item.development_state_at;path=f'/partnerships/{item.pk}/edit/'
        response=self.client.get(path);self.assertEqual(response.context['form']['financial_capacity'].value(),'125000.50')
        preview=self.preview(path,financial_capacity='987654.32')
        item.refresh_from_db();self.assertEqual(item.financial_capacity,Decimal('125000.50'))
        self.client.post(path,{'action':'confirm','token':preview.context['pending']['token']})
        item.refresh_from_db();self.assertEqual(item.financial_capacity,Decimal('987654.32'));self.assertEqual(item.development_state_at,date);self.assertEqual(item.development_history.count(),1)

    @override('en')
    def test_table_replaces_representative_and_detail_keeps_both(self):
        item=self.save()
        response=self.client.get('/partnerships/')
        self.assertContains(response,'<th scope="col">القدرة المالية</th>',html=True)
        self.assertNotContains(response,'<th scope="col">اسم الممثل</th>',html=True)
        self.assertContains(response,'125,000.50')
        response=self.client.get('/partnerships/',{'detail':item.pk})
        self.assertContains(response,'الممثل التجريبي');self.assertContains(response,'125,000.50');self.assertContains(response,'saudi-riyal.svg')

    def test_range_inclusive_zero_null_and_one_sided(self):
        zero=self.record('صفر مالي',Decimal('0'));a=self.record('مبلغ أول',Decimal('100.10'));b=self.record('مبلغ ثان',Decimal('200.20'));unknown=self.record('مبلغ غير محدد',None)
        cases=[({'capacity_min':'0','capacity_max':'0'},{zero.pk}),({'capacity_min':'100.10','capacity_max':'200.20'},{a.pk,b.pk}),({'capacity_min':'200.20'},{b.pk}),({'capacity_max':'100.10'},{zero.pk,a.pk}),({},{zero.pk,a.pk,b.pk,unknown.pk})]
        for params,expected in cases:
            with self.subTest(params=params):
                response=self.client.get('/partnerships/',params);self.assertEqual(response.status_code,200);self.assertEqual(self.ids(response),expected)

    def test_data_driven_bounds_combined_search_status_and_range(self):
        a=self.record('شركة تطابق أول',Decimal('100.25'));b=self.record('شركة تطابق ثان',Decimal('500.75'));self.record('شركة تطابق معطلة',Decimal('9000'),False);self.record('اسم مختلف',Decimal('99999'))
        response=self.client.get('/partnerships/',{'q':'شركة تطابق','status':'1','capacity_min':'150'})
        self.assertEqual(self.ids(response),{b.pk});self.assertEqual(response.context['financial_bounds_min'],'100.25');self.assertEqual(response.context['financial_bounds_max'],'500.75')
        b.financial_capacity=Decimal('800.90');b.save()
        response=self.client.get('/partnerships/',{'q':'شركة تطابق','status':'1'})
        self.assertEqual(response.context['financial_bounds_max'],'800.90')

    def test_invalid_range_is_visible_error_not_silently_ignored(self):
        self.record('جهة مبلغ',Decimal('100'))
        for params in [{'capacity_min':'200','capacity_max':'100'},{'capacity_min':'-1'},{'capacity_max':'bad'},{'capacity_min':'1.123'}]:
            with self.subTest(params=params):
                response=self.client.get('/partnerships/',params);self.assertEqual(response.status_code,400);self.assertEqual(len(response.context['rows']),0);self.assertTrue(response.context['financial_range_form'].errors)

    def test_pagination_and_detail_keep_capacity_range(self):
        for index in range(18):self.record(f'صفحات مالية {index}',Decimal('500'))
        params={'q':'صفحات مالية','capacity_min':'400','capacity_max':'600','status':'1'}
        response=self.client.get('/partnerships/',params);self.assertEqual(len(response.context['rows']),15)
        self.assertIn('capacity_min=400.00',response.context['financial_pagination_query']);self.assertIn('capacity_max=600.00',response.context['result_query'])
        response=self.client.get('/partnerships/',{**params,'page':2});self.assertEqual(len(response.context['rows']),3)
        pk=response.context['rows'][0]['item'].pk
        detail=self.client.get('/partnerships/',{**params,'page':2,'detail':pk})
        query=parse_qs(urlsplit(detail.context['list_url']).query)
        self.assertEqual(query['capacity_min'],['400.00']);self.assertEqual(query['capacity_max'],['600.00']);self.assertEqual(query['page'],['2'])

    def test_capacity_numeric_free_text_search(self):
        target=self.record('بحث بالمبلغ',Decimal('1250.50'));self.record('مبلغ آخر',Decimal('2000'))
        response=self.client.get('/partnerships/',{'q':'1,250.50'})
        self.assertEqual(self.ids(response),{target.pk})

    @override('en')
    def test_legacy_amount_not_fabricated_and_zero_is_visible(self):
        legacy=self.record('جهة سابقة',None)
        response=self.client.get('/partnerships/')
        self.assertContains(response,'غير محددة');self.assertFalse(response.context['financial_has_bounds']);self.assertTrue(response.context['financial_slider_disabled'])
        edit=self.client.get(f'/partnerships/{legacy.pk}/edit/');self.assertEqual(edit.context['form']['financial_capacity'].value(),'')
        legacy.financial_capacity=Decimal('0');legacy.save()
        response=self.client.get('/partnerships/');self.assertContains(response,'0.00');self.assertTrue(response.context['financial_has_bounds']);self.assertTrue(response.context['financial_slider_disabled'])

    def test_amount_and_range_payloads_are_escaped(self):
        response=self.client.get('/partnerships/',{'capacity_min':'<script>alert(1)</script>'})
        self.assertEqual(response.status_code,400);self.assertNotContains(response,'<script>alert(1)</script>',status_code=400);self.assertContains(response,'&lt;script&gt;',status_code=400)
        response=self.preview(financial_capacity='<img src=x onerror=alert(1)>');self.assertEqual(response.status_code,400);self.assertIn('financial_capacity',response.context['form'].errors)

    def test_database_rejects_negative_amount(self):
        with self.assertRaises(IntegrityError),transaction.atomic():self.record('قيمة سالبة',Decimal('-1'))

    def test_status_confirmation_preserves_range_parameters(self):
        item=self.save()
        params={'q':item.name,'status':'1','capacity_min':'100000','capacity_max':'150000'}
        response=self.client.get('/partnerships/',params);row=response.context['rows'][0]
        from urllib.parse import urlencode
        path='/partnerships/?'+urlencode(params)
        preview=self.client.post(path,{'action':'preview','token':row['toggle']})
        response=self.client.post(path,{'action':'confirm','token':preview.context['pending']['token']})
        self.assertEqual(response.status_code,302);query=parse_qs(urlsplit(response.url).query);self.assertEqual(query['capacity_min'],['100000']);self.assertEqual(query['capacity_max'],['150000'])


class FinancialMigrationTests(TransactionTestCase):
    def restore_latest_schema(self):
        executor = MigrationExecutor(connection)
        executor.migrate(executor.loader.graph.leaf_nodes())

    def test_existing_record_keeps_fields_and_gets_unknown_capacity(self):
        self.addCleanup(self.restore_latest_schema)
        executor=MigrationExecutor(connection);executor.migrate([('partnerships','0001_initial')])
        old=executor.loader.project_state([('partnerships','0001_initial')]).apps
        old.get_model('care_states','StateColor').objects.get_or_create(state='capability',defaults={'color':'#BA1D1D'})
        entity=old.get_model('entities','Entity').objects.create(name='كيان قديم',name_key='كيان قديم',entity_type='government',branch='')
        item=old.get_model('partnerships','Partnership').objects.create(name='شراكة قديمة',name_key='شراكة قديمة',representative='ممثل قديم',phone_country='SA',phone='+966501234567',email='old@example.com',entity_id=entity.pk,scope='local')
        original_date=item.development_state_at
        try:
            executor=MigrationExecutor(connection);executor.migrate([('partnerships','0002_financial_capacity')])
            current=executor.loader.project_state([('partnerships','0002_financial_capacity')]).apps.get_model('partnerships','Partnership').objects.get(pk=item.pk)
            self.assertIsNone(current.financial_capacity);self.assertEqual(current.name,'شراكة قديمة');self.assertEqual(current.representative,'ممثل قديم');self.assertEqual(current.development_state_at,original_date)
        finally:
            self.restore_latest_schema()
