"""One actual page/download/export event; no synthetic export page visits."""
from django.apps import apps
from django.db import transaction
from .activity_capture import Capture, current, emit, regions_for, record_label, MODELS
from .activity_data import clean_text

REQUEST_TARGETS = {v: k for k,v in MODELS.items() if k not in {'auth.user','market_needs.sponsorship','market_needs.needexecution'}}
REQUEST_TARGETS.update(provider_assignments='market_needs.need', approved_programs='market_needs.need')


class ActivityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if getattr(request, '_makken_export_internal', False):
            return self.get_response(request)
        ctx = Capture(request)
        token = current.set(ctx)
        try:
            response = self.get_response(request)
            self.record_request(request, response, ctx)
            return response
        finally:
            current.reset(token)

    @staticmethod
    def record_request(request, response, ctx):
        user = getattr(request, 'user', None)
        match = getattr(request, 'resolver_match', None)
        if match is None:
            from django.urls import resolve, Resolver404
            try:
                match = resolve(request.path_info, urlconf=getattr(request,'urlconf',None))
                request.resolver_match = match
            except Resolver404:
                return
        if not user or not user.is_authenticated or not match:
            return
        module = getattr(match.func, '_access_module', None)
        if not module:
            module = 'accounts' if match.namespace == 'accounts' else 'access_control' if match.namespace in {'access_control','admin'} else 'dashboard' if match.view_name in {'makken_home','home'} else None
        if not module or match.url_name in {'login','login_slash','logout','logout_slash'}:
            return
        if response.status_code == 403:
            # Do not resolve a denied target: its name/existence is itself private.
            action, description = 'denied', 'محاولة وصول غير مسموحة'
            item = None
        elif request.method == 'GET' and response.status_code == 200:
            action = getattr(request,'_dashboard_export_format',request.GET.get('_mk_export'))
            action = 'export_' + action if action in {'xlsx','pdf'} else 'download' if match.url_name in {'download','attachment_download'} else 'view'
            description = {'view':'مشاهدة الصفحة', 'download':'تنزيل مرفق', 'export_xlsx':'تصدير Excel', 'export_pdf':'تصدير PDF'}[action]
            item = getattr(request, '_activity_target', None)
            model_label = REQUEST_TARGETS.get(module)
            pk = match.kwargs.get('pk') or request.GET.get('detail') or request.GET.get('edit')
            if item is None and model_label and pk and str(pk).isascii() and str(pk).isdigit() and len(str(pk)) < 19:
                # Scope every detail lookup independently. Never turn a route
                # guessing attempt into a successfully viewed object in the log.
                from .regions import scoped
                item = scoped(apps.get_model(model_label).objects.filter(pk=pk), user).first()
        else:
            # Successful POST previews and validation failures are not writes.
            # Committed signals/business audit sources record real mutations.
            return
        from .models import UserActivity
        regions = ({r.region_key:r.name for r in item.region_snapshots.all()}
                   if isinstance(item, UserActivity) else regions_for(item))
        if not regions and item is None:
            regions = regions_for(user)
        values = dict(actor=user, module=module, action=action, description=description,
            target_model=item._meta.label_lower if item else '',
            target_key=str(item.pk) if item else '',
            target_label=clean_text(record_label(item) if item and not isinstance(item, UserActivity) else
                f'حدث رقم {item.pk}' if item else '', 300),
            regions=regions, context=ctx, http_status=response.status_code,
            outcome='denied' if action == 'denied' else 'success',
            source_key=f'request:{ctx.request_id}:response')
        transaction.on_commit(lambda: emit(**values), robust=True)
