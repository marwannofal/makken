import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from care_states.models import DevelopmentState
from entities.models import normalize_name, validate_name

from decimal import Decimal
from django.core.validators import MinValueValidator


class Scope(models.TextChoices):
    LOCAL = "local", "محلي"
    GLOBAL = "global", "عالمي"


class PreliminaryAgreementType(models.TextChoices):
    OFFICIAL_LETTER = "official_letter", "خطاب رسمي"
    SIGNED_MEMO = "signed_memo", "مذكرة موقعة"
    SIGNED_MEETING_MINUTES = "signed_meeting_minutes", "محضر اجتماع موقع"
    AGREEMENT_OR_MOU = "agreement_or_mou", "اتفاقية أو مذكرة تفاهم"


class Partnership(models.Model):
    name = models.CharField("اسم الجهة", max_length=200, validators=[validate_name])
    name_key = models.CharField(max_length=600, unique=True, editable=False)
    representative = models.CharField("اسم الممثل عن الجهة", max_length=200, validators=[validate_name])
    phone_country = models.CharField(max_length=2, default="SA")
    phone = models.CharField("هاتف التواصل", max_length=16)
    email = models.EmailField("البريد الإلكتروني", max_length=254)
    financial_capacity = models.DecimalField("القدرة المالية", max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0"))])
    entity = models.ForeignKey("entities.Entity", on_delete=models.PROTECT, related_name="partnerships", verbose_name="الكيان")
    scope = models.CharField("النطاق", max_length=8, choices=Scope.choices)
    is_active = models.BooleanField("حالة السجل", default=True)
    development_state = models.ForeignKey("care_states.StateColor", default=DevelopmentState.CAPABILITY, on_delete=models.PROTECT, related_name="partnerships", editable=False)
    preliminary_agreement_type = models.CharField("نوع الاتفاق المبدئي", max_length=32, choices=PreliminaryAgreementType.choices, blank=True, default="", editable=False)
    development_state_at = models.DateTimeField(default=timezone.now, editable=False)
    version = models.PositiveBigIntegerField(default=1, editable=False)
    request_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False, related_name="created_partnerships")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=models.Q(preliminary_agreement_type__in=["", *PreliminaryAgreementType.values]), name="partnership_agreement_enum"), models.CheckConstraint(condition=models.Q(scope__in=Scope.values), name="partnership_scope_enum"), models.CheckConstraint(condition=models.Q(financial_capacity__isnull=True) | models.Q(financial_capacity__gte=0), name="partnership_financial_nonnegative")]

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


from django.db.models.signals import post_delete
from django.dispatch import receiver
from .attachment_storage import willingness_storage, attachment_path, delete_private_files


class WillingnessAttachment(models.Model):
    partnership = models.ForeignKey(Partnership, on_delete=models.CASCADE, related_name="willingness_attachments")
    file = models.FileField(storage=willingness_storage, upload_to=attachment_path, max_length=255)
    original_name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    content_type = models.CharField(max_length=40)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["uploaded_at", "id"]
        default_permissions = ()

    @property
    def file_type(self):
        return "PDF" if self.content_type == "application/pdf" else "PNG" if self.content_type == "image/png" else "JPG"


@receiver(post_delete, sender=WillingnessAttachment)
def remove_willingness_file(sender, instance, **kwargs):
    from django.db import transaction
    if instance.file.name:
        name = instance.file.name
        transaction.on_commit(lambda: delete_private_files([name]))

