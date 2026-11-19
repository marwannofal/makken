from django.db import migrations

KEY = 'work_assignments'
TITLE = 'إسناد المهام'
OPERATIONS = {
    'view': 'عرض',
    'create': 'إضافة',
    'edit': 'تعديل',
    'export_xlsx': 'تصدير Excel',
    'export_pdf': 'تصدير PDF',
}


def register(apps, schema_editor):
    alias = schema_editor.connection.alias
    Module = apps.get_model('access_control', 'Module').objects.using(alias)
    Permission = apps.get_model('auth', 'Permission').objects.using(alias)
    content, _ = apps.get_model('contenttypes', 'ContentType').objects.using(alias).get_or_create(
        app_label='access_control', model='module'
    )
    Module.get_or_create(
        key=KEY,
        defaults={
            'title': TITLE,
            'route_name': 'makken_mail:work_index',
            'operations': list(OPERATIONS),
            'position': 23,
        },
    )
    for operation, label in OPERATIONS.items():
        Permission.get_or_create(
            content_type_id=content.pk,
            codename=f'{operation}_{KEY}',
            defaults={'name': f'{TITLE} / {label}'},
        )


class Migration(migrations.Migration):
    dependencies = [('access_control', '0008_agreement_clause_catalog')]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
