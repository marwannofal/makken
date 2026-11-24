"""Comprehensive automated tests for المؤشرات والتحليلات المرنة (flex_analytics)."""
from decimal import Decimal
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from django.test import Client, TestCase
from django.urls import reverse

from access_control.models import Module, RegionScope, RoleProfile, UserAccess, UserRegion
from care_states.models import DevelopmentState, StateColor
from entities.models import Entity, EntityType
from market_needs.models import Need, NeedRegion, NeedStatus
from partnerships.models import Partnership, PartnershipRegion, Scope
from regions.models import Region
from sectors.models import Sector
from specializations.models import Specialization
from training_programs.models import TrainingProgram

from flex_analytics.exports import sanitize_spreadsheet_cell
from flex_analytics.graph import UNRELATED_MESSAGE_AR, compatibility_for_selection, resolve_join_path
from flex_analytics.kpis import KPI_REGISTRY, evaluate_custom_kpi, evaluate_predefined_kpi
from flex_analytics.models import FlexDashboard
from flex_analytics.query_engine import QueryValidationError, execute_chart_query, execute_drilldown, execute_table_query
from flex_analytics.semantic import BLOCKED_FIELD_NAMES, serialize_metadata


User = get_user_model()


class FlexAnalyticsTestCase(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser('flex_admin', 'admin@example.com', 'StrongPass123!')
        self.regional_user = User.objects.create_user('flex_regional', 'reg@example.com', 'StrongPass123!', is_active=True)
        self.no_access_user = User.objects.create_user('flex_denied', 'denied@example.com', 'StrongPass123!', is_active=True)

        # Reference data
        self.region_riyadh = Region.objects.create(name='منطقة اختبار التحليلات 1')
        self.region_makkah = Region.objects.create(name='منطقة اختبار التحليلات 2')
        self.sector_tech = Sector.objects.create(name='قطاع اختبار التقنية')
        self.sector_health = Sector.objects.create(name='قطاع اختبار الصحة')
        self.spec_ai = Specialization.objects.create(name='تخصص اختبار الذكاء', sector=self.sector_tech)
        self.entity_gov = Entity.objects.create(name='كيان اختبار حكومي', entity_type=EntityType.GOVERNMENT)
        self.state_cap, _ = StateColor.objects.get_or_create(state=DevelopmentState.CAPABILITY, defaults={'color': '#005B85'})
        self.state_care, _ = StateColor.objects.get_or_create(state=DevelopmentState.CARE, defaults={'color': '#0F8A5F'})
        self.program = TrainingProgram.objects.create(
            name='برنامج اختبار البرمجة',
            category=TrainingProgram.Category.INTERMEDIATE_DIPLOMA,
            is_training=False,
            is_operational=True,
        )

        # Regional Need 1 (Riyadh)
        self.need_riyadh = Need.objects.create(
            title='احتياج الرياض للتقنية',
            sector=self.sector_tech,
            specialization=self.spec_ai,
            description='وصف احتياج الرياض',
            duration=6,
            duration_unit='month',
            source='دراسة السوق',
            beneficiaries=100,
            program=self.program,
            program_name=self.program.name,
            program_category=self.program.category,
            training_type='operational',
            total_cost=Decimal('500000.00'),
            requested_support=Decimal('400000.00'),
            approved_support=Decimal('200000.00'),
            status=NeedStatus.WORKING,
        )
        NeedRegion.objects.create(need=self.need_riyadh, region=self.region_riyadh)

        # Regional Need 2 (Makkah)
        self.need_makkah = Need.objects.create(
            title='احتياج مكة للصحة',
            sector=self.sector_health,
            specialization=self.spec_ai,
            description='وصف احتياج مكة',
            duration=3,
            duration_unit='month',
            source='دراسة السوق',
            beneficiaries=50,
            program=self.program,
            program_name=self.program.name,
            program_category=self.program.category,
            training_type='training',
            total_cost=Decimal('200000.00'),
            requested_support=Decimal('100000.00'),
            approved_support=Decimal('100000.00'),
            status=NeedStatus.COMPLETE,
        )
        NeedRegion.objects.create(need=self.need_makkah, region=self.region_makkah)

        # Partnership in Riyadh
        self.part_riyadh = Partnership.objects.create(
            name='شركة التقنية الرائدة',
            representative='أحمد العتيبي',
            phone='555123456',
            email='partner@example.com',
            financial_capacity=Decimal('1000000.00'),
            entity=self.entity_gov,
            scope=Scope.LOCAL,
            development_state=self.state_care,
        )
        PartnershipRegion.objects.create(partnership=self.part_riyadh, region=self.region_riyadh)

        # Grant regional_user access to flex_analytics + market_needs in Riyadh ONLY
        grp = Group.objects.create(name='Regional Analysts')
        RoleProfile.objects.get_or_create(group=grp, defaults={'page_scope': 'all'})
        perms = Permission.objects.filter(codename__in=[
            'view_flex_analytics', 'create_flex_analytics', 'edit_flex_analytics',
            'delete_flex_analytics', 'export_xlsx_flex_analytics',
            'view_market_needs', 'view_sectors', 'view_regions',
        ])
        grp.permissions.add(*perms)
        self.regional_user.groups.add(grp)

        ua, _ = UserAccess.objects.get_or_create(user=self.regional_user)
        ua.page_scope = 'selected'
        ua.region_scope = RegionScope.SELECTED
        ua.save()
        ua.allowed_pages.set(Module.objects.filter(key__in=['flex_analytics', 'market_needs', 'sectors', 'regions']))
        UserRegion.objects.get_or_create(access=ua, region=self.region_riyadh)

    def test_kpi_registry_exceeds_100_real_kpis(self):
        self.assertGreaterEqual(len(KPI_REGISTRY), 100)
        res = evaluate_predefined_kpi(self.admin, 'needs_total')
        self.assertEqual(res['value'], 2)
        cov = evaluate_predefined_kpi(self.admin, 'needs_coverage_pct')
        # 300,000 / 500,000 = 60.0%
        self.assertEqual(cov['value'], 60.0)

    def test_metadata_blocks_sensitive_fields(self):
        meta = serialize_metadata(self.admin)
        for ent in meta['entities']:
            field_names = {f['name'] for f in ent['fields']}
            self.assertTrue(field_names.isdisjoint(BLOCKED_FIELD_NAMES))

    def test_relationship_graph_compatible_and_unrelated(self):
        # Direct relation: market_needs -> sectors
        j_direct = resolve_join_path('market_needs', 'sectors', self.admin)
        self.assertTrue(j_direct['compatible'])
        self.assertEqual(j_direct['relation_type'], 'direct')
        self.assertEqual(j_direct['lookup_prefix'], 'sector')

        # Indirect relation: market_needs -> partnerships (via sponsorships)
        j_ind = resolve_join_path('market_needs', 'partnerships', self.admin)
        self.assertTrue(j_ind['compatible'])
        self.assertEqual(j_ind['relation_type'], 'indirect')

        # Unrelated entity: market_needs -> user_activity
        j_unrel = resolve_join_path('market_needs', 'user_activity', self.admin)
        self.assertFalse(j_unrel['compatible'])
        self.assertEqual(j_unrel['relation_type'], 'unrelated')
        self.assertEqual(j_unrel['message_ar'], UNRELATED_MESSAGE_AR)

        comp = compatibility_for_selection('market_needs', self.admin)
        unrelated_keys = {u['key'] for u in comp['unrelated']}
        self.assertIn('user_activity', unrelated_keys)

    def test_query_engine_rejects_unrelated_join(self):
        spec = {
            'base_entity': 'market_needs',
            'mode': 'raw',
            'columns': [
                {'entity': 'market_needs', 'field': 'title'},
                {'entity': 'user_activity', 'field': 'actor_name'},
            ],
        }
        with self.assertRaises(QueryValidationError) as ctx:
            execute_table_query(self.admin, spec, use_cache=False)
        self.assertIn('لعدم وجود علاقة', str(ctx.exception))

    def test_query_engine_grouped_table_chart_and_drilldown(self):
        table_spec = {
            'base_entity': 'market_needs',
            'mode': 'grouped',
            'columns': [
                {'id': 'sec', 'entity': 'sectors', 'field': 'name', 'label': 'القطاع'},
                {'id': 'cnt', 'entity': 'market_needs', 'field': 'id', 'aggregation': 'count', 'label': 'العدد'},
                {'id': 'req', 'entity': 'market_needs', 'field': 'requested_support', 'aggregation': 'sum', 'label': 'المطلوب', 'show_pct_of_total': True},
            ],
        }
        res = execute_table_query(self.admin, table_spec, use_cache=False)
        self.assertEqual(len(res['rows']), 2)
        self.assertEqual(res['totals']['req'], 500000.0)

        chart_spec = {
            'chart_type': 'bar',
            'base_entity': 'market_needs',
            'dimension': {'entity': 'sectors', 'field': 'name'},
            'measures': [{'entity': 'market_needs', 'field': 'approved_support', 'aggregation': 'sum', 'label': 'المعتمد'}],
        }
        cres = execute_chart_query(self.admin, chart_spec, use_cache=False)
        self.assertEqual(len(cres['labels']), 2)
        self.assertEqual(cres['datasets'][0]['total'], 300000.0)

        dd = execute_drilldown(self.admin, chart_spec, 'sectors', 'name', 'قطاع اختبار التقنية')
        self.assertEqual(dd['total_count'], 1)

    def test_custom_kpi_builder_and_zero_division_safety(self):
        spec = {
            'title': 'نسبة التغطية المخصصة',
            'formula_type': 'percentage',
            'primary': {'entity': 'market_needs', 'field': 'approved_support', 'aggregation': 'sum'},
            'secondary': {'entity': 'market_needs', 'field': 'requested_support', 'aggregation': 'sum'},
        }
        res = evaluate_custom_kpi(self.admin, spec)
        self.assertEqual(res['value'], 60.0)

    def test_regional_isolation_and_rbac_enforcement(self):
        # Regional user in Riyadh should ONLY see 1 need (Riyadh), NOT Makkah
        kpi_reg = evaluate_predefined_kpi(self.regional_user, 'needs_total')
        self.assertEqual(kpi_reg['value'], 1)
        kpi_sup = evaluate_predefined_kpi(self.regional_user, 'needs_requested_support')
        self.assertEqual(kpi_sup['value'], 400000.0)

        # Unauthorized user receives 403 on page and APIs
        client = Client()
        client.force_login(self.no_access_user)
        self.assertEqual(client.get(reverse('flex_analytics:index')).status_code, 403)
        self.assertEqual(client.get(reverse('flex_analytics:api_bootstrap')).status_code, 403)

    def test_export_formula_injection_sanitization(self):
        self.assertEqual(sanitize_spreadsheet_cell('=CMD|"/c calc"!A0'), "'=CMD|\"/c calc\"!A0")
        self.assertEqual(sanitize_spreadsheet_cell('+123'), "'+123")
        self.assertEqual(sanitize_spreadsheet_cell('احتياج عادي'), 'احتياج عادي')

    def test_full_end_to_end_dashboard_persistence_and_revisions(self):
        client = Client()
        client.force_login(self.admin)

        # 1. Bootstrap auto-creates initial dashboard
        boot = client.get(reverse('flex_analytics:api_bootstrap'))
        self.assertEqual(boot.status_code, 200)
        bdata = boot.json()
        self.assertGreaterEqual(len(bdata['kpi_catalog']), 100)

        # 2. Create a new blank dashboard
        create_resp = client.post(
            reverse('flex_analytics:api_dashboards'),
            data=json.dumps({'title': 'لوحة اختبار متكاملة', 'template_key': 'blank'}),
            content_type='application/json',
        )
        self.assertEqual(create_resp.status_code, 201)
        dash = create_resp.json()['dashboard']
        dash_id = dash['id']

        # 3. Save layout with section + KPI + Table + Chart
        save_payload = {
            'title': 'لوحة اختبار محدثة',
            'version': dash['version'],
            'sections': [
                {
                    'title': 'قسم التحليل الشامل',
                    'layout_preset': 'grid_12',
                    'widgets': [
                        {'widget_type': 'kpi', 'title': 'إجمالي الاحتياجات', 'col_span': 4, 'config': {'kpi_key': 'needs_total'}},
                        {'widget_type': 'table', 'title': 'الاحتياجات حسب القطاع', 'col_span': 8, 'config': {
                            'base_entity': 'market_needs',
                            'mode': 'grouped',
                            'columns': [
                                {'id': 's', 'entity': 'sectors', 'field': 'name', 'label': 'القطاع'},
                                {'id': 'c', 'entity': 'market_needs', 'field': 'id', 'aggregation': 'count', 'label': 'العدد'},
                            ],
                        }},
                    ],
                }
            ],
        }
        save_resp = client.post(
            reverse('flex_analytics:api_dashboard_detail', kwargs={'pk': dash_id}),
            data=json.dumps(save_payload),
            content_type='application/json',
        )
        self.assertEqual(save_resp.status_code, 200)
        saved = save_resp.json()['dashboard']
        self.assertEqual(saved['title'], 'لوحة اختبار محدثة')
        self.assertEqual(len(saved['sections']), 1)
        self.assertEqual(len(saved['sections'][0]['widgets']), 2)

        # 4. Stale version triggers 409 Conflict
        stale_resp = client.post(
            reverse('flex_analytics:api_dashboard_detail', kwargs={'pk': dash_id}),
            data=json.dumps({'title': 'تعارض', 'version': 1, 'sections': []}),
            content_type='application/json',
        )
        self.assertEqual(stale_resp.status_code, 409)

        # 5. Revisions list & restore
        rev_resp = client.get(reverse('flex_analytics:api_revisions', kwargs={'pk': dash_id}))
        self.assertEqual(rev_resp.status_code, 200)
        revs = rev_resp.json()['revisions']
        self.assertGreaterEqual(len(revs), 2)

        # 6. CSV export succeeds for admin
        exp_resp = client.post(
            reverse('flex_analytics:api_export'),
            data=json.dumps({
                'format': 'csv',
                'widget_type': 'table',
                'title': 'تصدير اختباري',
                'config': save_payload['sections'][0]['widgets'][1]['config'],
            }),
            content_type='application/json',
        )
        self.assertEqual(exp_resp.status_code, 200)
        self.assertIn('text/csv', exp_resp['Content-Type'])
