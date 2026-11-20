"""Celery application configuration for Makken background tasks (RabbitMQ broker)."""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "makken.settings")

app = Celery("makken")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
