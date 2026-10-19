from django.conf import settings
from django.contrib.auth.models import Group
from django.db import models


class PageScope(models.TextChoices):
    ALL = 'all', 'جميع الصفحات المسموح بها'
    SELECTED = 'selected', 'صفحات محددة فقط'


class Operation(models.TextChoices):
    VIEW = 'view', 'عرض'
    CREATE = 'create', 'إضافة'
    EDIT = 'edit', 'تعديل'
    DELETE = 'delete', 'حذف'
    STATUS = 'change_status', 'تغيير الحالة'
    EXPORT = 'export', 'تنزيل / تصدير'


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
    version = models.PositiveBigIntegerField(default=1, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=models.Q(page_scope__in=PageScope.values), name='access_user_scope_valid')]


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
