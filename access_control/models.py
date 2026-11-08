from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models
from django.utils import timezone


class PageScope(models.TextChoices):
    ALL = 'all', 'جميع الصفحات المسموح بها'
    SELECTED = 'selected', 'صفحات محددة فقط'


class RegionScope(models.TextChoices):
    ALL = 'all', 'جميع المناطق'
    SELECTED = 'selected', 'مناطق محددة فقط'


class Operation(models.TextChoices):
    VIEW = 'view', 'عرض'
    CREATE = 'create', 'إضافة'
    EDIT = 'edit', 'تعديل'
    DELETE = 'delete', 'حذف'
    STATUS = 'change_status', 'تغيير الحالة'
    EXPORT = 'export', 'تنزيل المرفقات'
    EXPORT_XLSX = 'export_xlsx', 'تصدير Excel'
    EXPORT_PDF = 'export_pdf', 'تصدير PDF'


class Module(models.Model):
    key = models.SlugField(primary_key=True, max_length=60)
    title = models.CharField(max_length=150)
    route_name = models.CharField(max_length=120)
    operations = models.JSONField(default=list)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['position', 'key']
        default_permissions = ()

    def __str__(self):
        return self.title


class RoleProfile(models.Model):
    group = models.OneToOneField(Group, on_delete=models.CASCADE, related_name='makken_role')
    description = models.CharField(max_length=500, blank=True)
    system_key = models.CharField(max_length=20, null=True, blank=True, unique=True, editable=False)
    page_scope = models.CharField(max_length=10, choices=PageScope.choices, default=PageScope.ALL)
    allowed_pages = models.ManyToManyField(Module, blank=True, related_name='roles')
    version = models.PositiveBigIntegerField(default=1, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['group__name', 'pk']
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=models.Q(page_scope__in=PageScope.values), name='access_role_scope_valid')]

    def __str__(self):
        return self.group.name


class UserAccess(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='makken_access')
    page_scope = models.CharField(max_length=10, choices=PageScope.choices, default=PageScope.SELECTED)
    allowed_pages = models.ManyToManyField(Module, blank=True, related_name='users')
    region_scope = models.CharField(max_length=10, choices=RegionScope.choices, default=RegionScope.ALL)
    allowed_regions = models.ManyToManyField('regions.Region', through='UserRegion', blank=True, related_name='regional_users')
    version = models.PositiveBigIntegerField(default=1, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=models.Q(page_scope__in=PageScope.values), name='access_user_scope_valid'),
                       models.CheckConstraint(condition=models.Q(region_scope__in=RegionScope.values), name='access_user_regions_valid')]


class UserRegion(models.Model):
    access = models.ForeignKey(UserAccess, on_delete=models.CASCADE)
    region = models.ForeignKey('regions.Region', on_delete=models.PROTECT)

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['access', 'region'], name='access_user_region_unique')]


class PermissionOverride(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='makken_overrides')
    module = models.ForeignKey(Module, on_delete=models.CASCADE)
    operation = models.CharField(max_length=20, choices=Operation.choices)
    effect = models.CharField(max_length=5, choices=[('grant', 'منح مباشر'), ('deny', 'منع صريح')])

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=['user', 'module', 'operation'], name='access_user_module_op_unique'),
            models.CheckConstraint(condition=models.Q(operation__in=Operation.values), name='access_operation_valid'),
            models.CheckConstraint(condition=models.Q(effect__in=['grant', 'deny']), name='access_effect_valid'),
        ]


class SecurityLock(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)

    class Meta:
        default_permissions = ()


class SecurityAudit(models.Model):
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name='access_actions')
    actor_name = models.CharField(max_length=150)
    target_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='access_history')
    target_role = models.ForeignKey(RoleProfile, null=True, blank=True, on_delete=models.SET_NULL)
    target_name = models.CharField(max_length=150)
    action = models.CharField(max_length=100)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-pk']
        default_permissions = ()
        indexes = [models.Index(fields=['target_user', '-created_at'], name='access_user_history_idx'), models.Index(fields=['action', '-created_at'], name='access_action_time_idx')]


class ActivityAction(models.TextChoices):
    VIEW = 'view', 'مشاهدة'
    CREATE = 'create', 'إضافة'
    UPDATE = 'update', 'تعديل'
    DELETE = 'delete', 'حذف'
    STATUS = 'status', 'تغيير الحالة'
    LOGIN = 'login', 'تسجيل الدخول'
    LOGOUT = 'logout', 'تسجيل الخروج'
    DOWNLOAD = 'download', 'تنزيل مرفق'
    XLSX = 'export_xlsx', 'تصدير Excel'
    PDF = 'export_pdf', 'تصدير PDF'
    DENIED = 'denied', 'محاولة غير مسموحة'


class UserActivity(models.Model):
    """Append-only portal events; snapshots survive renamed/deleted source rows.

    No CRUD routes or default Django edit/delete permissions are exposed.
    This is an application audit trail, not a tamper-proof external ledger.
    """
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    actor_key = models.PositiveBigIntegerField(null=True)
    actor_name = models.CharField(max_length=200)
    actor_username = models.CharField(max_length=150, blank=True)
    module = models.SlugField(max_length=60)
    action = models.CharField(max_length=20, choices=ActivityAction.choices)
    description = models.CharField(max_length=200)
    target_model = models.CharField(max_length=100, blank=True)
    target_key = models.CharField(max_length=40, blank=True)
    target_label = models.CharField(max_length=300, blank=True)
    scope = models.CharField(max_length=10, choices=[('global', 'عام'), ('regional', 'مناطقي'), ('unknown', 'غير محدد')])
    route = models.CharField(max_length=150, blank=True)
    outcome = models.CharField(max_length=10, choices=[('success', 'ناجحة'), ('denied', 'مرفوضة')], default='success')
    http_status = models.PositiveSmallIntegerField(null=True)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict)
    request_id = models.UUIDField(null=True)
    source_key = models.CharField(max_length=180, unique=True, null=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ['-created_at', '-pk']
        default_permissions = ()
        indexes = [
            models.Index(fields=['-created_at', '-id'], name='activity_time_idx'),
            models.Index(fields=['actor_key', '-created_at'], name='activity_actor_time_idx'),
            models.Index(fields=['module', '-created_at'], name='activity_module_time_idx'),
            models.Index(fields=['action', '-created_at'], name='activity_action_time_idx'),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(action__in=ActivityAction.values), name='activity_action_valid'),
            models.CheckConstraint(condition=models.Q(scope__in=['global', 'regional', 'unknown']), name='activity_scope_valid'),
            models.CheckConstraint(condition=models.Q(outcome__in=['success', 'denied']), name='activity_outcome_valid'),
        ]


class ActivityRegion(models.Model):
    # Deliberately not a FK to Region: deleting/renaming a reference must never
    # erase history or become blocked solely by the log.
    event = models.ForeignKey(UserActivity, on_delete=models.CASCADE, related_name='region_snapshots')
    region_key = models.PositiveBigIntegerField(db_index=True)
    name = models.CharField(max_length=100)

    class Meta:
        default_permissions = ()
        ordering = ['region_key']
        constraints = [models.UniqueConstraint(fields=['event', 'region_key'], name='activity_event_region_unique')]
