"""No cross-request permission cache: changes apply on the very next request."""
from django.contrib.auth.models import Permission
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.urls import reverse
from .models import Module, Operation, UserAccess, PermissionOverride, RoleProfile, PageScope
from .registry import DEFINITIONS, codename


class AccessPolicy:
    def __init__(self, user):
        self.user = user
        self.active = bool(user.is_authenticated and user.is_active)
        self.superuser = bool(self.active and user.is_superuser)
        self.sources = {}
        self.denials = set()
        self.allowed_pages = set()
        self.scope = PageScope.SELECTED
        if not self.active or self.superuser:
            return
        access = UserAccess.objects.filter(user_id=user.pk).first()
        if access is None:
            return  # Existing/unconfigured users start with no business access.
        self.scope = access.page_scope
        self.allowed_pages = set(access.allowed_pages.values_list('pk', flat=True))
        roles = RoleProfile.objects.filter(group__user=user).select_related('group').prefetch_related('allowed_pages', Prefetch('group__permissions', queryset=Permission.objects.filter(content_type__app_label='access_control', content_type__model='module')))
        self.role_names = []
        for role in roles:
            self.role_names.append(role.group.name)
            pages = {p.pk for p in role.allowed_pages.all()}
            codes = {p.codename for p in role.group.permissions.all()}
            for module, definition in DEFINITIONS.items():
                if role.page_scope == PageScope.SELECTED and module not in pages:
                    continue
                for operation in definition.operations:
                    if codename(module, operation) in codes:
                        self.sources.setdefault((module, operation), []).append('دور: ' + role.group.name)
        codes = set(user.user_permissions.filter(content_type__app_label='access_control',content_type__model='module').values_list('codename',flat=True))
        for module, definition in DEFINITIONS.items():
            for operation in definition.operations:
                if codename(module, operation) in codes:
                    self.sources.setdefault((module, operation), []).append('منح مباشر')
        for rule in PermissionOverride.objects.filter(user_id=user.pk):
            key=(rule.module_id, rule.operation)
            if rule.effect == 'deny':
                self.denials.add(key)
            else:
                self.sources.setdefault(key, []).append('منح مباشر')

    def decision(self, module, operation='view'):
        definition = DEFINITIONS.get(module)
        if not self.active:
            return False, 'الحساب غير نشط أو غير مسجل الدخول'
        if definition is None or operation not in definition.operations:
            return False, 'عملية أو صفحة غير معرّفة'
        if self.superuser:
            return True, 'مدير النظام الأعلى'
        if self.scope == PageScope.SELECTED and module not in self.allowed_pages:
            return False, 'خارج الصفحات المحددة للمستخدم'
        key=(module, operation)
        if key in self.denials:
            return False, 'منع صريح للمستخدم'
        if operation != 'view':
            permitted, source = self.decision(module,'view')
            if not permitted:
                return False, 'صلاحية العرض مطلوبة: ' + source
        sources = self.sources.get(key, [])
        return (bool(sources), ' + '.join(dict.fromkeys(sources)) if sources else 'لم تُمنح الصلاحية')

    def can(self, module, operation='view'):
        return self.decision(module,operation)[0]

    def first_url(self):
        for module in DEFINITIONS.values():
            if self.can(module.key):
                return reverse(module.route_name)
        return reverse('access_control:no_access')


def for_request(request):
    if not hasattr(request,'_makken_policy'):
        request._makken_policy=AccessPolicy(request.user)
    return request._makken_policy


def require(user, module, *operations):
    policy=AccessPolicy(user)
    for operation in operations or ('view',):
        if not policy.can(module,operation):
            raise PermissionDenied('ليست لديك صلاحية لتنفيذ هذه العملية على هذه الصفحة.')


def require_superuser(user):
    if not user.is_authenticated or not user.is_active or not user.is_superuser:
        raise PermissionDenied('هذه الصفحة متاحة لمدير النظام الأعلى فقط.')
