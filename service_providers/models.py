import uuid
from django.conf import settings
from django.db import models
from entities.models import normalize_name, validate_name
from partnerships.models import Scope


class ProviderType(models.TextChoices):
    GOVERNMENT = "government", "وحدات تدريبية حكومية"
    PRIVATE = "private", "وحدات تدريبية أهلية"


class ServiceProvider(models.Model):
    program = models.ForeignKey("training_programs.TrainingProgram", null=True, blank=True, on_delete=models.PROTECT, related_name="service_providers", verbose_name="البرنامج التدريبي")
    name = models.CharField("اسم مزود الخدمة", max_length=200, validators=[validate_name])
    name_key = models.CharField(max_length=600, editable=False)
    representative = models.CharField("اسم الممثل عن مزود الخدمة", max_length=200, blank=True, validators=[validate_name])
    phone_country = models.CharField(max_length=2, default="SA")
    phone = models.CharField("هاتف التواصل لمزود الخدمة", max_length=16, blank=True)
    email = models.EmailField("البريد الإلكتروني", blank=True)
    provider_type = models.CharField("نوع مزود الخدمة", max_length=12, choices=ProviderType.choices)
    scope = models.CharField("نطاق مزود الخدمة", max_length=8, choices=Scope.choices)
    is_active = models.BooleanField("حالة السجل", default=True)
    converted_partnership = models.OneToOneField("partnerships.Partnership", null=True, blank=True, on_delete=models.PROTECT, related_name="source_service_provider", editable=False)
    converted_at = models.DateTimeField(null=True, blank=True, editable=False)
    request_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    version = models.PositiveBigIntegerField(default=1, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="created_service_providers", editable=False)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="updated_service_providers", editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]
        default_permissions = ()
        indexes = [models.Index(fields=["is_active", "id"], name="provider_status_idx")]
        constraints = [
            models.UniqueConstraint(fields=["name_key"], name="mk_service_providers_name_uq"),
            models.CheckConstraint(condition=models.Q(provider_type__in=ProviderType.values), name="provider_type_valid"),
            models.CheckConstraint(condition=models.Q(scope__in=Scope.values), name="provider_scope_valid"),
            models.CheckConstraint(condition=(models.Q(converted_partnership__isnull=True, converted_at__isnull=True) | models.Q(converted_partnership__isnull=False, converted_at__isnull=False)), name="provider_conversion_consistent"),
        ]

    def save(self, *args, **kwargs):
        self.name = normalize_name(self.name)
        self.name_key = self.name.casefold()
        self.representative = normalize_name(self.representative)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ProviderCoverage(models.Model):
    provider = models.ForeignKey(ServiceProvider, on_delete=models.CASCADE, related_name="coverage")
    region = models.ForeignKey("regions.Region", on_delete=models.PROTECT, related_name="service_provider_coverage")
    specializations = models.ManyToManyField("specializations.Specialization", through="CoverageSpecialization", related_name="service_provider_coverage")
    is_active = models.BooleanField(default=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["provider", "region"], name="provider_region_unique")]


class CoverageSpecialization(models.Model):
    coverage = models.ForeignKey(ProviderCoverage, on_delete=models.CASCADE)
    specialization = models.ForeignKey("specializations.Specialization", on_delete=models.PROTECT)

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["coverage", "specialization"], name="provider_coverage_spec_unique")]


class ProviderAudit(models.Model):
    provider = models.ForeignKey(ServiceProvider, null=True, on_delete=models.SET_NULL, related_name="events")
    provider_key = models.PositiveBigIntegerField(editable=False)
    provider_name = models.CharField(max_length=200, editable=False)
    action = models.CharField(max_length=20, choices=[("create", "إضافة"), ("edit", "تعديل"), ("toggle", "تغيير حالة السجل"), ("delete", "حذف"), ("convert", "تحويل إلى رغبة")])
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="service_provider_events")
    actor_name = models.CharField(max_length=150, editable=False)
    before = models.JSONField(default=dict, editable=False)
    after = models.JSONField(default=dict, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        default_permissions = ()

# MAKKEN NAMED NAME KEY UNIQUE v1
