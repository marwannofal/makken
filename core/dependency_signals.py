"""Defense in depth for model saves and queryset/model deletion.

Application writes already use atomic blocks and parent row locks. Preview
checks are advisory; these checks revalidate the current database at commit.
Raw SQL and QuerySet.update intentionally remain administrative operations.
"""
from django.apps import apps
from django.db import connections
from django.db.models.signals import pre_delete, pre_save
from .dependencies import TITLES, ensure_allowed


def before_save(sender, instance, raw=False, using='default', update_fields=None, **kwargs):
    if raw or instance._state.adding or instance.pk is None:
        return
    if update_fields is not None and 'is_active' not in update_fields:
        return
    if instance.is_active:
        return
    query = sender._base_manager.using(using)
    if connections[using].in_atomic_block:
        query = query.select_for_update()
    current = query.filter(pk=instance.pk).first()
    if current is not None:
        ensure_allowed(current, 'deactivate', active=False, using=using)


def before_delete(sender, instance, using='default', **kwargs):
    # Django's collector calls pre_delete before issuing any cascading DELETE.
    ensure_allowed(instance, 'delete', using=using)


def connect():
    for label in TITLES:
        try:
            model = apps.get_model(label)
        except LookupError:
            continue
        pre_save.connect(before_save, sender=model, weak=False, dispatch_uid='makken.dependency.save.' + label)
        pre_delete.connect(before_delete, sender=model, weak=False, dispatch_uid='makken.dependency.delete.' + label)
