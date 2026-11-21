import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone
from care_states.models import DevelopmentState
from entities.models import normalize_name, validate_name

from decimal import Decimal
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator


class Scope(models.TextChoices):
    LOCAL = "local", "محلي"
    GLOBAL = "global", "عالمي"


class PartnershipType(models.Model):
    name = models.CharField("نوع الشراكة", max_length=200, validators=[validate_name])
    name_key = models.CharField(max_length=600, editable=False)
    is_active = models.BooleanField("نشط", default=True)
    revision = models.PositiveIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["name_key"], name="mk_partnership_types_name_uq"),
        ]

    def save(self, *args, **kwargs):
        self.name = normalize_name(self.name)
        self.name_key = self.name.casefold()
        if kwargs.get("update_fields") is not None and "name" in kwargs["update_fields"]:
            kwargs["update_fields"] = {*kwargs["update_fields"], "name_key"}
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class PreliminaryAgreementType(models.TextChoices):
    MOU = "mou", "مذكرة تفاهم"
    COOPERATION = "cooperation", "تعاون"
    SERVICE_CONTRACT = "service_contract", "عقد خدمة"
    SOCIAL = "social", "اجتماعية"
    OTHER = "other", "أخرى"



class RenewalRule(models.TextChoices):
    AUTOMATIC = "automatic", "تلقائي"
    PRIOR_APPROVAL = "prior_approval", "موافقة مسبقة"


class TeamSide(models.TextChoices):
    INSTITUTION = "institution", "فريق عمل المؤسسة"
    PARTNER = "partner", "فريق عمل الجهة"


class TeamMemberRole(models.TextChoices):
    REPRESENTATIVE = "representative", "ممثل"
    LEAD = "lead", "رئيس"
    CONTACT = "contact", "ضابط اتصال"


