from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from expense_items.models import normalize_name, validate_name
from partnerships.attachment_storage import willingness_storage

from .evidence_storage import evidence_path


class AgreementClause(models.Model):
    name = models.CharField("بند الاتفاقية", max_length=200, validators=[validate_name])
    name_key = models.CharField(max_length=600, editable=False)
    is_active = models.BooleanField("نشط", default=True)
    version = models.PositiveBigIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["name_key"], name="mk_clause_name_uq")]

    def clean(self):
        super().clean()
        self.name = normalize_name(self.name)
        self.name_key = self.name.casefold()
        if not self.name:
            raise ValidationError({"name": "أدخل بند الاتفاقية."})

    def save(self, *args, **kwargs):
        self.name = normalize_name(self.name)
        self.name_key = self.name.casefold()
        if kwargs.get("update_fields") is not None and "name" in kwargs["update_fields"]:
            kwargs["update_fields"] = {*kwargs["update_fields"], "name_key"}
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Agreement(models.Model):
    partnership = models.ForeignKey("partnerships.Partnership", on_delete=models.PROTECT, related_name="agreements")
    title = models.CharField("عنوان الاتفاقية", max_length=200, validators=[validate_name])
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        default_permissions = ()

    @property
    def number(self):
        return f"AGR-{self.pk:06d}" if self.pk else ""

    def __str__(self):
        return f"{self.number} · {self.title}"


class OptionKind(models.TextChoices):
    ENTITY = "entity", "أنواع الجهات"
    STATUS = "status", "إدارة حالات الشراكة"
    PARTNERSHIP_TYPE = "partnership_type", "أنواع الشراكة"
    CLASSIFICATION = "classification", "تصنيفات الاتفاقية"
    DEPARTMENT = "department", "الإدارات والوحدات"
    CITY = "city", "المدن السعودية"


class DepartmentType(models.TextChoices):
    UNIT = "unit", "وحدة من وحدات المؤسسة"
    DEPARTMENT = "department", "إدارة من إدارات المؤسسة"


class AgreementOption(models.Model):
    kind = models.CharField("القائمة", max_length=20, choices=OptionKind.choices)
    name = models.CharField("الاسم", max_length=160, validators=[validate_name])
    department_type = models.CharField("نوع الإدارة", max_length=12, choices=DepartmentType.choices, blank=True)
    is_active = models.BooleanField("نشط", default=True)
    revision = models.PositiveIntegerField(default=1, editable=False)

    class Meta:
        ordering = ["name", "pk"]
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["kind", "name"], name="mk_agreement_option_unique"),
            models.CheckConstraint(
                condition=(models.Q(kind=OptionKind.DEPARTMENT, department_type__in=DepartmentType.values) |
                           (~models.Q(kind=OptionKind.DEPARTMENT) & models.Q(department_type=""))),
                name="mk_agreement_department_type",
            ),
        ]

    def __str__(self):
        return self.name


class RenewalRule(models.TextChoices):
    AUTOMATIC = "automatic", "تلقائي وفق الاتفاقية"
    PRIOR_APPROVAL = "prior_approval", "يتطلب موافقة مسبقة"


