"""Explicitly isolated SQLite checks; this module never uses production MySQL."""
import os
os.environ.setdefault("DJANGO_SECRET_KEY", "execution-tests-not-a-production-secret")
for key in ("MYSQL_DATABASE", "MYSQL_USER", "MYSQL_PASSWORD"):
    os.environ.setdefault(key, "unused-isolated-tests")
from access_control.export_checks_settings import *
DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": os.environ.get("MAKKEN_EXECUTION_TEST_DB", ":memory:")}}
