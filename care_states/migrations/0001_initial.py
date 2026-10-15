from django.core.validators import RegexValidator
from django.db import migrations, models


def seed(apps, schema_editor):
    StateColor = apps.get_model("care_states", "StateColor")
    for state, color in [("capability", "#BA1D1D"), ("willingness", "#FDD2CF"), ("care", "#1C5D34")]:
        StateColor.objects.using(schema_editor.connection.alias).get_or_create(state=state, defaults={"color": color})


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name="StateColor",
            fields=[
                ("state", models.CharField(choices=[("capability", "قدرة"), ("willingness", "رغبة"), ("care", "رعاية")], editable=False, max_length=16, primary_key=True, serialize=False)),
                ("color", models.CharField(max_length=7, validators=[RegexValidator(r"\A#[0-9A-Fa-f]{6}\Z", "أدخل لونًا صحيحًا مثل #24B3AF.")])),
                ("version", models.PositiveBigIntegerField(default=1, editable=False)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"default_permissions": (), "constraints": [models.CheckConstraint(condition=models.Q(state__in=["capability", "willingness", "care"]), name="care_state_fixed_enum")]},
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
