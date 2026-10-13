from .settings import *

DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "[::1]"]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": "/data/db.sqlite3",
    }
}
