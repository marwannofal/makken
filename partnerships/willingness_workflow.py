"""Shared clause-assignment, work-assignment, willingness-details, and team helpers."""
import json

from django import forms
from django.contrib.auth import get_user_model
from django.core.validators import validate_email
from django.db.models import Q

from accounts.models import Department
from agreement_clauses.models import AgreementClassification, AgreementClause, AgreementOption, ClauseAssignment, OptionKind, Responsibility
from makken_mail.forms import PeopleField, PersonField, SELECT, active_users
from makken_mail.models import WorkAssignment
from makken_mail.work import record_update

from regions.models import Region
from .models import PartnershipTeamMember, PartnershipType, RenewalRule, TeamMemberRole, TeamSide

User = get_user_model()

DETAIL_FIELDS = (
    'institution_signatory',
    'institution_signatory_title',
    'partner_signatory',
    'partner_signatory_title',
    'partner_rep_email',
    'partner_rep_phone',
    'institution_rep_name',
    'institution_rep_email',
    'institution_rep_phone',
    'partnership_type',
    'signed_on',
    'starts_on',
    'duration_months',
    'renewal_rule',
    'partnership_status',
    'agreement_classification',
    'concerned_departments',
    'headquarters_city',
    'signing_region',
    'signing_city',
    'objective',
    'announcement',
    'audience',
    'expected_results',
)


class DepartmentMultiField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return f'{obj.name} ({obj.get_kind_display()})'


