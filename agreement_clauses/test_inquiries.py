from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.defaults import initialize
from accounts.models import Department
from agreement_clauses.models import AgreementClassification, AgreementClause, ClauseAssignment, Responsibility
from care_states.models import DevelopmentState
from entities.models import Entity
from makken_mail.models import WorkAssignment
from partnerships.models import Partnership, PartnershipTeamMember, PartnershipType, TeamMemberRole, TeamSide
from regions.models import Region

User = get_user_model()
AUTH_BACKEND = 'accounts.backends.EmailOrUsernameBackend'


class UnifiedPartnershipInquiryUS18Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()
        cls.admin = User.objects.create_superuser('inq-admin', 'inq-admin@makken.test', 'AdminPass!9876')
        cls.emp_a = User.objects.create_user('inq-emp-a', 'emp-a@makken.test', 'Pass!9876', first_name='أحمد', last_name='الشمري')
        cls.emp_b = User.objects.create_user('inq-emp-b', 'emp-b@makken.test', 'Pass!9876', first_name='سارة', last_name='العتيبي')

        cls.reg_riyadh = Region.objects.create(name='منطقة الرياض للاستعلام')
        cls.reg_makkah = Region.objects.create(name='منطقة مكة للاستعلام')
        cls.dept_1 = Department.objects.create(name='إدارة التدريب للاستعلام')
        cls.dept_2 = Department.objects.create(name='إدارة الجودة للاستعلام')
        cls.entity = Entity.objects.create(name='جهة استعلام موحدة', entity_type='government')
        cls.ptype = PartnershipType.objects.first()
        cls.pcls = AgreementClassification.objects.first()
        cls.clause_1 = AgreementClause.objects.create(name='بند استعلام 1')
        cls.clause_2 = AgreementClause.objects.create(name='بند استعلام 2')

        # Willingness Partnership 1 (2026, Riyadh, dept_1, progress 70%)
        cls.p1 = Partnership.objects.create(
            name='شراكة استعلام الرياض الأولى',
            representative='خالد القحطاني',
            phone_country='SA',
            phone='+966501110001',
            email='p1@makken.test',
            entity=cls.entity,
            scope='local',
            development_state_id=DevelopmentState.WILLINGNESS,
            partnership_type=cls.ptype,
            agreement_classification=cls.pcls,
            signing_region=cls.reg_riyadh,
            signing_city='الرياض',
            headquarters_city='الرياض',
            signed_on=date(2026, 3, 10),
            duration_months=24,
            institution_signatory='د. ماجد الدوسري',
            partner_signatory='م. طارق الحربي',
            institution_rep_name='سلمان العسيري',
            created_by=cls.admin,
        )
        cls.p1.ensure_agreement_number()
        cls.p1.administrative_regions.add(cls.reg_riyadh)
        cls.p1.concerned_departments.add(cls.dept_1)
        ClauseAssignment.objects.create(partnership=cls.p1, clause=cls.clause_1, responsibility=Responsibility.INSTITUTION, progress=60)
        ClauseAssignment.objects.create(partnership=cls.p1, clause=cls.clause_2, responsibility=Responsibility.PARTNER, progress=80)
        PartnershipTeamMember.objects.create(
            partnership=cls.p1, side=TeamSide.INSTITUTION, name='عبدالله الغامدي',
            phone='+966501234000', email='contact@tvtc.gov.sa', organization='التشاركية', role=TeamMemberRole.CONTACT,
        )
        w1 = WorkAssignment.objects.create(
            created_by=cls.admin, title='متابعة شراكة الرياض', employee=cls.emp_a, manager=cls.admin,
            target_model='partnerships.partnership', target_key=cls.p1.pk,
        )
        w1.assignees.set([cls.emp_a])

        # Willingness Partnership 2 (2025, Makkah, dept_2, progress 100%)
        cls.p2 = Partnership.objects.create(
            name='شراكة استعلام مكة الثانية',
            representative='نورة السبيعي',
            phone_country='SA',
            phone='+966502220002',
            email='p2@makken.test',
            entity=cls.entity,
            scope='local',
            development_state_id=DevelopmentState.WILLINGNESS,
            signing_region=cls.reg_makkah,
            signed_on=date(2025, 6, 1),
            duration_months=12,
            institution_signatory='د. فهد الزهراني',
            created_by=cls.admin,
        )
        cls.p2.ensure_agreement_number()
        cls.p2.administrative_regions.add(cls.reg_makkah)
        cls.p2.concerned_departments.add(cls.dept_2)
        ClauseAssignment.objects.create(partnership=cls.p2, clause=cls.clause_1, responsibility=Responsibility.SHARED, progress=100)
        w2 = WorkAssignment.objects.create(
            created_by=cls.admin, title='متابعة شراكة مكة', employee=cls.emp_b, manager=cls.admin,
            target_model='partnerships.partnership', target_key=cls.p2.pk,
        )
        w2.assignees.set([cls.emp_b])

        cls.url = reverse('partnerships:agreement_inquiries')

    def setUp(self):
        self.client.force_login(self.admin, backend=AUTH_BACKEND)

    def test_all_us18_search_dimensions_stats_and_detail_modal(self):
        # 1. Partner name / agreement number
        r = self.client.get(self.url, {'q': 'الرياض الأولى'})
        self.assertEqual([x['partnership'].pk for x in r.context['rows']], [self.p1.pk])

        # 2. Year + stats
        r = self.client.get(self.url, {'year': '2026'})
        self.assertEqual([x['partnership'].pk for x in r.context['rows']], [self.p1.pk])
        self.assertEqual(r.context['stats']['total_count'], 1)
        self.assertEqual(r.context['stats']['avg_progress'], Decimal('70.00'))

        # 3. Signatory
        r = self.client.get(self.url, {'signatory': 'طارق الحربي'})
        self.assertEqual([x['partnership'].pk for x in r.context['rows']], [self.p1.pk])

        # 4. Concerned department
        r = self.client.get(self.url, {'department': str(self.dept_2.pk)})
        self.assertEqual([x['partnership'].pk for x in r.context['rows']], [self.p2.pk])

        # 5. Region + stats
        r = self.client.get(self.url, {'region': str(self.reg_makkah.pk)})
        self.assertEqual([x['partnership'].pk for x in r.context['rows']], [self.p2.pk])
        self.assertEqual(r.context['stats']['completed_count'], 1)

        # 6. Team member by email/phone/name
        r = self.client.get(self.url, {'team': 'contact@tvtc.gov.sa'})
        self.assertEqual([x['partnership'].pk for x in r.context['rows']], [self.p1.pk])

        # 7. Contact officer
        r = self.client.get(self.url, {'contact': 'عبدالله الغامدي'})
        self.assertEqual([x['partnership'].pk for x in r.context['rows']], [self.p1.pk])

        # 8. Representative
        r = self.client.get(self.url, {'representative': 'سلمان العسيري'})
        self.assertEqual([x['partnership'].pk for x in r.context['rows']], [self.p1.pk])

        # 9. Progress range
        r = self.client.get(self.url, {'progress_min': '65', 'progress_max': '75'})
        self.assertEqual([x['partnership'].pk for x in r.context['rows']], [self.p1.pk])

        # 10. Employee + stats
        r = self.client.get(self.url, {'employee': str(self.emp_a.pk)})
        self.assertEqual([x['partnership'].pk for x in r.context['rows']], [self.p1.pk])
        self.assertEqual(r.context['stats']['total_count'], 1)

        # Detail modal opens with all data and no legacy agreement links
        d = self.client.get(self.url, {'detail': str(self.p1.pk)})
        self.assertEqual(d.status_code, 200)
        self.assertIsNotNone(d.context['detail_row'])
        self.assertContains(d, 'id="inquiry-detail"')
        self.assertContains(d, 'د. ماجد الدوسري')
        self.assertNotContains(d, 'بطاقة المتابعة')

    def test_invalid_numeric_filters_return_400_instead_of_500(self):
        self.client.force_login(self.admin)
        url = reverse('partnerships:agreement_inquiries')
        res = self.client.get(url, {'progress_min': '1', 'progress_max': '/'})
        self.assertEqual(res.status_code, 400)
        self.assertTrue(res.context['filter_error'])
        res_yr = self.client.get(url, {'year': 'abc'})
        self.assertEqual(res_yr.status_code, 400)
        self.assertContains(res_yr, 'type="number"', status_code=400)
