"""Views and JSON APIs for المؤشرات والتحليلات المرنة."""
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from access_control.enforcement import module_view
from access_control.policy import for_request
from access_control.regions import scoped as regional_scoped
from regions.models import Region
from sectors.models import Sector

from .exports import build_export_response
from .graph import compatibility_for_selection, serialize_graph
from .kpis import evaluate_custom_kpi, evaluate_predefined_kpi, list_kpi_catalog
from .models import (
    FlexDashboard,
    FlexDashboardRevision,
    FlexDashboardShare,
    FlexDashboardTemplate,
    SharePermission,
)
from .query_engine import (
    QueryValidationError,
    execute_chart_query,
    execute_drilldown,
    execute_table_query,
)
from .semantic import serialize_metadata
from .services import (
    apply_snapshot_to_dashboard,
    can_edit_dashboard,
    can_view_dashboard,
    create_dashboard_from_template,
    ensure_system_templates,
    get_or_create_initial_dashboard,
    list_accessible_dashboards,
    list_share_targets,
    serialize_dashboard,
    snapshot_from_dashboard,
)


def _json_body(request):
    if not request.body:
        return {}
    try:
        data = json.loads(request.body.decode('utf-8'))
        return data if isinstance(data, dict) else {}
    except (ValueError, UnicodeDecodeError):
        return {}


@module_view('flex_analytics')
@require_GET
def index(request):
    name = request.user.get_full_name() or request.user.get_username()
    return render(request, 'flex_analytics/index.html', {
        'active_page': 'flex_analytics',
        'page_heading': 'المؤشرات والتحليلات المرنة',
        'display_name': name,
    })


@module_view('flex_analytics')
@require_GET
def api_bootstrap(request):
    ensure_system_templates()
    active_id = request.GET.get('dashboard_id')
    dashboards_qs = list_accessible_dashboards(request.user, include_archived=request.GET.get('archived') == '1')
    active_dash = None
    if active_id:
        cand = FlexDashboard.objects.filter(pk=active_id).first()
        if cand and can_view_dashboard(request.user, cand):
            active_dash = cand
    if active_dash is None:
        active_dash = get_or_create_initial_dashboard(request.user)
        dashboards_qs = list_accessible_dashboards(request.user, include_archived=request.GET.get('archived') == '1')

    policy = for_request(request)
    regions_list = [
        {'id': r.pk, 'name': r.name}
        for r in regional_scoped(Region.objects.filter(is_active=True), request.user).order_by('name')
    ]
    sectors_list = [
        {'id': s.pk, 'name': s.name}
        for s in Sector.objects.filter(is_active=True).order_by('name')
    ]
    templates = [
        {
            'key': t.key,
            'title': t.title,
            'description': t.description,
            'category': t.category,
            'is_system': t.is_system,
        }
        for t in FlexDashboardTemplate.objects.all()
    ]
    dashboards_list = [
        {
            'id': d.pk,
            'title': d.title,
            'description': d.description,
            'is_default': d.is_default,
            'is_favorite': d.is_favorite,
            'is_archived': d.is_archived,
            'is_owner': d.owner_id == request.user.pk,
            'can_edit': can_edit_dashboard(request.user, d),
            'owner_name': d.owner.get_full_name() or d.owner.get_username(),
            'version': d.version,
        }
        for d in dashboards_qs
    ]

    return JsonResponse({
        'permissions': {
            'can_create': policy.can('flex_analytics', 'create'),
            'can_edit': policy.can('flex_analytics', 'edit'),
            'can_delete': policy.can('flex_analytics', 'delete'),
            'can_export_xlsx': policy.can('flex_analytics', 'export_xlsx'),
            'can_export_pdf': policy.can('flex_analytics', 'export_pdf'),
        },
        'metadata': serialize_metadata(request.user),
        'graph': serialize_graph(request.user),
        'kpi_catalog': list_kpi_catalog(request.user),
        'dashboards': dashboards_list,
        'active_dashboard': serialize_dashboard(active_dash, request.user),
        'templates': templates,
        'filter_options': {
            'regions': regions_list,
            'sectors': sectors_list,
        },
    })


