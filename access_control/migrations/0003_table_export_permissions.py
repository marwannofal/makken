"""Add format-specific rights without granting them to existing roles or users."""
from django.db import migrations, models

FORMATS = [('export_xlsx', 'تصدير Excel'), ('export_pdf', 'تصدير PDF')]
CHOICES = [('view', 'عرض'), ('create', 'إضافة'), ('edit', 'تعديل'), ('delete', 'حذف'),
           ('change_status', 'تغيير الحالة'), ('export', 'تنزيل المرفقات'), *FORMATS]
MODULE_KEYS = ('care_states', 'levels', 'regions', 'entities', 'specializations',
               'sectors', 'expense_items', 'training_programs', 'sponsorship_shapes',
               'partnerships', 'market_needs', 'service_providers')


def seed(apps, schema_editor):
    alias = schema_editor.connection.alias
    Module = apps.get_model('access_control', 'Module')
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    content, _ = ContentType.objects.using(alias).get_or_create(app_label='access_control', model='module')
    for key in MODULE_KEYS:
        module = Module.objects.using(alias).get(pk=key)
        operations = list(module.operations)
        for operation, label in FORMATS:
            if operation not in operations:
                operations.append(operation)
            Permission.objects.using(alias).get_or_create(
                content_type_id=content.pk, codename=operation+'_'+key,
                defaults={'name': module.title+' / '+label})
        Module.objects.using(alias).filter(pk=key).update(operations=operations)
    # No role/user permission M2M or override is written here.


def unseed(apps, schema_editor):
    alias = schema_editor.connection.alias
    Module = apps.get_model('access_control', 'Module')
    Override = apps.get_model('access_control', 'PermissionOverride')
    Permission = apps.get_model('auth', 'Permission')
    operations = [operation for operation, _ in FORMATS]
    Override.objects.using(alias).filter(operation__in=operations).delete()
    Permission.objects.using(alias).filter(
        content_type__app_label='access_control', content_type__model='module',
        codename__in=[operation+'_'+key for key in MODULE_KEYS for operation in operations]).delete()
    for module in Module.objects.using(alias).filter(pk__in=MODULE_KEYS):
        Module.objects.using(alias).filter(pk=module.pk).update(
            operations=[operation for operation in module.operations if operation not in operations])


class Migration(migrations.Migration):
    dependencies = [('access_control', '0002_default_roles')]
    operations = [
        migrations.RemoveConstraint(model_name='permissionoverride', name='access_operation_valid'),
        migrations.AlterField(model_name='permissionoverride', name='operation', field=models.CharField(choices=CHOICES, max_length=20)),
        migrations.AddConstraint(model_name='permissionoverride', constraint=models.CheckConstraint(
            condition=models.Q(operation__in=[operation for operation, _ in CHOICES]), name='access_operation_valid')),
        migrations.RunPython(seed, unseed),
    ]
