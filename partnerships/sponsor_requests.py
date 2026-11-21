"""US-15 External sponsor registration (public form) and RBAC/region-scoped admin review queue."""
import json
import logging
import uuid

from django import forms
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Q
from pathlib import Path
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from access_control.enforcement import denied, module_view
from access_control.policy import AccessPolicy
from access_control.regions import RegionalPolicy
from accounts.security import add_login_headers
from care_states.models import DevelopmentState
from entities.models import Entity, EntityType
from makken_mail.events import enqueue
from regions.models import Region
from sectors.models import Sector
from specializations.models import Specialization
from sponsorship_shapes.models import SponsorshipShape

from .forms import COUNTRIES
from .attachment_storage import willingness_storage
from .models import (
    Partnership,
    PartnershipOffering,
    PartnershipType,
    PreliminaryAgreementType,
    Scope,
    SponsorRegistrationRequest,
    SponsorRequestAttachment,
    SponsorRequestStatus,
    WillingnessAttachment,
    normalize_name,
    validate_name,
)
from .willingness import (
    LEGACY_TYPE_BY_NAME,
    MultipleAttachmentField,
    MultipleAttachmentInput,
    safe_filename,
)

logger = logging.getLogger(__name__)


def _public_catalog():
    entities = list(
        Entity.objects.filter(is_active=True)
        .order_by('name')
        .values('id', 'name', 'entity_type')
    )
    sectors = list(
        Sector.objects.filter(is_active=True)
        .order_by('name')
        .values('id', 'name')
    )
    specializations = list(
        Specialization.objects.filter(is_active=True)
        .order_by('name')
        .values('id', 'name', 'sector_id')
    )
    shapes = list(
        SponsorshipShape.objects.filter(is_active=True)
        .order_by('name')
        .values('id', 'name')
    )
    return {
        'entities': entities,
        'sectors': sectors,
        'specializations': specializations,
        'shapes': shapes,
    }


def _resolve_offerings_display(offerings):
    """Turn stored offerings JSON list into human-readable dicts for the review page."""
    if not offerings or not isinstance(offerings, list):
        return []
    sector_ids = {row.get('sector') for row in offerings if isinstance(row, dict) and row.get('sector')}
    shape_ids = {row.get('shape') for row in offerings if isinstance(row, dict) and row.get('shape')}
    spec_ids = {
        sid
        for row in offerings
        if isinstance(row, dict)
        for sid in (row.get('specializations') or [])
    }
    sectors_map = dict(Sector.objects.filter(pk__in=sector_ids).values_list('pk', 'name'))
    shapes_map = dict(SponsorshipShape.objects.filter(pk__in=shape_ids).values_list('pk', 'name'))
    specs_map = dict(Specialization.objects.filter(pk__in=spec_ids).values_list('pk', 'name'))
    resolved = []
    for row in offerings:
        if not isinstance(row, dict):
            continue
        resolved.append({
            'sector_name': sectors_map.get(row.get('sector'), '—'),
            'shape_name': shapes_map.get(row.get('shape'), '—'),
            'specializations': [specs_map[sid] for sid in (row.get('specializations') or []) if sid in specs_map],
        })
    return resolved


