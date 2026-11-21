"""Automatic synchronization of WorkAssignment progress & status from Agreement Clause progress."""
from decimal import Decimal, ROUND_HALF_UP
from zoneinfo import ZoneInfo

from django.db.models import F, Q
from django.utils import timezone

from .models import WorkAssignment, WorkHistory, WorkStatus

RIYADH_TZ = ZoneInfo("Asia/Riyadh")


def riyadh_today():
    return timezone.now().astimezone(RIYADH_TZ).date()


def is_work_overdue(work, today=None):
    ref_day = today or riyadh_today()
    return bool(
        work.due_on
        and work.due_on < ref_day
        and work.status in {WorkStatus.NEW, WorkStatus.RUNNING}
    )


def _compute_progress_pct(values):
    if not values:
        return 0
    total = sum(int(v or 0) for v in values)
    avg = int((Decimal(total) / Decimal(len(values))).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    if any(int(v or 0) < 100 for v in values) and avg >= 100:
        avg = 99
    return max(0, min(100, avg))


def calculate_partnership_clause_progress(partnership_id):
    from agreement_clauses.models import ClauseAssignment
    values = list(
        ClauseAssignment.objects.filter(
            Q(partnership_id=partnership_id) | Q(agreement__partnership_id=partnership_id)
        ).values_list("progress", flat=True)
    )
    return _compute_progress_pct(values)


def calculate_agreement_clause_progress(agreement_id):
    from agreement_clauses.models import ClauseAssignment
    values = list(
        ClauseAssignment.objects.filter(agreement_id=agreement_id).values_list("progress", flat=True)
    )
    return _compute_progress_pct(values)


def derive_status_and_progress(progress_pct, current_status):
    pct = max(0, min(100, int(progress_pct or 0)))
    if current_status == WorkStatus.CANCELLED:
        return WorkStatus.CANCELLED, None
    if pct >= 100:
        return WorkStatus.COMPLETE, 100
    if pct > 0:
        return WorkStatus.RUNNING, pct
    return WorkStatus.NEW, 0


def sync_work_assignment(work, progress_pct, actor=None, note="تحديث تلقائي من نسب إنجاز بنود الاتفاقية"):
    new_status, new_progress = derive_status_and_progress(progress_pct, work.status)
    if new_progress is None:
        return False
    if work.status == new_status and work.progress == new_progress:
        return False
    work.status = new_status
    work.progress = new_progress
    work.revision = F("revision") + 1
    work.save(update_fields=["status", "progress", "revision", "updated_at"])
    work.refresh_from_db(fields=["status", "progress", "revision", "updated_at"])
    WorkHistory.objects.create(
        assignment=work,
        actor=actor,
        action="progress",
        snapshot={
            "title": work.title,
            "status": work.status,
            "progress": work.progress,
            "employee": work.employee_id,
            "manager": work.manager_id,
            "due_on": work.due_on.isoformat() if work.due_on else None,
        },
        note=note,
    )
    return True


def sync_work_for_partnership(partnership_id, actor=None):
    if not partnership_id:
        return 0
    pct = calculate_partnership_clause_progress(partnership_id)
    works = list(
        WorkAssignment.objects.filter(
            target_model="partnerships.partnership",
            target_key=partnership_id,
        ).exclude(status=WorkStatus.CANCELLED)
    )
    updated = 0
    for wk in works:
        if sync_work_assignment(wk, pct, actor=actor):
            updated += 1
    return updated


def sync_work_for_agreement(agreement_id, partnership_id=None, actor=None):
    updated = 0
    if agreement_id:
        pct = calculate_agreement_clause_progress(agreement_id)
        works = list(
            WorkAssignment.objects.filter(
                target_model="agreement_clauses.agreement",
                target_key=agreement_id,
            ).exclude(status=WorkStatus.CANCELLED)
        )
        for wk in works:
            if sync_work_assignment(wk, pct, actor=actor):
                updated += 1
    if partnership_id:
        updated += sync_work_for_partnership(partnership_id, actor=actor)
    return updated


def sync_single_work(work, actor=None):
    if work.status == WorkStatus.CANCELLED or not work.target_key:
        return False
    if work.target_model == "partnerships.partnership":
        pct = calculate_partnership_clause_progress(work.target_key)
        return sync_work_assignment(work, pct, actor=actor)
    if work.target_model == "agreement_clauses.agreement":
        pct = calculate_agreement_clause_progress(work.target_key)
        return sync_work_assignment(work, pct, actor=actor)
    return False


def sync_all_partnership_works():
    updated = 0
    p_ids = set(
        WorkAssignment.objects.filter(target_model="partnerships.partnership")
        .exclude(target_key__isnull=True)
        .exclude(status=WorkStatus.CANCELLED)
        .values_list("target_key", flat=True)
    )
    for pid in p_ids:
        updated += sync_work_for_partnership(pid)
    a_ids = set(
        WorkAssignment.objects.filter(target_model="agreement_clauses.agreement")
        .exclude(target_key__isnull=True)
        .exclude(status=WorkStatus.CANCELLED)
        .values_list("target_key", flat=True)
    )
    for aid in a_ids:
        updated += sync_work_for_agreement(aid)
    return updated
