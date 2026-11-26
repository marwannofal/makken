"""Tests for dedicated capability and willingness partnership pages and creating directly in willingness."""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.defaults import initialize
from care_states.models import DevelopmentState
from entities.models import Entity
from regions.models import Region
from sectors.models import Sector
from specializations.models import Specialization
from sponsorship_shapes.models import SponsorshipShape

from .models import DevelopmentHistory, Partnership

User = get_user_model()
AUTH_BACKEND = 'accounts.backends.EmailOrUsernameBackend'


class SplitCapabilityWillingnessPagesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()

    def setUp(self):
        self.admin = User.objects.create_superuser('split_admin', 'split_admin@example.com', 'StrongPass123!')
        self.region = Region.objects.create(name='منطقة فصل الشراكات', is_active=True)
        self.entity = Entity.objects.create(name='جهة فصل الشراكات', entity_type='government', is_active=True)
        self.sector = Sector.objects.create(name='قطاع فصل الشراكات', is_active=True)
        self.spec = Specialization.objects.create(name='تخصص فصل الشراكات', sector=self.sector, is_active=True)
        self.shape = SponsorshipShape.objects.create(name='رعاية فصل الشراكات', is_active=True)

        self.p_cap = Partnership.objects.create(
            name='جهة قدرة مستقلة',
            representative='أحمد',
            phone='0501111111',
            email='cap@example.com',
            entity=self.entity,
            scope='local',
            development_state_id=DevelopmentState.CAPABILITY,
        )
        self.p_will = Partnership.objects.create(
            name='جهة رغبة مستقلة',
            representative='سالم',
            phone='0502222222',
            email='will@example.com',
            entity=self.entity,
            scope='local',
            development_state_id=DevelopmentState.WILLINGNESS,
        )

    def test_capability_and_willingness_pages_are_separate_and_titled(self):
        self.client.force_login(self.admin, backend=AUTH_BACKEND)

        cap_res = self.client.get(reverse('partnerships:capability_index'))
        self.assertEqual(cap_res.status_code, 200)
        self.assertContains(cap_res, 'إدارة سجل شراكات القدرة')
        self.assertContains(cap_res, 'جهة قدرة مستقلة')
        self.assertNotContains(cap_res, 'جهة رغبة مستقلة')

        will_res = self.client.get(reverse('partnerships:willingness_index'))
        self.assertEqual(will_res.status_code, 200)
        self.assertContains(will_res, 'إدارة سجل شراكات الرغبة')
        self.assertContains(will_res, 'جهة رغبة مستقلة')
        self.assertNotContains(will_res, 'جهة قدرة مستقلة')

    def test_can_create_partnership_directly_in_willingness_state(self):
        self.client.force_login(self.admin, backend=AUTH_BACKEND)
        url = reverse('partnerships:create_willingness')
        get_res = self.client.get(url)
        self.assertEqual(get_res.status_code, 200)
        self.assertContains(get_res, 'إضافة جهة لسجل الشراكات المحتملة التي لها الرغبة')

        payload = {
            'action': 'preview',
            'snapshot': get_res.context['snapshot'],
            'name': 'جهة جديدة من الرغبة مباشرة',
            'representative': 'فيصل',
            'phone_country': 'SA',
            'phone': '0503333333',
            'email': 'newwill@example.com',
            'financial_capacity': '50000.00',
            'entity_type': 'government',
            'entity': str(self.entity.pk),
            'scope': 'local',
            'administrative_regions': [str(self.region.pk)],
            'partnership_date': '2026-11',
            'is_active': '1',
            'offerings': json.dumps([{
                'sector': self.sector.pk,
                'shape': self.shape.pk,
                'specializations': [self.spec.pk],
                'is_active': True,
            }]),
        }
        prev = self.client.post(url, payload)
        self.assertEqual(prev.status_code, 200)
        token = prev.context['pending']['token']

        conf = self.client.post(url, {'action': 'confirm', 'token': token})
        self.assertEqual(conf.status_code, 302)

        created = Partnership.objects.get(name='جهة جديدة من الرغبة مباشرة')
        self.assertEqual(created.development_state_id, DevelopmentState.WILLINGNESS)
        self.assertTrue(
            DevelopmentHistory.objects.filter(partnership=created, state_id=DevelopmentState.WILLINGNESS).exists()
        )

    def test_capability_and_willingness_detail_modals_show_only_corner_close_button(self):
        self.client.force_login(self.admin, backend=AUTH_BACKEND)
        for route, obj in (
            ('partnerships:capability_index', self.p_cap),
            ('partnerships:willingness_index', self.p_will),
        ):
            with self.subTest(route=route):
                res = self.client.get(reverse(route), {'detail': str(obj.pk)})
                self.assertEqual(res.status_code, 200)
                self.assertNotContains(res, '>تعديل بيانات الجهة</a>')
                self.assertContains(res, 'detail-dialog-actions')
                self.assertContains(res, 'detail-close-btn')
                self.assertContains(res, 'إغلاق')

    def test_partnerships_table_displays_only_entity_branch_column(self):
        self.client.force_login(self.admin, backend=AUTH_BACKEND)
        res = self.client.get(reverse('partnerships:capability_index'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, '<th scope="col">فرع الكيان</th>', html=True)
        self.assertNotContains(res, '<th scope="col">الكيان / فرعه</th>', html=True)

    def test_all_partnerships_page_lists_all_states_and_statuses_read_only(self):
        p_care = Partnership.objects.create(
            name='جهة رعاية مستقلة',
            representative='عمر',
            phone='0503333333',
            email='care@example.com',
            entity=self.entity,
            scope='local',
            development_state_id=DevelopmentState.CARE,
            is_active=True,
        )
        p_inactive = Partnership.objects.create(
            name='جهة غير نشطة مستقلة',
            representative='فيصل',
            phone='0504444444',
            email='inactive@example.com',
            entity=self.entity,
            scope='local',
            development_state_id=DevelopmentState.CAPABILITY,
            is_active=False,
        )
        self.client.force_login(self.admin, backend=AUTH_BACKEND)
        url = reverse('partnerships:all_index')
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'جميع الشراكات')
        for obj in (self.p_cap, self.p_will, p_care, p_inactive):
            self.assertContains(res, obj.name)
        self.assertNotContains(res, 'إضافة جهة جديدة')
        self.assertNotContains(res, 'delete-action')
        self.assertNotContains(res, 'تحويل إلى رغبة')
        self.assertContains(res, 'مشاهدة')
        self.assertEqual(self.client.post(url, {'action': 'preview'}).status_code, 405)
        will_only = self.client.get(url, {'development_state': 'رغبة'})
        self.assertEqual(will_only.status_code, 200)
        self.assertContains(will_only, self.p_will.name)
        self.assertNotContains(will_only, self.p_cap.name)
        self.assertNotContains(will_only, p_care.name)

    def test_capability_and_willingness_hide_development_state_filter_and_scope_rows(self):
        self.client.force_login(self.admin, backend=AUTH_BACKEND)

        # Capability page: hides development state filter and lists only قدرة
        cap_url = reverse('partnerships:capability_index')
        cap_res = self.client.get(cap_url)
        self.assertEqual(cap_res.status_code, 200)
        self.assertTrue(cap_res.context['hide_development_filter'])
        self.assertNotContains(cap_res, 'id="register-development-state"')
        self.assertNotContains(cap_res, 'name="development_state"')
        self.assertContains(cap_res, self.p_cap.name)
        self.assertNotContains(cap_res, self.p_will.name)

        # Willingness page: hides development state filter and lists only رغبة
        will_url = reverse('partnerships:willingness_index')
        will_res = self.client.get(will_url)
        self.assertEqual(will_res.status_code, 200)
        self.assertTrue(will_res.context['hide_development_filter'])
        self.assertNotContains(will_res, 'id="register-development-state"')
        self.assertNotContains(will_res, 'name="development_state"')
        self.assertContains(will_res, self.p_will.name)
        self.assertNotContains(will_res, self.p_cap.name)

        # Passing development_state query param manually cannot leak other states
        will_forced = self.client.get(will_url, {'development_state': 'قدرة'})
        self.assertEqual(will_forced.status_code, 200)
        self.assertContains(will_forced, self.p_will.name)
        self.assertNotContains(will_forced, self.p_cap.name)

        # All partnerships page still shows the development state filter
        all_res = self.client.get(reverse('partnerships:all_index'))
        self.assertEqual(all_res.status_code, 200)
        self.assertFalse(all_res.context['hide_development_filter'])
        self.assertContains(all_res, 'id="register-development-state"')

    def test_edit_capability_and_willingness_save_works_and_button_is_save(self):
        import json, re
        from partnerships.models import Partnership, PartnershipOffering, DevelopmentHistory, Scope
        self.client.force_login(self.admin, backend=AUTH_BACKEND)

        for state, from_param, expected_list_url in (
            (DevelopmentState.CAPABILITY, 'capability', reverse('partnerships:capability_index')),
            (DevelopmentState.WILLINGNESS, 'willingness', reverse('partnerships:willingness_index')),
        ):
            with self.subTest(state=state):
                p = Partnership.objects.create(
                    name=f'جهة تعديل {state}',
                    representative='ممثل الجهة',
                    phone_country='SA',
                    phone='+966501234567',
                    email=f'edit_{from_param}@example.com',
                    entity=self.entity,
                    scope=Scope.LOCAL,
                    is_active=True,
                    development_state_id=state,
                )
                DevelopmentHistory.objects.create(partnership=p, state_id=state)
                off = PartnershipOffering.objects.create(
                    partnership=p, sector=self.sector, sponsorship_shape=self.shape, is_active=True, position=0
                )
                off.specializations.set([self.spec])

                edit_url = reverse('partnerships:edit', args=[p.pk]) + f'?from={from_param}'
                res = self.client.get(edit_url)
                self.assertEqual(res.status_code, 200)
                html = res.content.decode('utf-8')
                self.assertNotContains(res, 'حفظ الجهة')
                self.assertIn('data-save-partnership', html)
                self.assertNotIn('<details class="mk-accordion" open>', html)
                if state == DevelopmentState.WILLINGNESS:
                    self.assertIsNone(re.search(r'<input[^>]*name="work-title"[^>]*\brequired\b', html))
                    self.assertIsNone(re.search(r'<select[^>]*name="work-manager"[^>]*\brequired\b', html))

                snap = re.search(r'name="snapshot" value="([^"]+)"', html).group(1)
                offerings_payload = json.dumps([
                    {'sector': self.sector.pk, 'specializations': [self.spec.pk], 'shape': self.shape.pk, 'is_active': True}
                ])
                preview_post = {
                    'action': 'preview',
                    'snapshot': snap,
                    'name': f'جهة محدثة {state}',
                    'representative': 'ممثل محدث',
                    'phone_country': 'SA',
                    'phone': '0501234567',
                    'email': f'updated_{from_param}@example.com',
                    'financial_capacity': '50000.00',
                    'entity_type': self.entity.entity_type,
                    'entity': str(self.entity.pk),
                    'scope': Scope.LOCAL,
                    'is_active': '1',
                    'offerings': offerings_payload,
                }
                if state == DevelopmentState.WILLINGNESS:
                    preview_post['clauses_json'] = '[]'
                    preview_post['teams_json'] = '[]'

                prev_res = self.client.post(edit_url, preview_post)
                self.assertEqual(prev_res.status_code, 200)
                prev_html = prev_res.content.decode('utf-8')
                token_m = re.search(r'name="token" value="([^"]+)"', prev_html)
                self.assertIsNotNone(token_m, f'Preview confirmation dialog missing for {state}')

                conf_res = self.client.post(edit_url, {'action': 'confirm', 'token': token_m.group(1)})
                self.assertEqual(conf_res.status_code, 302)
                self.assertTrue(conf_res['Location'].startswith(expected_list_url))
                p.refresh_from_db()
                self.assertEqual(p.name, f'جهة محدثة {state}')

    def test_existing_work_edit_opens_popup_and_updates_via_json_endpoint(self):
        from agreement_clauses.models import AgreementClause, ClauseAssignment, Responsibility
        from makken_mail.models import WorkAssignment, WorkStatus
        cl = AgreementClause.objects.create(name='بند اختباري للمهمة المنبثقة', is_active=True)
        ClauseAssignment.objects.create(
            clause=cl, partnership=self.p_will, responsibility=Responsibility.INSTITUTION, progress=65
        )
        emp = User.objects.create_user('work_emp_popup', 'work_emp_popup@example.com', 'StrongPass123!')
        mgr = User.objects.create_user('work_mgr_popup', 'work_mgr_popup@example.com', 'StrongPass123!')
        wk = WorkAssignment.objects.create(
            title='متابعة شراكة أولية',
            instructions='تعليمات أولية',
            target_model='partnerships.partnership',
            target_key=self.p_will.pk,
            employee=emp,
            manager=mgr,
            created_by=self.admin,
            status=WorkStatus.NEW,
            progress=0,
        )
        wk.assignees.set([emp])

        self.client.force_login(self.admin, backend=AUTH_BACKEND)
        edit_url = reverse('partnerships:edit', args=[self.p_will.pk]) + '?from=willingness'
        res = self.client.get(edit_url)
        self.assertEqual(res.status_code, 200)
        work_api_url = reverse('partnerships:work_edit', args=[self.p_will.pk, wk.pk])
        self.assertContains(res, f'data-edit-work-url="{work_api_url}"')
        self.assertNotContains(res, reverse('makken_mail:work_detail', args=[wk.pk]))
        self.assertContains(res, 'id="we-assignees" name="assignee_ids" multiple data-market-select')

        get_res = self.client.get(work_api_url)
        self.assertEqual(get_res.status_code, 200)
        self.assertEqual(get_res.json()['work']['title'], 'متابعة شراكة أولية')

        post_res = self.client.post(
            work_api_url,
            data=json.dumps({
                'title': 'متابعة شراكة محدثة',
                'assignee_ids': [emp.pk],
                'manager_id': mgr.pk,
                'status': WorkStatus.RUNNING,
                'progress': 65,
                'due_on': '2026-12-31',
                'instructions': 'تم تحديث التفاصيل من النافذة المنبثقة',
            }),
            content_type='application/json',
        )
        self.assertEqual(post_res.status_code, 200)
        data = post_res.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['work']['title'], 'متابعة شراكة محدثة')
        self.assertEqual(data['work']['progress'], 65)
        wk.refresh_from_db()
        self.assertEqual(wk.title, 'متابعة شراكة محدثة')
        self.assertEqual(wk.status, WorkStatus.RUNNING)
        self.assertEqual(wk.progress, 65)
