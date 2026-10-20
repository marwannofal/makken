from .settings import *
import os

DEBUG = False
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

ALLOWED_HOSTS = ["46.101.119.184", "localhost", "127.0.0.1"]
CSRF_TRUSTED_ORIGINS = ["https://46.101.119.184"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.environ["MYSQL_DATABASE"],
        "USER": os.environ["MYSQL_USER"],
        "PASSWORD": os.environ["MYSQL_PASSWORD"],
        "HOST": "db",
        "PORT": "3306",
        "CONN_MAX_AGE": 60,
        "CONN_HEALTH_CHECKS": True,
        "OPTIONS": {
            "charset": "utf8mb4",
            "connect_timeout": 10,
        },
    }
}

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

FILE_UPLOAD_PERMISSIONS = 0o644
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o755

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = os.environ.get("DJANGO_HTTPS", "0") == "1"

SESSION_COOKIE_SECURE = SECURE_SSL_REDIRECT
CSRF_COOKIE_SECURE = SECURE_SSL_REDIRECT
SECURE_CONTENT_TYPE_NOSNIFF = True

# BEGIN MAKKEN DOMAIN
ALLOWED_HOSTS = list(dict.fromkeys([*ALLOWED_HOSTS, "makken.menatech.edu.jo"]))
CSRF_TRUSTED_ORIGINS = list(dict.fromkeys([*CSRF_TRUSTED_ORIGINS, "https://makken.menatech.edu.jo"]))
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SESSION_COOKIE_DOMAIN = None
CSRF_COOKIE_DOMAIN = None
# END MAKKEN DOMAIN

# BEGIN MAKKEN ARABIC VALIDATION
LANGUAGE_CODE = "ar"
USE_I18N = True
LANGUAGES = [("ar", "العربية")]
# END MAKKEN ARABIC VALIDATION

# BEGIN MAKKEN FRIENDLY ERRORS
if "core.error_pages.FriendlyErrorMiddleware" not in MIDDLEWARE:
    MIDDLEWARE = [*MIDDLEWARE, "core.error_pages.FriendlyErrorMiddleware"]
CSRF_FAILURE_VIEW = "core.error_pages.csrf_failure"
MAKKEN_ERROR_ASSET_BASE = "/__makken_errors/assets/"
# END MAKKEN FRIENDLY ERRORS

# BEGIN MAKKEN SERVICE PROVIDERS
if not any(_app == "service_providers" or _app.startswith("service_providers.") for _app in INSTALLED_APPS):
    INSTALLED_APPS = [*INSTALLED_APPS, "service_providers.apps.ServiceProvidersConfig"]
# END MAKKEN SERVICE PROVIDERS

# MAKKEN RBAC INTEGRATION v1
if not any(app == 'access_control' or app.startswith('access_control.') for app in INSTALLED_APPS):
    INSTALLED_APPS = [*INSTALLED_APPS, 'access_control.apps.AccessControlConfig']
if 'access_control.middleware.AccessBoundaryMiddleware' not in MIDDLEWARE:
    MIDDLEWARE = [*MIDDLEWARE, 'access_control.middleware.AccessBoundaryMiddleware']

# BEGIN MAKKEN SHARED TABLE EXPORTS v1
# Appended last so authentication and page access checks always run first.
if "core.table_exports.TableExportMiddleware" not in MIDDLEWARE:
    MIDDLEWARE = [*MIDDLEWARE, "core.table_exports.TableExportMiddleware"]
# END MAKKEN SHARED TABLE EXPORTS v1
