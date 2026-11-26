"""Self-service profile & separate change-password pages with avatar upload and signed snapshots."""
from datetime import timedelta
import json
import uuid

import phonenumbers
from django.contrib import messages
from django.contrib.auth import get_user_model, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.http import FileResponse, Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_GET, require_http_methods

from .models import UserProfile
from .profile_forms import (
    COUNTRIES,
    MAX_AVATAR_BYTES,
    ProfileDetailsForm,
    ProfilePasswordForm,
    detect_avatar_mime,
    minimum_password_length,
)
from .security import add_login_headers

SALT = 'makken.self-profile.v2'
WINDOW = timedelta(minutes=15)
_EXT_BY_MIME = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}


def fingerprint(user, profile):
    values = [
        str(user.pk),
        user.first_name,
        user.last_name,
        user.email,
        user.password,
        profile.phone,
        profile.phone_country,
        str(profile.avatar.name if profile.avatar else ''),
        profile.version,
    ]
    return salted_hmac(SALT, json.dumps(values, ensure_ascii=False), algorithm='sha256').hexdigest()


def snapshot(user, profile, action):
    return signing.dumps({'user': str(user.pk), 'action': action, 'state': fingerprint(user, profile)}, salt=SALT, compress=True)


def validate_snapshot(token, user, profile, action):
    if not isinstance(token, str) or len(token) > 2000:
        raise signing.BadSignature
    data = signing.loads(token, salt=SALT, max_age=20 * 60)
    if (
        not isinstance(data, dict)
        or data.get('user') != str(user.pk)
        or data.get('action') != action
        or not constant_time_compare(data.get('state', ''), fingerprint(user, profile))
    ):
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
@require_GET
def profile_avatar(request):
    info = UserProfile.objects.filter(user_id=request.user.pk).only('avatar').first()
    if not info or not info.avatar:
        raise Http404('لا توجد صورة شخصية.')
    try:
        fh = info.avatar.open('rb')
        header = fh.read(16)
        fh.seek(0)
    except OSError as exc:
        raise Http404('تعذّر قراءة الصورة.') from exc
    mime = detect_avatar_mime(header) or 'application/octet-stream'
    response = FileResponse(fh, content_type=mime)
    response['X-Content-Type-Options'] = 'nosniff'
    response['Cache-Control'] = 'private, max-age=300'
    return response


@login_required(login_url='accounts:login')
@require_http_methods(['GET', 'POST'])
def profile(request):
    """Profile details & photo upload page (username & email are read-only; no password confirmation needed)."""
    User = get_user_model()
    user = request.user
    stored = UserProfile.objects.filter(user_id=user.pk).first()
    info = stored or UserProfile(user=user)
    detail_form = None
    feedback = None
    status = 200

    if request.method == 'POST':
        try:
            size = int(request.META.get('CONTENT_LENGTH') or 0)
        except (TypeError, ValueError):
            size = MAX_AVATAR_BYTES + 100_000
        if size > MAX_AVATAR_BYTES + 65_536:
            feedback = 'حجم الطلب أو الصورة يتجاوز الحد المسموح (5 ميجابايت).'
            status = 400
        else:
            try:
                with transaction.atomic():
                    user = User._default_manager.select_for_update().get(pk=request.user.pk)
                    info = UserProfile.objects.select_for_update().filter(user_id=user.pk).first() or UserProfile(user=user)
                    if not user.is_active:
                        raise signing.BadSignature
                    validate_snapshot(request.POST.get('snapshot'), user, info, 'details')
                    form = ProfileDetailsForm(request.POST, request.FILES, user=user, profile=info)
                    detail_form = form
                    if form.is_valid():
                        if not info.pk:
                            info.save()
                        user.first_name = form.cleaned_data['first_name']
                        user.last_name = form.cleaned_data['last_name']
                        user.save(update_fields=['first_name', 'last_name'])

                        info.phone = form.cleaned_data['phone']
                        info.phone_country = form.cleaned_data['phone_country']

                        upload = form.cleaned_data.get('avatar')
                        remove_avatar = form.cleaned_data.get('remove_avatar')
                        if upload:
                            old_name = info.avatar.name if info.avatar else ''
                            ext = _EXT_BY_MIME.get(getattr(upload, '_detected_mime', ''), '.png')
                            new_name = f'user_{user.pk}_{uuid.uuid4().hex[:12]}{ext}'
                            info.avatar.save(new_name, ContentFile(upload.read()), save=False)
                            if old_name and old_name != info.avatar.name:
                                try:
                                    info.avatar.storage.delete(old_name)
                                except OSError:
                                    pass
                        elif remove_avatar and info.avatar:
                            old_name = info.avatar.name
                            info.avatar = ''
                            try:
                                info.avatar.storage.delete(old_name)
                            except OSError:
                                pass

                        info.version += 1
                        info.save()
                        messages.success(request, 'تم تحديث بيانات ملفك الشخصي بنجاح.')
                        return add_login_headers(redirect('accounts:profile'))
                    else:
                        status = 400
            except signing.BadSignature:
                feedback = 'انتهت صلاحية النموذج أو تغيّرت بيانات الحساب. أعد تحميل الصفحة قبل الحفظ.'
                status = 409
            except IntegrityError:
                feedback = 'تعذّر حفظ التغييرات. حاول مرة أخرى.'
                status = 409

    if request.method == 'POST':
        user = User._default_manager.get(pk=request.user.pk)
        info = UserProfile.objects.filter(user_id=user.pk).first() or UserProfile(user=user)
    if detail_form is None:
        detail_form = ProfileDetailsForm(
            user=user,
            profile=info,
            initial={
                'snapshot': snapshot(user, info, 'details'),
                'first_name': user.first_name,
                'last_name': user.last_name,
                'phone_country': info.phone_country,
                'phone': initial_phone(info),
            },
        )
    if detail_form.is_bound:
        for fname in detail_form.errors:
            if fname in detail_form.fields:
                detail_form.fields[fname].widget.attrs['aria-invalid'] = 'true'

    name = user.get_short_name() or user.get_username()
    return add_login_headers(render(
        request,
        'accounts/profile/index.html',
        {
            'page_heading': 'الملف الشخصي',
            'active_page': 'profile',
            'display_name': name,
            'avatar_initial': name[:1],
            'profile_user': user,
            'profile_info': info,
            'detail_form': detail_form,
            'profile_feedback': feedback,
            'must_change_password': bool(info.must_change_password),
            'country_catalog': [{'id': code, 'dial': '+' + str(phonenumbers.country_code_for_region(code))} for code, _ in COUNTRIES],
        },
        status=status,
    ))


