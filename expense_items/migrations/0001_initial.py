from django.db import migrations, models
import expense_items.models


def seed(apps, schema_editor):
    ExpenseItem = apps.get_model("expense_items", "ExpenseItem")
    rows = [('مواد لوجستية', True), ('مصروف جيب', True), ('سيولة نقدية', True), ('مصروف جيب نقدي', True), ('تكاليف التشغيل والإدارة', True), ('أجور ورواتب العاملين التدريب والتطوير', True), ('شراء المعدات والأجهزة', True), ('المواد والمستلزمات التشغيلية', True), ('الصيانة والإصلاحات', True), ('الإيجارات والخدمات (كهرباء، ماء، إنترنت)', True)]
    for name, active in rows:
        ExpenseItem.objects.using(schema_editor.connection.alias).get_or_create(name_key=name.casefold(), defaults={"name": name, "is_active": active})


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(name="ExpenseItem", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("name", models.CharField(max_length=200, validators=[expense_items.models.validate_name], verbose_name="بند الصرف")),
            ("name_key", models.CharField(editable=False, max_length=600, unique=True)),
            ("is_active", models.BooleanField(default=True, verbose_name="نشط")),
            ("version", models.PositiveBigIntegerField(default=1, editable=False)),
            ("created_at", models.DateTimeField(auto_now_add=True)),
            ("updated_at", models.DateTimeField(auto_now=True)),
        ], options={"ordering": ["id"], "default_permissions": ()}),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