class PublicSponsorRegistrationForm(forms.ModelForm):
    # Anti-spam honeypot (must stay blank)
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={'tabindex': '-1', 'autocomplete': 'off'}))
    phone_country = forms.ChoiceField(label='رمز الدولة', choices=COUNTRIES, initial='SA', required=False)
    entity_type = forms.ChoiceField(
        label='نوع الكيان',
        choices=[('', 'اختر نوع الكيان'), *EntityType.choices],
        required=False,
    )
    administrative_regions = forms.ModelMultipleChoiceField(
        label='المناطق الإدارية للجهة',
        queryset=Region.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )
    offerings_json = forms.CharField(required=False, widget=forms.HiddenInput, initial='[]')
    attachments = MultipleAttachmentField(
        label='المرفقات الداعمة',
        required=False,
        widget=MultipleAttachmentInput(attrs={'id': 'pub-attachments-input', 'accept': '.pdf,.png,.jpg,.jpeg'}),
    )

    class Meta:
        model = SponsorRegistrationRequest
        fields = [
            'name', 'representative', 'phone_country', 'phone', 'email',
            'entity', 'scope', 'administrative_regions',
            'partnership_type', 'sector', 'sponsorship_shape', 'financial_capacity', 'notes',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'مثال: شركة التقنية المتقدمة', 'maxlength': '200'}),
            'representative': forms.TextInput(attrs={'placeholder': 'الاسم الكامل لممثل الجهة', 'maxlength': '200'}),
            'phone': forms.TextInput(attrs={'placeholder': '05XXXXXXXX', 'dir': 'ltr', 'maxlength': '16', 'inputmode': 'tel'}),
            'email': forms.EmailInput(attrs={'placeholder': 'sponsor@company.com', 'dir': 'ltr', 'maxlength': '254'}),
            'financial_capacity': forms.NumberInput(attrs={'min': '0', 'step': '0.01', 'placeholder': 'اختياري (ريال سعودي)'}),
            'notes': forms.Textarea(attrs={'rows': 4, 'placeholder': 'نبذة مختصرة عن الجهة ومجالات الرعاية المقترحة (اختياري)'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['entity'].queryset = Entity.objects.filter(is_active=True).order_by('name')
        self.fields['entity'].empty_label = 'اختر الكيان'
        self.fields['administrative_regions'].queryset = Region.objects.filter(is_active=True).order_by('name')
        self.fields['sector'].queryset = Sector.objects.filter(is_active=True).order_by('name')
        self.fields['sector'].empty_label = 'اختر القطاع (اختياري)'
        self.fields['sponsorship_shape'].queryset = SponsorshipShape.objects.filter(is_active=True).order_by('name')
        self.fields['sponsorship_shape'].empty_label = 'اختر شكل الرعاية (اختياري)'
        self.fields['partnership_type'].queryset = PartnershipType.objects.filter(is_active=True).order_by('id')
        self.fields['partnership_type'].empty_label = 'اختر نوع الشراكة (اختياري)'

    def clean_phone_country(self):
        return (self.cleaned_data.get('phone_country') or 'SA').strip() or 'SA'

    def clean_name(self):
        value = normalize_name(self.cleaned_data.get('name', ''))
        validate_name(value)
        if not value:
            raise forms.ValidationError('أدخل اسم الجهة.')
        key = value.casefold()
        if Partnership.objects.filter(name_key=key).exists():
            raise forms.ValidationError('يوجد سجل شراكة معتمد بنفس اسم الجهة بالفعل.')
        if SponsorRegistrationRequest.objects.filter(name_key=key, status=SponsorRequestStatus.NEW).exists():
            raise forms.ValidationError('يوجد طلب تسجيل قيد المراجعة بنفس اسم الجهة بالفعل.')
        return value

    def clean_phone(self):
        raw = (self.cleaned_data.get('phone') or '').strip()
        digits = ''.join(ch for ch in raw if ch.isdigit())
        if len(digits) < 8 or len(raw) > 16:
            raise forms.ValidationError('أدخل رقم هاتف تواصل صحيحًا.')
        return raw

    def clean_offerings_json(self):
        raw = (self.cleaned_data.get('offerings_json') or '').strip()
        if not raw:
            return []
        try:
            items = json.loads(raw)
        except (ValueError, TypeError) as exc:
            raise forms.ValidationError('تنسيق القطاعات وأشكال الرعاية غير صالح.') from exc
        if not isinstance(items, list):
            raise forms.ValidationError('تنسيق القطاعات وأشكال الرعاية غير صالح.')
        if len(items) > 30:
            raise forms.ValidationError('الحد الأقصى للقطاعات المضافة هو 30 عنصرًا.')

        active_sectors = set(Sector.objects.filter(is_active=True).values_list('pk', flat=True))
        active_shapes = set(SponsorshipShape.objects.filter(is_active=True).values_list('pk', flat=True))
        active_specs = dict(Specialization.objects.filter(is_active=True).values_list('pk', 'sector_id'))

        cleaned_rows = []
        seen_pairs = set()
        for entry in items:
            if not isinstance(entry, dict):
                raise forms.ValidationError('بيانات أحد القطاعات غير صالحة.')
            try:
                sec_id = int(entry.get('sector'))
                shape_id = int(entry.get('shape'))
            except (ValueError, TypeError) as exc:
                raise forms.ValidationError('اختر القطاع وشكل الرعاية لكل عنصر.') from exc
            if sec_id not in active_sectors or shape_id not in active_shapes:
                raise forms.ValidationError('أحد القطاعات أو أشكال الرعاية المختارة غير متاح.')
            raw_specs = entry.get('specializations') or []
            if not isinstance(raw_specs, list):
                raise forms.ValidationError('تنسيق التخصصات غير صالح.')
            spec_ids = []
            for raw_sid in raw_specs:
                try:
                    sid = int(raw_sid)
                except (ValueError, TypeError) as exc:
                    raise forms.ValidationError('أحد التخصصات المختارة غير صالح.') from exc
                if active_specs.get(sid) != sec_id:
                    raise forms.ValidationError('أحد التخصصات المختارة لا يتبع للقطاع المحدد.')
                if sid not in spec_ids:
                    spec_ids.append(sid)
            pair = (sec_id, shape_id)
            if pair in seen_pairs:
                raise forms.ValidationError('لا يمكن تكرار نفس القطاع وشكل الرعاية أكثر من مرة.')
            seen_pairs.add(pair)
            cleaned_rows.append({'sector': sec_id, 'specializations': spec_ids, 'shape': shape_id})
        return cleaned_rows

    def clean(self):
        cleaned = super().clean()
        scope = cleaned.get('scope')
        regions = cleaned.get('administrative_regions')
        if scope == Scope.LOCAL and (not regions or not regions.exists()):
            self.add_error('administrative_regions', 'اختر منطقة إدارية واحدة على الأقل للشراكة المحلية.')
        entity = cleaned.get('entity')
        entity_type = cleaned.get('entity_type')
        if entity and entity_type and entity.entity_type != entity_type:
            self.add_error('entity', 'الكيان المختار لا يطابق نوع الكيان المحدد.')
        return cleaned


class RejectSponsorRequestForm(forms.Form):
    rejection_reason = forms.CharField(
        label='سبب الرفض',
        max_length=1000,
        required=True,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'اذكر سبب رفض الطلب بوضوح'}),
        error_messages={'required': 'يجب إدخال سبب الرفض قبل حفظ القرار.'},
    )


