import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from care_states.models import DevelopmentState
from entities.models import normalize_name, validate_name


class Scope(models.TextChoices):
    LOCAL = "local", "محلي"
    GLOBAL = "global", "عالمي"


class Partnership(models.Model):
    name = models.CharField("اسم الجهة", max_length=200, validators=[validate_name])
    name_key = models.CharField(max_length=600, unique=True, editable=False)
    representative = models.CharField("اسم الممثل عن الجهة", max_length=200, validators=[validate_name])
    phone_country = models.CharField(max_length=2, default="SA")
    phone = models.CharField("هاتف التواصل", max_length=16)
    email = models.EmailField("البريد الإلكتروني", max_length=254)
    entity = models.ForeignKey("entities.Entity", on_delete=models.PROTECT, related_name="partnerships", verbose_name="الكيان")
    scope = models.CharField("النطاق", max_length=8, choices=Scope.choices)
    is_active = models.BooleanField("حالة السجل", default=True)
    development_state = models.ForeignKey("care_states.StateColor", default=DevelopmentState.CAPABILITY, on_delete=models.PROTECT, related_name="partnerships", editable=False)
    development_state_at = models.DateTimeField(default=timezone.now, editable=False)
    version = models.PositiveBigIntegerField(default=1, editable=False)
    request_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False, related_name="created_partnerships")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=models.Q(scope__in=Scope.values), name="partnership_scope_enum")]

    def save(self, *args, **kwargs):
        self.name = normalize_name(self.name)
        self.name_key = self.name.casefold()
        self.representative = normalize_name(self.representative)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class PartnershipOffering(models.Model):
    partnership = models.ForeignKey(Partnership, on_delete=models.CASCADE, related_name="offerings")
    sector = models.ForeignKey("sectors.Sector", on_delete=models.PROTECT, related_name="partnership_offerings")
    specializations = models.ManyToManyField("specializations.Specialization", through="OfferingSpecialization", related_name="partnership_offerings")
    sponsorship_shape = models.ForeignKey("sponsorship_shapes.SponsorshipShape", on_delete=models.PROTECT, related_name="partnership_offerings")
    is_active = models.BooleanField(default=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]
        default_permissions = ()


class DevelopmentHistory(models.Model):
    partnership = models.ForeignKey(Partnership, on_delete=models.CASCADE, related_name="development_history")
    state = models.ForeignKey("care_states.StateColor", on_delete=models.PROTECT, related_name="partnership_history")
    entered_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        ordering = ["entered_at", "id"]
        default_permissions = ()


class OfferingSpecialization(models.Model):
    offering = models.ForeignKey(PartnershipOffering, on_delete=models.CASCADE)
    specialization = models.ForeignKey("specializations.Specialization", on_delete=models.PROTECT)

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["offering", "specialization"], name="unique_partnership_offering_spec")]
