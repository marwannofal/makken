from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from access_control.defaults import initialize
from access_control.models import PermissionOverride, RoleProfile, UserAccess
from entities.models import Entity
from partnerships.models import Partnership
from regions.models import Region

from .models import (
    Agreement,
    AgreementClause,
    AgreementDetails,
    AgreementMember,
    AgreementOption,
    ClauseAssignment,
    DepartmentType,
    OptionKind,
    TeamRole,
    TeamSide,
)

User = get_user_model()


class AgreementInquiriesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()
        cls.admin = User.objects.create_superuser('inquiry-admin', first_name='مدير الاستعلامات')
        cls.emp_a = User.objects.create_user('emp-alpha', first_name='أحمد', last_name='العتيبي')
        cls.emp_b = User.objects.create_user('emp-beta', first_name='سارة', last_name='القحطاني')
        cls.emp_other = User.objects.create_user('emp-gamma', first_name='خالد', last_name='الشمري')

        cls.riyadh = Region.objects.create(name='منطقة الرياض للاستعلام')
        cls.jeddah = Region.objects.create(name='منطقة مكة للاستعلام')
        cls.dammam = Region.objects.create(name='المنطقة الشرقية للاستعلام')

        emp_a_access = UserAccess.objects.create(user=cls.emp_a, page_scope='all', region_scope='selected')
        emp_a_access.allowed_regions.add(cls.riyadh)
        emp_b_access = UserAccess.objects.create(user=cls.emp_b, page_scope='all', region_scope='selected')
        emp_b_access.allowed_regions.add(cls.riyadh)
        emp_other_access = UserAccess.objects.create(user=cls.emp_other, page_scope='all', region_scope='selected')
        emp_other_access.allowed_regions.add(cls.jeddah)

        entity = Entity.objects.create(name='جهة اختبار الاستعلامات', entity_type='government')

        cls.partner_riyadh = Partnership.objects.create(name='شراكة الرياض', entity=entity, scope='local')
        cls.partner_riyadh.administrative_regions.add(cls.riyadh)

        cls.partner_shared = Partnership.objects.create(name='شراكة مشتركة', entity=entity, scope='local')
        cls.partner_shared.administrative_regions.add(cls.riyadh, cls.jeddah)

        cls.partner_jeddah = Partnership.objects.create(name='شراكة مكة فقط', entity=entity, scope='local')
        cls.partner_jeddah.administrative_regions.add(cls.jeddah)

        cls.partner_legacy = Partnership.objects.create(name='شراكة قديمة بلا منطقة', entity=entity, scope='local')

        cls.dept_training = AgreementOption.objects.create(
            kind=OptionKind.DEPARTMENT,
            name='إدارة التدريب',
            department_type=DepartmentType.DEPARTMENT,
        )
        cls.dept_quality = AgreementOption.objects.create(
            kind=OptionKind.DEPARTMENT,
            name='وحدة الجودة',
            department_type=DepartmentType.UNIT,
        )
        cls.status_active = AgreementOption.objects.create(kind=OptionKind.STATUS, name='سارية')

        cls.clause_1 = AgreementClause.objects.create(name='بند التنفيذ الأول')
        cls.clause_2 = AgreementClause.objects.create(name='بند المتابعة الثاني')
        cls.clause_3 = AgreementClause.objects.create(name='بند التقارير الثالث')

        # Agreement 1: Riyadh, 2026, progress = (33 + 34 + 34) / 3 = 33.67%
        cls.agr_1 = Agreement.objects.create(
            partnership=cls.partner_riyadh,
            title='اتفاقية تدريب الرياض',
            created_by=cls.admin,
        )
        cls.details_1 = AgreementDetails.objects.create(
            agreement=cls.agr_1,
            status=cls.status_active,
            signing_region=cls.riyadh,
            responsible_employee=cls.emp_a,
            department_representative=cls.emp_b,
            institution_signatory='د. فهد المنصور',
            partner_signatory='م. ناصر الدوسري',
            signed_on=date(2026, 3, 15),
            duration_months=12,
        )
        cls.details_1.departments.add(cls.dept_training, cls.dept_quality)
        AgreementMember.objects.create(
            agreement=cls.agr_1,
            side=TeamSide.INSTITUTION,
            name='سلمان الحربي',
            organization='المؤسسة',
            role=TeamRole.CONTACT,
            phone='0501234567',
            email='salman@makken.test',
        )
        AgreementMember.objects.create(
            agreement=cls.agr_1,
            side=TeamSide.PARTNER,
            name='ريم السبيعي',
            organization='الشريك التقني',
            role=TeamRole.MEMBER,
            phone='0557654321',
            email='reem@partner.test',
        )
        ClauseAssignment.objects.create(agreement=cls.agr_1, clause=cls.clause_1, responsibility='shared', progress=33)
        ClauseAssignment.objects.create(agreement=cls.agr_1, clause=cls.clause_2, responsibility='shared', progress=34)
        ClauseAssignment.objects.create(agreement=cls.agr_1, clause=cls.clause_3, responsibility='shared', progress=34)

        # Agreement 2: Shared (Riyadh + Jeddah), 2025, progress = 80.00%, NO contact officer (only representative)
        cls.agr_2 = Agreement.objects.create(
            partnership=cls.partner_shared,
            title='اتفاقية الجودة المشتركة',
            created_by=cls.admin,
        )
        cls.details_2 = AgreementDetails.objects.create(
            agreement=cls.agr_2,
            signing_region=cls.dammam,
            responsible_employee=cls.emp_b,
            department_representative=cls.emp_a,
            institution_signatory='أ. ماجد الزهراني',
            partner_signatory='أ. هدى العسيري',
            signed_on=date(2025, 11, 20),
            duration_months=24,
        )
        cls.details_2.departments.add(cls.dept_quality)
        AgreementMember.objects.create(
            agreement=cls.agr_2,
            side=TeamSide.INSTITUTION,
            name='سارة القحطاني',
            organization='وحدة الجودة',
            role=TeamRole.REPRESENTATIVE,
            phone='0540001111',
            email='sara.rep@makken.test',
        )
        ClauseAssignment.objects.create(agreement=cls.agr_2, clause=cls.clause_1, responsibility='institution', progress=80)

        # Agreement 3: Jeddah only (unauthorized for Riyadh-scoped user), 2026, progress = 100%
        cls.agr_3 = Agreement.objects.create(
            partnership=cls.partner_jeddah,
            title='اتفاقية مكة السرية',
            created_by=cls.admin,
        )
        cls.details_3 = AgreementDetails.objects.create(
            agreement=cls.agr_3,
            signing_region=cls.jeddah,
            responsible_employee=cls.emp_other,
            institution_signatory='د. فهد المنصور',
            signed_on=date(2026, 5, 1),
            duration_months=12,
        )
        cls.details_3.departments.add(cls.dept_training)
        AgreementMember.objects.create(
            agreement=cls.agr_3,
            side=TeamSide.PARTNER,
            name='ضابط مكة',
            organization='جهة مكة',
            role=TeamRole.CONTACT,
            phone='0599998888',
            email='makkah@partner.test',
        )
        ClauseAssignment.objects.create(agreement=cls.agr_3, clause=cls.clause_1, responsibility='partner', progress=100)

        # Agreement 4: Legacy partnership with no regions and no clauses (progress = None)
        cls.agr_4 = Agreement.objects.create(
            partnership=cls.partner_legacy,
            title='اتفاقية قديمة بدون بنود',
            created_by=cls.admin,
        )

    def setUp(self):
        self.url = reverse('partnerships:agreement_inquiries')
        self.client.force_login(self.admin, backend='accounts.backends.EmailOrUsernameBackend')

    def _make_user(self, username, *ops, region=None, scope='selected', deny_ops=()):
        user = User.objects.create_user(username)
        access = UserAccess.objects.create(user=user, page_scope='all', region_scope=scope)
        if scope == 'selected' and region is not None:
            access.allowed_regions.add(region)
        for op in ops:
            PermissionOverride.objects.create(user=user, module_id='partnerships', operation=op, effect='grant')
        for op in deny_ops:
            PermissionOverride.objects.create(user=user, module_id='partnerships', operation=op, effect='deny')
        return user

    def _result_ids(self, response):
        return [row['agreement'].pk for row in response.context['rows']]

    def test_individual_filters_and_arabic_digits(self):
        # Year (Western & Arabic numerals)
        self.assertEqual(set(self._result_ids(self.client.get(self.url, {'year': '2026'}))), {self.agr_1.pk, self.agr_3.pk})
        self.assertEqual(self._result_ids(self.client.get(self.url, {'year': '٢٠٢٥'})), [self.agr_2.pk])

        # Region (matches administrative region OR signing_region)
        self.assertEqual(set(self._result_ids(self.client.get(self.url, {'region': self.riyadh.pk}))), {self.agr_1.pk, self.agr_2.pk})
        self.assertEqual(self._result_ids(self.client.get(self.url, {'region': self.dammam.pk})), [self.agr_2.pk])

        # Signatory (institution & partner)
        self.assertEqual(set(self._result_ids(self.client.get(self.url, {'signatory': 'فهد المنصور'}))), {self.agr_1.pk, self.agr_3.pk})
        self.assertEqual(self._result_ids(self.client.get(self.url, {'signatory': 'هدى العسيري'})), [self.agr_2.pk])

        # Department (M2M without duplicates)
        res_dept = self.client.get(self.url, {'department': self.dept_quality.pk})
        self.assertEqual(set(self._result_ids(res_dept)), {self.agr_1.pk, self.agr_2.pk})
        self.assertEqual(len(self._result_ids(res_dept)), 2)

        # Team search by name, email, and phone (including Arabic digits)
        self.assertEqual(self._result_ids(self.client.get(self.url, {'team': 'ريم السبيعي'})), [self.agr_1.pk])
        self.assertEqual(self._result_ids(self.client.get(self.url, {'team': 'reem@partner.test'})), [self.agr_1.pk])
        self.assertEqual(self._result_ids(self.client.get(self.url, {'team': '٠٥٥٧٦٥٤٣٢١'})), [self.agr_1.pk])

        # Contact officer strictly filters role=TeamRole.CONTACT (distinct from department_representative and role=REPRESENTATIVE)
        self.assertEqual(self._result_ids(self.client.get(self.url, {'contact': 'سلمان الحربي'})), [self.agr_1.pk])
        self.assertEqual(self._result_ids(self.client.get(self.url, {'contact': '0501234567'})), [self.agr_1.pk])
        self.assertEqual(self._result_ids(self.client.get(self.url, {'contact': 'سارة القحطاني'})), [])
        self.assertEqual(self._result_ids(self.client.get(self.url, {'contact': 'ريم السبيعي'})), [])

        # Employee matches responsible_employee OR department_representative
        self.assertEqual(set(self._result_ids(self.client.get(self.url, {'employee': self.emp_a.pk}))), {self.agr_1.pk, self.agr_2.pk})
        self.assertEqual(self._result_ids(self.client.get(self.url, {'employee': self.emp_other.pk})), [self.agr_3.pk])

    def test_progress_range_rounding_boundaries_and_no_clauses(self):
        # agr_1 has 3 clauses (33, 34, 34) -> mean_progress = 33.67%
        res_exact = self.client.get(self.url, {'progress_min': '33.67', 'progress_max': '33.67'})
        self.assertEqual(self._result_ids(res_exact), [self.agr_1.pk])
        self.assertEqual(res_exact.context['rows'][0]['progress'], Decimal('33.67'))
        self.assertEqual(res_exact.context['rows'][0]['clause_count'], 3)

        # Just above / below rounded boundary
        self.assertEqual(self._result_ids(self.client.get(self.url, {'progress_max': '33.66'})), [])
        self.assertEqual(self._result_ids(self.client.get(self.url, {'progress_min': '33.68', 'progress_max': '79.99'})), [])

        # Numeric range excludes agreements without clauses (agr_4)
        res_all_percent = self.client.get(self.url, {'progress_min': '0', 'progress_max': '100'})
        self.assertNotIn(self.agr_4.pk, self._result_ids(res_all_percent))
        self.assertEqual(set(self._result_ids(res_all_percent)), {self.agr_1.pk, self.agr_2.pk, self.agr_3.pk})

    def test_combined_filters_and_semantics_and_no_m2m_duplicates(self):
        response = self.client.get(self.url, {
            'year': '2026',
            'region': self.riyadh.pk,
            'signatory': 'فهد',
            'department': self.dept_training.pk,
            'team': 'سلمان',
            'contact': 'salman@makken.test',
            'employee': self.emp_a.pk,
            'progress_min': '30',
            'progress_max': '40',
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._result_ids(response), [self.agr_1.pk])

        # Changing one criterion to mismatch yields empty results
        miss = self.client.get(self.url, {
            'year': '2026',
            'region': self.riyadh.pk,
            'progress_min': '50',
        })
        self.assertEqual(self._result_ids(miss), [])
        self.assertContains(miss, 'لا توجد اتفاقيات مطابقة لمعايير الاستعلام')

    def test_invalid_inputs_return_empty_with_arabic_errors(self):
        bad_year = self.client.get(self.url, {'year': 'abcd'})
        self.assertEqual(bad_year.status_code, 200)
        self.assertTrue(bad_year.context['filter_error'])
        self.assertEqual(self._result_ids(bad_year), [])
        self.assertContains(bad_year, 'أدخل سنة صالحة')

        bad_range = self.client.get(self.url, {'progress_min': '80', 'progress_max': '20'})
        self.assertTrue(bad_range.context['filter_error'])
        self.assertEqual(self._result_ids(bad_range), [])
        self.assertContains(bad_range, 'أكبر من أو تساوي النسبة الدنيا')

        bad_pct = self.client.get(self.url, {'progress_max': '150'})
        self.assertTrue(bad_pct.context['filter_error'])
        self.assertEqual(self._result_ids(bad_pct), [])

        bad_decimals = self.client.get(self.url, {'progress_min': '12.345'})
        self.assertTrue(bad_decimals.context['filter_error'])
        self.assertEqual(self._result_ids(bad_decimals), [])

    def test_pagination_and_filter_persistence(self):
        for idx in range(16):
            agr = Agreement.objects.create(partnership=self.partner_riyadh, title=f'اتفاقية ترقيم {idx}', created_by=self.admin)
            AgreementDetails.objects.create(agreement=agr, signed_on=date(2024, 1, 10), duration_months=12)

        page_1 = self.client.get(self.url, {'year': '2024', 'region': self.riyadh.pk})
        self.assertEqual(page_1.context['page_obj'].paginator.count, 16)
        self.assertEqual(len(page_1.context['rows']), 15)
        self.assertIn('year=2024', page_1.context['pagination_query'])
        self.assertIn(f'region={self.riyadh.pk}', page_1.context['pagination_query'])

        page_2 = self.client.get(self.url, {'year': '2024', 'region': self.riyadh.pk, 'page': '2'})
        self.assertEqual(len(page_2.context['rows']), 1)
        self.assertNotIn('page=', page_2.context['pagination_query'])

    def test_regional_isolation_and_crafted_parameter_protection(self):
        riyadh_watcher = self._make_user('riyadh-watcher', 'view', region=self.riyadh, scope='selected')
        self.client.force_login(riyadh_watcher, backend='accounts.backends.EmailOrUsernameBackend')

        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        ids = set(self._result_ids(res))
        self.assertEqual(ids, {self.agr_1.pk, self.agr_2.pk})
        self.assertNotIn(self.agr_3.pk, ids)
        self.assertNotIn(self.agr_4.pk, ids)

        # Region & employee dropdowns do not leak out-of-scope regions/employees
        region_ids = set(res.context['form'].fields['region'].queryset.values_list('pk', flat=True))
        self.assertEqual(region_ids, {self.riyadh.pk})
        emp_ids = set(res.context['form'].fields['employee'].queryset.values_list('pk', flat=True))
        self.assertNotIn(self.emp_other.pk, emp_ids)

        # Crafted query targeting unauthorized region or employee returns empty + validation error
        crafted_region = self.client.get(self.url, {'region': self.jeddah.pk})
        self.assertTrue(crafted_region.context['filter_error'])
        self.assertEqual(self._result_ids(crafted_region), [])

        crafted_emp = self.client.get(self.url, {'employee': self.emp_other.pk})
        self.assertTrue(crafted_emp.context['filter_error'])
        self.assertEqual(self._result_ids(crafted_emp), [])

        # Crafted ?edit=1 must not break Watcher read access or grant mutations
        crafted_edit = self.client.get(self.url, {'edit': '1'})
        self.assertEqual(crafted_edit.status_code, 200)

    def test_rbac_positive_negative_and_ui_links(self):
        # Anonymous redirects to login
        self.assertEqual(Client().get(self.url).status_code, 302)

        # User without partnerships view is denied
        no_access = self._make_user('no-partnerships', scope='all')
        self.client.force_login(no_access, backend='accounts.backends.EmailOrUsernameBackend')
        self.assertEqual(self.client.get(self.url).status_code, 403)

        # Explicit deny overrides role-level view grant
        denied_user = self._make_user('denied-partnerships', scope='all', deny_ops=('view',))
        denied_user.groups.add(RoleProfile.objects.get(system_key='watcher').group)
        self.client.force_login(denied_user, backend='accounts.backends.EmailOrUsernameBackend')
        self.assertEqual(self.client.get(self.url).status_code, 403)

        # Watcher with view can read, cannot POST, and cannot export without export_xlsx
        watcher = self._make_user('watcher-all', 'view', scope='all')
        self.client.force_login(watcher, backend='accounts.backends.EmailOrUsernameBackend')
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'الاستعلامات عن الاتفاقيات')
        self.assertContains(res, reverse('partnerships:agreement', args=[self.partner_riyadh.pk, self.agr_1.pk]))
        self.assertContains(res, reverse('partnerships:agreement_details', args=[self.partner_riyadh.pk, self.agr_1.pk]))
        self.assertContains(res, 'إعادة تعيين الفلاتر')
        self.assertEqual(self.client.post(self.url, {'year': '2026'}).status_code, 403)
        self.assertEqual(self.client.get(self.url, {'_mk_export': 'xlsx'}).status_code, 403)
