"""MySQL 8.4 checks in a disposable, internal-only Compose network."""
import os
if os.environ.get("MAKKEN_ISOLATED_EXECUTION_MYSQL_TESTS") != "1":
    raise RuntimeError("Use compose.execution-tests.yaml; production database access is forbidden here.")
from .execution_checks_settings import *
DATABASES = {"default": {
    "ENGINE": "django.db.backends.mysql", "NAME": "execution_checks", "USER": "root",
    "PASSWORD": "execution-checks-disposable-only", "HOST": "mysql-execution-tests", "PORT": "3306",
    "CONN_MAX_AGE": 0, "OPTIONS": {"charset": "utf8mb4", "isolation_level": "read committed"},
    "TEST": {"NAME": "test_execution_checks"},
}}
