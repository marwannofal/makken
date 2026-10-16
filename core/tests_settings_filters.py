from urllib.parse import parse_qs, urlencode, urlsplit
from html.parser import HTMLParser

class LinkCollector(HTMLParser):
    def __init__(self):
        super().__init__(); self.links=[]
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.extend(value for key,value in attrs if key == "href")
from django.contrib.auth import get_user_model
from django.test import TestCase

from levels.models import Level
from regions.models import Region
from entities.models import Entity
from specializations.models import Specialization
from sectors.models import Sector
from expense_items.models import ExpenseItem
from training_programs.models import TrainingProgram
from sponsorship_shapes.models import SponsorshipShape


class SettingsFiltersTests(TestCase):
    routes = {'levels':'levels', 'regions':'regions', 'entities':'entities', 'specializations':'specializations', 'sectors':'sectors', 'expense_items':'expense-items', 'training_programs':'training-programs', 'sponsorship_shapes':'sponsorship-shapes'}

    @classmethod
    def setUpTestData(cls):
        cls.user=get_user_model().objects.create_user(username='settings-filter-user',password='Testing!123456')
        cls.records={}
        for app,model in [('levels',Level),('regions',Region),('entities',Entity),('specializations',Specialization),('sectors',Sector),('expense_items',ExpenseItem),('training_programs',TrainingProgram),('sponsorship_shapes',SponsorshipShape)]:
            records=[]
            for active in [True,False]:
                data={'name':f'فحص البحث {app} '+('الأول' if active else 'الثاني'),'is_active':active}
                if app=='entities':data.update(entity_type='government' if active else 'non_government',branch='' if active else 'private_large')
                if app=='training_programs':data.update(category='development_course' if active else 'qualifying_course',is_training=active,is_operational=not active)
                if app=='sponsorship_shapes':data.update(description='وصف فرصة مميزة' if active else 'وصف آخر',is_employment=active)
                records.append(model.objects.create(**data))
            cls.records[app]=records
        cls.spec_a=Specialization.objects.create(name='خبرة مشتركة أولى',sector=cls.records['sectors'][0])
        cls.spec_b=Specialization.objects.create(name='خبرة مشتركة ثانية',sector=cls.records['sectors'][0])
        cls.records['specializations'][0].sector=cls.records['sectors'][0]
        cls.records['specializations'][0].save()
        cls.exp_a=ExpenseItem.objects.create(name='مصروف مرتبط أول')
        cls.exp_b=ExpenseItem.objects.create(name='مصروف مرتبط ثان')
        cls.records['training_programs'][0].expense_items.set([cls.exp_a,cls.exp_b])

    def setUp(self):self.client.force_login(self.user)
    def url(self,app):return '/settings/'+self.routes[app]+'/'
    def ids(self,response):return {row['id'] for row in response.context['rows']}

    def test_all_eight_pages_have_working_search_and_status(self):
        for app in self.routes:
            with self.subTest(app=app):
                response=self.client.get(self.url(app),{'q':'فحص البحث '+app})
                self.assertEqual(response.status_code,200)
                self.assertContains(response,'class="settings-filters"',count=1)
                self.assertEqual(self.ids(response),{r.pk for r in self.records[app]})
                for active in [True,False]:
                    response=self.client.get(self.url(app),{'q':'فحص البحث '+app,'status':'1' if active else '0'})
                    self.assertEqual(self.ids(response),{self.records[app][0 if active else 1].pk})
                    self.assertEqual(response.context['page_obj'].paginator.count,1)

    def test_name_search_across_full_database_not_current_page(self):
        for index in range(20):Level.objects.create(name=f'اختبار صفحات {index}',is_active=True)
        target=Level.objects.create(name='إبرة في آخر القائمة')
        response=self.client.get(self.url('levels'),{'q':'إبرة'})
        self.assertEqual(self.ids(response),{target.pk})

    def test_choice_labels_and_government_phrase(self):
        response=self.client.get(self.url('entities'),{'q':'غير حكومي'})
        self.assertIn(self.records['entities'][1].pk,self.ids(response))
        self.assertNotIn(self.records['entities'][0].pk,self.ids(response))
        response=self.client.get(self.url('entities'),{'q':'حكومي'})
        self.assertIn(self.records['entities'][0].pk,self.ids(response))
        self.assertNotIn(self.records['entities'][1].pk,self.ids(response))
        response=self.client.get(self.url('entities'),{'q':'خاص كبير'})
        self.assertIn(self.records['entities'][1].pk,self.ids(response))
        response=self.client.get(self.url('training_programs'),{'q':'الدورة التطويرية'})
        self.assertIn(self.records['training_programs'][0].pk,self.ids(response))
        self.assertNotIn(self.records['training_programs'][1].pk,self.ids(response))

    def test_training_types_and_sponsorship_values(self):
        for word,index in [('تدريبي',0),('تشغيلي',1)]:
            response=self.client.get(self.url('training_programs'),{'q':'فحص البحث '+word})
            self.assertEqual(self.ids(response),{self.records['training_programs'][index].pk})
        for word,index in [('نعم',0),('لا',1),('وصف فرصة مميزة',0)]:
            response=self.client.get(self.url('sponsorship_shapes'),{'q':'فحص البحث '+word})
            self.assertEqual(self.ids(response),{self.records['sponsorship_shapes'][index].pk})

    def test_related_names_are_searchable_without_duplicate_rows(self):
        response=self.client.get(self.url('sectors'),{'q':'خبرة مشتركة'})
        self.assertEqual(self.ids(response),{self.records['sectors'][0].pk})
        self.assertEqual(response.context['page_obj'].paginator.count,1)
        response=self.client.get(self.url('training_programs'),{'q':'مصروف مرتبط'})
        self.assertEqual(self.ids(response),{self.records['training_programs'][0].pk})
        self.assertEqual(response.context['page_obj'].paginator.count,1)
        response=self.client.get(self.url('specializations'),{'q':self.records['sectors'][0].name})
        self.assertIn(self.records['specializations'][0].pk,self.ids(response))

    def test_status_phrase_in_search(self):
        for word,index in [('نشط',0),('غير نشط',1),('inactive',1)]:
            response=self.client.get(self.url('levels'),{'q':'فحص البحث '+word})
            self.assertEqual(self.ids(response),{self.records['levels'][index].pk})

    def test_empty_results_and_clear_link(self):
        for app in self.routes:
            with self.subTest(app=app):
                response=self.client.get(self.url(app),{'q':'لن توجد هذه العبارة أبدًا'})
                self.assertEqual(response.context['page_obj'].paginator.count,0)
                self.assertContains(response,'لا توجد نتائج مطابقة')
                self.assertContains(response,f'href="{self.url(app)}">مسح')
                self.assertContains(response,'نتائج البحث:')

    def test_pagination_and_form_actions_keep_filters(self):
        for index in range(20):Level.objects.create(name=f'مجموعة صفحات {index}',is_active=True)
        params={'q':'مجموعة صفحات','status':'1'}
        response=self.client.get(self.url('levels'),params)
        self.assertEqual(response.context['page_obj'].paginator.count,20)
        self.assertEqual(len(response.context['rows']),15)
        links=LinkCollector();links.feed(response.content.decode())
        self.assertIn({'q':[params['q']], 'status':['1'], 'page':['2']}, [parse_qs(urlsplit(link).query) for link in links.links])
        response=self.client.get(self.url('levels'),{**params,'page':2})
        self.assertEqual(len(response.context['rows']),5)
        self.assertIn('page=2',response.context['settings_filter_query'])
        self.assertContains(response,'&amp;page=2&amp;edit=')
        self.assertContains(response,'action="/settings/levels/?')

    def test_confirmation_and_success_keep_filters(self):
        for app in self.routes:
            with self.subTest(app=app):
                query=urlencode({'q':'فحص البحث '+app,'status':'1'})
                url=self.url(app)+'?'+query
                response=self.client.get(url)
                row=response.context['rows'][0]
                preview=self.client.post(url,{'action':'preview','snapshot':row['toggle_snapshot']})
                self.assertEqual(preview.status_code,200)
                self.assertEqual(preview.context['settings_filter_status'],'1')
                self.assertContains(preview,'class="settings-filters"',count=1)
                token=preview.context['pending']['token']
                response=self.client.post(url,{'action':'confirm','token':token})
                self.assertEqual(response.status_code,302)
                self.assertEqual(parse_qs(urlsplit(response.url).query),{'q':['فحص البحث '+app],'status':['1']})
                self.records[app][0].refresh_from_db()
                self.assertFalse(self.records[app][0].is_active)
                self.assertEqual(self.client.get(response.url).context['page_obj'].paginator.count,0)

    def test_get_editor_keeps_filters(self):
        for app in self.routes:
            with self.subTest(app=app):
                response=self.client.get(self.url(app),{'q':'فحص البحث '+app,'status':'1','edit':self.records[app][0].pk})
                self.assertEqual(response.status_code,200)
                self.assertTrue(response.context['editing'])
                self.assertNotIn('edit=',response.context['settings_filter_query'])
                self.assertContains(response,'class="settings-filters"',count=1)

    def test_development_states_excluded_and_partnerships_unchanged(self):
        response=self.client.get('/settings/development-states/',{'q':'غير مهم','status':'0'})
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'class="settings-filters"')
        response=self.client.get('/partnerships/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'class="register-search"')
        self.assertNotContains(response,'class="settings-filters"')

    def test_malformed_parameters_escaped_and_bounded(self):
        response=self.client.get(self.url('levels'),{'q':'<script>alert(1)</script>','status':'bad','page':'garbage'})
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'<script>alert(1)</script>')
        self.assertContains(response,'&lt;script&gt;')
        self.assertEqual(response.context['settings_filter_status'],'')
        response=self.client.get(self.url('levels'),{'q':'x'*1000,'page':'9999999999999999999'})
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.context['settings_filter_q']),200)
        self.assertNotIn('page=',response.context['settings_filter_query'])