class Partnership(models.Model):
    administrative_regions = models.ManyToManyField('regions.Region', through='PartnershipRegion', blank=True, related_name='administrative_partnerships', verbose_name='المناطق الإدارية للجهة')
    name = models.CharField("اسم الجهة", max_length=200, validators=[validate_name])
    name_key = models.CharField(max_length=600, editable=False)
    representative = models.CharField("اسم الممثل عن الجهة", max_length=200, validators=[validate_name])
    phone_country = models.CharField(max_length=2, default="SA")
    phone = models.CharField("هاتف التواصل", max_length=16)
    email = models.EmailField("البريد الإلكتروني", max_length=254)
    financial_capacity = models.DecimalField("القدرة المالية", max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0"))])
    entity = models.ForeignKey("entities.Entity", on_delete=models.PROTECT, related_name="partnerships", verbose_name="الكيان")
    scope = models.CharField("النطاق", max_length=8, choices=Scope.choices)
    partnership_date = models.CharField("تاريخ الشراكة", max_length=7, blank=True, default="", validators=[RegexValidator(r"\A(?:[12]\d{3}-(?:0[1-9]|1[0-2]))?\Z", "أدخل تاريخ الشراكة بصيغة الشهر والسنة (YYYY-MM).")])
    starts_on = models.DateField("تاريخ بداية الشراكة", null=True, blank=True)
    ends_on = models.DateField("تاريخ نهاية الشراكة", null=True, blank=True)
    is_active = models.BooleanField("حالة السجل", default=True)
    development_state = models.ForeignKey("care_states.StateColor", default=DevelopmentState.CAPABILITY, on_delete=models.PROTECT, related_name="partnerships", editable=False)
    preliminary_agreement_type = models.CharField("نوع الاتفاق المبدئي", max_length=32, choices=PreliminaryAgreementType.choices, blank=True, default="", editable=False)
    partnership_type = models.ForeignKey("partnerships.PartnershipType", on_delete=models.PROTECT, null=True, blank=True, related_name="partnerships", verbose_name="نوع الشراكة")
    signing_region = models.ForeignKey("regions.Region", on_delete=models.PROTECT, null=True, blank=True, related_name="signed_partnerships", verbose_name="منطقة التوقيع")
    signing_city = models.CharField("مدينة التوقيع", max_length=120, blank=True, default="")
    agreement_classification = models.ForeignKey("agreement_clauses.AgreementClassification", on_delete=models.PROTECT, null=True, blank=True, related_name="partnerships", verbose_name="تصنيف الاتفاقية")
    concerned_departments = models.ManyToManyField("accounts.Department", through="PartnershipDepartment", blank=True, related_name="concerned_partnerships", verbose_name="الإدارة المعنية")
    headquarters_city = models.CharField("عنوان الجهة (مدينة المقر)", max_length=120, blank=True, default="")
    development_state_at = models.DateTimeField(default=timezone.now, editable=False)
    agreement_number = models.CharField("رقم الاتفاقية", max_length=24, unique=True, null=True, blank=True, editable=False)
    institution_signatory = models.CharField("اسم موقّع الشراكة من طرف المؤسسة", max_length=160, blank=True, default="")
    institution_signatory_title = models.CharField("صفته الاعتبارية (المؤسسة)", max_length=160, blank=True, default="")
    partner_signatory = models.CharField("اسم موقّع الشراكة من طرف الجهة", max_length=160, blank=True, default="")
    partner_signatory_title = models.CharField("صفته الاعتبارية (الجهة)", max_length=160, blank=True, default="")
    partner_rep_email = models.EmailField("البريد الإلكتروني لممثل الجهة", max_length=254, blank=True, default="")
    partner_rep_phone = models.CharField("رقم الجوال لممثل الجهة", max_length=32, blank=True, default="")
    institution_rep_name = models.CharField("اسم ممثل المؤسسة", max_length=160, blank=True, default="")
    institution_rep_email = models.EmailField("البريد الإلكتروني لممثل المؤسسة", max_length=254, blank=True, default="")
    institution_rep_phone = models.CharField("رقم الجوال لممثل المؤسسة", max_length=32, blank=True, default="")
    signed_on = models.DateField("تاريخ التوقيع (بداية الشراكة)", null=True, blank=True)
    duration_months = models.PositiveSmallIntegerField("مدة الاتفاقية (بالأشهر)", null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(600)])
    renewal_rule = models.CharField("نوع التجديد", max_length=16, choices=RenewalRule.choices, blank=True, default="")
    objective = models.TextField("هدف الشراكة", max_length=2000, blank=True, default="")
    announcement = models.TextField("خبر عن الشراكة", max_length=2000, blank=True, default="")
    audience = models.TextField("الفئات المستهدفة", max_length=2000, blank=True, default="")
    expected_results = models.TextField("النتائج المتوقعة", max_length=2000, blank=True, default="")
    version = models.PositiveBigIntegerField(default=1, editable=False)
    request_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False, related_name="created_partnerships")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["name_key"], name="mk_partnerships_name_uq"),models.CheckConstraint(condition=models.Q(preliminary_agreement_type__in=["", *PreliminaryAgreementType.values]), name="partnership_agreement_enum"), models.CheckConstraint(condition=models.Q(scope__in=Scope.values), name="partnership_scope_enum"), models.CheckConstraint(condition=models.Q(financial_capacity__isnull=True) | models.Q(financial_capacity__gte=0), name="partnership_financial_nonnegative"),
            models.CheckConstraint(
                condition=(
                    models.Q(starts_on__isnull=True, ends_on__isnull=True)
                    | models.Q(starts_on__isnull=False, ends_on__isnull=False, ends_on__gte=models.F("starts_on"))
                ),
                name="partnership_term_dates_valid",
            ),
        ]

    def save(self, *args, **kwargs):
        self.name = normalize_name(self.name)
        self.name_key = self.name.casefold()
        self.representative = normalize_name(self.representative)
        super().save(*args, **kwargs)

    @property
    def calculated_expiry(self):
        if self.signed_on and self.duration_months:
            from agreement_clauses.calendar import end_after_months
            return end_after_months(self.signed_on, self.duration_months)
        return None

    def format_agreement_number(self):
        dt = timezone.localtime(self.created_at) if self.created_at else timezone.localtime(timezone.now())
        return f"{dt:%Y%m}{self.pk:03d}"

    def ensure_agreement_number(self):
        if not self.agreement_number and self.pk:
            self.agreement_number = self.format_agreement_number()
            Partnership.objects.filter(pk=self.pk, agreement_number__isnull=True).update(agreement_number=self.agreement_number)

    def __str__(self):
        return self.name


class PartnershipRegion(models.Model):
    partnership = models.ForeignKey(Partnership, on_delete=models.CASCADE)
    region = models.ForeignKey('regions.Region', on_delete=models.PROTECT)

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['partnership', 'region'], name='partnership_admin_region_unique')]


