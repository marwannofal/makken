from django.conf import settings
from django.db import migrations, models


def backfill_assignees(apps, schema_editor):
    alias = schema_editor.connection.alias
    WorkAssignment = apps.get_model('makken_mail', 'WorkAssignment')
    through = WorkAssignment.assignees.through
    existing = set(through.objects.using(alias).values_list('workassignment_id', 'user_id'))
    rows = [
        through(workassignment_id=work_id, user_id=emp_id)
        for work_id, emp_id in WorkAssignment.objects.using(alias).values_list('pk', 'employee_id')
        if emp_id and (work_id, emp_id) not in existing
    ]
    if rows:
        through.objects.using(alias).bulk_create(rows)
    rules = apps.get_model('makken_mail', 'EventRule').objects.using(alias)
    for action in ('create', 'update', 'status', 'delete', 'view', 'download', 'export_xlsx', 'export_pdf', 'denied'):
        rules.get_or_create(code=f'work_assignments.{action}')


class Migration(migrations.Migration):

    dependencies = [
        ('makken_mail', '0005_account_regions_assigned'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='workassignment',
            name='assignees',
            field=models.ManyToManyField(
                blank=True,
                related_name='makken_work_assignments',
                to=settings.AUTH_USER_MODEL,
                verbose_name='الموظفون المسند إليهم',
            ),
        ),
        migrations.RunPython(backfill_assignees, migrations.RunPython.noop),
    ]
