"""US-15 External sponsor registration (public form) and RBAC/region-scoped admin review queue."""
import logging
import uuid

from django import forms
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

from access_control.enforcement import denied, module_view
from access_control.policy import AccessPolicy
from access_control.regions import RegionalPolicy
from accounts.security import add_login_headers
from care_states.models import DevelopmentState
from entities.models import Entity
from regions.models import Region
from sectors.models import Sector
from sponsorship_shapes.models import SponsorshipShape

from .models import (
    Partnership,
    PartnershipOffering,
    Scope,
    SponsorRegistrationRequest,
    SponsorRequestStatus,
    normalize_name,
    validate_name,
)

logger = logging.getLogger(__name__)


class PublicSponsorRegistrationForm(forms.ModelForm):
    # Anti-spam honeypot (must stay blank)
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={'tabindex': '-1', 'autocomplete': 'off'}))
    administrative_regions = forms.ModelMultipleChoiceField(
        label='المناطق الإدارية للجهة',
        queryset=Region.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple(),
    )

    class Meta:
        model = SponsorRegistrationRequest
        fields = [
            'name', 'representative', 'phone', 'email',
            'entity', 'scope', 'administrative_regions',
            'sector', 'sponsorship_shape', 'financial_capacity', 'notes',
        ]
        widgets = {
            'name': forms.TextInput(attrs={'placeholder': 'مثال: شركة التقنية المتقدمة', 'maxlength': '200'}),
            'representative': forms.TextInput(attrs={'placeholder': 'الاسم الكامل لممثل الجهة', 'maxlength': '200'}),
            'phone': forms.TextInput(attrs={'placeholder': '05XXXXXXXX', 'dir': 'ltr', 'maxlength': '16'}),
            'email': forms.EmailInput(attrs={'placeholder': 'sponsor@company.com', 'dir': 'ltr', 'maxlength': '254'}),
            'financial_capacity': forms.NumberInput(attrs={'min': '0', 'step': '0.01', 'placeholder': 'اختياري (ريال سعودي)'}),
            'notes': forms.Textarea(attrs={'rows': 4, 'placeholder': 'نبذة مختصرة عن الجهة ومجالات الرعاية المقترحة (اختياري)'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['entity'].queryset = Entity.objects.filter(is_active=True).order_by('name')
        self.fields['entity'].empty_label = 'اختر نوع الكيان'
        self.fields['administrative_regions'].queryset = Region.objects.filter(is_active=True).order_by('name')
        self.fields['sector'].queryset = Sector.objects.filter(is_active=True).order_by('name')
        self.fields['sector'].empty_label = 'اختر القطاع (اختياري)'
        self.fields['sponsorship_shape'].queryset = SponsorshipShape.objects.filter(is_active=True).order_by('name')
        self.fields['sponsorship_shape'].empty_label = 'اختر شكل الرعاية (اختياري)'

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

    def clean(self):
        cleaned = super().clean()
        scope = cleaned.get('scope')
        regions = cleaned.get('administrative_regions')
        if scope == Scope.LOCAL and (not regions or not regions.exists()):
            self.add_error('administrative_regions', 'اختر منطقة إدارية واحدة على الأقل للشراكة المحلية.')
        return cleaned


class RejectSponsorRequestForm(forms.Form):
    rejection_reason = forms.CharField(
        label='سبب الرفض',
        max_length=1000,
        required=True,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'اذكر سبب رفض الطلب بوضوح'}),
        error_messages={'required': 'يجب إدخال سبب الرفض قبل حفظ القرار.'},
    )


def _send_decision_email(req, approved):
    """Best-effort notification to the external sponsor via Makken SMTP (never breaks workflow)."""
    if not req.email:
        return
    try:
        from makken_mail.models import SMTPConfig
        from makken_mail.smtp import SendFailure, message_link, ready, send
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
        'entity', 'sector', 'sponsorship_shape', 'reviewed_by', 'created_partnership'
    ).prefetch_related('administrative_regions')
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
    form = PublicSponsorRegistrationForm(request.POST or None)
    status_code = 200
    if request.method == 'POST':
        if (request.POST.get('website') or '').strip():
            # Honeypot triggered by bot: pretend success without persisting
            request.session['sponsor_request_ref'] = 'REQ-RECEIVED'
            return redirect('partnerships:public_sponsor_thanks')
        if form.is_valid():
            req = form.save(commit=False)
            req.status = SponsorRequestStatus.NEW
            req.save()
            form.save_m2m()
            request.session['sponsor_request_ref'] = req.reference_code
            request.session['sponsor_request_name'] = req.name
            return redirect('partnerships:public_sponsor_thanks')
        status_code = 400
    return add_login_headers(render(request, 'partnerships/public_register.html', {
        'form': form,
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
    can_decide = request.user.is_superuser or policy.can('partnerships', 'create')
    name = request.user.get_short_name() or request.user.get_username()
    return add_login_headers(render(request, 'partnerships/sponsor_requests.html', {
        'display_name': name,
        'avatar_initial': name[:1],
        'active_page': 'sponsor_requests',
        'page_heading': 'طلبات الرعاة الخارجيين',
        'rows': list(qs),
        'counts': counts,
        'selected_status': selected_status,
        'statuses': SponsorRequestStatus.choices,
        'q': q,
        'can_decide': can_decide,
    }))


@module_view('partnerships')
@require_http_methods(['GET', 'POST'])
def sponsor_request_review(request, request_id):
    """Review, approve (creating a Partnership), or permanently reject an external sponsor request."""
    req = get_object_or_404(
        SponsorRegistrationRequest.objects.select_related(
            'entity', 'sector', 'sponsorship_shape', 'reviewed_by', 'created_partnership'
        ).prefetch_related('administrative_regions'),
        pk=request_id,
    )
    if not _can_review_request(request.user, req):
        return denied(request, 'هذا الطلب خارج نطاق مناطقك المصرح بها.')

    policy = AccessPolicy(request.user)
    can_decide = request.user.is_superuser or policy.can('partnerships', 'create')
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
                    locked = SponsorRegistrationRequest.objects.select_related('entity', 'sector', 'sponsorship_shape').get(pk=req.pk)
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
                            is_active=True,
                            development_state_id=DevelopmentState.CAPABILITY,
                            created_by=request.user,
                        )
                        region_ids = list(locked.administrative_regions.values_list('pk', flat=True))
                        if region_ids:
                            partnership.administrative_regions.set(region_ids)
                        if locked.sector_id and locked.sponsorship_shape_id:
                            PartnershipOffering.objects.create(
                                partnership=partnership,
                                sector=locked.sector,
                                sponsorship_shape=locked.sponsorship_shape,
                                is_active=True,
                            )
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
                    messages.success(request, f'تم اعتماد الطلب ({req.reference_code}) وإدراج الشراكة في السجل الرئيسي.')
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
        'can_decide': can_decide,
        'reject_form': reject_form,
        'error_message': error_message,
    }, status=status_code))