class WillingnessDetailsForm(forms.Form):
    institution_signatory = forms.CharField(label='اسم موقّع الشراكة من طرف المؤسسة', max_length=160, required=False, widget=forms.TextInput(attrs={'placeholder': 'الاسم الكامل للموقّع من طرف المؤسسة'}))
    institution_signatory_title = forms.CharField(label='صفته الاعتبارية (المنصب) — المؤسسة', max_length=160, required=False, widget=forms.TextInput(attrs={'placeholder': 'المنصب لدى المؤسسة'}))
    partner_signatory = forms.CharField(label='اسم موقّع الشراكة من طرف الجهة', max_length=160, required=False, widget=forms.TextInput(attrs={'placeholder': 'الاسم الكامل للموقّع من طرف الجهة'}))
    partner_signatory_title = forms.CharField(label='صفته الاعتبارية (المنصب) — الجهة', max_length=160, required=False, widget=forms.TextInput(attrs={'placeholder': 'المنصب لدى الجهة'}))
    partner_rep_email = forms.EmailField(label='البريد الإلكتروني لممثل الجهة', max_length=254, required=False, widget=forms.EmailInput(attrs={'dir': 'ltr', 'placeholder': 'example@domain.com'}))
    partner_rep_phone = forms.CharField(label='رقم الجوال لممثل الجهة', max_length=32, required=False, widget=forms.TextInput(attrs={'dir': 'ltr', 'placeholder': '+9665XXXXXXXX'}))
    institution_rep_name = forms.CharField(label='اسم ممثل المؤسسة', max_length=160, required=False, widget=forms.TextInput(attrs={'placeholder': 'الاسم الكامل لممثل المؤسسة'}))
    institution_rep_email = forms.EmailField(label='البريد الإلكتروني لممثل المؤسسة', max_length=254, required=False, widget=forms.EmailInput(attrs={'dir': 'ltr', 'placeholder': 'example@tvtc.gov.sa'}))
    institution_rep_phone = forms.CharField(label='رقم الجوال لممثل المؤسسة', max_length=32, required=False, widget=forms.TextInput(attrs={'dir': 'ltr', 'placeholder': '+9665XXXXXXXX'}))
    signed_on = forms.DateField(label='تاريخ توقيع الشراكة', required=False, widget=forms.DateInput(attrs={'type': 'date', 'data-signed-on': ''}, format='%Y-%m-%d'))
    starts_on = forms.DateField(label='تاريخ بداية الشراكة', required=False, widget=forms.DateInput(attrs={'type': 'date', 'data-starts-on': ''}, format='%Y-%m-%d'))
    duration_months = forms.IntegerField(label='مدة الشراكة بالأشهر', min_value=1, max_value=600, required=False, widget=forms.NumberInput(attrs={'min': '1', 'max': '600', 'placeholder': 'مثال: 12 أو 24', 'data-duration-months': ''}))
    partnership_type = forms.ModelChoiceField(label='نوع الشراكة', queryset=PartnershipType.objects.none(), required=False, empty_label='اختر نوع الشراكة')
    renewal_rule = forms.ChoiceField(label='نوع التجديد', choices=[('', 'اختر نوع التجديد'), *RenewalRule.choices], required=False)
    partnership_status = forms.ModelChoiceField(label='حالة الشراكة', queryset=AgreementOption.objects.none(), required=False, empty_label='اختر حالة الشراكة', widget=forms.Select(attrs={'data-partnership-status': ''}))
    signing_region = forms.ModelChoiceField(label='منطقة التوقيع', queryset=Region.objects.none(), required=False, empty_label='اختر منطقة التوقيع')
    agreement_classification = forms.ModelChoiceField(label='تصنيف الاتفاقية', queryset=AgreementClassification.objects.none(), required=False, empty_label='اختر تصنيف الاتفاقية')
    concerned_departments = DepartmentMultiField(label='الإدارة المعنية', queryset=Department.objects.none(), required=False, widget=forms.SelectMultiple(attrs={**SELECT, 'data-label': 'الإدارة المعنية'}), help_text='يمكنك اختيار إدارة واحدة أو أكثر (تُعرض مع نوعها: إدارات المؤسسة / وحدات المؤسسة).')
    headquarters_city = forms.CharField(label='عنوان الجهة (مدينة المقر)', max_length=120, required=False, widget=forms.TextInput(attrs={'placeholder': 'أدخل مدينة المقر'}))
    signing_city = forms.CharField(label='مدينة التوقيع', max_length=120, required=False, widget=forms.TextInput(attrs={'placeholder': 'أدخل مدينة التوقيع'}))

    def __init__(self, *args, partnership=None, require_term_fields=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.require_term_fields = bool(require_term_fields)
        if require_term_fields:
            req_msgs = {
                'signed_on': 'أدخل تاريخ توقيع الشراكة.',
                'starts_on': 'أدخل تاريخ بداية الشراكة.',
                'duration_months': 'أدخل مدة الشراكة بالأشهر.',
                'renewal_rule': 'اختر نوع التجديد.',
                'partnership_status': 'اختر حالة الشراكة.',
            }
            for fname, msg in req_msgs.items():
                self.fields[fname].required = True
                self.fields[fname].error_messages['required'] = msg
        cur_type_id = partnership.partnership_type_id if partnership and partnership.pk else None
        cur_reg_id = partnership.signing_region_id if partnership and partnership.pk else None
        cur_cls_id = partnership.agreement_classification_id if partnership and partnership.pk else None
        cur_status_id = partnership.partnership_status_id if partnership and partnership.pk else None
        cur_dept_ids = list(partnership.concerned_departments.values_list('pk', flat=True)) if partnership and partnership.pk else []
        self.fields['partnership_type'].queryset = PartnershipType.objects.filter(Q(is_active=True) | Q(pk=cur_type_id)).order_by('id')
        self.fields['partnership_status'].queryset = AgreementOption.objects.filter(kind=OptionKind.STATUS).filter(Q(is_active=True) | Q(pk=cur_status_id)).order_by('id')
        self.fields['signing_region'].queryset = Region.objects.filter(Q(is_active=True) | Q(pk=cur_reg_id)).order_by('id')
        self.fields['agreement_classification'].queryset = AgreementClassification.objects.filter(Q(is_active=True) | Q(pk=cur_cls_id)).order_by('id')
        self.fields['concerned_departments'].queryset = Department.objects.filter(Q(is_active=True) | Q(pk__in=cur_dept_ids)).order_by('id')
    objective = forms.CharField(label='هدف الشراكة', max_length=2000, required=False, widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'اذكر الهدف الرئيسي من الشراكة'}))
    announcement = forms.CharField(label='خبر عن الشراكة', max_length=2000, required=False, widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'نبذة أو خبر إعلامي عن الشراكة'}))
    audience = forms.CharField(label='الفئات المستهدفة', max_length=2000, required=False, widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'حدد الفئات المستهدفة من الشراكة'}))
    expected_results = forms.CharField(label='النتائج المتوقعة', max_length=2000, required=False, widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'اذكر النتائج والمخرجات المتوقعة'}))

    def clean(self):
        cleaned = super().clean()
        starts = cleaned.get('starts_on')
        signed = cleaned.get('signed_on')
        months = cleaned.get('duration_months')
        if starts and not months:
            self.add_error('duration_months', 'أدخل مدة الشراكة بالأشهر لحساب تاريخ نهاية الشراكة تلقائيًا.')
        elif months and not starts and not signed:
            self.add_error('starts_on', 'أدخل تاريخ بداية الشراكة عند تحديد المدة بالأشهر.')
        return cleaned


