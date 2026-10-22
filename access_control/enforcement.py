"""Authorization uses the verified operation from existing signed confirmations."""
import importlib
import json
from functools import wraps
from django.apps import apps
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import resolve
from accounts.security import add_login_headers
from .policy import for_request, require, require_superuser
from .registry import DEFINITIONS, SETTINGS_MODULES

MODELS={'levels':'levels.Level','regions':'regions.Region','entities':'entities.Entity','specializations':'specializations.Specialization','sectors':'sectors.Sector','expense_items':'expense_items.ExpenseItem','training_programs':'training_programs.TrainingProgram','sponsorship_shapes':'sponsorship_shapes.SponsorshipShape','partnerships':'partnerships.Partnership','market_needs':'market_needs.Need','service_providers':'service_providers.ServiceProvider'}


def denied(request, message='لا تملك صلاحية الوصول إلى هذه الصفحة أو تنفيذ هذه العملية.'):
    if request.headers.get('X-Requested-With')=='XMLHttpRequest' or 'application/json' in request.headers.get('Accept',''):
        return add_login_headers(JsonResponse({'error':message},status=403))
    name=request.user.get_short_name() or request.user.get_username() if request.user.is_authenticated else ''
    return add_login_headers(render(request,'access_control/denied.html',{'page_heading':'الوصول غير مسموح','display_name':name,'avatar_initial':name[:1],'denied_message':message},status=403))


def _status_permission(module, item_id, value, creating=False):
    if value not in ('1','0',True,False):
        return []  # The existing form will reject the invalid value.
    active=value is True or value=='1'
    if creating:
        return ['change_status'] if not active else []
    item=apps.get_model(MODELS[module])._base_manager.filter(pk=item_id).only('is_active').first()
    return ['change_status'] if item and item.is_active!=active else []


def _details_permissions(module,item_id,data):
    if module not in {'partnerships','service_providers'}:
        return []
    from partnerships.forms import offering_data
    from service_providers.forms import coverage_data
    item=apps.get_model(MODELS[module]).objects.filter(pk=item_id).first() if item_id else None
    key='offerings' if module=='partnerships' else 'coverage'
    old=offering_data(item) if module=='partnerships' else coverage_data(item)
    raw=data.get(key,'[]')
    try:rows=json.loads(raw) if isinstance(raw,str) else raw
    except (ValueError,TypeError):return []
    if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):return []
    needed=[]
    if len(rows)<len(old):needed.append('delete')
    # Status of owned rows is also a separate permission. New rows default active.
    if any(type(row.get('is_active')) is bool and row['is_active']!=(old[index]['is_active'] if index<len(old) else True) for index,row in enumerate(rows)):
        needed.append('change_status')
    return needed


def requested_operations(request,module,view,kwargs):
    if module in {'approved_programs', 'provider_assignments'}:
        if request.method in {'GET', 'HEAD'}:
            return ['view']
        if request.method != 'POST' or module != 'provider_assignments':
            raise PermissionDenied
        from market_needs.execution_views import mutation_permissions
        return ['view', *mutation_permissions(request, kwargs.get('pk'))]
    name=request.resolver_match.url_name
    if request.method in {'GET','HEAD'}:
        if name in {'download','attachment_download'}:return ['view','export']
        if name=='create':return ['view','create']
        if name=='edit':return ['view','edit']
        if name=='followup':
            operation=request.GET.get('operation','')
            if operation in {'approve','reject'}:return ['view','edit','change_status']
            if operation in {'notes','allocate'}:return ['view','edit']
            if operation not in {'','details'}:raise PermissionDenied
        edit=request.GET.get('edit')
        if edit:return ['view','create' if edit=='new' else 'edit']
        return ['view']
    if request.method!='POST':raise PermissionDenied
    implementation=importlib.import_module(view.__module__)
    post=request.POST
    if module in SETTINGS_MODULES:
        action=post.get('action')
        if action not in {'preview','confirm'}:raise PermissionDenied
        payload=implementation._load(post.get('snapshot' if action=='preview' else 'token'),request.user,implementation.SNAPSHOT_SALT if action=='preview' else implementation.CONFIRM_SALT)
        operation=payload['operation'];needed=['view',{'add':'create','edit':'edit','toggle':'change_status','delete':'delete'}[operation]]
        if operation in {'add','edit'}:
            needed+=_status_permission(module,payload.get('id'),post.get('is_active') if action=='preview' else payload.get('is_active'),operation=='add')
        return needed
    if module=='care_states':return ['view','edit']
    if module=='partnerships':
        action=post.get('action')
        if action not in {'preview','confirm'}:raise PermissionDenied
        if name in {'create','edit'}:
            payload=implementation._load(post.get('snapshot' if action=='preview' else 'token'),request.user,'editor' if action=='preview' else 'save')
            data=post if action=='preview' else payload.get('data',{})
            return ['view','create' if name=='create' else 'edit',*_status_permission(module,kwargs.get('pk'),data.get('is_active'),name=='create'),*_details_permissions(module,kwargs.get('pk'),data)]
        payload=implementation._load(post.get('token'),request.user,'row' if action=='preview' else 'row-confirm')
        return ['view',{'toggle':'change_status','delete':'delete','advance':'change_status'}[payload['operation']]]
    if module=='service_providers':
        action=post.get('action')
        if action not in {'preview','confirm'}:raise PermissionDenied
        if name in {'create','edit'}:
            payload=implementation.load(post.get('snapshot' if action=='preview' else 'token'),request.user,'editor' if action=='preview' else 'save')
            data=post if action=='preview' else payload.get('data',{})
            return ['view','create' if name=='create' else 'edit',*_status_permission(module,kwargs.get('pk'),data.get('is_active'),name=='create'),*_details_permissions(module,kwargs.get('pk'),data)]
        payload=implementation.load(post.get('token'),request.user,'row' if action=='preview' else 'row-confirm')
        operation=post.get('operation') if action=='preview' else payload.get('row_operation')
        return ['view',{'toggle':'change_status','delete':'delete'}[operation]]
    if module=='market_needs':
        pk=kwargs.get('pk')
        if name=='index':
            raw=post.get('card','');pk=int(raw) if raw.isascii() and raw.isdigit() else None
            payload=implementation.load_token(request,pk,{'toggle','delete'})
            return ['view',{'toggle':'change_status','delete':'delete'}[payload['operation']]]
        if name in {'create','edit'}:
            implementation.load_token(request,pk,{'save'})
            return ['view','create' if name=='create' else 'edit',*_status_permission(module,pk,post.get('is_active'),name=='create')]
        payload=implementation.load_token(request,pk,{'add','notes','approve','reject','allocate'})
        return ['view',*({'add':['create'],'notes':['edit'],'approve':['edit','change_status'],'reject':['edit','change_status'],'allocate':['edit']}[payload['operation']])]
    raise PermissionDenied


