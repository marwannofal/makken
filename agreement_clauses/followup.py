"""Follow-up entries and team edits on the existing agreement page."""
from uuid import UUID, uuid4

from django import forms
from django.core import signing
from django.core.paginator import Paginator
from core.pagination import resolve_page_size
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from access_control.enforcement import module_view
from access_control.policy import for_request, require
from access_control.regions import regional_transaction, require_write, scoped
from accounts.security import add_login_headers
from partnerships.attachment_storage import delete_private_files, willingness_storage
from partnerships.models import Partnership
from partnerships.willingness import MultipleAttachmentInput, safe_filename, validate_attachment

from .evidence_storage import evidence_path
from .models import Agreement, AgreementEvidence, AgreementFollowupEntry, ClauseAssignment, TeamSide
from .records import details_for, team_forms
from .workflow import WorkflowConflict, audit, token, touch_followup, validate_token

FOLLOWUP_OPERATIONS = {'add_followup', 'save_followup_teams'}
MAX_FILES = 5
MAX_EVIDENCE_BYTES = 10 * 1024 * 1024


class EvidenceField(forms.FileField):
    widget = MultipleAttachmentInput(attrs={'accept': '.pdf,.png,.jpg,.jpeg'})

    def clean(self, data, initial=None):
        files = data if isinstance(data, (list, tuple)) else [data] if data else []
        if len(files) > MAX_FILES:
            raise forms.ValidationError('يمكن إضافة خمسة ملفات كحد أقصى لكل تحديث.')
        clean_one = super().clean
        result = []
        for file in files:
            if file.size > MAX_EVIDENCE_BYTES:
                raise forms.ValidationError('الحد الأقصى لكل ملف هو 10 ميغابايت.')
            result.append(validate_attachment(clean_one(file, initial)))
        return result