def details_initial(partnership):
    if not partnership or not partnership.pk:
        return {}
    out = {}
    for field in DETAIL_FIELDS:
        if field == 'concerned_departments':
            out[field] = list(partnership.concerned_departments.values_list('pk', flat=True))
        elif field in {'partnership_type', 'partnership_status', 'signing_region', 'agreement_classification'}:
            out[field] = getattr(partnership, f'{field}_id')
        else:
            val = getattr(partnership, field)
            out[field] = val.isoformat() if field in {'signed_on', 'starts_on'} and val else ('' if val is None else val)
    return out


def serialize_details(cleaned):
    out = {}
    for field in DETAIL_FIELDS:
        val = cleaned.get(field)
        if field in {'signed_on', 'starts_on'}:
            out[field] = val.isoformat() if val else ''
        elif field == 'duration_months':
            out[field] = val if val is not None else None
        elif field == 'concerned_departments':
            out[field] = [d.pk if hasattr(d, 'pk') else int(d) for d in (val or [])]
        elif field in {'partnership_type', 'partnership_status', 'signing_region', 'agreement_classification'}:
            out[field] = val.pk if hasattr(val, 'pk') else (int(val) if val else None)
        else:
            out[field] = val or ''
    return out


def apply_willingness_details(partnership, cleaned_or_serialized, *, skip_partnership_type_if_empty=False):
    from datetime import date
    for field in DETAIL_FIELDS:
        val = cleaned_or_serialized.get(field)
        if field == 'partnership_type':
            if skip_partnership_type_if_empty and not val:
                continue
            partnership.partnership_type_id = val.pk if hasattr(val, 'pk') else (int(val) if val else None)
            continue
        if field == 'concerned_departments':
            continue
        if field == 'signing_region':
            partnership.signing_region_id = val.pk if hasattr(val, 'pk') else (int(val) if val else None)
            continue
        if field == 'agreement_classification':
            partnership.agreement_classification_id = val.pk if hasattr(val, 'pk') else (int(val) if val else None)
            continue
        if field == 'partnership_status':
            partnership.partnership_status_id = val.pk if hasattr(val, 'pk') else (int(val) if val else None)
            continue
        if field in {'signed_on', 'starts_on'}:
            if isinstance(val, str):
                val = date.fromisoformat(val) if val else None
        elif field == 'duration_months':
            if val in ('', None):
                val = None
            else:
                val = int(val)
        else:
            val = (val or '').strip()
        setattr(partnership, field, val)
    if partnership.starts_on and partnership.duration_months:
        partnership.ends_on = partnership.calculated_expiry
    elif partnership.signed_on and partnership.duration_months and not partnership.starts_on:
        partnership.starts_on = partnership.signed_on
        partnership.ends_on = partnership.calculated_expiry
    elif 'starts_on' in cleaned_or_serialized and not partnership.starts_on:
        partnership.ends_on = None


def save_partnership_departments(partnership, cleaned_or_serialized):
    if 'concerned_departments' not in cleaned_or_serialized:
        return
    raw = cleaned_or_serialized.get('concerned_departments') or []
    ids = [d.pk if hasattr(d, 'pk') else int(d) for d in raw]
    partnership.concerned_departments.set(ids)


def existing_team_rows(partnership):
    if not partnership or not partnership.pk:
        return []
    return [
        {
            'side': m.side,
            'name': m.name,
            'phone': m.phone,
            'email': m.email,
            'organization': m.organization,
            'role': m.role,
        }
        for m in partnership.team_members.all().order_by('pk')
    ]


def parse_teams_payload(raw):
    if not raw:
        return []
    try:
        items = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise forms.ValidationError('تنسيق بيانات فرق العمل غير صالح.') from exc
    if not isinstance(items, list):
        raise forms.ValidationError('تنسيق بيانات فرق العمل غير صالح.')
    valid_sides = set(TeamSide.values)
    valid_roles = set(TeamMemberRole.values)
    cleaned = []
    for entry in items[:100]:
        if not isinstance(entry, dict):
            raise forms.ValidationError('بيانات أحد أعضاء فريق العمل غير صالحة.')
        side = entry.get('side')
        role = entry.get('role')
        name = ' '.join(str(entry.get('name') or '').split())[:160]
        phone = str(entry.get('phone') or '').strip()[:32]
        email = str(entry.get('email') or '').strip()[:254]
        organization = ' '.join(str(entry.get('organization') or '').split())[:160]
        if side not in valid_sides:
            raise forms.ValidationError('فريق العمل المحدد غير صالح.')
        if role not in valid_roles:
            raise forms.ValidationError('صفة عضو فريق العمل غير صالحة.')
        if not name:
            raise forms.ValidationError('أدخل اسم كل عضو في فريق العمل.')
        if email:
            validate_email(email)
        cleaned.append({
            'side': side,
            'name': name,
            'phone': phone,
            'email': email,
            'organization': organization,
            'role': role,
        })
    return cleaned


