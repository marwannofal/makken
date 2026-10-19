from functools import wraps
from urllib.parse import urlsplit
from django.urls import resolve,Resolver404
from .policy import for_request
from .registry import SELF_ROUTES


def permission_aware_login(cls):
    """Retain the existing login implementation, remember-me and safe-next logic."""
    original=cls.get_success_url
    @wraps(original)
    def get_success_url(self):
        proposed=original(self)
        policy=for_request(self.request)
        if policy.superuser:return proposed
        try:
            match=resolve(urlsplit(proposed).path)
        except (Resolver404,ValueError):return policy.first_url()
        if match.view_name in SELF_ROUTES:return proposed
        module=getattr(match.func,'_access_module',None)
        operation='create' if match.url_name=='create' else 'edit' if match.url_name=='edit' else 'export' if match.url_name in {'download','attachment_download'} else 'view'
        return proposed if module and policy.can(module) and policy.can(module,operation) else policy.first_url()
    cls.get_success_url=get_success_url
    return cls
