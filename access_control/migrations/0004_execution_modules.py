"""Register execution modules without changing any existing role/user grants."""
from django.db import migrations


def seed(apps, schema_editor):
    alias = schema_editor.connection.alias
    Module = apps.get_model("access_control", "Module")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    content, _ = ContentType.objects.using(alias).get_or_create(app_label="access_control", model="module")
    definitions = [
        ("approved_programs", "البرامج المعتمدة وفقًا للتخصص", "program_execution:index", ["view", "export_xlsx", "export_pdf"]),
        ("provider_assignments", "اختيار مزودي تنفيذ البرامج", "program_execution:assignments", ["view", "create", "edit", "change_status", "export_xlsx", "export_pdf"]),
    ]
    labels = {"view": "عرض", "create": "إضافة", "edit": "تعديل", "change_status": "تغيير الحالة", "export_xlsx": "تصدير Excel", "export_pdf": "تصدير PDF"}
    for index, (key, title, route, operations) in enumerate(definitions, 20):
        Module.objects.using(alias).get_or_create(key=key, defaults={"title": title, "route_name": route, "operations": operations, "position": index})
        for operation in operations:
            Permission.objects.using(alias).get_or_create(content_type_id=content.pk, codename=operation + "_" + key, defaults={"name": title + " / " + labels[operation]})


class Migration(migrations.Migration):
    dependencies = [("access_control", "0003_table_export_permissions"), ("market_needs", "0003_needexecution_executionprovider_executionemployer_and_more")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
