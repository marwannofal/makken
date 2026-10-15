from django.db import migrations, models
import specializations.models


def seed(apps, schema_editor):
    Specialization = apps.get_model("specializations", "Specialization")
    rows = [('هندسة الميكاترونكس', True), ('كهرباء صناعي', True), ('لحام صناعي', True), ('هندسة ميكانيكية', True), ('هندسة كهربائية', True), ('هندسة مدنية', True), ('هندسة إلكترونيات', True), ('هندسة تحكم وأتمتة', True), ('صيانة المعدات الصناعية', True), ('تشغيل الآلات والمعدات', True), ('تكييف وتبريد', True), ('أنظمة الطاقة', False)]
    for name, active in rows:
        Specialization.objects.using(schema_editor.connection.alias).get_or_create(name_key=name.casefold(), defaults={"name": name, "is_active": active})


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(name="Specialization", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(max_length=200, validators=[specializations.models.validate_name], verbose_name="التخصص")),
            ("name_key", models.CharField(editable=False, max_length=600, unique=True)),
            ("is_active", models.BooleanField(default=True, verbose_name="نشط")),
            ("version", models.PositiveBigIntegerField(default=1, editable=False)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
        ], options={"ordering": ["id"], "default_permissions": ()}),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
