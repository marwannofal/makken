"""Internal agreement details, separate from the partnership's term."""
from django.contrib import messages
from django.core import signing
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from access_control.enforcement import module_view
from access_control.policy import for_request, require
from access_control.regions import regional_transaction, require_write, scoped
from accounts.security import add_login_headers
from partnerships.models import Partnership

from .models import Agreement, AgreementDetails, AgreementRenewal, TeamSide
from .record_forms import DetailsForm, RenewalForm, TeamForms, name_of
from .workflow import WorkflowConflict, audit, token, validate_token


def details_for(agreement):
    return AgreementDetails.objects.filter(agreement=agreement).first() or AgreementDetails(agreement=agreement)


def team_forms(agreement, data=None):
    return [
        (label, TeamForms(data, instance=agreement, side=side, prefix=side,
                         queryset=agreement.members.filter(side=side)))
        for side, label in TeamSide.choices
    ]


def current_expiry(agreement, details):
    latest = agreement.renewals.first()
    return latest.expires_on if latest else details.initial_expiry


def audit_record(agreement, details):
    return {
        'agreement_number': agreement.number,
        'agreement_signed_on': details.signed_on,
        'agreement_expires_on': current_expiry(agreement, details),
        'agreement_status': str(details.status or ''),
        'agreement_responsible': name_of(details.responsible_employee) if details.responsible_employee else '',
        'agreement_team_count': agreement.members.count(),
    }


def save_details(request, partnership_id, agreement_id):
    operation = request.POST.get('operation')
    if operation not in ('save_details', 'renew'):
        raise signing.BadSignature
    with regional_transaction(request.user) as policy:
        require(policy.user, 'partnerships', 'edit')
        partnership = get_object_or_404(scoped(Partnership.objects.select_for_update(), policy=policy), pk=partnership_id)
        require_write(policy.user, partnership, policy=policy)
        agreement = get_object_or_404(Agreement.objects.select_for_update(), pk=agreement_id, partnership=partnership)
        details = details_for(agreement)
        state = validate_token(request.POST.get('snapshot'), policy.user, partnership, agreement)
        if state.get('kind') != operation or state.get('revision') != (details.revision if details.pk else 0):
            raise WorkflowConflict('تغيّرت الاتفاقية منذ فتح الصفحة. حدّثها قبل الحفظ.')
        if not partnership.is_active:
            raise WorkflowConflict('هذه الشراكة غير نشطة. الاتفاقية متاحة للعرض فقط.')
        before = audit_record(agreement, details)
        if operation == 'renew':
            expiry = current_expiry(agreement, details)
            if not expiry or not details.renewal_rule:
                raise WorkflowConflict('احفظ تاريخ التوقيع والمدة ونوع التجديد أولًا.')
            form = RenewalForm(request.POST, prefix='renewal', start=expiry, rule=details.renewal_rule)
            if not form.is_valid():
                return None, None, form
            values = form.cleaned_data
            AgreementRenewal.objects.create(
                agreement=agreement, starts_on=expiry, expires_on=values['expires_on'],
                duration_months=values['duration_months'], rule=details.renewal_rule,
                approval_reference=values.get('approval_reference', ''), recorded_by=policy.user,
            )
            details.revision += 1
            details.updated_by = policy.user
            details.save(update_fields=['revision', 'updated_by', 'updated_at'])
            audit(policy.user, partnership, 'تسجيل تجديد الاتفاقية', before, audit_record(agreement, details))
            return 'تم تسجيل التجديد.', None, None

        form = DetailsForm(request.POST, instance=details, agreement=agreement)
        teams = team_forms(agreement, request.POST)
        forms_valid = [form.is_valid(), *(formset.is_valid() for _, formset in teams)]
        if not all(forms_valid):
            return None, (form, teams), None
        changed = form.has_changed() or any(row.has_changed() for _, team in teams for row in team.forms)
        if not changed:
            return 'لا توجد تغييرات.', None, None
        profile = form.save(commit=False)
        if profile.pk:
            profile.revision += 1
        profile.updated_by = policy.user
        profile.save()
        form.save_m2m()
        for _, team in teams:
            team.save()
        audit(policy.user, partnership, 'تحديث بيانات الاتفاقية', before, audit_record(agreement, profile))
        return 'تم حفظ بيانات الاتفاقية والفريقين.', None, None


@module_view('partnerships')
@require_http_methods(['GET', 'POST'])
def agreement_details(request, pk, agreement_id):
    partnership = get_object_or_404(scoped(Partnership.objects.all(), request.user), pk=pk)
    agreement = get_object_or_404(partnership.agreements, pk=agreement_id)
    details = details_for(agreement)
    error, bound, bound_renewal, status = '', None, None, 200
    if request.method == 'POST':
        try:
            success, bound, bound_renewal = save_details(request, pk, agreement_id)
            if success:
                messages.success(request, success)
                return add_login_headers(redirect('partnerships:agreement_details', pk=pk, agreement_id=agreement_id))
            status = 400
        except signing.BadSignature:
            error, status = 'انتهت صلاحية الطلب. حدّث الصفحة ثم حاول مجددًا.', 400
        except WorkflowConflict as exc:
            error, status = str(exc), 409
        except IntegrityError:
            error, status = 'تغيّرت البيانات قبل الحفظ. حدّث الصفحة ثم حاول مجددًا.', 409

    can_edit = partnership.is_active and partnership.region_writable and for_request(request).can('partnerships', 'edit')
    editing = can_edit and (bound is not None or request.GET.get('edit') == '1')
    expiry = current_expiry(agreement, details)
    form, teams = bound or (None, [])
    if editing and form is None:
        form = DetailsForm(instance=details, agreement=agreement)
        teams = team_forms(agreement)
    renew_form = bound_renewal
    if renew_form is None and expiry and details.renewal_rule and can_edit:
        renew_form = RenewalForm(prefix='renewal', start=expiry, rule=details.renewal_rule,
                                 initial={'duration_months': details.duration_months})
    state = {'revision': details.revision if details.pk else 0}
    name = request.user.get_short_name() or request.user.get_username()
    context = {
        'page_heading': 'بيانات الاتفاقية', 'active_page': 'partnerships', 'display_name': name, 'avatar_initial': name[:1],
        'partnership': partnership, 'agreement': agreement, 'details': details, 'form': form, 'team_forms': teams,
        'can_edit': can_edit, 'editing': editing, 'error': error, 'current_expiry': expiry,
        'teams': [(label, agreement.members.filter(side=side)) for side, label in TeamSide.choices],
        'renewals': agreement.renewals.select_related('recorded_by'),
        'save_token': token(request.user, partnership, agreement, kind='save_details', **state),
        'renew_token': token(request.user, partnership, agreement, kind='renew', **state),
        'renew_form': renew_form,
    }
    return add_login_headers(render(request, 'agreement_clauses/record.html', context, status=status))
