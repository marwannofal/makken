"""Extend the existing home module; never grant roles/users automatically."""
from django.db import migrations


def seed(apps,schema_editor):
    alias=schema_editor.connection.alias
    Module=apps.get_model('access_control','Module')
    Permission=apps.get_model('auth','Permission')
    ContentType=apps.get_model('contenttypes','ContentType')
    module,_=Module.objects.using(alias).get_or_create(pk='dashboard',defaults={
        'title':'الرئيسية','route_name':'makken_home','operations':['view'],'position':0})
    operations=list(module.operations)
    content,_=ContentType.objects.using(alias).get_or_create(app_label='access_control',model='module')
    for operation,label in [('export_xlsx','تصدير Excel'),('export_pdf','تصدير PDF')]:
        if operation not in operations:operations.append(operation)
        Permission.objects.using(alias).get_or_create(content_type_id=content.pk,codename=operation+'_dashboard',
            defaults={'name':'الرئيسية / '+label})
    Module.objects.using(alias).filter(pk='dashboard').update(operations=operations)


class Migration(migrations.Migration):
    dependencies=[('access_control','0006_useractivity_activityregion_and_more')]
    operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
