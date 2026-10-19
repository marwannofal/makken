"""Idempotent bootstrap; never grant a role to an existing account automatically."""
from django.db import transaction
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group,Permission
from django.contrib.contenttypes.models import ContentType
from .models import Module,RoleProfile,UserAccess,SecurityLock,PageScope
from .registry import MODULES,codename


@transaction.atomic
def initialize():
    SecurityLock.objects.get_or_create(pk=1)
    SecurityLock.objects.select_for_update().get(pk=1)
    content,_=ContentType.objects.get_or_create(app_label='access_control',model='module')
    for position,module in enumerate(MODULES):
        Module.objects.update_or_create(pk=module.key,defaults={'title':module.title,'route_name':module.route_name,'operations':list(module.operations),'position':position})
        for operation in module.operations:
            Permission.objects.get_or_create(content_type=content,codename=codename(module.key,operation),defaults={'name':module.title+' / '+operation})
    for key,title,operations in [('watcher','Watcher — مراقب',{'view'}),('editor','Editor — محرر',{'view','create','edit'})]:
        role=RoleProfile.objects.filter(system_key=key).first()
        if role is not None:continue
        name=title;number=2
        while Group.objects.filter(name=name).exists():name=title+' '+str(number);number+=1
        role=RoleProfile.objects.create(group=Group.objects.create(name=name),system_key=key,description='دور افتراضي قابل لتخصيص الصفحات والصلاحيات.',page_scope=PageScope.ALL)
        codes=[codename(module.key,operation) for module in MODULES for operation in module.operations if operation in operations]
        role.group.permissions.set(Permission.objects.filter(content_type=content,codename__in=codes))
    User=get_user_model()
    existing=set(UserAccess.objects.values_list('user_id',flat=True))
    UserAccess.objects.bulk_create([UserAccess(user_id=pk,page_scope=PageScope.SELECTED) for pk in User._default_manager.exclude(pk__in=existing).values_list('pk',flat=True)])
