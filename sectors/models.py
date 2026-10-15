import unicodedata

from django.core.exceptions import ValidationError
from django.db import models


def normalize_name(value):
    return " ".join(unicodedata.normalize("NFKC", value).split())


def validate_name(value):
    if any(unicodedata.category(char).startswith("C") for char in value) or "<" in value or ">" in value:
        raise ValidationError("أدخل اسمًا واضحًا دون وسوم أو محارف تحكم.")


class Sector(models.Model):
    name = models.CharField("القطاع", max_length=200, validators=[validate_name])
    name_key = models.CharField(max_length=600, unique=True, editable=False)
    is_active = models.BooleanField("نشط", default=True)
    version = models.PositiveBigIntegerField(default=1, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        default_permissions = ()

    def clean(self):
        super().clean()
        self.name = normalize_name(self.name)
        self.name_key = self.name.casefold()
        if not self.name:
            raise ValidationError({"name": "أدخل اسم القطاع."})

    def save(self, *args, **kwargs):
        self.name = normalize_name(self.name)
        self.name_key = self.name.casefold()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
