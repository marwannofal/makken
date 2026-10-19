"""Disposable provider test database only, never the production connection."""
from market_needs.mysql_checks_settings import *
INSTALLED_APPS = [*INSTALLED_APPS, "service_providers.apps.ServiceProvidersConfig"]
