"""Per-module document export rights using the existing Makken access policy."""
from django.core.exceptions import PermissionDenied
from django.urls import Resolver404, resolve

from .policy import for_request
from .registry import DEFINITIONS

FORMATS = {'xlsx': 'export_xlsx', 'pdf': 'export_pdf'}


def export_operation(format):
    try:
        return FORMATS[format]
    except (KeyError, TypeError):
        raise PermissionDenied('صيغة التصدير غير مدعومة.') from None


def export_access(request):
    """Fail closed for unresolved/unregistered routes and missing page access.

    Resolve the real protected callable; never trust GET, HTML or a browser
    supplied module name. User/role page scopes and explicit denials are handled
    by the same request-scoped policy as the rest of the portal.
    """
    rights = {'xlsx': False, 'pdf': False}
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated or not user.is_active:
        return rights
    match = getattr(request, 'resolver_match', None)
    if match is None:
        try:
            match = resolve(request.path_info, urlconf=getattr(request, 'urlconf', None))
        except Resolver404:
            return rights
    policy = for_request(request)
    module = getattr(match.func, '_access_module', None)
    if module in DEFINITIONS:
        return {format: policy.can(module, operation) for format, operation in FORMATS.items()}
    # These pages remain superuser-only. A role cannot gain account management
    # by acquiring export rights to a business module.
    if (policy.superuser and getattr(match.func, '_access_superuser', False)
            and match.view_name in {'access_control:index', 'access_control:roles', 'access_control:logs'}):
        return {'xlsx': True, 'pdf': True}
    return rights
