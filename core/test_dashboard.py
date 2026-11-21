"""Dashboard correctness, scopes, historical semantics and genuine exports."""
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal
from io import BytesIO
from zipfile import ZipFile
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.db.models import Sum
from django.http import QueryDict
from django.test import TestCase, Client, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse, resolve
from django.utils import timezone
from access_control.defaults import initialize
from access_control.models import UserAccess, PermissionOverride, RoleProfile, Module, UserActivity
from market_needs.tests.test_market import MarketFixtures
from market_needs.models import Need, NeedExecution, Sponsorship, ExecutionProvider
from service_providers.models import ServiceProvider, ProviderCoverage
from levels.models import Level
from .dashboard_data import Dashboard, SQL_TZ
from .dashboard_presenter import build_charts


class DashboardTests(MarketFixtures,TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData();initialize()
        cls.reader=get_user_model().objects.create_user('dashboard-reader',password='Safe!Dashboard123')
        cls.regional=get_user_model().objects.create_user('dashboard-region',password='Safe!Dashboard124')
        for user in [cls.reader,cls.regional]:
            a=UserAccess.objects.create(user=user,page_scope='all',region_scope='selected' if user==cls.regional else 'all')
            if user==cls.regional:a.allowed_regions.add(cls.region)
            for module in ['dashboard','market_needs','partnerships','service_providers','approved_programs','provider_assignments']:
                PermissionOverride.objects.create(user=user,module_id=module,operation='view',effect='grant')

    def setUp(self):
        super().setUp()
        self.own=self.create_need(title='VISIBLE_OWN',regions=[str(self.region.pk)],beneficiaries='10')
        self.shared=self.create_need(title='VISIBLE_SHARED',regions=[str(self.region.pk),str(self.region2.pk)],beneficiaries='20')
        self.hidden=self.create_need(title='PRIVATE_HIDDEN',regions=[str(self.region2.pk)],beneficiaries='30')
        self.org=self.organization(name='SPONSOR_ALLOWED');self.org.administrative_regions.add(self.region)
        self.secret=self.organization(name='SPONSOR_PRIVATE');self.secret.administrative_regions.add(self.region2)

    def report(self,user=None,**data):
        q=QueryDict('',mutable=True)
        for key,value in data.items():
            if isinstance(value,list):q.setlist(key,[str(v) for v in value])
            else:q[key]=str(value)
        return Dashboard(user or self.user,q)

    def support(self,need,org=None,amount='100.00',level=None,decided_at='now'):
        row=Sponsorship.objects.create(need=need,partnership=org or self.org,status='approved',amount=Decimal(amount),
            decided_at=timezone.now() if decided_at=='now' else decided_at,
            level=level,level_name=level.name if level else '')
        value=need.sponsorships.filter(status='approved').aggregate(v=Sum('amount'))['v']
        Need.objects.filter(pk=need.pk).update(approved_support=value,status='complete' if value==need.total_cost else 'working')
        need.refresh_from_db();return row

    def provider(self,name='PROVIDER_USED',regions=None):
        item=ServiceProvider.objects.create(name=name,provider_type='government',scope='local',program=self.program)
        for region in regions or [self.region]:
            c=ProviderCoverage.objects.create(provider=item,region=region);c.specializations.add(self.spec)
        return item

    def execute(self,need,status='new',providers=(),completed_at=None):
        row=NeedExecution.objects.create(need=need,status=status,completed_at=completed_at or (timezone.now() if status=='complete' else None))
        for p in providers:ExecutionProvider.objects.create(execution=row,provider=p)
        return row

    def login_as(self,user=None):
        self.client.force_login(user or self.reader,backend='accounts.backends.EmailOrUsernameBackend')

    def grant(self,format,user=None):
        PermissionOverride.objects.create(user=user or self.reader,module_id='dashboard',operation='export_'+format,effect='grant')

    def test_home_replaces_existing_route_without_second_dashboard(self):
        self.assertEqual(resolve('/').view_name,'makken_home')
        self.login_as();response=self.client.get('/')
        self.assertContains(response,'لوحة المتابعة')
        self.assertNotContains(response,'معًا نمكّن')
        self.assertIn('no-store',response['Cache-Control'])
        self.assertNotIn("'unsafe-inline'",response['Content-Security-Policy'])

    def test_empty_authorized_data_has_real_zero_counts(self):
        Need.objects.all().delete();report=self.report()
        self.assertEqual(report.summary['cards'],0)
        self.assertEqual(report.summary['cost'],Decimal('0.00'))
        self.assertEqual(report.summary['percentage'],0)
        self.assertEqual(report.execution_summary['percentage'],0)

    def test_regions_and_expenses_do_not_multiply_card_counts_or_costs(self):
        summary=self.report().summary
        self.assertEqual(summary['cards'],3)
        self.assertEqual(summary['cost'],Decimal('300.00'))
        self.assertEqual(summary['beneficiaries'],60)
        self.assertEqual(summary['programs'],1)

    def test_union_of_regions_deduplicates_overlapping_cards(self):
        report=self.report(regions=[self.region.pk,self.region2.pk])
        self.assertTrue(report.valid)
        self.assertEqual(report.summary['cards'],3)
        self.assertEqual(report.summary['cost'],300)

    def test_shared_finance_is_a_disjoint_bucket_not_an_equal_split(self):
        self.support(self.shared,amount='80')
        report=self.report(regions=[self.region.pk])
        rows=report.financial_regions
        self.assertEqual(report.summary['cards'],2)
        self.assertEqual(sum(r['cost'] for r in rows),report.summary['cost'])
        self.assertEqual(sum(r['approved'] for r in rows),80)
        self.assertEqual(next(r for r in rows if r['bucket']==-2)['approved'],80)
        self.assertEqual(next(r for r in rows if r['bucket']==self.region.pk)['approved'],0)

    def test_regional_scoping_precedes_aggregation_and_hides_other_region_names(self):
        report=self.report(self.regional)
        self.assertEqual(report.summary['cards'],2)
        self.assertEqual(report.summary['beneficiaries'],30)
        self.assertEqual([r['regions__name'] for r in report.region_rows],[self.region.name])
        self.assertNotIn(self.region2.pk,dict(report.form.fields['regions'].choices))
        self.assertFalse(self.report(self.regional,regions=[self.region2.pk]).valid)

    def test_legacy_unassigned_region_is_not_invented(self):
        self.own.regions.clear()
        self.assertTrue(any(r['bucket']==-1 for r in self.report().financial_regions))
        self.assertEqual(self.report(self.regional).summary['cards'],1)

    def test_dashboard_only_does_not_grant_business_aggregates(self):
        PermissionOverride.objects.filter(user=self.reader).exclude(module_id='dashboard').delete()
        self.login_as()
        with CaptureQueriesContext(connection) as queries:response=self.client.get('/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'مؤشرات بطاقات حاجة السوق والتمويل غير متاحة')
        self.assertIsNone(response.context['dashboard'].summary)
        self.assertNotContains(response,'VISIBLE_OWN')
        self.assertFalse(any('FROM "market_needs_need"' in q['sql'] for q in queries))

    def test_source_page_revoke_applies_immediately(self):
        self.login_as();self.assertContains(self.client.get('/'),'VISIBLE_OWN')
        PermissionOverride.objects.filter(user=self.reader,module_id='market_needs').update(effect='deny')
        response=self.client.get('/')
        self.assertIsNone(response.context['dashboard'].summary)
        self.assertNotContains(response,'SPONSOR_ALLOWED')

    def test_user_page_scope_limits_sources_even_when_permissions_granted(self):
        access=UserAccess.objects.get(user=self.reader);access.page_scope='selected';access.save();access.allowed_pages.add('dashboard')
        report=self.report(self.reader)
        self.assertIsNone(report.summary);self.assertIsNone(report.execution_summary)

    def test_missing_dashboard_permission_redirects_home_but_denies_exports(self):
        PermissionOverride.objects.filter(user=self.reader,module_id='dashboard').delete()
        self.login_as()
        self.assertEqual(self.client.get('/').status_code,302)
        self.assertEqual(self.client.get(reverse('core:dashboard_export',args=['xlsx'])).status_code,403)

    def test_activation_is_card_status_not_historical_provider_status(self):
        Need.objects.filter(pk=self.own.pk).update(is_active=False)
        self.assertEqual(self.report(activation='0').summary['cards'],1)
        self.assertEqual(self.report(activation='1').summary['cards'],2)

    def test_invalid_filters_never_fall_back_to_all_data(self):
        for params in [{'regions':['999999']},{'program':'999999'},{'date_from':'bad','period':'custom'},
                       {'period':'custom','date_from':'2026-12-01','date_to':'2026-01-01'},
                       {'period':'custom'},{'training_type':'UNKNOWN'},{'activation':'yes'}]:
            with self.subTest(params=params):
                r=self.report(**params);self.assertFalse(r.valid);self.assertEqual(r.summary['cards'],0)

    def test_specialization_is_restricted_to_selected_sector(self):
        self.create_need(title='OTHER_SECTOR',sector=str(self.sector2.pk),specialization=str(self.spec2.pk))
        self.assertFalse(self.report(sector=self.sector.pk,specialization=self.spec2.pk).valid)
        self.assertEqual(self.report(sector=self.sector.pk,specialization=self.spec.pk).summary['cards'],3)

    def test_program_and_training_type_filters_use_saved_card_data(self):
        Need.objects.filter(pk=self.own.pk).update(training_type='تشغيلي')
        self.assertEqual(self.report(training_type='تشغيلي').summary['cards'],1)
        self.assertEqual(self.report(program=self.program.pk).summary['cards'],3)

    def test_inactive_reference_remains_filterable_for_history(self):
        # Simulate a historical/imported inactive reference; normal UI deactivation remains protected.
        type(self.program).objects.filter(pk=self.program.pk).update(is_active=False)
        self.assertTrue(self.report(program=self.program.pk).valid)
        self.assertEqual(self.report(program=self.program.pk).summary['cards'],3)

    def test_weighted_coverage_is_not_average_of_card_percentages(self):
        self.shared.expense_lines.update(amount=Decimal('450'))
        Need.objects.filter(pk=self.shared.pk).update(total_cost=900)
        self.support(self.own)
        self.assertEqual(self.report(regions=[self.region.pk]).summary['percentage'],Decimal('10.00'))

    def test_rejected_and_new_candidates_do_not_count_as_approved_money(self):
        Sponsorship.objects.create(need=self.own,partnership=self.org,status='rejected',rejection_reason='test')
        Sponsorship.objects.create(need=self.shared,partnership=self.org)
        self.assertEqual(self.report().summary['approved'],0)
        self.assertEqual(self.report().organization_summary['sponsors'],0)

    def test_card_cohort_includes_lifetime_approved_support(self):
        Need.objects.filter(pk=self.own.pk).update(created_at=datetime(2026,10,5,tzinfo=dt_timezone.utc))
        Need.objects.filter(pk=self.shared.pk).update(created_at=datetime(2026,11,5,tzinfo=dt_timezone.utc))
        Need.objects.filter(pk=self.hidden.pk).update(created_at=datetime(2026,12,5,tzinfo=dt_timezone.utc))
        self.support(self.shared,decided_at=datetime(2026,10,10,tzinfo=dt_timezone.utc))
        r=self.report(period='custom',date_from='2026-11-01',date_to='2026-11-30')
        self.assertEqual(r.summary['cards'],1);self.assertEqual(r.summary['approved'],100)
        self.assertEqual(r.monthly_support,[])

    def test_approval_timeline_uses_decided_date_even_for_older_cards(self):
        Need.objects.filter(pk=self.own.pk).update(created_at=datetime(2026,10,5,tzinfo=dt_timezone.utc))
        self.support(self.own,decided_at=datetime(2026,11,6,tzinfo=dt_timezone.utc))
        r=self.report(period='custom',date_from='2026-11-01',date_to='2026-11-30')
        self.assertEqual(sum(x['value'] for x in r.monthly_support),100)

    def test_missing_approval_date_is_reported_without_invented_month(self):
        self.support(self.own,decided_at=None)
        r=self.report();self.assertEqual(r.missing_approval_dates,1)
        self.assertEqual(r.monthly_support,[]);self.assertEqual(r.summary['approved'],100)

    def test_date_boundaries_are_inclusive_in_riyadh(self):
        times=[datetime(2026,11,7,21,tzinfo=dt_timezone.utc),datetime(2026,11,8,20,59,59,tzinfo=dt_timezone.utc),datetime(2026,11,8,21,tzinfo=dt_timezone.utc)]
        for n,t in zip([self.own,self.shared,self.hidden],times):Need.objects.filter(pk=n.pk).update(created_at=t)
        r=self.report(period='custom',date_from='2026-11-08',date_to='2026-11-08')
        self.assertEqual(r.summary['cards'],2)

    def test_month_grouping_handles_utc_boundary_without_timezone_tables(self):
        Need.objects.filter(pk=self.own.pk).update(created_at=datetime(2026,10,31,21,tzinfo=dt_timezone.utc))
        r=self.report(period='custom',date_from='2026-11-01',date_to='2026-11-01')
        self.assertEqual(r.monthly_cards[0]['month'].month,11)
        self.assertEqual(SQL_TZ.tzname(None),'UTC+03:00')
        from django.db.backends.mysql.operations import DatabaseOperations
        self.assertEqual(DatabaseOperations(None)._prepare_tzname_delta(SQL_TZ.tzname(None)),'+03:00')

    def test_stale_complete_cache_is_not_execution_eligibility(self):
        Need.objects.filter(pk=self.own.pk).update(status='complete',approved_support=100)
        self.assertEqual(self.report().execution_summary['total'],0)
        self.assertEqual(self.report().summary['mismatch'],1)

    def test_waiting_is_subset_of_new_execution_and_counts_real_links(self):
        self.support(self.own);self.support(self.shared)
        e=self.execute(self.own)
        self.assertEqual(self.report().execution_summary['waiting'],2)
        ExecutionProvider.objects.create(execution=e,provider=self.provider())
        data=self.report().execution_summary
        self.assertEqual(data['new'],2);self.assertEqual(data['waiting'],1)

    def test_execution_states_and_beneficiaries_are_separate_from_funding(self):
        self.support(self.own);self.support(self.shared)
        self.execute(self.own,'running');self.execute(self.shared,'complete')
        r=self.report();e=r.execution_summary
        self.assertEqual(e['running'],1);self.assertEqual(e['complete'],1)
        self.assertEqual(e['running_beneficiaries'],10);self.assertEqual(e['completed_beneficiaries'],20)
        self.assertEqual(e['percentage'],50)
        self.assertEqual(r.summary['complete'],2)

    def test_completion_timeline_uses_completed_at_not_updated_at(self):
        self.support(self.own)
        e=self.execute(self.own,'complete',completed_at=datetime(2026,10,10,tzinfo=dt_timezone.utc))
        NeedExecution.objects.filter(pk=e.pk).update(updated_at=datetime(2026,11,8,tzinfo=dt_timezone.utc))
        r=self.report(period='custom',date_from='2026-11-01',date_to='2026-11-30')
        self.assertEqual(r.completion_months,[])

    def test_matching_candidates_are_not_counted_as_assigned_providers(self):
        self.support(self.own);self.provider()
        self.assertEqual(self.report().provider_query.count(),0)
        self.assertEqual(self.report().provider_rows(),[])

    def test_multiple_providers_do_not_multiply_global_beneficiaries(self):
        self.support(self.own)
        self.execute(self.own,'running',[self.provider('PROVIDER_A'),self.provider('PROVIDER_B')])
        r=self.report();rows=r.provider_rows()
        self.assertEqual(len(rows),2);self.assertEqual(r.execution_summary['running_beneficiaries'],10)
        self.assertEqual([x['beneficiaries'] for x in rows],[10,10])

    def test_historical_inactive_provider_is_still_a_real_assignment(self):
        self.support(self.own);p=self.provider();self.execute(self.own,'complete',[p])
        type(p).objects.filter(pk=p.pk).update(is_active=False)
        self.assertEqual(self.report().provider_rows()[0]['complete'],1)

    def test_regional_provider_and_partner_boundaries_are_independent(self):
        self.support(self.own,self.secret)
        p=self.provider(regions=[self.region2]);self.execute(self.own,'complete',[p])
        r=self.report(self.regional)
        self.assertEqual(r.summary['approved'],100)
        self.assertEqual(r.provider_rows(),[]);self.assertEqual(r.donor_rows(),[])

    def test_highest_level_counts_each_sponsor_once_and_preserves_snapshot(self):
        silver=Level.objects.get(funding_key='silver');gold=Level.objects.get(funding_key='gold')
        self.support(self.own,amount='60',level=silver);self.support(self.shared,amount='80',level=gold)
        old=gold.name;gold.name='CHANGED_LEVEL_NAME';gold.save()
        r=self.report();self.assertEqual(r.organization_summary['level_3'],1)
        self.assertEqual(r.organization_summary['level_2'],0)
        row=r.donor_rows()[0]
        self.assertEqual(row['cards'],2);self.assertEqual(row['amount'],140);self.assertEqual(row['snapshot_label'],old)

    def test_legacy_null_level_is_unclassified_not_recalculated(self):
        self.support(self.own)
        self.assertEqual(self.report().organization_summary['level_0'],1)

    def test_actual_partner_state_not_willingness_search_alias(self):
        Sponsorship.objects.create(need=self.own,partnership=self.org)
        self.org.development_state_id='capability';self.org.save()
        d=self.report().organization_summary
        self.assertEqual(d['capability'],1);self.assertEqual(d['willingness'],0)

    def test_single_partial_individual_full_and_alliance_are_distinct(self):
        self.support(self.own,amount='30')
        self.support(self.shared)
        self.support(self.hidden,self.org,amount='20');self.support(self.hidden,self.secret,amount='30')
        a=self.report().arrangement
        self.assertEqual(a['partial'],1);self.assertEqual(a['individual'],1);self.assertEqual(a['alliance'],1)

    def test_default_roles_get_no_new_export_grants(self):
        for key in ['editor','watcher']:
            self.assertFalse(RoleProfile.objects.get(system_key=key).group.permissions.filter(codename__in=['export_xlsx_dashboard','export_pdf_dashboard']).exists())
        self.assertEqual(Module.objects.get(pk='dashboard').operations,['view','export_xlsx','export_pdf'])

    def test_export_formats_are_independent_and_require_dashboard_view(self):
        self.login_as()
        for fmt in ['xlsx','pdf']:
            self.assertEqual(self.client.get(reverse('core:dashboard_export',args=[fmt])).status_code,403)
        self.grant('xlsx')
        self.assertEqual(self.client.get(reverse('core:dashboard_export',args=['pdf'])).status_code,403)
        PermissionOverride.objects.filter(user=self.reader,module_id='dashboard',operation='view').update(effect='deny')
        self.assertEqual(self.client.get(reverse('core:dashboard_export',args=['xlsx'])).status_code,403)

    def test_real_xlsx_has_all_sections_rtl_and_formula_safe_text(self):
        self.own.title='=FORMULA_NOT_EXECUTED';self.own.save()
        self.support(self.own,level=Level.objects.get(funding_key='strategic'))
        self.login_as();self.grant('xlsx')
        r=self.client.get(reverse('core:dashboard_export',args=['xlsx']))
        self.assertEqual(r.status_code,200)
        with ZipFile(BytesIO(r.content)) as z:xml=''.join(z.read(n).decode() for n in z.namelist() if n.endswith('.xml'))
        self.assertIn('rightToLeft="1"',xml);self.assertIn('ملخص البطاقات',xml);self.assertIn('الجهات الراعية',xml)
        self.assertNotIn('<f>',xml)

    def test_pdf_is_a_real_document_with_selectable_text(self):
        self.login_as();self.grant('pdf')
        r=self.client.get(reverse('core:dashboard_export',args=['pdf']))
        self.assertEqual(r.status_code,200);self.assertTrue(r.content.startswith(b'%PDF-'))
        from pypdf import PdfReader
        p=PdfReader(BytesIO(r.content));self.assertTrue(p.pages)
        self.assertTrue(any(page.extract_text() for page in p.pages))

    def test_invalid_filters_and_format_never_export_unfiltered_data(self):
        self.login_as();self.grant('xlsx')
        self.assertEqual(self.client.get(reverse('core:dashboard_export',args=['xlsx']),{'regions':'999999'}).status_code,400)
        self.assertEqual(self.client.get(reverse('core:dashboard_export',args=['csv'])).status_code,400)

    @override_settings(MAKKEN_EXPORT_MAX_ROWS=1)
    def test_export_size_limit_is_enforced(self):
        self.login_as();self.grant('xlsx')
        self.assertEqual(self.client.get(reverse('core:dashboard_export',args=['xlsx'])).status_code,413)

    def test_export_lock_returns_user_friendly_retry(self):
        from core.table_exports import EXPORT_LOCK
        self.login_as();self.grant('xlsx')
        EXPORT_LOCK.acquire()
        try:r=self.client.get(reverse('core:dashboard_export',args=['xlsx']))
        finally:EXPORT_LOCK.release()
        self.assertEqual(r.status_code,429);self.assertEqual(r['Retry-After'],'20')

    def test_regional_export_contains_no_other_region_or_private_org(self):
        self.support(self.own,self.secret)
        self.login_as(self.regional);self.grant('xlsx',self.regional)
        r=self.client.get(reverse('core:dashboard_export',args=['xlsx']))
        with ZipFile(BytesIO(r.content)) as z:xml=''.join(z.read(n).decode() for n in z.namelist() if n.endswith('.xml'))
        self.assertNotIn(self.region2.name,xml);self.assertNotIn('SPONSOR_PRIVATE',xml)

    def test_view_and_whole_report_export_are_logged_once(self):
        self.login_as();self.grant('xlsx')
        with self.captureOnCommitCallbacks(execute=True):
            self.client.get('/')
            self.client.get(reverse('core:dashboard_export',args=['xlsx']))
        self.assertEqual(UserActivity.objects.filter(module='dashboard',action='view').count(),1)
        self.assertEqual(UserActivity.objects.filter(module='dashboard',action='export_xlsx').count(),1)

    def test_drilldown_preserves_filters_and_does_not_allow_source_bypass(self):
        self.login_as(self.regional)
        path=reverse('core:dashboard_records',args=['cards'])
        r=self.client.get(path,{'regions':[self.region.pk]})
        self.assertEqual(r.context['page_obj'].paginator.count,2)
        self.assertNotContains(r,'PRIVATE_HIDDEN')
        self.assertEqual(self.client.get(path,{'state':'UNKNOWN'}).status_code,400)
        self.assertEqual(self.client.get(path,{'bucket':self.region2.pk}).status_code,400)
        PermissionOverride.objects.filter(user=self.regional,module_id='partnerships').update(effect='deny')
        self.assertEqual(self.client.get(reverse('core:dashboard_records',args=['donors'])).status_code,403)

    def test_unknown_drilldown_kind_and_post_are_not_write_routes(self):
        self.login_as(self.user)
        self.assertEqual(self.client.get(reverse('core:dashboard_records',args=['sql'])).status_code,404)
        self.assertEqual(self.client.post('/').status_code,405)

    def test_chart_values_have_real_table_alternatives_and_no_inline_styles(self):
        self.login_as();r=self.client.get('/')
        self.assertContains(r,'data-chart-open');self.assertContains(r,'pathLength="100"')
        self.assertNotContains(r,'style="')
        self.assertContains(r,'id="dash-chart-dialog"')

    def test_no_business_writes_when_loading_or_exporting(self):
        self.login_as();self.grant('xlsx')
        before=list(Need.objects.values('pk','version','status','total_cost','approved_support'))
        self.client.get('/');self.client.get(reverse('core:dashboard_export',args=['xlsx']))
        self.assertEqual(before,list(Need.objects.values('pk','version','status','total_cost','approved_support')))

    def test_query_count_does_not_grow_per_card(self):
        self.login_as()
        with CaptureQueriesContext(connection) as first:self.client.get('/')
        for i in range(16):self.create_need(title='EXTRA_CARD_'+str(i))
        with CaptureQueriesContext(connection) as second:self.client.get('/')
        self.assertLessEqual(len(second),len(first)+2)
        self.assertLessEqual(len(second),75)

    def test_date_index_is_available_for_range_filter(self):
        if connection.vendor=='sqlite':
            plan=Need.objects.filter(created_at__gte=timezone.now()).order_by().values('pk').explain()
            self.assertIn('dash_need_created_idx',plan)

    def test_actionable_lists_exclude_inactive_and_rejected_cards(self):
        Need.objects.filter(pk=self.own.pk).update(is_active=False)
        Need.objects.filter(pk=self.shared.pk).update(status='rejected')
        self.assertEqual(list(self.report().underfunded_cards.values_list('pk',flat=True)),[self.hidden.pk])
        self.support(self.own)
        self.assertEqual(self.report().waiting_cards.count(),0)
        self.assertEqual(self.report().execution_summary['waiting'],0)

    def test_maximum_end_date_is_a_validation_error_not_a_server_error(self):
        report=self.report(period='custom',date_from='2026-01-01',date_to='9999-12-31')
        self.assertFalse(report.valid)
        self.assertIn('date_to',report.form.errors)

    def test_whole_report_contains_followup_sections_beyond_preview(self):
        from .dashboard_presenter import report_table
        for i in range(8):self.create_need(title='REPORT_FOLLOWUP_'+str(i))
        self.support(self.own)
        report=self.report()
        text=str(report_table(report,build_charts(report),5000).rows)
        self.assertIn('REPORT_FOLLOWUP_7',text)
        self.assertIn('بطاقات نشطة تنتظر مزودًا',text)

    def test_consistent_snapshot_does_not_change_session_isolation(self):
        from contextlib import nullcontext
        from types import SimpleNamespace
        from .dashboard_snapshot import consistent_dashboard
        cursor=__import__('unittest.mock',fromlist=['MagicMock']).MagicMock()
        fake=SimpleNamespace(vendor='mysql',in_atomic_block=False,cursor=lambda:cursor)
        with patch('core.dashboard_snapshot.connection',fake), patch('core.dashboard_snapshot.transaction.atomic',return_value=nullcontext()):
            self.assertEqual(consistent_dashboard(lambda:42)(),42)
        cursor.__enter__.return_value.execute.assert_called_once_with('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        fake.in_atomic_block=True;cursor.reset_mock()
        with patch('core.dashboard_snapshot.connection',fake), patch('core.dashboard_snapshot.transaction.atomic',return_value=nullcontext()):
            consistent_dashboard(lambda:42)()
        cursor.assert_not_called()
