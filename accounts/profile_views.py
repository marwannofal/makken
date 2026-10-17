"""Self-service account updates with row locks, signed state and throttling."""
from datetime import timedelta
import json
import phonenumbers
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods
from .models import UserProfile
from .profile_forms import ProfileDetailsForm, ProfilePasswordForm, COUNTRIES, minimum_password_length, email_key
from .security import add_login_headers
SALT = 'makken.self-profile.v1'
WINDOW = timedelta(minutes=15)

def fingerprint(user, profile):
    values = [str(user.pk), user.first_name, user.last_name, user.email, user.password, profile.phone, profile.phone_country, profile.version]
    return salted_hmac(SALT, json.dumps(values, ensure_ascii=False), algorithm='sha256').hexdigest()

def snapshot(user, profile, action):
    return signing.dumps({'user': str(user.pk), 'action': action, 'state': fingerprint(user, profile)}, salt=SALT, compress=True)

def validate_snapshot(token, user, profile, action):
    if not isinstance(token, str) or len(token) > 2000:
        raise signing.BadSignature
    data = signing.loads(token, salt=SALT, max_age=20 * 60)
    if not isinstance(data, dict) or data.get('user') != str(user.pk) or data.get('action') != action or (not constant_time_compare(data.get('state', ''), fingerprint(user, profile))):
        raise signing.BadSignature

def initial_phone(profile):
    if not profile.phone:
        return ''
    try:
        number = phonenumbers.parse(profile.phone, profile.phone_country)
        return phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.NATIONAL)
    except phonenumbers.NumberParseException:
        return profile.phone

def record_failure(profile):
    now = timezone.now()
    if not profile.failure_window_started_at or now - profile.failure_window_started_at >= WINDOW:
        profile.failure_window_started_at = now
        profile.password_failures = 0
    profile.password_failures += 1
    if profile.password_failures >= 5:
        profile.password_locked_until = now + WINDOW
    profile.save(update_fields=['password_failures', 'failure_window_started_at', 'password_locked_until', 'updated_at'])

def reset_failures(profile):
    profile.password_failures = 0
    profile.failure_window_started_at = None
    profile.password_locked_until = None