def _send_submission_receipt_email(req):
    """Automatically send a confirmation receipt email to the sponsor's submitted email address."""
    if not req.email:
        return 'skipped'
    try:
        from makken_mail.models import SMTPConfig
        from makken_mail.smtp import message_link, ready, send
        config = SMTPConfig.objects.filter(pk=1).first()
        if not config or not config.enabled or not ready(config):
            return 'smtp_disabled'
        context = {
            'title': 'تأكيد استلام طلب تسجيل الراعي في منصة مكّن',
            'recipient_name': req.representative,
            'description': (
                f'شكرًا لتواصلكم مع منصة مكّن. تم استلام طلب تسجيل الجهة ({req.name}) بنجاح، '
                'وهو الآن قيد المراجعة لدى الفريق المختص وسيتم إشعاركم عبر البريد الإلكتروني فور البت في الطلب.'
            ),
            'details': [
                ('رقم الطلب', req.reference_code),
                ('اسم الجهة', req.name),
                ('ممثل الجهة', req.representative),
                ('حالة الطلب', 'جديد (قيد المراجعة)'),
            ],
            'link': message_link(reverse('partnerships:public_sponsor_register')),
        }
        send(config, req.email, context, f'<makken-sponsor-receipt-{req.pk}-{uuid.uuid4().hex}@makken-notifications.invalid>')
        return 'sent'
    except Exception:
        logger.warning('Sponsor request receipt email skipped for request %s', req.pk, exc_info=True)
        return 'failed'


def _send_decision_email(req, approved):
    """Best-effort notification to the external sponsor via Makken SMTP (never breaks workflow)."""
    if not req.email:
        return
    try:
        from makken_mail.models import SMTPConfig
        from makken_mail.smtp import message_link, ready, send
        config = SMTPConfig.objects.filter(pk=1).first()
        if not config or not config.enabled or not ready(config):
            return
        if approved:
            context = {
                'title': 'اعتماد طلب تسجيل الراعي في منصة مكّن',
                'recipient_name': req.representative,
                'description': f'يسعدنا إبلاغكم باعتماد طلب تسجيل الجهة ({req.name}) في منصة مكّن وإدراجها في سجل الشراكات.',
                'details': [
                    ('رقم الطلب', req.reference_code),
                    ('اسم الجهة', req.name),
                    ('حالة الطلب', 'معتمد'),
                ],
                'link': message_link(reverse('accounts:login')),
            }
        else:
            context = {
                'title': 'تحديث حول طلب تسجيل الراعي في منصة مكّن',
                'recipient_name': req.representative,
                'description': f'نعتذر عن عدم اعتماد طلب تسجيل الجهة ({req.name}) في الوقت الحالي.',
                'details': [
                    ('رقم الطلب', req.reference_code),
                    ('اسم الجهة', req.name),
                    ('حالة الطلب', 'مرفوض'),
                    ('سبب الرفض', req.rejection_reason or '—'),
                ],
                'link': message_link(reverse('partnerships:public_sponsor_register')),
            }
        send(config, req.email, context, f'<makken-sponsor-req-{req.pk}-{uuid.uuid4().hex}@makken-notifications.invalid>')
    except Exception:
        logger.warning('Sponsor request decision email skipped for request %s', req.pk, exc_info=True)


