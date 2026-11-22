from django.core.paginator import Paginator
from core.pagination import resolve_page_size
from django.db.models import Q, Max
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET
from accounts.security import add_login_headers
from .enforcement import module_view
from .activity_data import visible_events, decorate_event, audit_timezone
from .activity_forms import ActivityFilterForm


def base(request):
    name = request.user.get_short_name() or request.user.get_username()
    return {'page_heading':'سجل نشاط المستخدمين', 'active_page':'user_activity',
            'access_tab':'activity', 'display_name':name, 'avatar_initial':name[:1],
            'activity_timezone':audit_timezone()}


@module_view('user_activity')
@require_GET
def activity(request):
    events = visible_events(request.user)
    # Export pagination is a moving dataset. A fixed upper primary key freezes
    # membership; new audit records cannot shift offsets or appear mid-export.
    watermark = str(getattr(request, '_activity_until', request.GET.get('until','')))
    maximum = events.aggregate(value=Max('pk'))['value'] or 0
    if watermark.isascii() and watermark.isdigit() and len(watermark) < 19:
        maximum = min(maximum, int(watermark))
    events = events.filter(pk__lte=maximum)
    from .models import UserActivity
    last_actor_events = events.exclude(actor_key=None).order_by().values('actor_key').annotate(last=Max('pk')).values('last')
    actors = UserActivity.objects.filter(pk__in=last_actor_events).order_by('actor_name').values_list('actor_key','actor_name','actor_username')
    actor_options = {}
    for pk,name,username in actors:
        actor_options.setdefault(pk, name + (f' ({username})' if username else ''))
    # Options themselves are scoped; no user or region names leak through a
    # dropdown even when no rows are visible to the current auditor.
    from .models import ActivityRegion
    last_region_events = ActivityRegion.objects.filter(event_id__in=events.values('pk')).order_by().values('region_key').annotate(last=Max('pk')).values('last')
    regions = ActivityRegion.objects.filter(pk__in=last_region_events).order_by('name').values_list('region_key','name')
    region_options = {}
    for pk,name in regions:
        region_options.setdefault(pk, name)
    form = ActivityFilterForm(request.GET, actors=actor_options.items(), regions=region_options.items())
    valid = form.is_valid()
    if valid:
        data = form.cleaned_data
        if data['q']:
            q = data['q']
            events = events.filter(Q(actor_name__icontains=q) | Q(actor_username__icontains=q)
                | Q(target_label__icontains=q) | Q(description__icontains=q) | Q(target_key=q))
        for key in ['module','action','outcome']:
            if data[key]:
                events = events.filter(**{key: data[key]})
        if data['actor']:
            events = events.filter(actor_key=data['actor'])
        if data['region']:
            events = events.filter(region_snapshots__region_key=data['region'])
        if data.get('bound_from'):
            events = events.filter(created_at__gte=data['bound_from'])
        if data.get('bound_to'):
            events = events.filter(created_at__lt=data['bound_to'])
    else:
        events = events.none()
    if not valid and getattr(request, '_makken_export_internal', False):
        # A malformed filter must never silently export an unfiltered report.
        return add_login_headers(render(request, 'access_control/activity.html',
            {**base(request), 'form':form, 'rows':[], 'filter_error':True}, status=400))
    page = Paginator(events.prefetch_related('region_snapshots'), resolve_page_size(request, 25)).get_page(request.GET.get('page'))
    params = request.GET.copy()
    for key in ['page','_mk_export','_mk_table']:
        params.pop(key, None)
    params['until'] = str(maximum)
    response = add_login_headers(render(request, 'access_control/activity.html', {
        **base(request), 'form':form, 'rows':[decorate_event(e) for e in page],
        'page_obj':page, 'pagination_query':params.urlencode(), 'watermark':maximum,
        'filter_error':not valid,
    }))
    response['X-Makken-Activity-Until'] = str(maximum)
    return response


@module_view('user_activity')
@require_GET
def detail(request, pk):
    event = decorate_event(get_object_or_404(visible_events(request.user).prefetch_related('region_snapshots'), pk=pk))
    request._activity_target = event
    context = {**base(request), 'event':event}
    template = 'access_control/_activity_detail.html' if request.headers.get('X-Requested-With') == 'XMLHttpRequest' else 'access_control/activity_detail.html'
    return add_login_headers(render(request, template, context))
