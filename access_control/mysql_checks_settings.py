"""Isolated test containers only; this never uses the production DB settings."""
from service_providers.mysql_checks_settings import *
INSTALLED_APPS=[*INSTALLED_APPS,'access_control.apps.AccessControlConfig']
MIDDLEWARE=[*MIDDLEWARE,'access_control.middleware.AccessBoundaryMiddleware']

# MAKKEN RBAC ERROR TEST COMPAT v2
from pathlib import Path as _RbacTestPath
if (_RbacTestPath(__file__).resolve().parent.parent / 'core' / 'error_pages.py').is_file():
    if 'core.error_pages.FriendlyErrorMiddleware' not in MIDDLEWARE:
        MIDDLEWARE = [*MIDDLEWARE, 'core.error_pages.FriendlyErrorMiddleware']
    CSRF_FAILURE_VIEW = 'core.error_pages.csrf_failure'
