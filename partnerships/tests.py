# MAKKEN RBAC BUSINESS FIXTURES v1
# MAKKEN RBAC INTEGRATION v1
# MAKKEN DEPENDENCY TEST POLICY v1
from regions.models import Region
import json

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.test import Client, TestCase
from care_states.models import StateColor
from entities.models import Entity
from sectors.models import Sector
from specializations.models import Specialization
from sponsorship_shapes.models import SponsorshipShape
from .forms import PartnershipForm
from .models import Partnership, PartnershipOffering, DevelopmentHistory


class PartnershipTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = get_user_model().objects.create_user(username='partner-user', password='Testing!123456', is_superuser=True)
        cls.other = get_user_model().objects.create_user(username='other-user', password='Testing!123456', is_superuser=True)
        cls.entity = Entity.objects.create(name='هيئة حكومية تجريبية', entity_type='government')
        cls.private = Entity.objects.create(name='شركة أهلية', entity_type='non_government', branch='private_large')
        cls.sector = Sector.objects.create(name='قطاع الحاسب')
        cls.second_sector = Sector.objects.create(name='قطاع الصناعة')
        cls.spec = Specialization.objects.create(name='هندسة البرمجيات', sector=cls.sector)
        cls.second_spec = Specialization.objects.create(name='هندسة الشبكات', sector=cls.sector)
        cls.wrong_spec = Specialization.objects.create(name='التصنيع', sector=cls.second_sector)
        cls.shape = SponsorshipShape.objects.create(name='رعاية تجريبية', description='تغطية تكاليف البرنامج')

    def setUp(self):
        self.client.force_login(self.user)

    def data(self, **changes):
        values = {'name':'شركة الشراكة التجريبية', 'representative':'أحمد محمد', 'phone_country':'SA', 'phone':'0501234567', 'email':'partner@example.com', 'entity_type':'government', 'entity':str(self.entity.pk), 'scope':'local', 'is_active':'1', 'offerings':json.dumps([{'sector':self.sector.pk, 'specializations':[self.spec.pk], 'shape':self.shape.pk, 'is_active':True}]), "financial_capacity": "100000.00"}
        values["coverage_regions"] = [str(Region.objects.get_or_create(name="منطقة اختبار الشراكة")[0].pk)]
        values.update(changes)
        return values

    def preview(self, path='/partnerships/new/', **data):
        response = self.client.get(path)
        return self.client.post(path, {**self.data(**data), 'action':'preview', 'snapshot':response.context['snapshot']})

    def save(self, **data):
        preview = self.preview(**data)
        self.assertEqual(preview.status_code,200, preview.context['form'].errors)
        token = preview.context['pending']['token']
        response = self.client.post('/partnerships/new/', {'action':'confirm','token':token})
        self.assertEqual(response.status_code,302)
        return Partnership.objects.latest('pk'), token

    def test_create_is_confirmed_atomic_and_replay_safe(self):
        preview = self.preview()
        self.assertFalse(Partnership.objects.exists())
        token = preview.context['pending']['token']
        response = self.client.post('/partnerships/new/', {'action':'confirm','token':token})
        self.assertEqual(response.status_code,302)
        item = Partnership.objects.get()
        self.assertEqual(item.phone,'+966501234567')
        self.assertEqual(item.development_state_id,'capability')
        self.assertEqual(item.development_history.get().entered_at,item.development_state_at)
        self.assertEqual(item.offerings.get().specializations.count(),1)
        self.client.post('/partnerships/new/', {'action':'confirm','token':token})
        self.assertEqual(Partnership.objects.count(),1)
        self.assertEqual(DevelopmentHistory.objects.count(),1)

    def test_mobile_validation(self):
        for value in ['12','abcdefgh','0111234567','+962791234567','0501234567 ext 12']:
            with self.subTest(value=value):
                form = PartnershipForm(self.data(phone=value))
                self.assertFalse(form.is_valid())
                self.assertIn('phone',form.errors)
        form = PartnershipForm(self.data(phone='٠٥٠١٢٣٤٥٦٧'))
        self.assertTrue(form.is_valid(),form.errors)
        self.assertEqual(form.cleaned_data['phone'],'+966501234567')
        form = PartnershipForm(self.data(phone_country='JO',phone='0791234567'))
        self.assertTrue(form.is_valid(),form.errors)

    def test_required_fields_and_email(self):
        for field in ['name','representative','email','phone','phone_country','entity_type','scope','is_active']:
            with self.subTest(field=field):
                form = PartnershipForm(self.data(**{field:''}))
                self.assertFalse(form.is_valid())
                self.assertIn(field,form.errors)
        self.assertFalse(PartnershipForm(self.data(email='not-an-email')).is_valid())

    def test_entity_type_must_match(self):
        form = PartnershipForm(self.data(entity=str(self.private.pk)))
        self.assertFalse(form.is_valid())
        self.assertIn('entity',form.errors)
        self.assertTrue(PartnershipForm(self.data(entity=str(self.private.pk),entity_type='non_government')).is_valid())

    def test_related_specializations_and_duplicate_lines(self):
        row = {'sector':self.sector.pk,'specializations':[self.wrong_spec.pk],'shape':self.shape.pk,'is_active':True}
        for rows in [[],[row], [True], [{'sector':True}], 'bad-data']:
            with self.subTest(rows=rows):
                form = PartnershipForm(self.data(offerings=json.dumps(rows)))
                self.assertFalse(form.is_valid())
                self.assertIn('offerings',form.errors)
        row['specializations']=[self.spec.pk]
        form = PartnershipForm(self.data(offerings=json.dumps([row,row])))
        self.assertFalse(form.is_valid())
        row['specializations']=[self.spec.pk,self.spec.pk]
        self.assertFalse(PartnershipForm(self.data(offerings=json.dumps([row]))).is_valid())

    def test_edit_keeps_state_date_and_history(self):
        item,_ = self.save()
        before = item.development_state_at
        path = f'/partnerships/{item.pk}/edit/'
        preview = self.preview(path,name='شركة الشراكة بعد التعديل',scope='global',is_active='0')
        item.refresh_from_db()
        self.assertNotEqual(item.name,'شركة الشراكة بعد التعديل')
        self.client.post(path,{'action':'confirm','token':preview.context['pending']['token']})
        item.refresh_from_db()
        self.assertEqual(item.name,'شركة الشراكة بعد التعديل')
        self.assertEqual(item.scope,'global')
        self.assertFalse(item.is_active)
        self.assertEqual(item.development_state_at,before)
        self.assertEqual(item.development_history.count(),1)
        self.assertEqual(item.version,2)

    def test_stale_edit_rejected(self):
        item,_ = self.save()
        path=f'/partnerships/{item.pk}/edit/'
        first = self.preview(path,name='تعديل أول')
        second = self.preview(path,name='تعديل ثان')
        self.client.post(path,{'action':'confirm','token':first.context['pending']['token']})
        response = self.client.post(path,{'action':'confirm','token':second.context['pending']['token']})
        self.assertEqual(response.status_code,409)
        item.refresh_from_db();self.assertEqual(item.name,'تعديل أول')

    def test_catalog_changes_between_preview_and_confirm_rejected(self):
        preview = self.preview()
        self.shape.version+=1;self.shape.save()
        response=self.client.post('/partnerships/new/',{'action':'confirm','token':preview.context['pending']['token']})
        self.assertEqual(response.status_code,409)
        self.assertFalse(Partnership.objects.exists())

    def test_inactive_catalog_choices(self):
        item,_=self.save()
        self.entity.is_active=False;type(self.entity).objects.filter(pk=self.entity.pk).update(is_active=False)
        self.spec.is_active=False;type(self.spec).objects.filter(pk=self.spec.pk).update(is_active=False)
        self.shape.is_active=False;type(self.shape).objects.filter(pk=self.shape.pk).update(is_active=False)
        self.assertFalse(PartnershipForm(self.data()).is_valid())
        form=PartnershipForm(self.data(),instance=item)
        self.assertTrue(form.is_valid(),form.errors)

    def test_duplicate_name_and_html_rejected(self):
        self.save()
        self.assertFalse(PartnershipForm(self.data(name='  شركة الشراكة التجريبية  ')).is_valid())
        self.assertFalse(PartnershipForm(self.data(name='<script>alert(1)</script>')).is_valid())

    def test_search_pagination_and_details(self):
        item,_=self.save()
        for term in [item.name,'أحمد','501234567','partner@example.com','هيئة حكومية','حكومي','محلي','قدرة','نشط','هندسة البرمجيات','رعاية تجريبية']:
            with self.subTest(term=term):
                response=self.client.get('/partnerships/',{'q':term})
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.context['page_obj'].paginator.count,1)
        self.assertEqual(self.client.get('/partnerships/',{'q':'لا توجد هذه الجهة'}).context['page_obj'].paginator.count,0)
        self.assertEqual(self.client.get('/partnerships/',{'q':'غير نشط'}).context['page_obj'].paginator.count,0)
        response=self.client.get('/partnerships/',{'detail':item.pk})
        self.assertContains(response,'تغطية تكاليف البرنامج')
        self.assertContains(response,'تاريخ حالة تطور المنظمة للرعاية')
        self.assertContains(response,'محفوظة في السجل')
        for index in range(16):
            Partnership.objects.create(name=f'جهة أخرى {index}',representative='اسم ممثل',phone_country='SA',phone='+966501234567',email='x@example.com',entity=self.entity,scope='local')
        response=self.client.get('/partnerships/',{'page':2})
        self.assertEqual(len(response.context['rows']),2)
        self.assertEqual(response.context['page_obj'].paginator.num_pages,2)

    def test_toggle_delete_confirmation_and_replay(self):
        item,_=self.save()
        response=self.client.get('/partnerships/')
        row=response.context['rows'][0]
        preview=self.client.post('/partnerships/',{'action':'preview','token':row['toggle']})
        item.refresh_from_db();self.assertTrue(item.is_active)
        token=preview.context['pending']['token']
        self.client.post('/partnerships/',{'action':'confirm','token':token})
        item.refresh_from_db();self.assertFalse(item.is_active)
        self.assertEqual(self.client.post('/partnerships/',{'action':'confirm','token':token}).status_code,409)
        response=self.client.get('/partnerships/',{'q':'غير نشط'})
        self.assertEqual(response.context['page_obj'].paginator.count,1)
        token=self.client.get('/partnerships/').context['rows'][0]['delete']
        preview=self.client.post('/partnerships/',{'action':'preview','token':token})
        self.assertTrue(Partnership.objects.filter(pk=item.pk).exists())
        self.client.post('/partnerships/',{'action':'confirm','token':preview.context['pending']['token']})
        self.assertFalse(Partnership.objects.exists())
        self.assertFalse(PartnershipOffering.objects.exists())
        self.assertFalse(DevelopmentHistory.objects.exists())
        self.assertTrue(Sector.objects.filter(pk=self.sector.pk).exists())
        self.assertTrue(Specialization.objects.filter(pk=self.spec.pk).exists())

    def test_security_auth_csrf_tamper_and_cross_user(self):
        self.assertEqual(Client().get('/partnerships/').status_code,302)
        self.assertEqual(Client().get('/partnerships/new/').status_code,302)
        csrf=Client(enforce_csrf_checks=True);csrf.force_login(self.user)
        self.assertEqual(csrf.post('/partnerships/new/',self.data()).status_code,403)
        preview=self.preview();token=preview.context['pending']['token']
        self.assertEqual(self.client.post('/partnerships/new/',{'action':'confirm','token':token+'x'}).status_code,400)
        self.client.force_login(self.other)
        self.assertEqual(self.client.post('/partnerships/new/',{'action':'confirm','token':token}).status_code,400)
        self.assertFalse(Partnership.objects.exists())

    def test_referenced_catalog_deletions_protected(self):
        self.save()
        for item in [self.entity,self.sector,self.spec,self.shape]:
            with self.subTest(model=type(item).__name__),self.assertRaises(ProtectedError),transaction.atomic():
                item.delete()

    def test_sector_cannot_release_used_specialization(self):
        self.save()
        response=self.client.get('/settings/sectors/',{'edit':self.sector.pk})
        snapshot=response.context['editor_form'].initial['snapshot']
        preview=self.client.post('/settings/sectors/',{'action':'preview','operation':'edit','snapshot':snapshot,'name':self.sector.name,'is_active':'1','specializations':[self.second_spec.pk]})
        self.assertEqual(preview.status_code,200)
        response=self.client.post('/settings/sectors/',{'action':'confirm','token':preview.context['pending']['token']})
        self.assertEqual(response.status_code,409)
        self.spec.refresh_from_db();self.assertEqual(self.spec.sector_id,self.sector.pk)

    def test_live_care_colors_and_sidebar_links(self):
        item,_=self.save()
        StateColor.objects.filter(pk='capability').update(color='#123456')
        response=self.client.get('/partnerships/',{'detail':item.pk})
        self.assertContains(response,'fill="#123456"')
        self.assertContains(response,'href="/partnerships/new/"')
        self.assertContains(response,'href="/partnerships/"')
        self.assertEqual(response['X-Frame-Options'],'DENY')
        self.assertIn('no-store',response['Cache-Control'])

    def test_missing_detail_and_wrong_methods(self):
        self.assertEqual(self.client.get('/partnerships/',{'detail':'bad'}).status_code,404)
        self.assertEqual(self.client.get('/partnerships/999999/edit/').status_code,404)
        self.assertEqual(self.client.put('/partnerships/').status_code,405)
