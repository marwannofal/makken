from django.db import migrations, models
import sectors.models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(name="Sector", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(max_length=200, validators=[sectors.models.validate_name], verbose_name="القطاع")),
            ("name_key", models.CharField(editable=False, max_length=600, unique=True)),
            ("is_active", models.BooleanField(default=True, verbose_name="نشط")),
            ("version", models.PositiveBigIntegerField(default=1, editable=False)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
        ], options={"ordering": ["id"], "default_permissions": ()}),
    ]
