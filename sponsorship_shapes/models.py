import unicodedata

from django.core.exceptions import ValidationError
from django.core.validators import MaxLengthValidator
from django.db import models


def normalize_name(value):
    return " ".join(unicodedata.normalize("NFKC", value).split())


def validate_name(value):
    if any(unicodedata.category(char).startswith("C") for char in value) or "<" in value or ">" in value:
        raise ValidationError("أدخل اسمًا واضحًا دون وسوم أو محارف تحكم.")


def normalize_description(value):
    return unicodedata.normalize("NFKC", value).replace("\r\n", "\n").replace("\r", "\n").strip()


def validate_description(value):
    if any(unicodedata.category(char).startswith("C") and char not in "\n\t\r" for char in value) or "<" in value or ">" in value:
        raise ValidationError("أدخل وصفًا واضحًا دون وسوم أو محارف تحكم.")


class SponsorshipShape(models.Model):
    name = models.CharField("شكل الرعاية", max_length=200, validators=[validate_name])
    description = models.TextField("وصف شكل الرعاية", blank=True, default="", max_length=2000, validators=[validate_description, MaxLengthValidator(2000)])
    is_employment = models.BooleanField("هل الرعاية توظيف؟", default=False)
    name_key = models.CharField(max_length=600, editable=False)
    is_active = models.BooleanField("نشط", default=True)
    version = models.PositiveBigIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        default_permissions = ()

        constraints = [models.UniqueConstraint(fields=["name_key"], name="mk_sponsorship_shapes_name_uq")]

    def clean(self):
        super().clean()
        self.name = normalize_name(self.name)
        self.name_key = self.name.casefold()
        self.description = normalize_description(self.description)
        if not self.name:
            raise ValidationError({"name": "أدخل شكل الرعاية."})

    def save(self, *args, **kwargs):
        self.name = normalize_name(self.name)
        self.name_key = self.name.casefold()
        self.description = normalize_description(self.description)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name

# MAKKEN NAMED NAME KEY UNIQUE v1