@login_required(login_url='accounts:login')
@require_http_methods(['GET', 'POST'])
@sensitive_post_parameters('current_password', 'old_password', 'new_password1', 'new_password2')
@sensitive_variables()
def profile(request):
    User = get_user_model()
    user = request.user
    stored = UserProfile.objects.filter(user_id=user.pk).first()
    info = stored or UserProfile(user=user)
    detail_form = password_form = None
    feedback = None
    status = 200
    remaining = None
    completed = None
    if request.method == 'POST':
        try:
            size = int(request.META.get('CONTENT_LENGTH') or 0)
        except (TypeError, ValueError):
            size = 16385
        if size > 16384 or request.FILES:
            feedback = 'حجم الطلب أو محتواه غير مسموح. أعد تحميل الصفحة وحاول مرة أخرى.'
            status = 400
        else:
            action = request.POST.get('action')
            try:
                if action not in {'details', 'password'}:
                    raise signing.BadSignature
                with transaction.atomic():
                    user = User._default_manager.select_for_update().get(pk=request.user.pk)
                    info = UserProfile.objects.select_for_update().filter(user_id=user.pk).first() or UserProfile(user=user)
                    if not user.is_active:
                        raise signing.BadSignature
                    validate_snapshot(request.POST.get('snapshot'), user, info, action)
                    if info.password_locked_until and info.password_locked_until > timezone.now():
                        status = 429
                        feedback = 'تجاوزت الحد المسموح لمحاولات تأكيد كلمة المرور. حاول مجددًا بعد 15 دقيقة.'
                        remaining = max(1, int((info.password_locked_until - timezone.now()).total_seconds()))
                    else:
                        form = ProfileDetailsForm(request.POST, user=user, profile=info) if action == 'details' else ProfilePasswordForm(request.POST, user=user)
                        if action == 'details':
                            detail_form = form
                        else:
                            password_form = form
                        if form.is_valid():
                            if not info.pk:
                                info.save()
                            if action == 'details':
                                for field in ('first_name', 'last_name', 'email'):
                                    setattr(user, field, form.cleaned_data[field])
                                user.save(update_fields=['first_name', 'last_name', 'email'])
                                info.phone = form.cleaned_data['phone']
                                info.phone_country = form.cleaned_data['phone_country']
                                info.email_key = email_key(form.cleaned_data['email'])
                                text = 'تم تحديث بيانات ملفك الشخصي بنجاح.'
                            else:
                                user.set_password(form.cleaned_data['new_password1'])
                                user.save(update_fields=['password'])
                                text = 'تم تغيير كلمة المرور بنجاح. بقيت هذه الجلسة نشطة، وستُسجّل الجلسات الأخرى خروجها عند طلبها التالي.'
                            info.version += 1
                            reset_failures(info)
                            info.save()
                            completed = (action, user, form.sensitive_changed if action == 'details' else False, text)
                        else:
                            status = 400
                            wrong = any((error.code == 'wrong_current_password' for field in ('current_password', 'old_password') for error in form.errors.as_data().get(field, [])))
                            if wrong:
                                if not info.pk:
                                    info.save()
                                record_failure(info)
                                if info.password_locked_until and info.password_locked_until > timezone.now():
                                    status = 429
                                    remaining = 900
                                    feedback = 'تجاوزت الحد المسموح لمحاولات تأكيد كلمة المرور. حاول مجددًا بعد 15 دقيقة.'
                if completed:
                    saved_action, saved_user, sensitive_changed, text = completed
                    if saved_action == 'password':
                        update_session_auth_hash(request, saved_user)
                    elif sensitive_changed:
                        request.session.cycle_key()
                    messages.success(request, text)
                    return add_login_headers(redirect('accounts:profile'))
            except signing.BadSignature:
                feedback = 'انتهت صلاحية النموذج أو تغيّرت بيانات الحساب. أعد تحميل الصفحة قبل الحفظ.'
                status = 409
            except IntegrityError:
                feedback = 'تعذّر الحفظ لأن البريد أصبح غير متاح أو تغيّرت البيانات. لم يُحفظ أي تغيير.'
                status = 409
    if request.method == 'POST':
        user = User._default_manager.get(pk=request.user.pk)
        info = UserProfile.objects.filter(user_id=user.pk).first() or UserProfile(user=user)
    if detail_form is None:
        detail_form = ProfileDetailsForm(user=user, profile=info, initial={'snapshot': snapshot(user, info, 'details'), 'first_name': user.first_name, 'last_name': user.last_name, 'email': user.email, 'phone_country': info.phone_country, 'phone': initial_phone(info)})
    if password_form is None:
        password_form = ProfilePasswordForm(user=user, initial={'snapshot': snapshot(user, info, 'password')})
    for form in (detail_form, password_form):
        if form.is_bound:
            for name in form.errors:
                if name in form.fields:
                    form.fields[name].widget.attrs['aria-invalid'] = 'true'
    name = user.get_short_name() or user.get_username()
    response = render(request, 'accounts/profile/index.html', {'page_heading': 'الملف الشخصي', 'active_page': 'profile', 'display_name': name, 'avatar_initial': name[:1], 'profile_user': user, 'detail_form': detail_form, 'password_form': password_form, 'profile_feedback': feedback, 'profile_locked_until': info.password_locked_until if info.password_locked_until and info.password_locked_until > timezone.now() else None, 'password_minimum': minimum_password_length(), 'country_catalog': [{'id': code, 'dial': '+' + str(phonenumbers.country_code_for_region(code))} for code, _ in COUNTRIES]}, status=status)
    if remaining:
        response['Retry-After'] = str(remaining)
    return add_login_headers(response)
