"""Transactional user/role administration. Never record a password or token."""
import hashlib
import json
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group,Permission
from django.core.exceptions import PermissionDenied
from django.db import transaction
from accounts.models import UserProfile
from accounts.profile_forms import email_key
from .forms import UserForm,RoleForm,AdminPasswordForm
from .models import UserAccess,RoleProfile,PermissionOverride,SecurityAudit,SecurityLock,PageScope,Operation,Module
from .policy import require_superuser
from .registry import DEFINITIONS,codename


class Conflict(Exception):pass
class InvalidForm(Exception):
    def __init__(self,form):self.form=form


def user_snapshot(user):
    access=getattr(user,'makken_access',None)
    groups=list(user.groups.all()) if 'groups' in getattr(user,'_prefetched_objects_cache',{}) else list(user.groups.select_related('makken_role'))
    overrides=list(user.makken_overrides.all())
    direct=list(user.user_permissions.all()) if 'user_permissions' in getattr(user,'_prefetched_objects_cache',{}) else list(user.user_permissions.filter(content_type__app_label='access_control',content_type__model='module'))
    return {'username':user.get_username(),'full_name':user.get_full_name(),'email':user.email,'is_active':user.is_active,'is_superuser':user.is_superuser,
            'roles':sorted(group.name for group in groups if getattr(group,'makken_role',None) is not None),
            'page_scope':access.page_scope if access else PageScope.SELECTED,
            'pages':sorted(page.pk for page in access.allowed_pages.all()) if access else [],
            'overrides':[{'module_id':rule.module_id,'operation':rule.operation,'effect':rule.effect} for rule in sorted(overrides,key=lambda r:(r.module_id,r.operation))],
            'direct_permissions':sorted(rule.codename for rule in direct)}


def role_snapshot(role):
    return {'name':role.group.name,'description':role.description,'page_scope':role.page_scope,'pages':list(role.allowed_pages.order_by('pk').values_list('pk',flat=True)),
            'permissions':list(role.group.permissions.filter(content_type__app_label='access_control',content_type__model='module').order_by('pk').values_list('codename',flat=True))}


def fingerprint(target,kind):
    data=user_snapshot(target) if kind=='user' else role_snapshot(target)
    # Self-service profile changes invalidate an already-open management form.
    data['version']=UserAccess.objects.filter(user=target).values_list('version',flat=True).first() if kind=='user' else target.version
    return hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def audit(actor,action,target,before,after):
    return SecurityAudit.objects.create(actor=actor,actor_name=actor.get_username(),target_user=target if isinstance(target,get_user_model()) else None,target_role=target if isinstance(target,RoleProfile) else None,target_name=str(target),action=action,before=before,after=after)


def lock_actor(actor):
    # All account administration serializes here, including last-admin checks.
    SecurityLock.objects.select_for_update().get(pk=1)
    actor=get_user_model()._default_manager.get(pk=actor.pk)
    require_superuser(actor)
    return actor


def locked_target(pk,expected,kind):
    model=get_user_model() if kind=='user' else RoleProfile
    target=model._default_manager.select_for_update().filter(pk=pk).first()
    if not target or fingerprint(target,kind)!=expected:raise Conflict('تغيّرت البيانات أو نُفذ الطلب مسبقًا. أعد تحميل الصفحة قبل الحفظ.')
    return target


def ensure_active_admin(actor,target,active):
    if target.pk==actor.pk and not active:raise Conflict('لا يمكنك إيقاف حسابك الحالي من لوحة الإدارة.')
    if target.is_superuser and target.is_active and not active and not get_user_model().objects.filter(is_superuser=True,is_active=True).exclude(pk=target.pk).exists():
        raise Conflict('لا يمكن إيقاف آخر مدير نظام أعلى نشط.')


