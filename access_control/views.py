import json
import uuid
from django.contrib import messages
from django.contrib.auth import get_user_model,update_session_auth_hash
from django.contrib.auth.models import Group,Permission
from django.core import signing
from django.core.paginator import Paginator
from django.db import IntegrityError,OperationalError
from django.db.models import Q,Count,Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404,redirect,render
from django.urls import reverse
from django.views.decorators.http import require_http_methods,require_GET
from django.views.decorators.debug import sensitive_post_parameters
from accounts.security import add_login_headers
from .enforcement import superuser_view
from .forms import UserForm,RoleForm,AdminPasswordForm
from .models import Module,RoleProfile,UserAccess,PermissionOverride,SecurityAudit,Operation,PageScope
from .policy import AccessPolicy,for_request
from .registry import DEFINITIONS,codename
from . import services

SALT='makken.access-control.v1'


def numeric_id(value):
    return int(value) if isinstance(value,str) and 0<len(value)<19 and value.isascii() and value.isdigit() else None


def token(request,kind,action,target=None):
    return signing.dumps({'actor':request.user.pk,'kind':kind,'action':action,'pk':target.pk if target else None,'fingerprint':services.fingerprint(target,kind) if target else None,'nonce':str(uuid.uuid4())},salt=SALT,compress=True)


def load(request,kind,action,pk=None):
    raw=request.POST.get('snapshot','')
    if not isinstance(raw,str) or len(raw)>8192:raise signing.BadSignature
    data=signing.loads(raw,salt=SALT,max_age=1200)
    if data.get('actor')!=request.user.pk or data.get('kind')!=kind or data.get('action')!=action or data.get('pk')!=pk:raise signing.BadSignature
    return data


def base(request,tab='users'):
    name=request.user.get_short_name() or request.user.get_username()
    return {'page_heading':'إدارة المستخدمين والصلاحيات','active_page':'access_control','display_name':name,'avatar_initial':name[:1],'access_tab':tab}


def finish(request,template,context,status=200):
    return add_login_headers(render(request,'access_control/'+template,context,status=status))


def initial_user(target):
    if not target:return {'page_scope':'selected','is_active':'1'}
    access=UserAccess.objects.filter(user=target).first()
    values={'full_name':target.get_full_name() or target.get_username(),'username':target.get_username(),'email':target.email,'is_active':'1' if target.is_active else '0','roles':list(RoleProfile.objects.filter(group__user=target).values_list('pk',flat=True)),'page_scope':access.page_scope if access else 'selected','allowed_pages':list(access.allowed_pages.values_list('pk',flat=True)) if access else []}
    for rule in PermissionOverride.objects.filter(user=target):values[f'override__{rule.module_id}__{rule.operation}']=rule.effect
    # Legacy direct Django grants stay visible and become explicit managed grants on save.
    codes=set(target.user_permissions.filter(content_type__app_label='access_control',content_type__model='module').values_list('codename',flat=True))
    for module in DEFINITIONS.values():
        for operation in module.operations:
            key=f'override__{module.key}__{operation}'
            if key not in values and codename(module.key,operation) in codes:values[key]='grant'
    return values


def matrix(form,target=None,role=False):
    policy=AccessPolicy(target) if target is not None else None
    rows=[]
    chosen=set(form['permissions'].value() or []) if role else set()
    for module in DEFINITIONS.values():
        cells=[]
        for operation,label in Operation.choices:
            supported=operation in module.operations
            allowed,source=policy.decision(module.key,operation) if policy and supported else (False,'')
            cells.append({'operation':operation,'label':label,'supported':supported,'key':module.key+':'+operation,'checked':module.key+':'+operation in chosen,'field':form[f'override__{module.key}__{operation}'] if supported and not role else None,'effective':allowed,'source':source})
        rows.append({'module':module,'cells':cells})
    return rows


def role_catalog():
    result=[]
    for role in RoleProfile.objects.select_related('group').prefetch_related('allowed_pages','group__permissions__content_type'):
        codes={p.codename for p in role.group.permissions.all() if p.content_type.app_label=='access_control' and p.content_type.model=='module'}
        result.append({'id':role.pk,'name':role.group.name,'scope':role.page_scope,'pages':[p.pk for p in role.allowed_pages.all()],'permissions':[m.key+':'+op for m in DEFINITIONS.values() for op in m.operations if codename(m.key,op) in codes]})
    return result


