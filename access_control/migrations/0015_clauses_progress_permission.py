from django.db import migrations


def register_clauses_progress_permission(apps, schema_editor):
    alias = schema_editor.connection.alias
    Module = apps.get_model('access_control', 'Module').objects.using(alias)
    Permission = apps.get_model('auth', 'Permission').objects.using(alias)
    Group = apps.get_model('auth', 'Group').objects.using(alias)
    content, _ = apps.get_model('contenttypes', 'ContentType').objects.using(alias).get_or_create(
        app_label='access_control', model='module'
    )

    mod = Module.filter(key='partnerships').first()
    if mod:
        ops = list(mod.operations or [])
        if 'clauses_progress' not in ops:
            if 'export' in ops:
                ops.insert(ops.index('export'), 'clauses_progress')
            else:
                ops.append('clauses_progress')
            mod.operations = ops
            mod.save(update_fields=['operations'])

    perm, _ = Permission.get_or_create(
        content_type_id=content.pk,
        codename='clauses_progress_partnerships',
        defaults={'name': 'الشراكات / تحديث نسب إنجاز البنود'},
    )

    for grp in Group.all():
        codes = set(grp.permissions.values_list('codename', flat=True))
        if 'edit_partnerships' in codes:
            grp.permissions.add(perm)


class Migration(migrations.Migration):
    dependencies = [('access_control', '0014_flex_analytics_module')]
    operations = [migrations.RunPython(register_clauses_progress_permission, migrations.RunPython.noop)]
