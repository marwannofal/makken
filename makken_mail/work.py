"""Work assignment is distinct from existing funding and execution workflows."""
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from access_control.activity_capture import emit, regions_for
from access_control.policy import require
from .events import enqueue
from .forms import ProgressForm, WorkForm
from .models import WorkAssignment, WorkHistory, WorkStatus
from .targets import can_manage_work, can_read_work, is_assignee, record

User = get_user_model()


class WorkConflict(Exception):
    pass


class WorkInvalid(Exception):
    def __init__(self, form):
        self.form = form


def work_snapshot(work):
    assignee_ids = sorted(work.assignees.values_list('pk', flat=True)) if work.pk else []
    if not assignee_ids and work.employee_id:
        assignee_ids = [work.employee_id]
    return {
        'title': work.title, 'employee_id': work.employee_id, 'assignee_ids': assignee_ids,
        'manager_id': work.manager_id,
        'status': work.status, 'progress': work.progress,
        'due_on': work.due_on.isoformat() if work.due_on else None,
        'target_model': work.target_model, 'target_key': work.target_key,
    }


def _target_regions(attached):
    if attached is None:
        return []
    if attached._meta.label_lower == 'agreement_clauses.agreement':
        return regions_for(attached.partnership)
    return regions_for(attached)


def record_update(work, actor, action, before=None, note=''):
    snapshot = work_snapshot(work)
    history = WorkHistory.objects.create(assignment=work, actor=actor, action=action, snapshot=snapshot, note=note)
    attached = record(work.target_model, work.target_key)
    attached_regions = _target_regions(attached)
    emit(actor=actor, module='work_assignments', action='create' if action == 'created' else 'update',
         description={'created': 'إسناد عمل جديد', 'reassigned': 'تعديل إسناد عمل',
                      'progress': 'تحديث تقدم العمل', 'edited': 'تعديل تفاصيل عمل'}[action],
         target_model='makken_mail.workassignment', target_key=str(work.pk),
         target_label=f'عمل رقم {work.pk}', before={'status': before['status']} if before else {},
         after={'status': snapshot['status']},
         scope='regional' if attached_regions else 'unknown',
         regions=attached_regions, source_key=f'work:{history.pk}', live=False)
    enqueue('work.' + action, f'work:{history.pk}', actor_id=actor.pk, history=history, assignments=(work,))


@transaction.atomic
def save_work(actor, data, pk=None):
    actor = User.objects.get(pk=actor.pk)
    if not actor.is_superuser:
        require(actor, 'work_assignments', 'view', 'edit' if pk else 'create')
    work = WorkAssignment.objects.select_for_update().filter(pk=pk).first() if pk else None
    if pk and work is None:
        raise WorkConflict('لم يعد العمل متاحًا.')
    if work and not can_manage_work(actor, work):
        raise PermissionDenied('لا تملك صلاحية تعديل أو إعادة إسناد هذا العمل.')
    form = WorkForm(data, actor=actor)
    if not form.is_valid():
        raise WorkInvalid(form)
    values = form.cleaned_data
    if work and values['revision'] != work.revision:
        raise WorkConflict('عُدّل السجل منذ فتحه. حدّث الصفحة قبل الحفظ.')
    if work and work.status in {WorkStatus.COMPLETE, WorkStatus.CANCELLED}:
        raise WorkConflict('لا يمكن تعديل إسناد عمل مغلق.')
    new = work is None
    work = work or WorkAssignment(created_by=actor)
    before = work_snapshot(work)
    instructions = work.instructions
    for name in ('title', 'instructions', 'employee', 'manager', 'due_on', 'target_model', 'target_key'):
        setattr(work, name, values[name])
    desired_assignees = values['assignees']
    desired_ids = sorted(person.pk for person in desired_assignees)
    after = {
        **work_snapshot(work),
        'employee_id': work.employee_id,
        'assignee_ids': desired_ids,
        'manager_id': work.manager_id,
        'title': work.title,
        'due_on': work.due_on.isoformat() if work.due_on else None,
        'target_model': work.target_model,
        'target_key': work.target_key,
    }
    if not new and before == after and instructions == work.instructions:
        return work
    action = (
        'created'
        if new
        else 'reassigned'
        if any(before[k] != after[k] for k in ('employee_id', 'assignee_ids', 'manager_id'))
        else 'edited'
    )
    if not new:
        work.revision += 1
    work.save()
    work.assignees.set(desired_assignees)
    record_update(work, actor, action, before if not new else None)
    return work


@transaction.atomic
def change_progress(actor, pk, data):
    actor = User.objects.get(pk=actor.pk)
    work = WorkAssignment.objects.select_for_update().get(pk=pk)
    if not can_read_work(actor, work) or not (actor.is_superuser or is_assignee(actor, work)):
        raise PermissionDenied
    if work.status in {WorkStatus.COMPLETE, WorkStatus.CANCELLED}:
        raise WorkConflict('هذا العمل مغلق ولا يمكن تغيير تقدّمه.')
    form = ProgressForm(data, administrator=actor.is_superuser)
    if not form.is_valid():
        raise WorkInvalid(form)
    values = form.cleaned_data
    if values['revision'] != work.revision:
        raise WorkConflict('عُدّل السجل منذ فتحه. حدّث الصفحة قبل الحفظ.')
    before = work_snapshot(work)
    work.status, work.progress = values['status'], values['progress']
    if before == work_snapshot(work) and not values['note']:
        return work
    work.revision += 1
    work.save(update_fields=['status', 'progress', 'revision', 'updated_at'])
    record_update(work, actor, 'progress', before, values['note'])
    return work