@login_required(login_url='accounts:login')
@require_http_methods(['GET', 'POST'])
@sensitive_post_parameters('old_password', 'new_password1', 'new_password2')
@sensitive_variables()
def profile_password(request):
    """Dedicated Change Password page."""
    User = get_user_model()
    user = request.user
    stored = UserProfile.objects.filter(user_id=user.pk).first()
    info = stored or UserProfile(user=user)
    password_form = None
    feedback = None
    status = 200
    remaining = None

    if request.method == 'POST':
        try:
            size = int(request.META.get('CONTENT_LENGTH') or 0)
        except (TypeError, ValueError):
            size = 16385
        if size > 16384 or request.FILES:
            feedback = 'حجم الطلب أو محتواه غير مسموح. أعد تحميل الصفحة وحاول مرة أخرى.'
            status = 400
        else:
            try:
                completed_user = None
                with transaction.atomic():
                    user = User._default_manager.select_for_update().get(pk=request.user.pk)
                    info = UserProfile.objects.select_for_update().filter(user_id=user.pk).first() or UserProfile(user=user)
                    if not user.is_active:
                        raise signing.BadSignature
                    validate_snapshot(request.POST.get('snapshot'), user, info, 'password')
                    if info.password_locked_until and info.password_locked_until > timezone.now():
                        status = 429
                        feedback = 'تجاوزت الحد المسموح لمحاولات تأكيد كلمة المرور. حاول مجددًا بعد 15 دقيقة.'
                        remaining = max(1, int((info.password_locked_until - timezone.now()).total_seconds()))
                    else:
                        form = ProfilePasswordForm(request.POST, user=user)
                        password_form = form
                        if form.is_valid():
                            if not info.pk:
                                info.save()
                            user.set_password(form.cleaned_data['new_password1'])
                            user.save(update_fields=['password'])
                            info.must_change_password = False
                            info.version += 1
                            reset_failures(info)
                            info.save()
                            completed_user = user
                        else:
                            status = 400
                            wrong = any(
                                error.code == 'wrong_current_password'
                                for error in form.errors.as_data().get('old_password', [])
                            )
                            if wrong:
                                if not info.pk:
                                    info.save()
                                record_failure(info)
                                if info.password_locked_until and info.password_locked_until > timezone.now():
                                    status = 429
                                    remaining = 900
                                    feedback = 'تجاوزت الحد المسموح لمحاولات تأكيد كلمة المرور. حاول مجددًا بعد 15 دقيقة.'
                if completed_user:
                    update_session_auth_hash(request, completed_user)
                    messages.success(request, 'تم تغيير كلمة المرور بنجاح. بقيت هذه الجلسة نشطة، وستُسجّل الجلسات الأخرى خروجها عند طلبها التالي.')
                    return add_login_headers(redirect('accounts:profile_password'))
            except signing.BadSignature:
                feedback = 'انتهت صلاحية النموذج أو تغيّرت بيانات الحساب. أعد تحميل الصفحة قبل الحفظ.'
                status = 409

    if request.method == 'POST':
        user = User._default_manager.get(pk=request.user.pk)
        info = UserProfile.objects.filter(user_id=user.pk).first() or UserProfile(user=user)
    if password_form is None:
        password_form = ProfilePasswordForm(user=user, initial={'snapshot': snapshot(user, info, 'password')})
    if password_form.is_bound:
        for fname in password_form.errors:
            if fname in password_form.fields:
                password_form.fields[fname].widget.attrs['aria-invalid'] = 'true'

    name = user.get_short_name() or user.get_username()
    response = render(
        request,
        'accounts/profile/password.html',
        {
            'page_heading': 'تغيير كلمة المرور',
            'active_page': 'profile_password',
            'display_name': name,
            'avatar_initial': name[:1],
            'profile_user': user,
            'profile_info': info,
            'password_form': password_form,
            'profile_feedback': feedback,
            'must_change_password': bool(info.must_change_password),
            'profile_locked_until': info.password_locked_until if info.password_locked_until and info.password_locked_until > timezone.now() else None,
            'password_minimum': minimum_password_length(),
        },
        status=status,
    )
    if remaining:
        response['Retry-After'] = str(remaining)
    return add_login_headers(response)