class PartnershipDepartment(models.Model):
    partnership = models.ForeignKey(Partnership, on_delete=models.CASCADE)
    department = models.ForeignKey('accounts.Department', on_delete=models.PROTECT)

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=['partnership', 'department'], name='partnership_concerned_dept_unique')]


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

# MAKKEN NAMED NAME KEY UNIQUE v1


class SponsorRequestStatus(models.TextChoices):
    NEW = "new", "جديد"
    APPROVED = "approved", "معتمد"
    REJECTED = "rejected", "مرفوض"


class SponsorRegistrationRequest(models.Model):
    reference_code = models.CharField("رقم الطلب", max_length=24, unique=True, editable=False)
    name = models.CharField("اسم الجهة", max_length=200, validators=[validate_name])
    name_key = models.CharField(max_length=600, editable=False, db_index=True)
    representative = models.CharField("اسم الممثل عن الجهة", max_length=200, validators=[validate_name])
    phone_country = models.CharField(max_length=2, default="SA")
    phone = models.CharField("هاتف التواصل", max_length=16)
    email = models.EmailField("البريد الإلكتروني", max_length=254)
    entity = models.ForeignKey("entities.Entity", on_delete=models.PROTECT, related_name="sponsor_requests", verbose_name="الكيان")
    scope = models.CharField("النطاق", max_length=8, choices=Scope.choices, default=Scope.LOCAL)
    administrative_regions = models.ManyToManyField("regions.Region", blank=True, related_name="sponsor_requests", verbose_name="المناطق الإدارية للجهة")
    sector = models.ForeignKey("sectors.Sector", on_delete=models.PROTECT, null=True, blank=True, related_name="sponsor_requests", verbose_name="القطاع")
    sponsorship_shape = models.ForeignKey("sponsorship_shapes.SponsorshipShape", on_delete=models.PROTECT, null=True, blank=True, related_name="sponsor_requests", verbose_name="شكل الرعاية")
    financial_capacity = models.DecimalField("القدرة المالية", max_digits=14, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(Decimal("0"))])
    notes = models.TextField("نبذة وملاحظات إضافية", max_length=2000, blank=True)
    status = models.CharField("حالة الطلب", max_length=12, choices=SponsorRequestStatus.choices, default=SponsorRequestStatus.NEW, db_index=True)
    rejection_reason = models.TextField("سبب الرفض", max_length=1000, blank=True)
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="reviewed_sponsor_requests", verbose_name="تمت المراجعة بواسطة")
    reviewed_at = models.DateTimeField("تاريخ المراجعة", null=True, blank=True)
    created_partnership = models.OneToOneField(Partnership, on_delete=models.SET_NULL, null=True, blank=True, related_name="source_registration_request", verbose_name="الشراكة المنشأة")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        default_permissions = ()
        constraints = [
            models.CheckConstraint(condition=models.Q(status__in=SponsorRequestStatus.values), name="sponsor_request_status_enum"),
            models.CheckConstraint(condition=models.Q(scope__in=Scope.values), name="sponsor_request_scope_enum"),
            models.CheckConstraint(condition=models.Q(financial_capacity__isnull=True) | models.Q(financial_capacity__gte=0), name="sponsor_request_financial_nonnegative"),
        ]

    def save(self, *args, **kwargs):
        if not self.reference_code:
            self.reference_code = f"REQ-{uuid.uuid4().hex[:8].upper()}"
        self.name = normalize_name(self.name)
        self.name_key = self.name.casefold()
        self.representative = normalize_name(self.representative)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.reference_code} · {self.name}"

class PartnershipTeamMember(models.Model):
    partnership = models.ForeignKey(Partnership, on_delete=models.CASCADE, related_name="team_members")
    side = models.CharField("الفريق", max_length=12, choices=TeamSide.choices)
    name = models.CharField("الاسم", max_length=160, validators=[validate_name])
    phone = models.CharField("الهاتف", max_length=32, blank=True, default="")
    email = models.EmailField("البريد الإلكتروني", max_length=254, blank=True, default="")
    organization = models.CharField("الجهة أو الإدارة", max_length=160, blank=True, default="")
    role = models.CharField("الصفة", max_length=16, choices=TeamMemberRole.choices)

    class Meta:
        ordering = ["pk"]
        default_permissions = ()

    def __str__(self):
        return f"{self.name} ({self.get_role_display()})"