def module_view(module):
    if module not in DEFINITIONS:raise ValueError('Unknown protected module')
    def decorate(view):
        @wraps(view)
        def wrapped(request,*args,**kwargs):
            if not request.user.is_authenticated:
                from django.contrib.auth.views import redirect_to_login
                return redirect_to_login(request.get_full_path(),login_url='accounts:login')
            policy=for_request(request)
            if not policy.active:return denied(request)
            if policy.superuser:return view(request,*args,**kwargs)
            try:
                if not policy.can(module):raise PermissionDenied
                if request.method not in {'GET','HEAD'} and not any(policy.can(module,op) for op in DEFINITIONS[module].operations if op!='view'):
                    raise PermissionDenied
                needed = requested_operations(request,module,view,kwargs)
                # MAKKEN FORMAT EXPORT OPERATION CHECK
                if request.method in {'GET', 'HEAD'} and '_mk_export' in request.GET:
                    from .exports import export_operation
                    needed = [*needed, export_operation(request.GET.get('_mk_export'))]
                for operation in needed:
                    if not policy.can(module,operation):raise PermissionDenied
            except (PermissionDenied,signing.BadSignature,KeyError,ValueError,TypeError):
                return denied(request)
            return view(request,*args,**kwargs)
        wrapped._access_module=module
        return wrapped
    return decorate


def superuser_view(view):
    @wraps(view)
    def wrapped(request,*args,**kwargs):
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path(),login_url='accounts:login')
        try:require_superuser(request.user)
        except PermissionDenied:return denied(request,'إدارة المستخدمين والصلاحيات متاحة لمدير النظام الأعلى فقط.')
        return view(request,*args,**kwargs)
    wrapped._access_superuser=True
    return wrapped


def service_operation(module,operation):
    """An additional guard at public business-service entry points."""
    import inspect
    def decorate(function):
        signature=inspect.signature(function)
        @wraps(function)
        def wrapped(*args,**kwargs):
            bound=signature.bind(*args,**kwargs);bound.apply_defaults();values=bound.arguments
            user=values.get('actor') or values.get('user');needed=[]
            if operation in {'save_need','save_provider','save'}:
                payload=values.get('payload',{})
                pk=values.get('pk') or payload.get('id')
                data=values.get('data') or payload.get('data',{})
                needed=['create' if not pk else 'edit',*_status_permission(module,pk,data.get('is_active'),not pk),*_details_permissions(module,pk,data)]
            elif operation in {'card_action','row_action'}:
                action=values.get('operation') or values.get('payload',{}).get('operation')
                if action not in {'toggle','delete'}:raise PermissionDenied
                needed=[{'toggle':'change_status','delete':'delete'}[action]]
            elif operation=='add_candidates':needed=['create']
            elif operation=='followup':
                action=values.get('operation')
                if action not in {'notes','approve','reject','allocate'}:raise PermissionDenied
                needed=['edit',*(['change_status'] if action in {'approve','reject'} else [])]
            else:raise PermissionDenied
            require(user,module,'view',*needed)
            return function(*args,**kwargs)
        return wrapped
    return decorate
