from django.conf import settings
from django.db import models


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
        'agreement_clauses.AgreementOption',
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
