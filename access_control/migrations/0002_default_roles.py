"""Seed roles and place existing non-superusers into a defined no-access state."""
from django.conf import settings
from django.db import migrations

MODULES = [('dashboard', 'الرئيسية', 'makken_home', ['view']), ('care_states', 'حالات التطور', 'care_states:index', ['view', 'edit']), ('levels', 'المستويات', 'levels:index', ['view', 'create', 'edit', 'delete', 'change_status']), ('regions', 'المناطق', 'regions:index', ['view', 'create', 'edit', 'delete', 'change_status']), ('entities', 'الكيانات', 'entities:index', ['view', 'create', 'edit', 'delete', 'change_status']), ('specializations', 'التخصصات', 'specializations:index', ['view', 'create', 'edit', 'delete', 'change_status']), ('sectors', 'القطاعات', 'sectors:index', ['view', 'create', 'edit', 'delete', 'change_status']), ('expense_items', 'بنود الصرف', 'expense_items:index', ['view', 'create', 'edit', 'delete', 'change_status']), ('training_programs', 'برامج التدريب', 'training_programs:index', ['view', 'create', 'edit', 'delete', 'change_status']), ('sponsorship_shapes', 'أشكال الرعاية', 'sponsorship_shapes:index', ['view', 'create', 'edit', 'delete', 'change_status']), ('partnerships', 'الشراكات', 'partnerships:index', ['view', 'create', 'edit', 'delete', 'change_status', 'export']), ('market_needs', 'بطاقات حاجة السوق ومتابعة الرعاية', 'market_needs:index', ['view', 'create', 'edit', 'delete', 'change_status', 'export']), ('service_providers', 'مزودو الخدمات', 'service_providers:index', ['view', 'create', 'edit', 'delete', 'change_status'])]


def seed(apps,schema_editor):
    alias=schema_editor.connection.alias
    Module=apps.get_model('access_control','Module')
    Role=apps.get_model('access_control','RoleProfile')
    Access=apps.get_model('access_control','UserAccess')
    Lock=apps.get_model('access_control','SecurityLock')
    Group=apps.get_model('auth','Group')
    Permission=apps.get_model('auth','Permission')
    ContentType=apps.get_model('contenttypes','ContentType')
    User=apps.get_model(settings.AUTH_USER_MODEL)
    Lock.objects.using(alias).get_or_create(pk=1)
    content,_=ContentType.objects.using(alias).get_or_create(app_label='access_control',model='module')
    for index,(key,title,route,operations) in enumerate(MODULES):
        Module.objects.using(alias).get_or_create(pk=key,defaults={'title':title,'route_name':route,'operations':operations,'position':index})
        for operation in operations:
            Permission.objects.using(alias).get_or_create(content_type=content,codename=operation+'_'+key,defaults={'name':title+' / '+operation})
    for key,title,operations in [('watcher','Watcher — مراقب',{'view'}),('editor','Editor — محرر',{'view','create','edit'})]:
        if Role.objects.using(alias).filter(system_key=key).exists():continue
        name=title;index=2
        while Group.objects.using(alias).filter(name=name).exists():name=title+' '+str(index);index+=1
        group=Group.objects.using(alias).create(name=name)
        Role.objects.using(alias).create(group=group,system_key=key,description='دور افتراضي قابل لتخصيص الصفحات والصلاحيات.',page_scope='all')
        codes=[op+'_'+module[0] for module in MODULES for op in module[3] if op in operations]
        group.permissions.set(Permission.objects.using(alias).filter(content_type=content,codename__in=codes))
    existing=set(Access.objects.using(alias).values_list('user_id',flat=True))
    Access.objects.using(alias).bulk_create([Access(user_id=pk,page_scope='selected') for pk in User.objects.using(alias).exclude(pk__in=existing).values_list('pk',flat=True)])


class Migration(migrations.Migration):
    dependencies=[('access_control','0001_initial')]
    operations=[migrations.RunPython(seed,migrations.RunPython.noop)]
