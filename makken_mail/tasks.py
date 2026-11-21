"""Celery tasks and safe on-commit RabbitMQ dispatcher for Makken email deliveries."""
import logging

from django.conf import settings
from django.db import transaction
from django.utils import timezone

try:
    from celery import shared_task
except ImportError:  # pragma: no cover - fallback when celery is absent in minimal local dev
    def shared_task(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

from .models import Delivery, DeliveryStatus
from .worker import process, run_batch

logger = logging.getLogger(__name__)


@shared_task(name="makken_mail.tasks.deliver_one_mail", ignore_result=True)
def deliver_one_mail(delivery_id):
    """Atomically claim and deliver one queued Delivery row (idempotent)."""
    now = timezone.now()
    changed = Delivery.objects.filter(
        pk=delivery_id,
        status=DeliveryStatus.QUEUED,
        next_at__lte=now,
    ).update(status=DeliveryStatus.SENDING, last_at=now)
    if not changed:
        return False
    # Increment attempts cleanly after claim
    row = Delivery.objects.filter(pk=delivery_id).first()
    if row is None:
        return False
    Delivery.objects.filter(pk=delivery_id).update(attempts=row.attempts + 1, reason="")
    process(delivery_id)
    return True


@shared_task(name="makken_mail.tasks.deliver_pending_mail", ignore_result=True)
def deliver_pending_mail(limit=50):
    """Periodic safety sweep for retries, reminders, and any un-dispatched deliveries."""
    return run_batch(limit=max(1, min(100, int(limit))), max_seconds=50)


@shared_task(name="makken_mail.tasks.queue_partnership_expiry_reminders", ignore_result=True)
def queue_partnership_expiry_reminders():
    """Periodic Docker Beat task to queue US-06 2-month partnership expiry reminders."""
    from .reminders import queue_due_reminders
    return queue_due_reminders()


def _publish(delivery_id):
    try:
        deliver_one_mail.delay(delivery_id)
    except Exception:
        logger.warning("RabbitMQ publish failed for delivery %s; beat sweep will retry", delivery_id, exc_info=True)


def dispatch_delivery(delivery_id):
    """Push a committed Delivery ID to RabbitMQ when CELERY_BROKER_URL is configured."""
    if not delivery_id or not getattr(settings, "CELERY_BROKER_URL", ""):
        return False
    transaction.on_commit(lambda: _publish(delivery_id))
    return True
