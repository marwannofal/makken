from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from expense_items.models import normalize_name, validate_name


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


def mean_progress(total, count):
    if not count:
        return None
    return (Decimal(total) / count).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
