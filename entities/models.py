import unicodedata

from django.core.exceptions import ValidationError
from django.db import models


class EntityType(models.TextChoices):
    GOVERNMENT = "government", "حكومي"
    NON_GOVERNMENT = "non_government", "غير حكومي"


class EntityBranch(models.TextChoices):
    PRIVATE_LARGE = "private_large", "خاص كبير"
    PRIVATE_SME = "private_sme", "خاص صغير ومتوسط"
    NONPROFIT_PROFESSIONAL = "nonprofit_professional", "غير ربحي مهني"
    NONPROFIT_COMMUNITY = "nonprofit_community", "غير ربحي مجتمعي"


def normalize_name(value):
    return " ".join(unicodedata.normalize("NFKC", value).split())


def validate_name(value):
    if any(unicodedata.category(char).startswith("C") for char in value) or "<" in value or ">" in value:
        raise ValidationError("أدخل اسمًا واضحًا دون وسوم أو محارف تحكم.")


class Entity(models.Model):
    name = models.CharField("اسم الكيان", max_length=200, validators=[validate_name])
    name_key = models.CharField(max_length=600, editable=False)
    entity_type = models.CharField("الكيان", max_length=20, choices=EntityType.choices)
    branch = models.CharField("فرع الكيان", max_length=32, choices=EntityBranch.choices, blank=True, default="")
    is_active = models.BooleanField("نشط", default=True)
    version = models.PositiveBigIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["name_key"], name="mk_entities_name_uq"),
            models.CheckConstraint(condition=models.Q(entity_type__in=EntityType.values), name="entity_type_fixed_enum"),
            models.CheckConstraint(
                condition=(models.Q(entity_type=EntityType.GOVERNMENT, branch="") | models.Q(entity_type=EntityType.NON_GOVERNMENT, branch__in=EntityBranch.values)),
                name="entity_branch_matches_type",
            ),
        ]

    def clean(self):
        super().clean()
        self.name = normalize_name(self.name)
        self.name_key = self.name.casefold()
        if not self.name:
            raise ValidationError({"name": "أدخل اسم الكيان."})
        if self.entity_type == EntityType.GOVERNMENT:
            self.branch = ""
        elif self.entity_type == EntityType.NON_GOVERNMENT and self.branch not in EntityBranch.values:
            raise ValidationError({"branch": "اختر فرع الكيان للكيان غير الحكومي."})

    def save(self, *args, **kwargs):
        self.name = normalize_name(self.name)
        self.name_key = self.name.casefold()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

# MAKKEN NAMED NAME KEY UNIQUE v1
