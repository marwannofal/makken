"""Execution is separate from financial sponsorship and organization states."""
import uuid

from django.conf import settings
from django.db import models


class ExecutionStatus(models.TextChoices):
    NEW = "new", "جديد"
    RUNNING = "running", "تحت التنفيذ"
    COMPLETE = "complete", "مكتمل التنفيذ"


class NeedExecution(models.Model):
    need = models.OneToOneField("market_needs.Need", on_delete=models.PROTECT, related_name="execution")
    status = models.CharField(max_length=12, choices=ExecutionStatus.choices, default=ExecutionStatus.NEW)
    notes = models.TextField("ملاحظات التنفيذ", max_length=4000, blank=True)
    version = models.PositiveBigIntegerField(default=1, editable=False)
    last_request = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    last_digest = models.CharField(max_length=64, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="created_need_executions")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="updated_need_executions")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, editable=False)

    class Meta:
        default_permissions = ()
        constraints = [
            models.CheckConstraint(condition=models.Q(status__in=ExecutionStatus.values), name="mk_execution_status_valid"),
            models.CheckConstraint(condition=(models.Q(status="complete", completed_at__isnull=False) | (~models.Q(status="complete") & models.Q(completed_at__isnull=True))), name="mk_execution_completion_time"),
        ]
        indexes = [models.Index(fields=["status", "need"], name="mk_execution_status_idx")]


class ExecutionProvider(models.Model):
    execution = models.ForeignKey(NeedExecution, on_delete=models.CASCADE, related_name="provider_links")
    provider = models.ForeignKey("service_providers.ServiceProvider", on_delete=models.PROTECT, related_name="execution_links")
    evidence = models.JSONField(default=dict, editable=False)

    class Meta:
        default_permissions = ()
        ordering = ["pk"]
        constraints = [models.UniqueConstraint(fields=["execution", "provider"], name="mk_execution_provider_uq")]


class ExecutionEmployer(models.Model):
    execution = models.ForeignKey(NeedExecution, on_delete=models.CASCADE, related_name="employer_links")
    partnership = models.ForeignKey("partnerships.Partnership", on_delete=models.PROTECT, related_name="execution_links")
    evidence = models.JSONField(default=dict, editable=False)

    class Meta:
        default_permissions = ()
        ordering = ["pk"]
        constraints = [models.UniqueConstraint(fields=["execution", "partnership"], name="mk_execution_employer_uq")]
