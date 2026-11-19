from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone


class SMTPConfig(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    host = models.CharField(max_length=253, blank=True)
    port = models.PositiveSmallIntegerField(default=587)
    security = models.CharField(max_length=8, choices=[('starttls', 'STARTTLS'), ('tls', 'TLS')], default='starttls')
    username = models.CharField(max_length=254, blank=True)
    secret = models.TextField(blank=True, editable=False)
    sender = models.EmailField(blank=True)
    sender_name = models.CharField(max_length=100, default='مكّن')
    enabled = models.BooleanField(default=False)
    test_at = models.DateTimeField(null=True, editable=False)
    revision = models.PositiveIntegerField(default=1, editable=False)

    class Meta:
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=models.Q(pk=1), name='mk_mail_smtp_singleton')]


class EventRule(models.Model):
    code = models.CharField(max_length=90, primary_key=True)
    enabled = models.BooleanField(default=False)
    to_actor = models.BooleanField(default=False)
    to_subject = models.BooleanField(default=False)
    to_employee = models.BooleanField(default=False)
    to_manager = models.BooleanField(default=False)
    recipients = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='makken_email_rules')
    revision = models.PositiveIntegerField(default=1, editable=False)

    class Meta:
        default_permissions = ()


class RecipientMute(models.Model):
    rule = models.ForeignKey(EventRule, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='makken_email_mutes')

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['rule', 'user'], name='mk_mail_unique_mute')]


class WorkStatus(models.TextChoices):
    NEW = 'new', 'جديدة'
    RUNNING = 'running', 'قيد العمل'
    COMPLETE = 'complete', 'مكتملة'
    CANCELLED = 'cancelled', 'ملغاة'


class WorkAssignment(models.Model):
    title = models.CharField(max_length=160)
    instructions = models.TextField(blank=True, max_length=3000)
    target_model = models.CharField(max_length=55, blank=True, default='')
    target_key = models.PositiveBigIntegerField(null=True, blank=True)
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='makken_assigned_work')
    assignees = models.ManyToManyField(settings.AUTH_USER_MODEL, blank=True, related_name='makken_work_assignments', verbose_name='الموظفون المسند إليهم')
    manager = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='makken_managed_work')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    status = models.CharField(max_length=12, choices=WorkStatus.choices, default=WorkStatus.NEW)
    progress = models.PositiveSmallIntegerField(default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    due_on = models.DateField(null=True, blank=True)
    revision = models.PositiveIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ()
        ordering = ['-updated_at', '-pk']
        indexes = [models.Index(fields=['target_model', 'target_key', 'status'], name='mk_work_target_idx')]
        constraints = [
            models.CheckConstraint(condition=models.Q(progress__gte=0, progress__lte=100), name='mk_work_progress_range'),
            models.CheckConstraint(condition=models.Q(status__in=WorkStatus.values), name='mk_work_status_valid'),
            models.CheckConstraint(condition=models.Q(status='complete', progress=100) | (~models.Q(status='complete') & models.Q(progress__lt=100)), name='mk_work_complete_progress'),
            models.CheckConstraint(condition=~models.Q(employee=models.F('manager')), name='mk_work_separate_manager'),
            models.CheckConstraint(condition=models.Q(target_model='', target_key__isnull=True) | (~models.Q(target_model='') & models.Q(target_key__gt=0, target_key__isnull=False)), name='mk_work_target_pair'),
        ]


class WorkHistory(models.Model):
    assignment = models.ForeignKey(WorkAssignment, on_delete=models.CASCADE, related_name='history')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    action = models.CharField(max_length=20)
    snapshot = models.JSONField(default=dict)
    note = models.TextField(blank=True, max_length=1000)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        default_permissions = ()
        ordering = ['-pk']


class DeliveryStatus(models.TextChoices):
    QUEUED = 'queued', 'بانتظار الإرسال'
    SENDING = 'sending', 'قيد الإرسال'
    SENT = 'sent', 'قبله مزود البريد'
    FAILED = 'failed', 'فشل الإرسال'
    SKIPPED = 'skipped', 'تم التخطي'
    UNKNOWN = 'unknown', 'النتيجة غير مؤكدة'


class Delivery(models.Model):
    rule = models.ForeignKey(EventRule, on_delete=models.PROTECT, related_name='deliveries')
    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    recipient_key = models.PositiveBigIntegerField()
    email_digest = models.CharField(max_length=64, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    subject_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    activity = models.ForeignKey('access_control.UserActivity', on_delete=models.SET_NULL, null=True, related_name='+')
    work = models.ForeignKey(WorkAssignment, on_delete=models.SET_NULL, null=True, related_name='+')
    work_history = models.ForeignKey(WorkHistory, on_delete=models.SET_NULL, null=True, related_name='+')
    record_model = models.CharField(max_length=55, blank=True)
    record_key = models.PositiveBigIntegerField(null=True)
    source = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)
    next_at = models.DateTimeField(default=timezone.now)
    last_at = models.DateTimeField(null=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=10, choices=DeliveryStatus.choices, default=DeliveryStatus.QUEUED)
    reason = models.CharField(max_length=50, blank=True)

    class Meta:
        default_permissions = ()
        ordering = ['-pk']
        indexes = [models.Index(fields=['status', 'next_at', 'id'], name='mk_mail_due_idx')]
        constraints = [models.UniqueConstraint(fields=['source', 'recipient_key'], name='mk_mail_event_recipient')]
