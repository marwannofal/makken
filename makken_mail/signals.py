"""Signals keeping WorkAssignment progress/status synced with ClauseAssignment changes."""
from django.db.models.signals import post_delete, post_save

from agreement_clauses.models import ClauseAssignment
from .clause_sync import sync_work_for_agreement, sync_work_for_partnership


def _sync_from_clause(sender, instance, **kwargs):
    if kwargs.get("raw"):
        return
    actor = getattr(instance, "updated_by", None)
    if instance.partnership_id:
        sync_work_for_partnership(instance.partnership_id, actor=actor)
    elif instance.agreement_id:
        partnership_id = getattr(instance.agreement, "partnership_id", None)
        sync_work_for_agreement(instance.agreement_id, partnership_id=partnership_id, actor=actor)


def connect_clause_sync_signals():
    post_save.connect(_sync_from_clause, sender=ClauseAssignment, dispatch_uid="makken_mail_clause_sync_save")
    post_delete.connect(_sync_from_clause, sender=ClauseAssignment, dispatch_uid="makken_mail_clause_sync_delete")
