from django.db import migrations, models
import levels.models


def seed(apps, schema_editor):
    Level = apps.get_model("levels", "Level")
    for name, active in [("برونزي", True), ("فضي", True), ("ذهبي", False), ("استراتيجي", True)]:
        Level.objects.using(schema_editor.connection.alias).get_or_create(name_key=name, defaults={"name": name, "is_active": active})


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(name="Level", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(max_length=100, validators=[levels.models.validate_name], verbose_name="المستوى")),
            ("name_key", models.CharField(editable=False, max_length=300, unique=True)),
            ("is_active", models.BooleanField(default=True, verbose_name="نشط")),
            ("version", models.PositiveBigIntegerField(default=1, editable=False)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
        ], options={"ordering": ["id"], "default_permissions": ()}),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
