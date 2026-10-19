from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import QuerySet
from django.db.models.signals import pre_save,pre_delete
from .models import SecurityLock,RoleProfile


class LastAdminError(ValidationError):pass
class ProtectedRoleError(ValidationError):pass


def protect_admin_save(sender,instance,raw=False,using='default',update_fields=None,**kwargs):
    if raw or instance._state.adding or (instance.is_superuser and instance.is_active):return
    if update_fields is not None and not {'is_superuser','is_active'}.intersection(update_fields):return
    with transaction.atomic(using=using):
        SecurityLock.objects.using(using).select_for_update().get(pk=1)
        current=sender._base_manager.using(using).filter(pk=instance.pk,is_superuser=True,is_active=True).exists()
        if current and not sender._base_manager.using(using).filter(is_superuser=True,is_active=True).exclude(pk=instance.pk).exists():
            raise LastAdminError('لا يمكن تعطيل أو إزالة صلاحية آخر مدير نظام أعلى نشط.')


def protect_admin_delete(sender,instance,using='default',origin=None,**kwargs):
    if not instance.is_superuser or not instance.is_active:return
    with transaction.atomic(using=using):
        SecurityLock.objects.using(using).select_for_update().get(pk=1)
        removed=origin.values_list('pk',flat=True) if isinstance(origin,QuerySet) and origin.model is sender else [instance.pk]
        if not sender._base_manager.using(using).filter(is_superuser=True,is_active=True).exclude(pk__in=removed).exists():
            raise LastAdminError('لا يمكن حذف آخر مدير نظام أعلى نشط.')


def connect():
    user=get_user_model()
    pre_save.connect(protect_admin_save,sender=user,dispatch_uid='makken.access.last_admin_save',weak=False)
    pre_delete.connect(protect_admin_delete,sender=user,dispatch_uid='makken.access.last_admin_delete',weak=False)
    pre_delete.connect(protect_role_delete,sender=RoleProfile,dispatch_uid='makken.access.protected_role_delete',weak=False)


def protect_role_delete(sender,instance,using='default',**kwargs):
    if instance.system_key or instance.group.user_set.using(using).exists():
        raise ProtectedRoleError('لا يمكن حذف دور افتراضي أو دور مرتبط بمستخدمين.')
