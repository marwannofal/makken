from django.db import migrations, models
import regions.models


def seed(apps, schema_editor):
    Region = apps.get_model("regions", "Region")
    # Saudi General Authority for Statistics: 13 administrative regions.
    # Frozen here so seed data cannot change when runtime code evolves.
    names = ['منطقة الرياض', 'منطقة مكة المكرمة', 'منطقة المدينة المنورة', 'منطقة القصيم', 'المنطقة الشرقية', 'منطقة عسير', 'منطقة تبوك', 'منطقة حائل', 'منطقة الحدود الشمالية', 'منطقة جازان', 'منطقة نجران', 'منطقة الباحة', 'منطقة الجوف']
    for name in names:
        key = name
        for prefix in ("منطقة ", "المنطقة "):
            if key.startswith(prefix):
                key = key[len(prefix):]
                break
        Region.objects.using(schema_editor.connection.alias).get_or_create(name_key=key.casefold(), defaults={"name": name, "is_active": True})



class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(name="Region", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(max_length=100, validators=[regions.models.validate_name], verbose_name="المنطقة")),
            ("name_key", models.CharField(editable=False, max_length=300, unique=True)),
            ("is_active", models.BooleanField(default=True, verbose_name="نشط")),
            ("version", models.PositiveBigIntegerField(default=1, editable=False)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
        ], options={"ordering": ["id"], "default_permissions": ()}),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