@module_view('flex_analytics')
@require_GET
def api_compatibility(request):
    base = request.GET.get('base', '').strip()
    if not base:
        return JsonResponse({'error': 'يرجى تحديد الكيان الأساسي.'}, status=400)
    return JsonResponse(compatibility_for_selection(base, request.user))


@module_view('flex_analytics')
@require_http_methods(['GET', 'POST'])
def api_dashboards(request):
    if request.method == 'GET':
        qs = list_accessible_dashboards(request.user, include_archived=request.GET.get('archived') == '1')
        return JsonResponse({
            'dashboards': [serialize_dashboard(d, request.user) for d in qs],
        })

    body = _json_body(request)
    title = str(body.get('title') or '').strip()
    if not title:
        return JsonResponse({'error': 'عنوان اللوحة مطلوب.'}, status=400)
    description = str(body.get('description') or '').strip()
    template_key = body.get('template_key')
    is_default = bool(body.get('is_default', False))

    dash = create_dashboard_from_template(
        request.user,
        title=title,
        description=description,
        template_key=template_key if template_key != 'blank' else None,
        is_default=is_default,
    )
    return JsonResponse({'dashboard': serialize_dashboard(dash, request.user)}, status=201)


@module_view('flex_analytics')
@require_http_methods(['GET', 'POST', 'DELETE'])
def api_dashboard_detail(request, pk):
    dash = get_object_or_404(FlexDashboard, pk=pk)
    if not can_view_dashboard(request.user, dash):
        return JsonResponse({'error': 'لا تملك صلاحية الوصول إلى هذه اللوحة.'}, status=403)

    if request.method == 'GET':
        return JsonResponse({'dashboard': serialize_dashboard(dash, request.user)})

    if request.method == 'DELETE':
        if dash.owner_id != request.user.pk and not request.user.is_superuser:
            return JsonResponse({'error': 'فقط مالك اللوحة يمكنه حذفها.'}, status=403)
        dash.delete()
        return JsonResponse({'deleted': True})

    # POST: save dashboard layout/sections/widgets/filters
    if not can_edit_dashboard(request.user, dash):
        return JsonResponse({'error': 'لا تملك صلاحية تعديل هذه اللوحة.'}, status=403)

    body = _json_body(request)
    expected_version = body.get('version')
    if expected_version is not None and int(expected_version) != dash.version:
        return JsonResponse({
            'error': 'تم تحديث اللوحة من جلسة أخرى. يرجى إعادة تحميل اللوحة قبل الحفظ.',
            'current_version': dash.version,
        }, status=409)

    label = str(body.get('revision_label') or 'حفظ التغييرات')
    apply_snapshot_to_dashboard(dash, body, request.user, revision_label=label)
    dash.refresh_from_db()
    return JsonResponse({'dashboard': serialize_dashboard(dash, request.user)})