def _scoped_requests(user):
    qs = SponsorRegistrationRequest.objects.select_related(
        'entity', 'partnership_type', 'sector', 'sponsorship_shape', 'reviewed_by', 'created_partnership'
    ).prefetch_related('administrative_regions', 'attachments')
    if user.is_superuser:
        return qs
    reg = RegionalPolicy(user)
    if not reg.active:
        return qs.none()
    if reg.unrestricted:
        return qs
    if not reg.ids:
        return qs.none()
    return qs.filter(
        Q(administrative_regions__in=reg.ids) | Q(scope=Scope.GLOBAL, administrative_regions__isnull=True)
    ).distinct()


def _can_review_request(user, req):
    if user.is_superuser:
        return True
    reg = RegionalPolicy(user)
    if not reg.active:
        return False
    if reg.unrestricted:
        return True
    req_region_ids = set(req.administrative_regions.values_list('pk', flat=True))
    if not req_region_ids:
        return req.scope == Scope.GLOBAL
    return bool(req_region_ids & set(reg.ids))


@require_http_methods(['GET', 'POST'])
def public_sponsor_register(request):
    """Public unauthenticated registration form for external sponsors (US-15)."""
    form = PublicSponsorRegistrationForm(request.POST or None, request.FILES or None)
    status_code = 200
    if request.method == 'POST':
        if (request.POST.get('website') or '').strip():
            # Honeypot triggered by bot: pretend success without persisting
            request.session['sponsor_request_ref'] = 'REQ-RECEIVED'
            return redirect('partnerships:public_sponsor_thanks')
        if form.is_valid():
            req = form.save(commit=False)
            req.phone_country = form.cleaned_data.get('phone_country') or 'SA'
            offerings = form.cleaned_data.get('offerings_json') or []
            req.offerings = offerings
            if offerings and not req.sector_id:
                req.sector_id = offerings[0]['sector']
            if offerings and not req.sponsorship_shape_id:
                req.sponsorship_shape_id = offerings[0]['shape']
            req.status = SponsorRequestStatus.NEW
            req.save()
            form.save_m2m()
            uploads = form.cleaned_data.get('attachments') or []
            if uploads:
                storage = willingness_storage()
                for upload in uploads:
                    stored_name = 'sponsor_requests/' + uuid.uuid4().hex + Path(upload.name).suffix.lower()
                    actual = storage.save(stored_name, upload)
                    SponsorRequestAttachment.objects.create(
                        sponsor_request=req,
                        file=actual,
                        original_name=safe_filename(upload.name),
                        size=upload.size,
                        content_type=upload.verified_content_type,
                    )
            # 1) Send automatic receipt email to the sponsor's submitted email address
            _send_submission_receipt_email(req)
            # 2) Queue configurable admin alert rule (/notifications/rules/sponsor_request.submitted/)
            enqueue(
                'sponsor_request.submitted',
                f'sponsor-request:{req.pk}',
                item=req,
            )
            request.session['sponsor_request_ref'] = req.reference_code
            request.session['sponsor_request_name'] = req.name
            return redirect('partnerships:public_sponsor_thanks')
        status_code = 400
    return add_login_headers(render(request, 'partnerships/public_register.html', {
        'form': form,
        'public_catalog': _public_catalog(),
    }, status=status_code))


@require_GET
def public_sponsor_thanks(request):
    ref = request.session.pop('sponsor_request_ref', '')
    name = request.session.pop('sponsor_request_name', '')
    return add_login_headers(render(request, 'partnerships/public_register_thanks.html', {
        'reference_code': ref,
        'sponsor_name': name,
    }))