class AgreementDetails(models.Model):
    agreement = models.OneToOneField(Agreement, on_delete=models.CASCADE, related_name="details")
    entity_type = models.ForeignKey(AgreementOption, on_delete=models.PROTECT, related_name="+", null=True, blank=True, verbose_name="نوع الجهة")
    status = models.ForeignKey(AgreementOption, on_delete=models.PROTECT, related_name="+", null=True, blank=True, verbose_name="حالة الاتفاقية")
    partnership_type = models.ForeignKey(AgreementOption, on_delete=models.PROTECT, related_name="+", null=True, blank=True, verbose_name="نوع الشراكة")
    classification = models.ForeignKey(AgreementOption, on_delete=models.PROTECT, related_name="+", null=True, blank=True, verbose_name="تصنيف الاتفاقية")
    departments = models.ManyToManyField(AgreementOption, blank=True, related_name="+", verbose_name="الإدارات المعنية")
    headquarters_city = models.ForeignKey(AgreementOption, on_delete=models.PROTECT, related_name="+", null=True, blank=True, verbose_name="مدينة مقر الجهة")
    signing_city = models.ForeignKey(AgreementOption, on_delete=models.PROTECT, related_name="+", null=True, blank=True, verbose_name="مدينة التوقيع")
    signing_region = models.ForeignKey("regions.Region", on_delete=models.PROTECT, related_name="+", null=True, blank=True, verbose_name="منطقة التوقيع")
    responsible_employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="makken_responsible_agreements", null=True, blank=True, verbose_name="الموظف المسؤول عن الاتفاقية")
    department_representative = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="makken_department_agreements", null=True, blank=True, verbose_name="ممثل الإدارة المعنية")
    institution_signatory = models.CharField("الموقّع عن المؤسسة", max_length=160, blank=True)
    institution_signatory_title = models.CharField("المنصب لدى المؤسسة", max_length=160, blank=True)
    partner_signatory = models.CharField("الموقّع عن الجهة", max_length=160, blank=True)
    partner_signatory_title = models.CharField("المنصب لدى الجهة", max_length=160, blank=True)
    partner_phone = models.CharField("هاتف الجهة", max_length=32, blank=True)
    partner_email = models.EmailField("البريد الإلكتروني للجهة", blank=True)
    signed_on = models.DateField("تاريخ التوقيع", null=True, blank=True)
    duration_months = models.PositiveSmallIntegerField("مدة الاتفاقية بالأشهر", null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(600)])
    renewal_rule = models.CharField("نوع التجديد", max_length=16, choices=RenewalRule.choices, blank=True)
    objective = models.TextField("هدف الشراكة", max_length=2000, blank=True)
    announcement = models.TextField("خبر عن الشراكة", max_length=2000, blank=True)
    audience = models.TextField("الفئات المستهدفة", max_length=2000, blank=True)
    expected_results = models.TextField("النتائج المتوقعة", max_length=2000, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)
    revision = models.PositiveIntegerField(default=1, editable=False)

    class Meta:
        default_permissions = ()
        constraints = [models.CheckConstraint(
            condition=(models.Q(signed_on__isnull=True, duration_months__isnull=True) |
                       models.Q(signed_on__isnull=False, duration_months__isnull=False, duration_months__range=(1, 600))),
            name="mk_agreement_term_pair",
        )]

    @property
    def initial_expiry(self):
        from .calendar import end_after_months
        if self.signed_on and self.duration_months:
            return end_after_months(self.signed_on, self.duration_months)


class TeamSide(models.TextChoices):
    INSTITUTION = "institution", "فريق المؤسسة"
    PARTNER = "partner", "فريق الجهة"


class TeamRole(models.TextChoices):
    REPRESENTATIVE = "representative", "ممثل"
    LEAD = "lead", "رئيس"
    CONTACT = "contact", "ضابط اتصال"
    MEMBER = "member", "عضو"


class AgreementMember(models.Model):
    agreement = models.ForeignKey(Agreement, on_delete=models.CASCADE, related_name="members")
    side = models.CharField(max_length=12, choices=TeamSide.choices)
    name = models.CharField("الاسم", max_length=160, validators=[validate_name])
    organization = models.CharField("الجهة أو الإدارة", max_length=160)
    role = models.CharField("الصفة", max_length=16, choices=TeamRole.choices)
    phone = models.CharField("الهاتف", max_length=32, blank=True)
    email = models.EmailField("البريد الإلكتروني", blank=True)

    class Meta:
        ordering = ["pk"]
        default_permissions = ()


class AgreementRenewal(models.Model):
    agreement = models.ForeignKey(Agreement, on_delete=models.PROTECT, related_name="renewals")
    starts_on = models.DateField("بداية التجديد")
    expires_on = models.DateField("نهاية التجديد")
    duration_months = models.PositiveSmallIntegerField("مدة التجديد بالأشهر", validators=[MinValueValidator(1), MaxValueValidator(600)])
    rule = models.CharField("نوع التجديد", max_length=16, choices=RenewalRule.choices)
    approval_reference = models.CharField("مرجع الموافقة المسبقة", max_length=160, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-starts_on", "-pk"]
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["agreement", "starts_on"], name="mk_agreement_renewal_unique"),
            models.CheckConstraint(condition=models.Q(expires_on__gt=models.F("starts_on")), name="mk_agreement_renewal_order"),
        ]


