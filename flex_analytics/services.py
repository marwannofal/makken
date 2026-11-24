"""Dashboard lifecycle, starter templates, revisions, and sharing services."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.db.models import Q

from .models import (
    FlexDashboard,
    FlexDashboardRevision,
    FlexDashboardSection,
    FlexDashboardShare,
    FlexDashboardTemplate,
    FlexDashboardWidget,
    LayoutPreset,
    SharePermission,
    WidgetType,
)


STARTER_TEMPLATES = [
    {
        'key': 'executive_overview',
        'title': 'اللوحة التنفيذية الشاملة',
        'description': 'نظرة متكاملة على احتياجات السوق، التمويل المعتمد، الشراكات، وتنفيذ البرامج التدريبية.',
        'category': 'تنفيذي',
        'snapshot': {
            'global_filters': {},
            'sections': [
                {
                    'title': 'المؤشرات الاستراتيجية الرئيسية',
                    'description': 'أهم مؤشرات الأداء الفورية من قاعدة البيانات الحية',
                    'layout_preset': LayoutPreset.COLS_4,
                    'widgets': [
                        {'widget_type': WidgetType.KPI, 'title': 'إجمالي احتياجات السوق', 'col_span': 3, 'row_span': 1, 'config': {'kpi_key': 'needs_total', 'variant': 'accent'}},
                        {'widget_type': WidgetType.KPI, 'title': 'إجمالي الدعم المعتمد', 'col_span': 3, 'row_span': 1, 'config': {'kpi_key': 'needs_approved_support', 'variant': 'standard'}},
                        {'widget_type': WidgetType.KPI, 'title': 'نسبة تغطية التمويل', 'col_span': 3, 'row_span': 1, 'config': {'kpi_key': 'needs_coverage_pct', 'variant': 'progress', 'target': 100}},
                        {'widget_type': WidgetType.KPI, 'title': 'الشراكات النشطة', 'col_span': 3, 'row_span': 1, 'config': {'kpi_key': 'part_active', 'variant': 'standard'}},
                    ],
                },
                {
                    'title': 'التوزيع التحليلي للتمويل والاحتياجات',
                    'description': 'مقارنة الدعم المطلوب والمعتمد حسب القطاع وحالة الاحتياجات',
                    'layout_preset': LayoutPreset.SPLIT_2_1,
                    'widgets': [
                        {
                            'widget_type': WidgetType.CHART,
                            'title': 'الدعم المطلوب مقابل المعتمد حسب القطاع',
                            'subtitle': 'أعلى 8 قطاعات',
                            'col_span': 8,
                            'row_span': 2,
                            'config': {
                                'chart_type': 'grouped_bar',
                                'base_entity': 'market_needs',
                                'dimension': {'entity': 'sectors', 'field': 'name', 'label': 'القطاع'},
                                'measures': [
                                    {'entity': 'market_needs', 'field': 'requested_support', 'aggregation': 'sum', 'label': 'الدعم المطلوب'},
                                    {'entity': 'market_needs', 'field': 'approved_support', 'aggregation': 'sum', 'label': 'الدعم المعتمد'},
                                ],
                                'top_n': 8,
                            },
                        },
                        {
                            'widget_type': WidgetType.CHART,
                            'title': 'توزيع حالات احتياجات السوق',
                            'subtitle': 'حسب الحالة الحالية',
                            'col_span': 4,
                            'row_span': 2,
                            'config': {
                                'chart_type': 'donut',
                                'base_entity': 'market_needs',
                                'dimension': {'entity': 'market_needs', 'field': 'status', 'label': 'الحالة'},
                                'measures': [
                                    {'entity': 'market_needs', 'field': 'id', 'aggregation': 'count', 'label': 'عدد الاحتياجات'},
                                ],
                                'top_n': 10,
                            },
                        },
                    ],
                },
                {
                    'title': 'جدول متابعة الاحتياجات حسب القطاع والمنطقة',
                    'description': 'ملخص تجميعي قابل للتخصيص والتصدير والتفصيل',
                    'layout_preset': LayoutPreset.COLS_1,
                    'widgets': [
                        {
                            'widget_type': WidgetType.TABLE,
                            'title': 'ملخص الاحتياجات والمستفيدين حسب القطاع',
                            'subtitle': 'مرتب حسب الدعم المطلوب',
                            'col_span': 12,
                            'row_span': 2,
                            'config': {
                                'base_entity': 'market_needs',
                                'mode': 'grouped',
                                'columns': [
                                    {'id': 'sec', 'entity': 'sectors', 'field': 'name', 'label': 'القطاع'},
                                    {'id': 'cnt', 'entity': 'market_needs', 'field': 'id', 'aggregation': 'count', 'label': 'عدد الاحتياجات'},
                                    {'id': 'ben', 'entity': 'market_needs', 'field': 'beneficiaries', 'aggregation': 'sum', 'label': 'المستفيدون'},
                                    {'id': 'req', 'entity': 'market_needs', 'field': 'requested_support', 'aggregation': 'sum', 'label': 'الدعم المطلوب'},
                                    {'id': 'app', 'entity': 'market_needs', 'field': 'approved_support', 'aggregation': 'sum', 'label': 'الدعم المعتمد', 'show_pct_of_total': True},
                                ],
                                'sort': [{'col_id': 'req', 'dir': 'desc'}],
                                'top_n': 15,
                            },
                        },
                    ],
                },
            ],
        },
    },
    {
        'key': 'partnerships_funding',
        'title': 'لوحة الشراكات والتمويل',
        'description': 'تحليل مراحل تطور الشراكات، القدرة المالية، عروض الرعاية، ومعدلات الاعتماد.',
        'category': 'الشراكات',
        'snapshot': {
            'global_filters': {},
            'sections': [
                {
                    'title': 'مؤشرات منظومة الشراكات',
                    'layout_preset': LayoutPreset.COLS_4,
                    'widgets': [
                        {'widget_type': WidgetType.KPI, 'title': 'جهات في مرحلة الرعاية', 'col_span': 3, 'row_span': 1, 'config': {'kpi_key': 'part_stage_care', 'variant': 'accent'}},
                        {'widget_type': WidgetType.KPI, 'title': 'معدل التحويل للرعاية', 'col_span': 3, 'row_span': 1, 'config': {'kpi_key': 'part_care_conversion', 'variant': 'progress', 'target': 100}},
                        {'widget_type': WidgetType.KPI, 'title': 'إجمالي القدرة المالية', 'col_span': 3, 'row_span': 1, 'config': {'kpi_key': 'part_total_capacity'}},
                        {'widget_type': WidgetType.KPI, 'title': 'طلبات رعاة قيد المراجعة', 'col_span': 3, 'row_span': 1, 'config': {'kpi_key': 'sreq_new'}},
                    ],
                },
                {
                    'title': 'تحليل الشراكات حسب النطاق والكيان',
                    'layout_preset': LayoutPreset.COLS_2,
                    'widgets': [
                        {
                            'widget_type': WidgetType.CHART,
                            'title': 'توزيع الشراكات حسب الكيان',
                            'col_span': 6,
                            'row_span': 2,
                            'config': {
                                'chart_type': 'horizontal_bar',
                                'base_entity': 'partnerships',
                                'dimension': {'entity': 'entities', 'field': 'name', 'label': 'الكيان'},
                                'measures': [{'entity': 'partnerships', 'field': 'id', 'aggregation': 'count', 'label': 'عدد الشراكات'}],
                                'top_n': 10,
                            },
                        },
                        {
                            'widget_type': WidgetType.CHART,
                            'title': 'القدرة المالية حسب النطاق',
                            'col_span': 6,
                            'row_span': 2,
                            'config': {
                                'chart_type': 'pie',
                                'base_entity': 'partnerships',
                                'dimension': {'entity': 'partnerships', 'field': 'scope', 'label': 'النطاق'},
                                'measures': [{'entity': 'partnerships', 'field': 'financial_capacity', 'aggregation': 'sum', 'label': 'القدرة المالية'}],
                                'top_n': 6,
                            },
                        },
                    ],
                },
            ],
        },
    },
    {
        'key': 'execution_providers',
        'title': 'لوحة تنفيذ البرامج ومزودي الخدمة',
        'description': 'متابعة حالات التنفيذ، نسب الإنجاز، وتغطية مزودي خدمات التدريب بالمناطق.',
        'category': 'التنفيذ',
        'snapshot': {
            'global_filters': {},
            'sections': [
                {
                    'title': 'مؤشرات التنفيذ والمزودين',
                    'layout_preset': LayoutPreset.COLS_4,
                    'widgets': [
                        {'widget_type': WidgetType.KPI, 'title': 'ملفات التنفيذ', 'col_span': 3, 'row_span': 1, 'config': {'kpi_key': 'exec_total', 'variant': 'accent'}},
                        {'widget_type': WidgetType.KPI, 'title': 'برامج مكتملة التنفيذ', 'col_span': 3, 'row_span': 1, 'config': {'kpi_key': 'exec_complete'}},
                        {'widget_type': WidgetType.KPI, 'title': 'نسبة إكمال التنفيذ', 'col_span': 3, 'row_span': 1, 'config': {'kpi_key': 'exec_completion_rate', 'variant': 'progress', 'target': 100}},
                        {'widget_type': WidgetType.KPI, 'title': 'مزودو التدريب النشطون', 'col_span': 3, 'row_span': 1, 'config': {'kpi_key': 'prov_active'}},
                    ],
                },
                {
                    'title': 'توزيع حالات التنفيذ ونوع المزودين',
                    'layout_preset': LayoutPreset.COLS_2,
                    'widgets': [
                        {
                            'widget_type': WidgetType.CHART,
                            'title': 'حالات تنفيذ البرامج',
                            'col_span': 6,
                            'row_span': 2,
                            'config': {
                                'chart_type': 'funnel',
                                'base_entity': 'need_executions',
                                'dimension': {'entity': 'need_executions', 'field': 'status', 'label': 'حالة التنفيذ'},
                                'measures': [{'entity': 'need_executions', 'field': 'id', 'aggregation': 'count', 'label': 'العدد'}],
                            },
                        },
                        {
                            'widget_type': WidgetType.CHART,
                            'title': 'مزودو التدريب حسب النوع',
                            'col_span': 6,
                            'row_span': 2,
                            'config': {
                                'chart_type': 'donut',
                                'base_entity': 'service_providers',
                                'dimension': {'entity': 'service_providers', 'field': 'provider_type', 'label': 'نوع المزود'},
                                'measures': [{'entity': 'service_providers', 'field': 'id', 'aggregation': 'count', 'label': 'العدد'}],
                            },
                        },
                    ],
                },
            ],
        },
    },
]


def ensure_system_templates():
    if FlexDashboardTemplate.objects.filter(is_system=True).count() >= len(STARTER_TEMPLATES):
        return
    for tpl in STARTER_TEMPLATES:
        FlexDashboardTemplate.objects.get_or_create(
            key=tpl['key'],
            defaults={
                'title': tpl['title'],
                'description': tpl['description'],
                'category': tpl['category'],
                'is_system': True,
                'snapshot': tpl['snapshot'],
            },
        )


def get_org_default_dashboard():
    return (
        FlexDashboard.objects.filter(is_archived=False, owner__is_superuser=True)
        .order_by('-is_default', '-updated_at', 'id')
        .first()
        or FlexDashboard.objects.filter(is_archived=False)
        .order_by('-is_default', '-updated_at', 'id')
        .first()
    )


def can_view_dashboard(user, dashboard):
    if not user or not user.is_authenticated:
        return False
    if dashboard.owner_id == user.pk or user.is_superuser:
        return True
    group_ids = list(user.groups.values_list('id', flat=True))
    if FlexDashboardShare.objects.filter(
        dashboard=dashboard
    ).filter(
        Q(shared_with_user=user) | Q(shared_with_group_id__in=group_ids)
    ).exists():
        return True
    org_def = get_org_default_dashboard()
    return bool(org_def and org_def.pk == dashboard.pk)


def can_edit_dashboard(user, dashboard):
    if not user or not user.is_authenticated:
        return False
    if dashboard.owner_id == user.pk or user.is_superuser:
        return True
    group_ids = list(user.groups.values_list('id', flat=True))
    return FlexDashboardShare.objects.filter(
        dashboard=dashboard,
        permission=SharePermission.EDIT,
    ).filter(
        Q(shared_with_user=user) | Q(shared_with_group_id__in=group_ids)
    ).exists()


def list_accessible_dashboards(user, include_archived=False):
    group_ids = list(user.groups.values_list('id', flat=True))
    qs = FlexDashboard.objects.filter(
        Q(owner=user)
        | Q(shares__shared_with_user=user)
        | Q(shares__shared_with_group_id__in=group_ids)
    ).distinct()
    if not include_archived:
        qs = qs.filter(is_archived=False)
    return qs.select_related('owner').order_by('-is_default', '-is_favorite', '-updated_at', 'id')


def snapshot_from_dashboard(dashboard):
    sections_data = []
    for sec in dashboard.sections.prefetch_related('widgets').order_by('position', 'id'):
        widgets_data = [
            {
                'widget_type': w.widget_type,
                'title': w.title,
                'subtitle': w.subtitle,
                'position': w.position,
                'col_span': w.col_span,
                'row_span': w.row_span,
                'config': w.config or {},
                'is_visible': w.is_visible,
            }
            for w in sec.widgets.order_by('position', 'id')
        ]
        sections_data.append({
            'title': sec.title,
            'description': sec.description,
            'layout_preset': sec.layout_preset,
            'position': sec.position,
            'is_collapsed': sec.is_collapsed,
            'section_filters': sec.section_filters or {},
            'style_options': sec.style_options or {},
            'widgets': widgets_data,
        })
    return {
        'title': dashboard.title,
        'description': dashboard.description,
        'global_filters': dashboard.global_filters or {},
        'theme_options': dashboard.theme_options or {},
        'sections': sections_data,
    }


def serialize_dashboard(dashboard, user):
    sections_out = []
    for sec in dashboard.sections.prefetch_related('widgets').order_by('position', 'id'):
        widgets_out = [
            {
                'id': w.pk,
                'widget_type': w.widget_type,
                'title': w.title,
                'subtitle': w.subtitle,
                'position': w.position,
                'col_span': w.col_span,
                'row_span': w.row_span,
                'config': w.config or {},
                'is_visible': w.is_visible,
            }
            for w in sec.widgets.order_by('position', 'id')
        ]
        sections_out.append({
            'id': sec.pk,
            'title': sec.title,
            'description': sec.description,
            'layout_preset': sec.layout_preset,
            'position': sec.position,
            'is_collapsed': sec.is_collapsed,
            'section_filters': sec.section_filters or {},
            'style_options': sec.style_options or {},
            'widgets': widgets_out,
        })
    return {
        'id': dashboard.pk,
        'title': dashboard.title,
        'description': dashboard.description,
        'owner_id': dashboard.owner_id,
        'owner_name': dashboard.owner.get_full_name() or dashboard.owner.get_username(),
        'is_owner': dashboard.owner_id == user.pk,
        'can_edit': can_edit_dashboard(user, dashboard),
        'is_default': dashboard.is_default,
        'is_favorite': dashboard.is_favorite,
        'is_archived': dashboard.is_archived,
        'global_filters': dashboard.global_filters or {},
        'theme_options': dashboard.theme_options or {},
        'version': dashboard.version,
        'updated_at': dashboard.updated_at.isoformat() if dashboard.updated_at else None,
        'sections': sections_out,
    }


@transaction.atomic
def apply_snapshot_to_dashboard(dashboard, snapshot, actor, revision_label='تحديث اللوحة'):
    """Replace dashboard sections & widgets atomically and record a revision."""
    if 'title' in snapshot and snapshot['title']:
        dashboard.title = str(snapshot['title'])[:180]
    if 'description' in snapshot:
        dashboard.description = str(snapshot.get('description') or '')[:1000]
    if 'global_filters' in snapshot and isinstance(snapshot['global_filters'], dict):
        dashboard.global_filters = snapshot['global_filters']
    if 'theme_options' in snapshot and isinstance(snapshot['theme_options'], dict):
        dashboard.theme_options = snapshot['theme_options']

    dashboard.version = (dashboard.version or 0) + 1
    dashboard.save()

    dashboard.sections.all().delete()
    valid_presets = set(LayoutPreset.values)
    valid_wtypes = set(WidgetType.values)

    for s_idx, s_data in enumerate(snapshot.get('sections') or []):
        preset = s_data.get('layout_preset', LayoutPreset.GRID_12)
        if preset not in valid_presets:
            preset = LayoutPreset.GRID_12
        sec = FlexDashboardSection.objects.create(
            dashboard=dashboard,
            title=str(s_data.get('title') or '')[:180],
            description=str(s_data.get('description') or '')[:500],
            layout_preset=preset,
            position=s_idx,
            is_collapsed=bool(s_data.get('is_collapsed', False)),
            section_filters=s_data.get('section_filters') if isinstance(s_data.get('section_filters'), dict) else {},
            style_options=s_data.get('style_options') if isinstance(s_data.get('style_options'), dict) else {},
        )
        for w_idx, w_data in enumerate(s_data.get('widgets') or []):
            wtype = w_data.get('widget_type', WidgetType.KPI)
            if wtype not in valid_wtypes:
                wtype = WidgetType.KPI
            col_span = max(1, min(12, int(w_data.get('col_span') or 6)))
            row_span = max(1, min(6, int(w_data.get('row_span') or 1)))
            FlexDashboardWidget.objects.create(
                section=sec,
                widget_type=wtype,
                title=str(w_data.get('title') or 'عنصر جديد')[:200],
                subtitle=str(w_data.get('subtitle') or '')[:300],
                position=w_idx,
                col_span=col_span,
                row_span=row_span,
                config=w_data.get('config') if isinstance(w_data.get('config'), dict) else {},
                is_visible=bool(w_data.get('is_visible', True)),
            )

    FlexDashboardRevision.objects.create(
        dashboard=dashboard,
        version=dashboard.version,
        label=revision_label[:200],
        snapshot=snapshot_from_dashboard(dashboard),
        created_by=actor,
    )
    # Keep last 30 revisions per dashboard to avoid unbounded growth
    old_ids = list(dashboard.revisions.order_by('-version', '-id').values_list('id', flat=True)[30:])
    if old_ids:
        FlexDashboardRevision.objects.filter(id__in=old_ids).delete()
    return dashboard


@transaction.atomic
def create_dashboard_from_template(user, title=None, description='', template_key='executive_overview', is_default=False):
    ensure_system_templates()
    tpl = FlexDashboardTemplate.objects.filter(key=template_key).first() if template_key else None
    if is_default:
        FlexDashboard.objects.filter(owner=user, is_default=True).update(is_default=False)
    dash = FlexDashboard.objects.create(
        owner=user,
        title=(title or (tpl.title if tpl else 'لوحة تحليلات جديدة'))[:180],
        description=(description or (tpl.description if tpl else ''))[:1000],
        is_default=is_default,
        version=0,
    )
    snap = dict(tpl.snapshot) if tpl else {'global_filters': {}, 'sections': []}
    snap['title'] = dash.title
    snap['description'] = dash.description
    return apply_snapshot_to_dashboard(dash, snap, user, revision_label='إنشاء اللوحة')


def get_or_create_initial_dashboard(user, view_only=False):
    if view_only:
        group_ids = list(user.groups.values_list('id', flat=True))
        shared = (
            FlexDashboard.objects.filter(is_archived=False)
            .filter(Q(shares__shared_with_user=user) | Q(shares__shared_with_group_id__in=group_ids))
            .distinct()
            .order_by('-updated_at', 'id')
            .first()
        )
        if shared:
            return shared
        org_def = get_org_default_dashboard()
        if org_def:
            return org_def
    existing = list_accessible_dashboards(user).first()
    if existing:
        return existing
    return create_dashboard_from_template(
        user,
        title='لوحتي التحليلية الرئيسية',
        template_key='executive_overview',
        is_default=True,
    )


def list_share_targets():
    User = get_user_model()
    users = [
        {'id': u.pk, 'label': u.get_full_name() or u.get_username(), 'username': u.get_username()}
        for u in User.objects.filter(is_active=True).order_by('first_name', 'username')[:200]
    ]
    groups = [
        {'id': g.pk, 'label': g.name}
        for g in Group.objects.order_by('name')[:100]
    ]
    return {'users': users, 'groups': groups}