@module_view('partnerships')
@require_GET
def sponsor_request_queue(request):
    """RBAC and regionally-scoped admin review queue for external sponsor requests."""
    base_qs = _scoped_requests(request.user)
    selected_status = (request.GET.get('status') or '').strip()
    q = (request.GET.get('q') or '').strip()[:120]

    counts = {
        'total': base_qs.count(),
        'new': base_qs.filter(status=SponsorRequestStatus.NEW).count(),
        'approved': base_qs.filter(status=SponsorRequestStatus.APPROVED).count(),
        'rejected': base_qs.filter(status=SponsorRequestStatus.REJECTED).count(),
    }

    qs = base_qs
    if selected_status in SponsorRequestStatus.values:
        qs = qs.filter(status=selected_status)
    else:
        selected_status = ''
    if q:
        qs = qs.filter(
            Q(name__icontains=q)
            | Q(representative__icontains=q)
            | Q(email__icontains=q)
            | Q(reference_code__icontains=q)
        )

    policy = AccessPolicy(request.user)
    can_decide = request.user.is_superuser or policy.can('partnerships', 'create') or policy.can('partnerships', 'edit')
    name = request.user.get_short_name() or request.user.get_username()
    return add_login_headers(render(request, 'partnerships/sponsor_requests.html', {
        'display_name': name,
        'avatar_initial': name[:1],
        'active_page': 'sponsor_requests',
        'page_heading': 'طلبات الرعاة الخارجيين - شراكات القدرة',
        'requests_list': list(qs[:200]),
        'counts': counts,
        'selected_status': selected_status,
        'q': q,
        'statuses': SponsorRequestStatus.choices,
        'can_decide': can_decide,
    }))


