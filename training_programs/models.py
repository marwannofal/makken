from django.core.exceptions import ValidationError
from django.db import models

from expense_items.models import normalize_name, validate_name


class TrainingProgram(models.Model):
    class Category(models.TextChoices):
        INTERMEDIATE_DIPLOMA = "intermediate_diploma", "الدبلوم التدريبي (المتوسط)"
        ASSOCIATE_DIPLOMA = "associate_diploma", "الدبلوم التدريبي (المشارك)"
        QUALIFYING_PROGRAM = "qualifying_program", "البرنامج التأهيلي"
        QUALIFYING_COURSE = "qualifying_course", "الدورة التأهيلية"
        DEVELOPMENT_COURSE = "development_course", "الدورة التطويرية"

    class TrainingType(models.TextChoices):
        TRAINING = "training", "تدريبي"
        OPERATIONAL = "operational", "تشغيلي"

    name = models.CharField("البرنامج التدريبي", max_length=200, validators=[validate_name])
    name_key = models.CharField(max_length=600, editable=False)
    category = models.CharField("تصنيف البرامج", max_length=32, choices=Category.choices)
    expense_items = models.ManyToManyField("expense_items.ExpenseItem", through="ProgramExpenseItem", related_name="training_programs", verbose_name="بنود الصرف")
    is_training = models.BooleanField("تدريبي", default=True)
    is_operational = models.BooleanField("تشغيلي", default=False)
    is_active = models.BooleanField("نشط", default=True)
    version = models.PositiveBigIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["name_key"], name="mk_training_programs_name_uq"),
            models.CheckConstraint(condition=models.Q(category__in=["intermediate_diploma", "associate_diploma", "qualifying_program", "qualifying_course", "development_course"]), name="makken_program_category_valid"),
            models.CheckConstraint(condition=models.Q(is_training=True, is_operational=False) | models.Q(is_training=False, is_operational=True), name="makken_program_type_single"),
        ]

    @property
    def training_types(self):
        return [value for value, enabled in [(self.TrainingType.TRAINING, self.is_training), (self.TrainingType.OPERATIONAL, self.is_operational)] if enabled]

    @property
    def training_type_labels(self):
        return [self.TrainingType(value).label for value in self.training_types]

    def clean(self):
        super().clean()
        self.name = normalize_name(self.name)
        self.name_key = self.name.casefold()
        if not self.name:
            raise ValidationError({"name": "أدخل اسم البرنامج التدريبي."})
        if self.is_training == self.is_operational:
            raise ValidationError("اختر نوع تدريب واحدًا فقط.")

    def save(self, *args, **kwargs):
        self.name = normalize_name(self.name)
        self.name_key = self.name.casefold()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class ProgramExpenseItem(models.Model):
    program = models.ForeignKey(TrainingProgram, on_delete=models.CASCADE, related_name="expense_links")
    expense_item = models.ForeignKey("expense_items.ExpenseItem", on_delete=models.PROTECT, related_name="program_links")

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["program", "expense_item"], name="makken_program_expense_unique")]

# MAKKEN NAMED NAME KEY UNIQUE v1