@superuser_view
@require_GET
def index(request):
    tab=request.GET.get('tab','users');tab=tab if tab in {'users','permissions','pages'} else 'users'
    context=base(request,tab);User=get_user_model();q=request.GET.get('q','').strip()[:200];status=request.GET.get('status','');role=request.GET.get('role','')
    users=User._default_manager.prefetch_related(Prefetch('groups',queryset=Group.objects.select_related('makken_role')),'makken_access__allowed_pages','makken_overrides',Prefetch('user_permissions',queryset=Permission.objects.filter(content_type__app_label='access_control',content_type__model='module'))).order_by('-pk')
    for word in q.split()[:12]:
        condition=Q(username__icontains=word)|Q(email__icontains=word)|Q(first_name__icontains=word)|Q(last_name__icontains=word)|Q(groups__name__icontains=word)
        if word.isascii() and word.isdigit() and len(word)<19:condition|=Q(pk=int(word))
        users=users.filter(condition).distinct()
    if status in {'1','0'}:users=users.filter(is_active=status=='1')
    if numeric_id(role) is not None:users=users.filter(groups__makken_role__pk=numeric_id(role))
    page=Paginator(users,15).get_page(request.GET.get('page'))
    rows=[{'user':u,'roles':[g.name for g in u.groups.all()],'status_token':token(request,'user','status',u),'scope':getattr(getattr(u,'makken_access',None),'get_page_scope_display',lambda:'غير مهيأ')()} for u in page]
    context.update(rows=rows,page_obj=page,q=q,selected_status=status,selected_role=role,roles=RoleProfile.objects.select_related('group'),total_users=User.objects.count(),active_users=User.objects.filter(is_active=True).count(),inactive_users=User.objects.filter(is_active=False).count(),role_count=RoleProfile.objects.count())
    return finish(request,'users.html',context)


@superuser_view
@require_http_methods(['GET','POST'])
@sensitive_post_parameters('new_password1','new_password2')
def user_editor(request,pk=None):
    target=get_object_or_404(get_user_model(),pk=pk) if pk else None
    snapshot=token(request,'user','save',target)
    form=UserForm(initial={**initial_user(target),'snapshot':snapshot},target=target)
    context=base(request);status=200
    if request.method=='POST':
        form=UserForm(request.POST,target=target)
        try:
            payload=load(request,'user','save',pk)
            saved=services.save_user(request.user,request.POST,pk,payload['fingerprint'])
            messages.success(request,'تم حفظ الحساب والأدوار والصلاحيات بنجاح. تسري الصلاحيات في الطلب التالي.')
            return redirect('access_control:user_edit',pk=saved.pk)
        except services.InvalidForm as error:form=error.form;status=400
        except signing.BadSignature:context['error']='انتهت صلاحية النموذج. أعد تحميل الصفحة قبل الحفظ.';status=409
        except services.Conflict as error:context['error']=str(error);status=409
        except (IntegrityError,OperationalError):context['error']='تعارضت البيانات مع تحديث آخر أو اسم/بريد مستخدم. لم يُحفظ تغيير جزئي.';status=409
    context.update(target_user=target,form=form,matrix_rows=matrix(form,target),operations=Operation.choices,role_catalog=role_catalog(),status_token=token(request,'user','status',target) if target else None)
    return finish(request,'user_editor.html',context,status)


@superuser_view
@require_http_methods(['POST'])
def user_status(request,pk):
    try:
        data=load(request,'user','status',pk);services.toggle_user(request.user,pk,data['fingerprint'])
    except (services.Conflict,signing.BadSignature,IntegrityError,OperationalError) as error:
        message=str(error) if isinstance(error,services.Conflict) else 'انتهت صلاحية الطلب أو تغيّرت البيانات. حدّث الصفحة.'
        return add_login_headers(JsonResponse({'error':message},status=409)) if request.headers.get('X-Requested-With')=='XMLHttpRequest' else finish(request,'message.html',{**base(request),'error':message},409)
    if request.headers.get('X-Requested-With')=='XMLHttpRequest':return add_login_headers(JsonResponse({'message':'تم تحديث حالة الحساب.','redirect':reverse('access_control:index')}))
    messages.success(request,'تم تحديث حالة الحساب.');return redirect('access_control:index')


@superuser_view
@require_http_methods(['GET','POST'])
@sensitive_post_parameters('new_password1','new_password2')
def password(request,pk):
    target=get_object_or_404(get_user_model(),pk=pk);context=base(request);status=200
    form=AdminPasswordForm(initial={'snapshot':token(request,'user','password',target)},user=target)
    if request.method=='POST':
        form=AdminPasswordForm(request.POST,user=target)
        try:
            payload=load(request,'user','password',pk);saved=services.reset_password(request.user,pk,payload['fingerprint'],request.POST)
            if saved.pk==request.user.pk:update_session_auth_hash(request,saved)
            messages.success(request,'تم تعيين كلمة مرور جديدة. تُلغى جلسات المستخدم الأخرى عند طلبها التالي.')
            return redirect('access_control:user_edit',pk=pk)
        except services.InvalidForm as error:form=error.form;status=400
        except (services.Conflict,signing.BadSignature,IntegrityError,OperationalError) as error:context['error']=str(error) if isinstance(error,services.Conflict) else 'انتهت صلاحية الطلب أو تغيّرت البيانات.';status=409
    context.update(form=form,target_user=target)
    return finish(request,'password.html',context,status)