class Responsibility(models.TextChoices):
    INSTITUTION = "institution", "المؤسسة"
    PARTNER = "partner", "الجهة"
    SHARED = "shared", "مشترك"


class ClauseAssignment(models.Model):
    clause = models.ForeignKey(AgreementClause, on_delete=models.PROTECT, related_name="assignments")
    partnership = models.ForeignKey("partnerships.Partnership", on_delete=models.PROTECT, null=True, blank=True, related_name="agreement_clause_assignments")
    agreement = models.ForeignKey(Agreement, on_delete=models.PROTECT, null=True, blank=True, related_name="clause_assignments")
    responsibility = models.CharField("المسؤولية", max_length=12, choices=Responsibility.choices)
    progress = models.PositiveSmallIntegerField("نسبة الإنجاز", default=0, validators=[MinValueValidator(0), MaxValueValidator(100)])
    notes = models.TextField("ملاحظات البند", blank=True, default="")
    version = models.PositiveBigIntegerField(default=1, editable=False)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        default_permissions = ()
        constraints = [
            models.CheckConstraint(condition=(models.Q(partnership__isnull=False, agreement__isnull=True) | models.Q(partnership__isnull=True, agreement__isnull=False)), name="mk_clause_one_owner"),
            models.CheckConstraint(condition=models.Q(progress__gte=0, progress__lte=100), name="mk_clause_progress_range"),
            models.CheckConstraint(condition=models.Q(responsibility__in=Responsibility.values), name="mk_clause_resp_valid"),
            models.UniqueConstraint(fields=["partnership", "clause"], name="mk_clause_partnership_uq"),
            models.UniqueConstraint(fields=["agreement", "clause"], name="mk_clause_agreement_uq"),
        ]


class ProgramClause(models.Model):
    program = models.ForeignKey("training_programs.TrainingProgram", on_delete=models.CASCADE, related_name="agreement_clause_links")
    clause = models.ForeignKey(AgreementClause, on_delete=models.PROTECT, related_name="program_links")

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["program", "clause"], name="mk_clause_program_uq")]


class NeedClause(models.Model):
    need = models.ForeignKey("market_needs.Need", on_delete=models.CASCADE, related_name="agreement_clause_links")
    clause = models.ForeignKey(AgreementClause, on_delete=models.PROTECT, related_name="need_links")

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["need", "clause"], name="mk_clause_need_uq")]


class AgreementFollowupState(models.Model):
    agreement = models.OneToOneField(Agreement, on_delete=models.CASCADE, related_name="followup_state")
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        default_permissions = ()


class AgreementFollowupEntry(models.Model):
    agreement = models.ForeignKey(Agreement, on_delete=models.CASCADE, related_name="followup_entries")
    request_key = models.UUIDField(unique=True, editable=False)
    note = models.TextField("الملاحظة", max_length=2500, blank=True)
    clause = models.ForeignKey(ClauseAssignment, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    clause_name = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-pk"]
        default_permissions = ()


class AgreementEvidence(models.Model):
    entry = models.ForeignKey(AgreementFollowupEntry, on_delete=models.CASCADE, related_name="evidence")
    file = models.FileField(storage=willingness_storage, upload_to=evidence_path, max_length=240)
    original_name = models.CharField(max_length=240)
    size = models.PositiveBigIntegerField()
    content_type = models.CharField(max_length=80)

    class Meta:
        ordering = ["pk"]
        default_permissions = ()


def mean_progress(total, count):
    if not count:
        return None
    return (Decimal(total) / count).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


class AgreementClassification(models.Model):
    name = models.CharField("تصنيف الاتفاقية", max_length=200, validators=[validate_name])
    name_key = models.CharField(max_length=600, editable=False)
    is_active = models.BooleanField("نشط", default=True)
    revision = models.PositiveIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["name_key"], name="mk_agreement_classifications_name_uq"),
        ]

    def save(self, *args, **kwargs):
        self.name = normalize_name(self.name)
        self.name_key = self.name.casefold()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ClauseEvidence(models.Model):
    assignment = models.ForeignKey(ClauseAssignment, on_delete=models.CASCADE, related_name="evidences")
    file = models.CharField(max_length=255)
    original_name = models.CharField(max_length=255)
    size = models.PositiveBigIntegerField()
    content_type = models.CharField(max_length=40)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, editable=False, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at", "-id"]
        default_permissions = ()
