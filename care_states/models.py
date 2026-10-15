from django.core.validators import RegexValidator
from django.db import models


class DevelopmentState(models.TextChoices):
    CAPABILITY = "capability", "قدرة"
    WILLINGNESS = "willingness", "رغبة"
    CARE = "care", "رعاية"


DEFAULT_COLORS = {
    DevelopmentState.CAPABILITY: "#BA1D1D",
    DevelopmentState.WILLINGNESS: "#FDD2CF",
    DevelopmentState.CARE: "#1C5D34",
}


class StateColor(models.Model):
    state = models.CharField(primary_key=True, max_length=16, choices=DevelopmentState.choices, editable=False)
    color = models.CharField(max_length=7, validators=[RegexValidator(r"\A#[0-9A-Fa-f]{6}\Z", "أدخل لونًا صحيحًا مثل #24B3AF.")])
    version = models.PositiveBigIntegerField(default=1, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(state__in=DevelopmentState.values), name="care_state_fixed_enum")]
        default_permissions = ()

    def __str__(self):
        return self.get_state_display()
