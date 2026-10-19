from .settings import *

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "/data/db.sqlite3",
    }
}

# MAKKEN RBAC INTEGRATION v1
if not any(app == 'access_control' or app.startswith('access_control.') for app in INSTALLED_APPS):
    INSTALLED_APPS = [*INSTALLED_APPS, 'access_control.apps.AccessControlConfig']
if 'access_control.middleware.AccessBoundaryMiddleware' not in MIDDLEWARE:
    MIDDLEWARE = [*MIDDLEWARE, 'access_control.middleware.AccessBoundaryMiddleware']