class FollowupForm(forms.Form):
    clause = forms.ModelChoiceField(
        queryset=ClauseAssignment.objects.none(), label='البند المرتبط (اختياري)', required=False,
        empty_label='متابعة عامة للاتفاقية', error_messages={'invalid_choice': 'اختر بندًا من هذه الاتفاقية.'},
        widget=forms.Select(attrs={'data-market-select': ''}),
    )
    note = forms.CharField(
        label='ملاحظة المتابعة', required=False, max_length=2500,
        widget=forms.Textarea(attrs={'rows': 3}),
        error_messages={'max_length': 'يجب ألا تتجاوز الملاحظة 2500 حرف.'},
    )
    files = EvidenceField(label='الشواهد والمرفقات', required=False)

    def __init__(self, *args, agreement, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['clause'].queryset = agreement.clause_assignments.select_related('clause')
        self.fields['clause'].label_from_instance = lambda value: value.clause.name

    def clean(self):
        cleaned = super().clean()
        if not self.errors and not (cleaned['note'] or cleaned['files']):
            raise forms.ValidationError('أدخل ملاحظة أو أضف شاهدًا واحدًا على الأقل.')
        return cleaned


class InvalidFollowup(Exception):
    def __init__(self, **context):
        self.context = context


def change_followup(request, partnership_id, agreement_id):
    operation = request.POST.get('operation')
    if not agreement_id or operation not in FOLLOWUP_OPERATIONS:
        raise signing.BadSignature
    paths = []
    try:
        with regional_transaction(request.user) as policy:
            actor = policy.user
            require(actor, 'partnerships', 'edit')
            partnership = get_object_or_404(scoped(Partnership.objects.select_for_update(), policy=policy), pk=partnership_id)
            require_write(actor, partnership, policy=policy)
            agreement = get_object_or_404(Agreement.objects.select_for_update(), pk=agreement_id, partnership=partnership)
            state = validate_token(request.POST.get('snapshot'), actor, partnership, agreement)
            if state.get('kind') != operation:
                raise signing.BadSignature
            if not partnership.is_active:
                raise WorkflowConflict('هذه الشراكة غير نشطة. بطاقة المتابعة متاحة للعرض فقط.')
            if operation == 'save_followup_teams':
                return save_teams(request.POST, actor, partnership, agreement, state)
            try:
                key = UUID(state['entry_key'])
            except (KeyError, TypeError, ValueError):
                raise signing.BadSignature from None
            if agreement.followup_entries.filter(request_key=key).exists():
                return agreement, 'هذا التحديث محفوظ بالفعل.'
            form = FollowupForm(request.POST, request.FILES, agreement=agreement)
            if not form.is_valid():
                raise InvalidFollowup(bound_followup=form, entry_key=key.hex)
            note = form.cleaned_data['note']
            clause = form.cleaned_data['clause']
            entry = AgreementFollowupEntry.objects.create(
                agreement=agreement, request_key=key, note=note, clause=clause,
                clause_name=clause.clause.name if clause else '', created_by=actor,
            )
            storage = willingness_storage()
            for upload in form.cleaned_data['files']:
                name = evidence_path(None, upload.name)
                paths.append(name)
                actual = storage.save(name, upload)
                if actual != name:
                    paths.append(actual)
                AgreementEvidence.objects.create(
                    entry=entry, file=actual, original_name=safe_filename(upload.name),
                    size=upload.size, content_type=upload.verified_content_type,
                )
            touch_followup(agreement, actor)
            audit(actor, partnership, 'إضافة تحديث متابعة الاتفاقية', after={
                'agreement_number': agreement.number, 'clause': entry.clause_name,
                'attachment_count': len(form.cleaned_data['files']),
            })
            return agreement, 'تم حفظ تحديث المتابعة.'
    except Exception:
        if paths:
            delete_private_files(paths)
        raise


def save_teams(data, actor, partnership, agreement, state):
    details = details_for(agreement)
    if state.get('revision') != (details.revision if details.pk else 0):
        raise WorkflowConflict('تغيّرت بيانات الاتفاقية منذ فتح الصفحة. حدّثها قبل الحفظ.')
    teams = team_forms(agreement, data)
    if not all([team.is_valid() for _, team in teams]):
        raise InvalidFollowup(bound_teams=teams)
    if not any(team.has_changed() for _, team in teams):
        return agreement, 'لا توجد تغييرات.'
    if details.pk:
        details.revision += 1
        details.updated_by = actor
        details.save(update_fields=['revision', 'updated_by', 'updated_at'])
    else:
        details.updated_by = actor
        details.save()
    for _, team in teams:
        team.save()
    touch_followup(agreement, actor)
    audit(actor, partnership, 'تحديث فريقي عمل الاتفاقية', after={
        'agreement_number': agreement.number, 'agreement_team_count': agreement.members.count(),
    })
    return agreement, 'تم حفظ الفريقين وضباط الاتصال.'


def followup_context(request, partnership, agreement, children, *, bound_followup=None, entry_key=None, bound_teams=None):
    details = details_for(agreement)
    state = getattr(agreement, 'followup_state', None)
    if state:
        updated_at, updated_by = state.updated_at, state.updated_by
    else:
        # Legacy agreements may already have populated profiles and clause activity.
        latest = [(agreement.created_at, agreement.created_by)]
        if details.updated_at:
            latest.append((details.updated_at, details.updated_by))
        latest.extend((row.updated_at, row.updated_by) for row in children)
        updated_at, updated_by = max(latest, key=lambda pair: pair[0])

    policy = for_request(request)
    can_edit = partnership.is_active and partnership.region_writable and policy.can('partnerships', 'edit')
    editing_teams = can_edit and (bound_teams is not None or request.GET.get('edit_team') == '1')
    entries = agreement.followup_entries.select_related('created_by').prefetch_related('evidence')
    return {
        'details': details,
        'teams': [(label, agreement.members.filter(side=side)) for side, label in TeamSide.choices],
        'team_forms': (bound_teams if bound_teams is not None else team_forms(agreement)) if editing_teams else [],
        'entries_page': Paginator(entries, resolve_page_size(request, 10, param='updates_per_page')).get_page(request.GET.get('updates')),
        'followup_updated_at': updated_at, 'followup_updated_by': updated_by,
        'can_edit_followup': can_edit, 'can_download_evidence': policy.can('partnerships', 'export'),
        'editing_teams': editing_teams,
        'followup_form': (bound_followup if bound_followup is not None else FollowupForm(agreement=agreement)) if can_edit else None,
        'followup_token': token(request.user, partnership, agreement, kind='add_followup', entry_key=entry_key or uuid4().hex) if can_edit else '',
        'teams_token': token(request.user, partnership, agreement, kind='save_followup_teams',
                             revision=details.revision if details.pk else 0) if editing_teams else '',
    }


@module_view('partnerships')
@require_GET
def download_evidence(request, pk, agreement_id, attachment_id):
    partnership = get_object_or_404(scoped(Partnership.objects.all(), request.user), pk=pk)
    evidence = get_object_or_404(
        AgreementEvidence.objects.filter(entry__agreement_id=agreement_id, entry__agreement__partnership_id=pk),
        pk=attachment_id,
    )
    try:
        stream = evidence.file.open('rb')
    except (OSError, ValueError):
        raise Http404
    request._activity_target = partnership
    return add_login_headers(FileResponse(stream, as_attachment=True, filename=evidence.original_name,
                                          content_type=evidence.content_type))
