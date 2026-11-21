from django.db import migrations

NEW_MODULES = [
    ('home', 'الرئيسية', 'makken_home', ['view', 'export_xlsx', 'export_pdf'], 0),
    ('partnerships_all', 'جميع الشراكات', 'partnerships:all_index', ['view', 'export_xlsx', 'export_pdf'], 27),
    ('agreement_inquiries', 'الاستعلامات', 'partnerships:agreement_inquiries', ['view', 'export_xlsx', 'export_pdf'], 28),
    ('partnership_achievement', 'إنجاز الشراكات', 'partnerships:achievement_report', ['view', 'export_xlsx', 'export_pdf'], 29),
    ('sponsor_requests', 'طلبات الرعاة الخارجيين', 'partnerships:sponsor_requests', ['view', 'edit', 'export_xlsx', 'export_pdf'], 30),
]

OP_LABELS = {
    'view': 'عرض',
    'edit': 'تعديل / اعتماد',
    'export_xlsx': 'تصدير Excel',
    'export_pdf': 'تصدير PDF',
}


def register(apps, schema_editor):
    alias = schema_editor.connection.alias
    Module = apps.get_model('access_control', 'Module').objects.using(alias)
    Permission = apps.get_model('auth', 'Permission').objects.using(alias)
    Group = apps.get_model('auth', 'Group').objects.using(alias)
    content, _ = apps.get_model('contenttypes', 'ContentType').objects.using(alias).get_or_create(
        app_label='access_control', model='module'
    )

    Module.filter(key='dashboard').update(
        title='مركز المؤشرات والتحليلات',
        route_name='core:dashboard',
        position=1,
    )

    created_perms = {}
    for key, title, route_name, ops, pos in NEW_MODULES:
        Module.update_or_create(
            key=key,
            defaults={
                'title': title,
                'route_name': route_name,
                'operations': ops,
                'position': pos,
            },
        )
        for op in ops:
            perm, _ = Permission.get_or_create(
                content_type_id=content.pk,
                codename=f'{op}_{key}',
                defaults={'name': f'{title} / {OP_LABELS.get(op, op)}'},
            )
            created_perms[f'{op}_{key}'] = perm

    for grp in Group.all():
        codes = set(grp.permissions.values_list('codename', flat=True))
        to_add = []
        if 'view_dashboard' in codes and 'view_home' in created_perms:
            to_add.append(created_perms['view_home'])
        if 'view_partnerships' in codes:
            for code in ('view_partnerships_all', 'view_agreement_inquiries', 'view_partnership_achievement', 'view_sponsor_requests'):
                if code in created_perms:
                    to_add.append(created_perms[code])
        if ('edit_partnerships' in codes or 'create_partnerships' in codes) and 'edit_sponsor_requests' in created_perms:
            to_add.append(created_perms['edit_sponsor_requests'])
        if 'export_xlsx_partnerships' in codes:
            for code in ('export_xlsx_partnerships_all', 'export_xlsx_agreement_inquiries', 'export_xlsx_partnership_achievement', 'export_xlsx_sponsor_requests'):
                if code in created_perms:
                    to_add.append(created_perms[code])
        if 'export_pdf_partnerships' in codes:
            for code in ('export_pdf_partnerships_all', 'export_pdf_agreement_inquiries', 'export_pdf_partnership_achievement', 'export_pdf_sponsor_requests'):
                if code in created_perms:
                    to_add.append(created_perms[code])
        if to_add:
            grp.permissions.add(*to_add)


class Migration(migrations.Migration):
    dependencies = [('access_control', '0012_partnership_types_module')]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