@superuser_view
@require_GET
def roles(request):
    context=base(request,'roles');q=request.GET.get('q','').strip()[:200]
    items=RoleProfile.objects.select_related('group').annotate(user_count=Count('group__user')).order_by('group__name')
    if q:items=items.filter(Q(group__name__icontains=q)|Q(description__icontains=q))
    page=Paginator(items,15).get_page(request.GET.get('page'))
    context.update(rows=[{'role':role,'delete_token':token(request,'role','delete',role),'duplicate_token':token(request,'role','duplicate',role)} for role in page],page_obj=page,q=q)
    return finish(request,'roles.html',context)


@superuser_view
@require_http_methods(['GET','POST'])
def role_editor(request,pk=None):
    role=get_object_or_404(RoleProfile.objects.select_related('group'),pk=pk) if pk else None
    initial={**(services.role_snapshot(role) if role else {'page_scope':'all'}),'snapshot':token(request,'role','save',role)}
    if role:
        codes=set(role.group.permissions.values_list('codename',flat=True));initial['permissions']=[m.key+':'+op for m in DEFINITIONS.values() for op in m.operations if codename(m.key,op) in codes];initial['allowed_pages']=list(role.allowed_pages.values_list('pk',flat=True))
    form=RoleForm(initial=initial,role=role);context=base(request,'roles');status=200
    if request.method=='POST':
        form=RoleForm(request.POST,role=role)
        try:
            data=load(request,'role','save',pk);saved=services.save_role(request.user,request.POST,pk,data['fingerprint']);messages.success(request,'تم حفظ الدور وصلاحياته. يسري التغيير فورًا على طلبات المستخدمين التالية.');return redirect('access_control:role_edit',pk=saved.pk)
        except services.InvalidForm as error:form=error.form;status=400
        except (services.Conflict,signing.BadSignature,IntegrityError,OperationalError) as error:context['error']=str(error) if isinstance(error,services.Conflict) else 'تعذّر الحفظ. الاسم مكرر أو انتهت صلاحية النموذج.';status=409
    users=role.group.user_set.order_by('username') if role else get_user_model().objects.none()
    context.update(form=form,role=role,matrix_rows=matrix(form,role=True),operations=Operation.choices,assigned_users=Paginator(users,15).get_page(request.GET.get('users_page')))
    return finish(request,'role_editor.html',context,status)


@superuser_view
@require_http_methods(['POST'])
def role_action(request,pk,operation):
    if operation not in {'delete','duplicate'}:return finish(request,'message.html',{**base(request),'error':'عملية غير متاحة.'},400)
    try:
        data=load(request,'role',operation,pk);saved=services.role_action(request.user,pk,data['fingerprint'],operation)
    except (services.Conflict,signing.BadSignature,IntegrityError,OperationalError) as error:
        message=str(error) if isinstance(error,services.Conflict) else 'انتهت صلاحية الطلب أو تغيّرت البيانات.'
        return add_login_headers(JsonResponse({'error':message},status=409)) if request.headers.get('X-Requested-With')=='XMLHttpRequest' else finish(request,'message.html',{**base(request,'roles'),'error':message},409)
    destination=reverse('access_control:role_edit',args=[saved.pk]) if saved else reverse('access_control:roles')
    if request.headers.get('X-Requested-With')=='XMLHttpRequest':return add_login_headers(JsonResponse({'message':'تم تنفيذ العملية.','redirect':destination}))
    messages.success(request,'تم تنفيذ العملية بنجاح.');return redirect(destination)


@superuser_view
@require_GET
def logs(request):
    context=base(request,'logs');q=request.GET.get('q','').strip()[:200];action=request.GET.get('action','');target=request.GET.get('user','');actor=request.GET.get('actor','')
    events=SecurityAudit.objects.select_related('actor','target_user','target_role')
    if q:events=events.filter(Q(actor_name__icontains=q)|Q(target_name__icontains=q)|Q(action__icontains=q))
    if action:events=events.filter(action=action)
    if numeric_id(target) is not None:events=events.filter(target_user_id=numeric_id(target))
    if numeric_id(actor) is not None:events=events.filter(actor_id=numeric_id(actor))
    page=Paginator(events,20).get_page(request.GET.get('page'))
    context.update(page_obj=page,q=q,selected_action=action,actions=SecurityAudit.objects.order_by('action').values_list('action',flat=True).distinct(),target_filter=target,actor_filter=actor)
    return finish(request,'logs.html',context)


@require_GET
def landing(request):
    if not request.user.is_authenticated:return redirect('accounts:login')
    return redirect(for_request(request).first_url())


@require_GET
def no_access(request):
    if not request.user.is_authenticated:return redirect('accounts:login')
    return finish(request,'no_access.html',{**base(request),'page_heading':'لم تُمنح صلاحيات بعد','active_page':'no_access'})