@module_view('flex_analytics')
@require_POST
def api_dashboard_action(request, pk):
    dash = get_object_or_404(FlexDashboard, pk=pk)
    if not can_view_dashboard(request.user, dash):
        return JsonResponse({'error': 'لا تملك صلاحية الوصول إلى هذه اللوحة.'}, status=403)

    body = _json_body(request)
    action = str(body.get('action') or '').strip()

    if action == 'duplicate':
        snap = snapshot_from_dashboard(dash)
        new_title = str(body.get('title') or f'نسخة من {dash.title}')[:180]
        snap['title'] = new_title
        with transaction.atomic():
            copy_dash = FlexDashboard.objects.create(
                owner=request.user,
                title=new_title,
                description=dash.description,
                version=0,
            )
            apply_snapshot_to_dashboard(copy_dash, snap, request.user, revision_label='نسخ من لوحة قائمة')
        return JsonResponse({'dashboard': serialize_dashboard(copy_dash, request.user)}, status=201)

    if action == 'save_as_template':
        tpl_title = str(body.get('title') or dash.title)[:180]
        base_slug = slugify(tpl_title, allow_unicode=False) or f'tpl-{dash.pk}'
        key = f'{base_slug[:60]}-{dash.pk}-{dash.version}'
        tpl = FlexDashboardTemplate.objects.create(
            key=key,
            title=tpl_title,
            description=str(body.get('description') or dash.description)[:1000],
            category=str(body.get('category') or 'مخصص')[:80],
            is_system=False,
            created_by=request.user,
            snapshot=snapshot_from_dashboard(dash),
        )
        return JsonResponse({'template': {'key': tpl.key, 'title': tpl.title}}, status=201)

    if not can_edit_dashboard(request.user, dash):
        return JsonResponse({'error': 'لا تملك صلاحية تعديل هذه اللوحة.'}, status=403)

    if action == 'set_default':
        with transaction.atomic():
            FlexDashboard.objects.filter(owner=request.user, is_default=True).update(is_default=False)
            dash.is_default = True
            dash.save(update_fields=['is_default', 'updated_at'])
        return JsonResponse({'dashboard': serialize_dashboard(dash, request.user)})

    if action == 'toggle_favorite':
        dash.is_favorite = not dash.is_favorite
        dash.save(update_fields=['is_favorite', 'updated_at'])
        return JsonResponse({'dashboard': serialize_dashboard(dash, request.user)})

    if action == 'toggle_archive':
        dash.is_archived = not dash.is_archived
        if dash.is_archived:
            dash.is_default = False
        dash.save(update_fields=['is_archived', 'is_default', 'updated_at'])
        return JsonResponse({'dashboard': serialize_dashboard(dash, request.user)})

    return JsonResponse({'error': 'الإجراء المطلوب غير مدعوم.'}, status=400)


@module_view('flex_analytics')
@require_http_methods(['GET', 'POST'])
def api_revisions(request, pk):
    dash = get_object_or_404(FlexDashboard, pk=pk)
    if not can_view_dashboard(request.user, dash):
        return JsonResponse({'error': 'لا تملك صلاحية الوصول إلى هذه اللوحة.'}, status=403)

    if request.method == 'GET':
        revs = [
            {
                'id': r.pk,
                'version': r.version,
                'label': r.label,
                'created_by': (r.created_by.get_full_name() or r.created_by.get_username()) if r.created_by else 'النظام',
                'created_at': r.created_at.isoformat(),
            }
            for r in dash.revisions.select_related('created_by').order_by('-version', '-id')[:30]
        ]
        return JsonResponse({'revisions': revs})

    if not can_edit_dashboard(request.user, dash):
        return JsonResponse({'error': 'لا تملك صلاحية استعادة نسخ هذه اللوحة.'}, status=403)

    body = _json_body(request)
    rev = get_object_or_404(FlexDashboardRevision, pk=body.get('revision_id'), dashboard=dash)
    apply_snapshot_to_dashboard(dash, rev.snapshot, request.user, revision_label=f'استعادة الإصدار v{rev.version}')
    dash.refresh_from_db()
    return JsonResponse({'dashboard': serialize_dashboard(dash, request.user)})


@module_view('flex_analytics')
@require_http_methods(['GET', 'POST', 'DELETE'])
def api_shares(request, pk):
    dash = get_object_or_404(FlexDashboard, pk=pk)
    if dash.owner_id != request.user.pk and not request.user.is_superuser:
        return JsonResponse({'error': 'إدارة المشاركة متاحة لمالك اللوحة فقط.'}, status=403)

    if request.method == 'GET':
        shares = [
            {
                'id': s.pk,
                'target_type': 'user' if s.shared_with_user_id else 'group',
                'target_name': (
                    (s.shared_with_user.get_full_name() or s.shared_with_user.get_username())
                    if s.shared_with_user else (s.shared_with_group.name if s.shared_with_group else '')
                ),
                'permission': s.permission,
                'permission_label': s.get_permission_display(),
            }
            for s in dash.shares.select_related('shared_with_user', 'shared_with_group')
        ]
        return JsonResponse({'shares': shares, 'targets': list_share_targets()})

    body = _json_body(request)
    if request.method == 'DELETE':
        share_id = body.get('share_id') or request.GET.get('share_id')
        FlexDashboardShare.objects.filter(pk=share_id, dashboard=dash).delete()
        return JsonResponse({'deleted': True})

    perm = body.get('permission', SharePermission.VIEW)
    if perm not in set(SharePermission.values):
        perm = SharePermission.VIEW
    target_type = body.get('target_type')
    target_id = body.get('target_id')

    if target_type == 'user':
        User = get_user_model()
        target_user = get_object_or_404(User, pk=target_id, is_active=True)
        share, _ = FlexDashboardShare.objects.update_or_create(
            dashboard=dash,
            shared_with_user=target_user,
            defaults={'permission': perm, 'created_by': request.user},
        )
    elif target_type == 'group':
        target_group = get_object_or_404(Group, pk=target_id)
        share, _ = FlexDashboardShare.objects.update_or_create(
            dashboard=dash,
            shared_with_group=target_group,
            defaults={'permission': perm, 'created_by': request.user},
        )
    else:
        return JsonResponse({'error': 'يرجى تحديد مستخدم أو دور للمشاركة.'}, status=400)

    return JsonResponse({'share_id': share.pk, 'permission': share.permission}, status=201)


