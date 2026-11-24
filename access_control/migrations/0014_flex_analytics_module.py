from django.db import migrations


OP_LABELS = {
    'view': 'عرض',
    'create': 'إنشاء',
    'edit': 'تعديل',
    'delete': 'حذف',
    'export_xlsx': 'تصدير Excel',
    'export_pdf': 'تصدير PDF',
}

OPS = ['view', 'create', 'edit', 'delete', 'export_xlsx', 'export_pdf']


def register_flex_analytics(apps, schema_editor):
    alias = schema_editor.connection.alias
    Module = apps.get_model('access_control', 'Module').objects.using(alias)
    Permission = apps.get_model('auth', 'Permission').objects.using(alias)
    Group = apps.get_model('auth', 'Group').objects.using(alias)
    content, _ = apps.get_model('contenttypes', 'ContentType').objects.using(alias).get_or_create(
        app_label='access_control', model='module'
    )

    Module.update_or_create(
        key='flex_analytics',
        defaults={
            'title': 'المؤشرات والتحليلات المرنة',
            'route_name': 'flex_analytics:index',
            'operations': OPS,
            'position': 2,
        },
    )

    created = {}
    for op in OPS:
        perm, _ = Permission.get_or_create(
            content_type_id=content.pk,
            codename=f'{op}_flex_analytics',
            defaults={'name': f'المؤشرات والتحليلات المرنة / {OP_LABELS[op]}'},
        )
        created[op] = perm

    for grp in Group.all():
        codes = set(grp.permissions.values_list('codename', flat=True))
        if 'view_dashboard' in codes:
            grp.permissions.add(*created.values())


class Migration(migrations.Migration):
    dependencies = [('access_control', '0013_home_dashboard_and_new_pages_modules')]
    operations = [migrations.RunPython(register_flex_analytics, migrations.RunPython.noop)]
