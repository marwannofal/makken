"""US-08 tests: partnership achievement reports by year, region, sector, activity, status, RBAC, and exports."""
from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from access_control.defaults import initialize
from access_control.models import PermissionOverride, RegionScope, UserAccess
from agreement_clauses.models import Agreement, AgreementClause, AgreementDetails, AgreementOption, ClauseAssignment, OptionKind
from care_states.models import DevelopmentState
from entities.models import Entity
from regions.models import Region
from sectors.models import Sector
from specializations.models import Specialization
from sponsorship_shapes.models import SponsorshipShape

from .models import Partnership, PartnershipOffering

User = get_user_model()
AUTH_BACKEND = 'accounts.backends.EmailOrUsernameBackend'


class PartnershipAchievementUS08Tests(TestCase):
    @classmethod
    def setUpTestData(cls):
        initialize()

    def setUp(self):
        self.region_a = Region.objects.create(name='منطقة إنجاز أ', is_active=True)
        self.region_b = Region.objects.create(name='منطقة إنجاز ب', is_active=True)
        self.sector_tech = Sector.objects.create(name='قطاع التقنية للإنجاز', is_active=True)
        self.sector_ind = Sector.objects.create(name='قطاع الصناعة للإنجاز', is_active=True)
        self.spec_ai = Specialization.objects.create(name='تخصص الذكاء الاصطناعي', sector=self.sector_tech, is_active=True)
        self.spec_mech = Specialization.objects.create(name='تخصص الميكانيكا', sector=self.sector_ind, is_active=True)
        self.shape = SponsorshipShape.objects.create(name='رعاية تدريبية للإنجاز', is_active=True)
        self.entity = Entity.objects.create(name='جهة إنجاز اختبارية', entity_type='government', is_active=True)
        self.status_active_agr = AgreementOption.objects.create(kind=OptionKind.STATUS, name='سارية للإنجاز', is_active=True)

        self.admin = User.objects.create_superuser('ach_admin', 'ach_admin@example.com', 'StrongPass123!')
        self.regional_user = User.objects.create_user('ach_reg', 'ach_reg@example.com', 'StrongPass123!')
        self.no_perm_user = User.objects.create_user('ach_noperm', 'ach_noperm@example.com', 'StrongPass123!')

        acc, _ = UserAccess.objects.get_or_create(
            user=self.regional_user,
            defaults={'page_scope': 'all', 'region_scope': RegionScope.SELECTED},
        )
        acc.page_scope = 'all'
        acc.region_scope = RegionScope.SELECTED
        acc.save()
        acc.allowed_regions.set([self.region_a])
        PermissionOverride.objects.create(user=self.regional_user, module_id='partnership_achievement', operation='view', effect='grant')

        # Partnership A: Region A, 2025, Tech/AI, active, 100% progress (2 clauses: 100 + 100)
        self.p_a = Partnership.objects.create(
            name='شراكة إنجاز الرياض',
            entity=self.entity,
            scope='local',
            starts_on=date(2025, 3, 1),
            ends_on=date(2026, 3, 1),
            is_active=True,
            development_state_id=DevelopmentState.CARE,
        )
        self.p_a.administrative_regions.set([self.region_a])
        off_a = PartnershipOffering.objects.create(
            partnership=self.p_a, sector=self.sector_tech, sponsorship_shape=self.shape, is_active=True
        )
        off_a.specializations.set([self.spec_ai])
        agr_a = Agreement.objects.create(partnership=self.p_a, title='اتفاقية الرياض', created_by=self.admin)
        AgreementDetails.objects.create(
            agreement=agr_a,
            status=self.status_active_agr,
            signed_on=date(2025, 4, 1),
            duration_months=12,
        )
        clause1 = AgreementClause.objects.create(name='بند إنجاز أول', is_active=True)
        clause2 = AgreementClause.objects.create(name='بند إنجاز ثاني', is_active=True)
        ClauseAssignment.objects.create(agreement=agr_a, clause=clause1, responsibility='partner', progress=100)
        ClauseAssignment.objects.create(agreement=agr_a, clause=clause2, responsibility='institution', progress=100)

        # Partnership B: Region B, 2026, Industry/Mech, inactive, 50% progress
        self.p_b = Partnership.objects.create(
            name='شراكة إنجاز جدة',
            entity=self.entity,
            scope='local',
            starts_on=date(2026, 1, 10),
            ends_on=date(2026, 12, 31),
            is_active=False,
            development_state_id=DevelopmentState.CAPABILITY,
        )
        self.p_b.administrative_regions.set([self.region_b])
        off_b = PartnershipOffering.objects.create(
            partnership=self.p_b, sector=self.sector_ind, sponsorship_shape=self.shape, is_active=True
        )
        off_b.specializations.set([self.spec_mech])
        agr_b = Agreement.objects.create(partnership=self.p_b, title='اتفاقية جدة', created_by=self.admin)
        ClauseAssignment.objects.create(agreement=agr_b, clause=clause1, responsibility='partner', progress=50)

    def test_rbac_and_write_methods_denied(self):
        url = reverse('partnerships:achievement_report')
        self.client.force_login(self.no_perm_user, backend=AUTH_BACKEND)
        self.assertEqual(self.client.get(url).status_code, 403)

        self.client.force_login(self.regional_user, backend=AUTH_BACKEND)
        self.assertEqual(self.client.post(url).status_code, 403)

    def test_five_dimension_filters_and_grouping_for_superuser(self):
        url = reverse('partnerships:achievement_report')
        self.client.force_login(self.admin, backend=AUTH_BACKEND)

        # Unfiltered: sees both p_a (100%) and p_b (50%) -> avg 75.00%
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertNotContains(res, '<th scope="col">عدد الاتفاقيات</th>', html=True)
        self.assertNotContains(res, '<th scope="col">الاتفاقيات</th>', html=True)
        rep = res.context['report']
        self.assertEqual(rep['totals']['partnership_count'], 2)
        self.assertEqual(rep['totals']['completed_count'], 1)
        self.assertEqual(rep['totals']['avg_progress'], Decimal('75.00'))

        # Filter by year=2025 + sector=tech + activity=ai + status=agr:<id>
        res_f = self.client.get(url, {
            'year': '2025',
            'sector': str(self.sector_tech.pk),
            'activity': str(self.spec_ai.pk),
            'status': f'agr:{self.status_active_agr.pk}',
            'group_by': 'sector',
        })
        self.assertEqual(res_f.status_code, 200)
        rep_f = res_f.context['report']
        self.assertEqual([r['pk'] for r in rep_f['rows']], [self.p_a.pk])
        self.assertEqual(rep_f['totals']['avg_progress'], Decimal('100.00'))
        self.assertEqual(rep_f['groups'][0]['label'], self.sector_tech.name)

        # Filter by status=inactive + group_by=year
        res_inact = self.client.get(url, {'status': 'inactive', 'group_by': 'year'})
        rep_inact = res_inact.context['report']
        self.assertEqual([r['pk'] for r in rep_inact['rows']], [self.p_b.pk])
        self.assertEqual(rep_inact['groups'][0]['label'], '2026')

    def test_regional_scoping_and_export_permissions(self):
        url = reverse('partnerships:achievement_report')
        self.client.force_login(self.regional_user, backend=AUTH_BACKEND)

        # Sees only region_a partnership (p_a), never p_b
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual([r['pk'] for r in res.context['report']['rows']], [self.p_a.pk])

        # Attempting to filter by region_b returns validation error and 0 rows
        res_bad = self.client.get(url, {'region': str(self.region_b.pk)})
        self.assertEqual(res_bad.status_code, 200)
        self.assertTrue(res_bad.context['report']['errors'])
        self.assertEqual(res_bad.context['report']['rows'], [])

        # Without export_xlsx permission -> 403
        self.assertEqual(self.client.get(url, {'_mk_export': 'xlsx'}).status_code, 403)

        # Grant export_xlsx -> 200 with valid Excel file
        PermissionOverride.objects.create(
            user=self.regional_user, module_id='partnership_achievement', operation='export_xlsx', effect='grant'
        )
        ok_export = self.client.get(url, {'_mk_export': 'xlsx'})
        self.assertEqual(ok_export.status_code, 200)
        self.assertIn('spreadsheetml', ok_export['Content-Type'])

    def test_summary_and_details_tables_paginate_15_per_page_preserving_filters(self):
        from partnerships.models import Partnership
        url = reverse('partnerships:achievement_report')
        self.client.force_login(self.admin, backend=AUTH_BACKEND)

        for i in range(16):
            p = Partnership.objects.create(
                name=f'جهة ترقيم {i:02d}',
                representative=f'ممثل {i:02d}',
                phone_country='SA',
                phone=f'+96650000{i:04d}',
                email=f'page_{i}@example.com',
                entity=self.entity,
                scope='local',
                is_active=True,
                development_state_id=DevelopmentState.CAPABILITY,
            )
            p.administrative_regions.set([self.region_a])

        res1 = self.client.get(url, {'status': 'active'})
        self.assertEqual(res1.status_code, 200)
        self.assertEqual(len(res1.context['rows_page_obj']), 15)
        self.assertEqual(res1.context['rows_page_obj'].paginator.num_pages, 2)
        self.assertContains(res1, '1 / 2')
        self.assertContains(res1, 'status=active&amp;page=2')
        self.assertContains(res1, 'class="table-footer"')

        res2 = self.client.get(url, {'status': 'active', 'page': '2'})
        self.assertEqual(res2.status_code, 200)
        self.assertEqual(res2.context['rows_page_obj'].number, 2)
        self.assertContains(res2, '2 / 2')
        self.assertContains(res2, 'status=active&amp;page=1')
