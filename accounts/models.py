from django.conf import settings
from django.db import models
from expense_items.models import normalize_name, validate_name


class Department(models.Model):
    name = models.CharField('اسم الإدارة أو الوحدة', max_length=200, validators=[validate_name])
    name_key = models.CharField(max_length=600, editable=False)
    is_active = models.BooleanField('نشط', default=True)
    revision = models.PositiveIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['id']
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=['name_key'], name='mk_departments_name_uq'),
        ]

    def save(self, *args, **kwargs):
        self.name = normalize_name(self.name)
        self.name_key = self.name.casefold()
        if kwargs.get('update_fields') is not None and 'name' in kwargs['update_fields']:
            kwargs['update_fields'] = {*kwargs['update_fields'], 'name_key'}
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class UserProfile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='makken_profile')
    phone_country = models.CharField(max_length=2, default='SA')
    phone = models.CharField(max_length=16, blank=True, default='')
    city = models.ForeignKey(
        'agreement_clauses.AgreementOption',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='المدينة',
    )
    department = models.ForeignKey(
        'accounts.Department',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='+',
        verbose_name='الإدارة أو الوحدة',
    )
    must_change_password = models.BooleanField('تغيير كلمة المرور عند أول دخول', default=False)
    # The built-in user email is not unique; reserve self-service addresses here.
    email_key = models.CharField(max_length=64, unique=True, null=True, blank=True, editable=False)
    version = models.PositiveBigIntegerField(default=1, editable=False)
    password_failures = models.PositiveSmallIntegerField(default=0, editable=False)
    failure_window_started_at = models.DateTimeField(null=True, blank=True, editable=False)
    password_locked_until = models.DateTimeField(null=True, blank=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ()
