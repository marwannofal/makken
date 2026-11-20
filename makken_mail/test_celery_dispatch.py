"""Tests for RabbitMQ/Celery on-commit dispatch and idempotent single-delivery task."""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from .models import Delivery, DeliveryStatus, EventRule, SMTPConfig
from .tasks import deliver_one_mail, dispatch_delivery

User = get_user_model()


class CeleryMailDispatchTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            "celery_emp", "celery_emp@example.com", "StrongPass123!", first_name="سالم"
        )
        self.rule, _ = EventRule.objects.update_or_create(
            code="account.created",
            defaults={"enabled": True, "to_subject": True},
        )
        SMTPConfig.objects.update_or_create(
            pk=1,
            defaults={
                "enabled": True,
                "host": "pro.turbo-smtp.com",
                "port": 465,
                "security": "tls",
                "sender": "noreply@menatech.edu.jo",
                "sender_name": "منصة مكّن",
            },
        )

    @override_settings(CELERY_BROKER_URL="")
    def test_dispatch_is_noop_when_broker_unconfigured(self):
        with patch("makken_mail.tasks.deliver_one_mail.delay") as mock_delay:
            result = dispatch_delivery(123)
            self.assertFalse(result)
            mock_delay.assert_not_called()

    @override_settings(CELERY_BROKER_URL="amqp://makken:secret@rabbitmq:5672//")
    def test_dispatch_publishes_on_commit_when_broker_configured(self):
        with patch("makken_mail.tasks.deliver_one_mail.delay") as mock_delay:
            with self.captureOnCommitCallbacks(execute=True):
                result = dispatch_delivery(456)
                self.assertTrue(result)
        mock_delay.assert_called_once_with(456)

    def test_deliver_one_mail_claims_once_and_is_idempotent(self):
        from .events import email_digest
        row = Delivery.objects.create(
            rule=self.rule,
            source="test:celery:1",
            recipient=self.user,
            recipient_key=self.user.pk,
            subject_user=self.user,
            email_digest=email_digest(self.user.email),
            status=DeliveryStatus.QUEUED,
        )
        with patch("makken_mail.tasks.process") as mock_process:
            first = deliver_one_mail(row.pk)
            self.assertTrue(first)
            mock_process.assert_called_once_with(row.pk)

            # Second invocation sees status != QUEUED and safely no-ops
            second = deliver_one_mail(row.pk)
            self.assertFalse(second)
            mock_process.assert_called_once()
