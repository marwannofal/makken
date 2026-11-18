from django.db import migrations

KEY = "agreement_clauses"
TITLE = "بنود الاتفاقية"
OPERATIONS = {
    "view": "عرض", "create": "إضافة", "edit": "تعديل", "delete": "حذف",
    "change_status": "تغيير الحالة", "export_xlsx": "تصدير Excel", "export_pdf": "تصدير PDF",
}


def register(apps, schema_editor):
    alias = schema_editor.connection.alias
    Module = apps.get_model("access_control", "Module").objects.using(alias)
    Permission = apps.get_model("auth", "Permission").objects.using(alias)
    content, _ = apps.get_model("contenttypes", "ContentType").objects.using(alias).get_or_create(app_label="access_control", model="module")
    Module.get_or_create(key=KEY, defaults={"title": TITLE, "route_name": "agreement_clauses:index",
                                          "operations": list(OPERATIONS), "position": 22})
    for operation, label in OPERATIONS.items():
        Permission.get_or_create(content_type_id=content.pk, codename=f"{operation}_{KEY}",
                                 defaults={"name": f"{TITLE} / {label}"})


class Migration(migrations.Migration):
    dependencies = [("access_control", "0007_dashboard_export_permissions")]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