def save_partnership_teams(partnership, rows):
    partnership.team_members.all().delete()
    if rows:
        PartnershipTeamMember.objects.bulk_create([
            PartnershipTeamMember(
                partnership=partnership,
                side=r['side'],
                name=r['name'],
                phone=r['phone'],
                email=r['email'],
                organization=r['organization'],
                role=r['role'],
            )
            for r in rows
        ])


class PartnershipWorkForm(forms.Form):
    """Same fields as /my-work/new/ without target_model and target_key (auto-linked to partnership)."""
    title = forms.CharField(
        label='عنوان العمل',
        max_length=160,
        error_messages={'required': 'أدخل عنوان العمل.', 'max_length': 'عنوان العمل أطول من الحد المسموح.'},
        widget=forms.TextInput(attrs={'placeholder': 'أدخل عنوان العمل المرتبط بالشراكة'}),
    )
    instructions = forms.CharField(
        label='تفاصيل العمل',
        max_length=3000,
        required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'أدخل تفاصيل العمل أو التعليمات (اختياري)'}),
    )
    assignees = PeopleField(
        label='الموظفون المسند إليهم',
        queryset=User.objects.none(),
        required=True,
        error_messages={'required': 'اختر موظفًا واحدًا على الأقل لإسناد العمل.'},
        widget=forms.SelectMultiple(attrs={**SELECT, 'data-label': 'الموظفون المسند إليهم'}),
        help_text='يمكنك إسناد العمل لموظف واحد أو عدة موظفين.',
    )
    manager = PersonField(
        label='مدير العمل',
        queryset=User.objects.none(),
        required=True,
        error_messages={'required': 'اختر مدير العمل.'},
        widget=forms.Select(attrs={**SELECT, 'data-label': 'مدير العمل'}),
    )
    due_on = forms.DateField(
        label='تاريخ الاستحقاق',
        required=False,
        widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
    )

    def __init__(self, *args, actor=None, optional=False, **kwargs):
        super().__init__(*args, **kwargs)
        if optional:
            for fname in ('title', 'assignees', 'manager'):
                self.fields[fname].required = False
                self.fields[fname].widget.attrs.pop('required', None)
        self.actor = actor
        users = active_users()
        if actor and not actor.is_superuser:
            from access_control.models import RegionScope
            from access_control.regions import RegionalPolicy
            reg = RegionalPolicy(actor)
            if not reg.unrestricted:
                users = users.filter(
                    Q(is_superuser=True)
                    | Q(makken_access__region_scope=RegionScope.ALL)
                    | Q(makken_access__allowed_regions__in=reg.ids)
                ).distinct()
        self.fields['assignees'].queryset = users
        self.fields['manager'].queryset = users

    def clean_title(self):
        value = ' '.join((self.cleaned_data.get('title') or '').split())
        if not value:
            raise forms.ValidationError('أدخل عنوان العمل.')
        return value

    def clean_assignees(self):
        people = list(self.cleaned_data.get('assignees') or [])
        if not people:
            raise forms.ValidationError('اختر موظفًا واحدًا على الأقل لإسناد العمل.')
        return people


def clause_catalog(partnership=None):
    existing_ids = set()
    if partnership and partnership.pk:
        existing_ids = set(
            ClauseAssignment.objects.filter(partnership=partnership, agreement__isnull=True)
            .values_list('clause_id', flat=True)
        )
    clauses = list(
        AgreementClause.objects.filter(Q(is_active=True) | Q(pk__in=existing_ids))
        .order_by('id')
        .values('id', 'name', 'is_active')
    )
    responsibilities = [
        {'value': value, 'label': label}
        for value, label in Responsibility.choices
    ]
    team_roles = [
        {'value': value, 'label': label}
        for value, label in TeamMemberRole.choices
    ]
    return {'clauses': clauses, 'responsibilities': responsibilities, 'team_roles': team_roles}


def existing_clause_rows(partnership):
    if not partnership or not partnership.pk:
        return []
    rows = ClauseAssignment.objects.filter(
        partnership=partnership, agreement__isnull=True
    ).select_related('clause').order_by('id')
    return [
        {
            'clause_id': row.clause_id,
            'clause_name': row.clause.name,
            'responsibility': row.responsibility,
            'progress': row.progress,
        }
        for row in rows
    ]


