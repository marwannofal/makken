"""Disposable MySQL test container only; never points to the production service."""
import os
from pathlib import Path

if os.environ.get("MAKKEN_ISOLATED_MYSQL_TESTS") != "1":
    raise RuntimeError("Use compose.market-tests.yaml for isolated MySQL checks.")

SECRET_KEY = "isolated-market-tests-only-not-for-production"
BASE_DIR = Path(__file__).resolve().parent.parent
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost", "127.0.0.1"]
ROOT_URLCONF = "makken.urls"
INSTALLED_APPS = [
    "django.contrib.admin", "django.contrib.auth", "django.contrib.contenttypes",
    "django.contrib.sessions", "django.contrib.messages", "django.contrib.staticfiles",
    "accounts", "core", "care_states", "levels", "regions", "entities",
    "specializations", "sectors", "expense_items", "training_programs",
    "sponsorship_shapes", "partnerships", "market_needs",
]
TEMPLATES = [{
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [], "APP_DIRS": True,
    "OPTIONS": {"context_processors": [
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
    ]},
}]
STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "/"
LANGUAGE_CODE = "ar"
TIME_ZONE = "Asia/Riyadh"
DATABASES = {"default": {
    "ENGINE": "django.db.backends.mysql", "NAME": "makken_market_checks",
    "USER": "root", "PASSWORD": "isolated-market-tests-only",
    "HOST": "mysql-tests", "PORT": "3306", "CONN_MAX_AGE": 0,
    "OPTIONS": {"charset": "utf8mb4", "isolation_level": "read committed"},
    "TEST": {"NAME": "test_makken_market_checks"},
}}
AUTHENTICATION_BACKENDS = ["accounts.backends.EmailOrUsernameBackend"]
MIDDLEWARE = ["django.middleware.security.SecurityMiddleware", "django.contrib.sessions.middleware.SessionMiddleware", "django.middleware.csrf.CsrfViewMiddleware", "django.contrib.auth.middleware.AuthenticationMiddleware", "django.contrib.messages.middleware.MessageMiddleware"]
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
USE_TZ = True
MAKKEN_PRIVATE_UPLOAD_ROOT = "/tmp/makken-market-test-uploads"
