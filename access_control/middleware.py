from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin
from .enforcement import denied
from .policy import for_request
from .registry import PUBLIC_ROUTES, SELF_ROUTES


class AccessBoundaryMiddleware(MiddlewareMixin):
    """Fail-closed route boundary; views independently authorize operations."""
    def process_view(self,request,view_func,view_args,view_kwargs):
        route=request.resolver_match.view_name
        if route in PUBLIC_ROUTES:return None
        if not request.user.is_authenticated:
            from django.contrib.auth.views import redirect_to_login
            return redirect_to_login(request.get_full_path(),login_url='accounts:login')
        policy=for_request(request)
        if not policy.active:return denied(request,'هذا الحساب غير نشط.')
        if route in SELF_ROUTES:return None
        if request.resolver_match.namespace=='admin' or getattr(view_func,'_access_superuser',False):
            return None if policy.superuser else denied(request,'هذه الصفحة متاحة لمدير النظام الأعلى فقط.')
        if route in {'makken_home','home'} and not policy.can('dashboard'):
            return redirect(policy.first_url())
        module=getattr(view_func,'_access_module',None)
        if module is None:
            return None if policy.superuser else denied(request,'لم تُمنح صلاحية لهذه الصفحة.')
        if not policy.can(module):return denied(request)
        return None

    def process_exception(self,request,exception):
        from .signals import LastAdminError,ProtectedRoleError
        if isinstance(exception,LastAdminError):
            return denied(request,'لا يمكن تعطيل أو حذف آخر مدير نظام أعلى نشط.')
        if isinstance(exception,ProtectedRoleError):
            return denied(request,'لا يمكن حذف دور افتراضي أو دور مرتبط بمستخدمين.')
        return None