def parse_clauses_payload(raw, *, partnership=None, require_at_least_one=True, allow_progress=False):
    """Validate and normalize JSON list of {clause_id, responsibility, progress?}."""
    if not raw:
        items = []
    else:
        try:
            items = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise forms.ValidationError('تنسيق بنود الاتفاقية غير صالح.') from exc
    if not isinstance(items, list):
        raise forms.ValidationError('تنسيق بنود الاتفاقية غير صالح.')
    if require_at_least_one and not items:
        raise forms.ValidationError('أضف بندًا واحدًا على الأقل من بنود الاتفاقية.')

    existing_ids = set()
    if partnership and partnership.pk:
        existing_ids = set(
            ClauseAssignment.objects.filter(partnership=partnership, agreement__isnull=True)
            .values_list('clause_id', flat=True)
        )
    allowed_clauses = set(
        AgreementClause.objects.filter(Q(is_active=True) | Q(pk__in=existing_ids))
        .values_list('pk', flat=True)
    )
    valid_responsibilities = set(Responsibility.values)

    seen = set()
    cleaned = []
    for entry in items:
        if not isinstance(entry, dict):
            raise forms.ValidationError('بيانات أحد بنود الاتفاقية غير صالحة.')
        try:
            cid = int(entry.get('clause_id'))
        except (ValueError, TypeError) as exc:
            raise forms.ValidationError('اختر بند اتفاقية صالحًا.') from exc
        if cid not in allowed_clauses:
            raise forms.ValidationError('أحد بنود الاتفاقية المختارة غير متاح أو غير نشط.')
        if cid in seen:
            raise forms.ValidationError('لا يمكن تكرار نفس بند الاتفاقية أكثر من مرة.')
        seen.add(cid)

        resp = entry.get('responsibility')
        if resp not in valid_responsibilities:
            raise forms.ValidationError('اختر المسؤولية لكل بند من بنود الاتفاقية.')

        if allow_progress:
            try:
                prog = int(entry.get('progress', 0))
            except (ValueError, TypeError) as exc:
                raise forms.ValidationError('نسبة الإنجاز يجب أن تكون رقمًا صحيحًا بين 0 و100.') from exc
            if prog < 0 or prog > 100:
                raise forms.ValidationError('نسبة الإنجاز يجب أن تكون بين 0% و100%.')
        else:
            prog = 0

        cleaned.append({'clause_id': cid, 'responsibility': resp, 'progress': prog})
    return cleaned


def save_partnership_clauses(partnership, rows, user, *, allow_progress=False):
    """Sync ClauseAssignment rows directly on partnership (agreement=None)."""
    existing = {
        row.clause_id: row
        for row in ClauseAssignment.objects.select_for_update().filter(
            partnership=partnership, agreement__isnull=True
        )
    }
    keep_ids = set()
    for entry in rows:
        cid = entry['clause_id']
        keep_ids.add(cid)
        current = existing.get(cid)
        if current is None:
            ClauseAssignment.objects.create(
                partnership=partnership,
                agreement=None,
                clause_id=cid,
                responsibility=entry['responsibility'],
                progress=entry['progress'] if allow_progress else 0,
                updated_by=user,
            )
        else:
            new_progress = entry['progress'] if allow_progress else current.progress
            if current.responsibility != entry['responsibility'] or current.progress != new_progress:
                current.responsibility = entry['responsibility']
                current.progress = new_progress
                current.version += 1
                current.updated_by = user
                current.save(update_fields=['responsibility', 'progress', 'version', 'updated_by', 'updated_at'])

    stale_ids = [row.pk for cid, row in existing.items() if cid not in keep_ids]
    if stale_ids:
        ClauseAssignment.objects.filter(pk__in=stale_ids).delete()


def create_partnership_work(actor, cleaned_work, partnership):
    """Create WorkAssignment auto-linked to the partnership and trigger notifications."""
    assignees = list(cleaned_work['assignees'])
    work = WorkAssignment.objects.create(
        created_by=actor,
        title=cleaned_work['title'],
        instructions=cleaned_work.get('instructions') or '',
        employee=assignees[0],
        manager=cleaned_work['manager'],
        due_on=cleaned_work.get('due_on'),
        target_model='partnerships.partnership',
        target_key=partnership.pk,
    )
    work.assignees.set(assignees)
    from makken_mail.clause_sync import sync_single_work
    sync_single_work(work, actor=actor)
    record_update(work, actor, 'created', None)
    return work
