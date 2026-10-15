import unicodedata

from django.core.exceptions import ValidationError
from django.db import models


def normalize_name(value):
    return " ".join(unicodedata.normalize("NFKC", value).split())


def region_name_key(value):
    value = normalize_name(value)
    # "الرياض" and "منطقة الرياض" refer to the same region. Keep the
    # entered display name, but prevent prefix variants from duplicating it.
    for prefix in ("منطقة ", "المنطقة "):
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    return value.casefold()


def validate_name(value):
    if any(unicodedata.category(char).startswith("C") for char in value) or "<" in value or ">" in value:
        raise ValidationError("أدخل اسمًا واضحًا دون وسوم أو محارف تحكم.")


class Region(models.Model):
    name = models.CharField("المنطقة", max_length=100, validators=[validate_name])
    name_key = models.CharField(max_length=300, unique=True, editable=False)
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
        self.name_key = region_name_key(self.name)
        if not self.name:
            raise ValidationError({"name": "أدخل اسم المنطقة."})

    def save(self, *args, **kwargs):
        self.name = normalize_name(self.name)
        self.name_key = region_name_key(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name