@module_view('partnerships')
@require_http_methods(['GET', 'POST'])
def sponsor_request_review(request, request_id):
    """Review and approve/reject an external sponsor registration request."""
    req = get_object_or_404(
        SponsorRegistrationRequest.objects.select_related(
            'entity', 'partnership_type', 'sector', 'sponsorship_shape', 'reviewed_by', 'created_partnership'
        ).prefetch_related('administrative_regions', 'attachments'),
        pk=request_id,
    )
    if not _can_review_request(request.user, req):
        return denied(request, 'لا تملك صلاحية الوصول إلى هذا الطلب خارج نطاق مناطقك.')

    policy = AccessPolicy(request.user)
    can_decide = request.user.is_superuser or policy.can('partnerships', 'create') or policy.can('partnerships', 'edit')
    reject_form = RejectSponsorRequestForm()
    error_message = ''
    status_code = 200

    if request.method == 'POST':
        if not can_decide:
            return denied(request, 'لا تملك صلاحية اعتماد أو رفض طلبات الرعاة.')
        operation = (request.POST.get('operation') or '').strip()
        if req.status != SponsorRequestStatus.NEW:
            error_message = 'تم البت في هذا الطلب مسبقًا ولا يمكن تغيير حالته.'
            status_code = 409
        elif operation == 'approve':
            try:
                with transaction.atomic():
                    locked = SponsorRegistrationRequest.objects.select_related('entity', 'partnership_type', 'sector', 'sponsorship_shape').prefetch_related('attachments').get(pk=req.pk)
                    if locked.status != SponsorRequestStatus.NEW:
                        error_message = 'تم البت في هذا الطلب مسبقًا.'
                        status_code = 409
                    elif Partnership.objects.filter(name_key=locked.name_key).exists():
                        error_message = 'يوجد سجل شراكة بنفس اسم الجهة بالفعل. لا يمكن اعتماد الطلب.'
                        status_code = 409
                    else:
                        partnership = Partnership.objects.create(
                            name=locked.name,
                            representative=locked.representative,
                            phone_country=locked.phone_country or 'SA',
                            phone=locked.phone,
                            email=locked.email,
                            financial_capacity=locked.financial_capacity,
                            entity=locked.entity,
                            scope=locked.scope,
                            partnership_type=locked.partnership_type,
                            preliminary_agreement_type=(
                                LEGACY_TYPE_BY_NAME.get(locked.partnership_type.name, PreliminaryAgreementType.OTHER)
                                if locked.partnership_type_id else ''
                            ),
                            is_active=True,
                            development_state_id=DevelopmentState.CAPABILITY,
                            created_by=request.user,
                        )
                        region_ids = list(locked.administrative_regions.values_list('pk', flat=True))
                        if region_ids:
                            partnership.administrative_regions.set(region_ids)
                        if locked.offerings:
                            for pos, row in enumerate(locked.offerings):
                                sec_id = row.get('sector')
                                shape_id = row.get('shape')
                                if sec_id and shape_id:
                                    off = PartnershipOffering.objects.create(
                                        partnership=partnership,
                                        sector_id=sec_id,
                                        sponsorship_shape_id=shape_id,
                                        is_active=True,
                                        position=pos,
                                    )
                                    spec_ids = row.get('specializations') or []
                                    if spec_ids:
                                        off.specializations.set(spec_ids)
                        elif locked.sector_id and locked.sponsorship_shape_id:
                            PartnershipOffering.objects.create(
                                partnership=partnership,
                                sector=locked.sector,
                                sponsorship_shape=locked.sponsorship_shape,
                                is_active=True,
                            )
                        req_atts = list(locked.attachments.all())
                        if req_atts:
                            storage = willingness_storage()
                            for att in req_atts:
                                try:
                                    with att.file.open('rb') as src:
                                        copied_name = 'willingness/' + uuid.uuid4().hex + Path(att.original_name).suffix.lower()
                                        actual = storage.save(copied_name, src)
                                    WillingnessAttachment.objects.create(
                                        partnership=partnership,
                                        file=actual,
                                        original_name=att.original_name,
                                        size=att.size,
                                        content_type=att.content_type,
                                        uploaded_by=request.user,
                                    )
                                except (OSError, ValueError):
                                    logger.warning('Could not copy sponsor attachment %s to partnership %s', att.pk, partnership.pk)
                        locked.status = SponsorRequestStatus.APPROVED
                        locked.reviewed_by = request.user
                        locked.reviewed_at = timezone.now()
                        locked.created_partnership = partnership
                        locked.save(update_fields=['status', 'reviewed_by', 'reviewed_at', 'created_partnership', 'updated_at'])
                        req = locked
            except IntegrityError:
                error_message = 'تعذّر إنشاء الشراكة بسبب تعارض في اسم الجهة.'
                status_code = 409
            else:
                if not error_message:
                    _send_decision_email(req, approved=True)
                    messages.success(request, f'تم اعتماد الطلب ({req.reference_code}) وإدراج الشراكة في سجل شراكات القدرة.')
                    return redirect('partnerships:sponsor_request_review', request_id=req.pk)
        elif operation == 'reject':
            reject_form = RejectSponsorRequestForm(request.POST)
            if reject_form.is_valid():
                with transaction.atomic():
                    locked = SponsorRegistrationRequest.objects.get(pk=req.pk)
                    if locked.status != SponsorRequestStatus.NEW:
                        error_message = 'تم البت في هذا الطلب مسبقًا.'
                        status_code = 409
                    else:
                        locked.status = SponsorRequestStatus.REJECTED
                        locked.rejection_reason = reject_form.cleaned_data['rejection_reason'].strip()
                        locked.reviewed_by = request.user
                        locked.reviewed_at = timezone.now()
                        locked.save(update_fields=['status', 'rejection_reason', 'reviewed_by', 'reviewed_at', 'updated_at'])
                        req = locked
                if not error_message:
                    _send_decision_email(req, approved=False)
                    messages.success(request, f'تم رفض الطلب ({req.reference_code}) والإبقاء عليه في حالة مرفوض.')
                    return redirect('partnerships:sponsor_request_review', request_id=req.pk)
            else:
                status_code = 400
        else:
            return denied(request, 'إجراء غير صالح.')

    name = request.user.get_short_name() or request.user.get_username()
    return add_login_headers(render(request, 'partnerships/sponsor_request_detail.html', {
        'display_name': name,
        'avatar_initial': name[:1],
        'active_page': 'sponsor_requests',
        'page_heading': f'مراجعة طلب راعٍ · {req.reference_code}',
        'req': req,
        'offering_rows': _resolve_offerings_display(req.offerings),
        'can_decide': can_decide,
        'reject_form': reject_form,
        'error_message': error_message,
    }, status=status_code))


@module_view('partnerships')
@require_GET
def sponsor_request_attachment_download(request, request_id, attachment_id):
    req = get_object_or_404(SponsorRegistrationRequest.objects.prefetch_related('administrative_regions'), pk=request_id)
    if not _can_review_request(request.user, req):
        return denied(request, 'لا تملك صلاحية تنزيل مرفقات هذا الطلب.')
    att = get_object_or_404(SponsorRequestAttachment, pk=attachment_id, sponsor_request=req)
    try:
        source = att.file.open('rb')
    except (OSError, ValueError):
        raise Http404
    response = FileResponse(source, as_attachment=True, filename=att.original_name, content_type=att.content_type)
    return add_login_headers(response)