@transaction.atomic
def save_user(actor,data,pk=None,expected=None):
    actor=lock_actor(actor);target=locked_target(pk,expected,'user') if pk else None
    form=UserForm(data,target=target)
    if not form.is_valid():raise InvalidForm(form)
    values=form.cleaned_data;before=user_snapshot(target) if target else {};new=target is None
    if target:ensure_active_admin(actor,target,values['is_active']=='1')
    User=get_user_model()
    if target is None:target=User(is_superuser=False,is_staff=False)
    names=values['full_name'].split(' ',1)
    target.first_name=names[0];target.last_name=names[1] if len(names)>1 else ''
    setattr(target,User.USERNAME_FIELD,values['username']);target.email=values['email'];target.is_active=values['is_active']=='1'
    if new:target.set_password(values['new_password1'])
    target.save()
    access,_=UserAccess.objects.get_or_create(user=target)
    access.page_scope=values['page_scope'];access.version+=1;access.save();access.allowed_pages.set(values['allowed_pages'])
    # Preserve unrelated existing Django groups/permissions; only manage RBAC here.
    other=list(target.groups.filter(makken_role__isnull=True).values_list('pk',flat=True))
    target.groups.set(other+[r.group_id for r in values['roles']])
    target._state.fields_cache.pop('makken_access',None)
    PermissionOverride.objects.filter(user=target).delete()
    rules=[]
    for module in DEFINITIONS.values():
        for operation in module.operations:
            effect=values.get(f'override__{module.key}__{operation}')
            if effect in {'grant','deny'}:rules.append(PermissionOverride(user=target,module_id=module.key,operation=operation,effect=effect))
    PermissionOverride.objects.bulk_create(rules)
    target.user_permissions.remove(*target.user_permissions.filter(content_type__app_label='access_control',content_type__model='module'))
    profile,_=UserProfile.objects.get_or_create(user=target)
    profile.email_key=email_key(target.email);profile.version+=1;profile.save(update_fields=['email_key','version','updated_at'])
    audit(actor,'إنشاء مستخدم' if new else 'تعديل المستخدم والصلاحيات',target,before,user_snapshot(target))
    return target


@transaction.atomic
def toggle_user(actor,pk,expected):
    actor=lock_actor(actor);target=locked_target(pk,expected,'user')
    ensure_active_admin(actor,target,not target.is_active);before=user_snapshot(target)
    target.is_active=not target.is_active;target.save(update_fields=['is_active'])
    access,_=UserAccess.objects.get_or_create(user=target);access.version+=1;access.save()
    audit(actor,'تغيير حالة حساب',target,before,user_snapshot(target));return target


@transaction.atomic
def reset_password(actor,pk,expected,data):
    actor=lock_actor(actor);target=locked_target(pk,expected,'user')
    form=AdminPasswordForm(data,user=target)
    if not form.is_valid():raise InvalidForm(form)
    target.set_password(form.cleaned_data['new_password1']);target.save(update_fields=['password'])
    access,_=UserAccess.objects.get_or_create(user=target);access.version+=1;access.save()
    profile,_=UserProfile.objects.get_or_create(user=target);profile.version+=1;profile.password_failures=0;profile.password_locked_until=None;profile.failure_window_started_at=None;profile.save()
    audit(actor,'إعادة تعيين كلمة المرور',target,{}, {'password_reset':True})
    return target


@transaction.atomic
def save_role(actor,data,pk=None,expected=None):
    actor=lock_actor(actor);role=locked_target(pk,expected,'role') if pk else None
    form=RoleForm(data,role=role)
    if not form.is_valid():raise InvalidForm(form)
    values=form.cleaned_data;before=role_snapshot(role) if role else {};new=role is None
    if role is None:role=RoleProfile(group=Group.objects.create(name=values['name']))
    else:role.group.name=values['name'];role.group.save(update_fields=['name'])
    role.description=values['description'];role.page_scope=values['page_scope'];role.version+=1;role.save();role.allowed_pages.set(values['allowed_pages'])
    codes=[codename(*key.split(':')) for key in values['permissions']]
    permissions=Permission.objects.filter(content_type__app_label='access_control',content_type__model='module',codename__in=codes)
    unrelated=list(role.group.permissions.exclude(content_type__app_label='access_control',content_type__model='module'))
    role.group.permissions.set([*unrelated,*permissions])
    audit(actor,'إنشاء دور' if new else 'تعديل دور وصلاحياته',role,before,role_snapshot(role));return role


@transaction.atomic
def role_action(actor,pk,expected,operation):
    actor=lock_actor(actor);role=locked_target(pk,expected,'role');before=role_snapshot(role)
    if operation=='delete':
        if role.system_key:raise Conflict('الدور الافتراضي محفوظ للنظام. يمكنك تعديل صلاحياته بدل حذفه.')
        if role.group.user_set.exists():raise Conflict('لا يمكن حذف دور مرتبط بمستخدمين. أزل تعييناته أولًا.')
        audit(actor,'حذف دور',role,before,{})
        group=role.group;role.delete();group.delete();return None
    if operation!='duplicate':raise Conflict('عملية غير متاحة.')
    role.version+=1;role.save(update_fields=['version','updated_at'])
    base=role.group.name[:120]+' — نسخة';name=base;index=2
    while Group.objects.filter(name=name).exists():name=base+' '+str(index);index+=1
    clone=RoleProfile.objects.create(group=Group.objects.create(name=name),description=role.description,page_scope=role.page_scope)
    clone.allowed_pages.set(role.allowed_pages.all());clone.group.permissions.set(role.group.permissions.all())
    audit(actor,'نسخ دور',clone,{'source_role_id':role.pk,'source_role':role.group.name},role_snapshot(clone));return clone