@module_view('flex_analytics')
@require_POST
def api_query(request):
    body = _json_body(request)
    widget_type = str(body.get('widget_type') or 'table').lower()
    config = body.get('config') or {}
    global_filters = body.get('global_filters') or {}

    try:
        if widget_type == 'kpi':
            kpi_key = config.get('kpi_key')
            data = evaluate_predefined_kpi(
                request.user,
                kpi_key,
                global_filters=global_filters,
                target=config.get('target'),
                thresholds=config.get('thresholds'),
            )
            return JsonResponse({'widget_type': 'kpi', 'data': data})

        if widget_type == 'custom_kpi':
            data = evaluate_custom_kpi(request.user, config, global_filters=global_filters)
            return JsonResponse({'widget_type': 'custom_kpi', 'data': data})

        if widget_type == 'chart':
            data = execute_chart_query(request.user, config, global_filters=global_filters)
            return JsonResponse({'widget_type': 'chart', 'data': data})

        if widget_type in {'table', 'summary'}:
            data = execute_table_query(request.user, config, global_filters=global_filters)
            return JsonResponse({'widget_type': widget_type, 'data': data})

        return JsonResponse({'error': f'نوع العنصر غير مدعوم: {widget_type}'}, status=400)
    except PermissionError as exc:
        return JsonResponse({'error': str(exc)}, status=403)
    except QueryValidationError as exc:
        return JsonResponse({'error': str(exc)}, status=400)


@module_view('flex_analytics')
@require_POST
def api_drilldown(request):
    body = _json_body(request)
    try:
        data = execute_drilldown(
            request.user,
            body.get('config') or {},
            body.get('filter_entity'),
            body.get('filter_field'),
            body.get('filter_value'),
            global_filters=body.get('global_filters') or {},
        )
        return JsonResponse({'data': data})
    except PermissionError as exc:
        return JsonResponse({'error': str(exc)}, status=403)
    except QueryValidationError as exc:
        return JsonResponse({'error': str(exc)}, status=400)


@module_view('flex_analytics')
@require_POST
def api_export(request):
    body = _json_body(request)
    fmt = str(body.get('format') or 'csv').lower()
    policy = for_request(request)
    if fmt in {'xlsx', 'csv'} and not policy.can('flex_analytics', 'export_xlsx'):
        return JsonResponse({'error': 'لا تملك صلاحية تصدير ملفات Excel/CSV.'}, status=403)
    if fmt == 'pdf' and not policy.can('flex_analytics', 'export_pdf'):
        return JsonResponse({'error': 'لا تملك صلاحية تصدير ملفات PDF.'}, status=403)
    try:
        return build_export_response(
            request.user,
            fmt=fmt,
            widget_type=str(body.get('widget_type') or 'table').lower(),
            config=body.get('config') or {},
            title=str(body.get('title') or 'تقرير تحليلي'),
            global_filters=body.get('global_filters') or {},
        )
    except PermissionError as exc:
        return JsonResponse({'error': str(exc)}, status=403)
    except (QueryValidationError, ValueError) as exc:
        return JsonResponse({'error': str(exc)}, status=400)
