"""Explicit account fields; username & email are read-only and never editable via self-service POST."""
import hashlib
import re
import unicodedata

import phonenumbers
from django import forms
from django.contrib.auth import password_validation
from django.contrib.auth.hashers import check_password
from django.core.exceptions import ValidationError
from django.utils.translation import override
from django.views.decorators.debug import sensitive_variables

COUNTRY_CODES = ['SA', 'JO', *sorted(phonenumbers.SUPPORTED_REGIONS - {'SA', 'JO', 'IL'})]
COUNTRIES = [(code, f'{code} +{phonenumbers.country_code_for_region(code)}') for code in COUNTRY_CODES]
_FALLBACK_VALIDATORS = [
    password_validation.UserAttributeSimilarityValidator(),
    password_validation.MinimumLengthValidator(12),
    password_validation.CommonPasswordValidator(),
    password_validation.NumericPasswordValidator(),
]
MAX_AVATAR_BYTES = 5 * 1024 * 1024


def minimum_password_length():
    return max([12, *[v.min_length for v in password_validation.get_default_password_validators() if isinstance(v, password_validation.MinimumLengthValidator)]])


def normalize_email(value):
    return value.strip().casefold()


def email_key(value):
    return hashlib.sha256(normalize_email(value).encode('utf-8')).hexdigest() if value else None


def normalize_name(value):
    value = ' '.join(unicodedata.normalize('NFKC', value).split())
    if not value or any((not (c.isalpha() or unicodedata.category(c).startswith('M') or c in " -.'’") for c in value)):
        raise ValidationError('استخدم حروف الاسم والمسافات والشرطة أو الفاصلة العليا فقط.')
    return value


def detect_avatar_mime(header: bytes) -> str:
    if header.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'image/png'
    if header.startswith(b'\xff\xd8\xff'):
        return 'image/jpeg'
    if len(header) >= 12 and header[:4] == b'RIFF' and header[8:12] == b'WEBP':
        return 'image/webp'
    return ''


def password_widget(autocomplete):
    return forms.PasswordInput(attrs={'autocomplete': autocomplete, 'dir': 'ltr'}, render_value=False)


class ProfileDetailsForm(forms.Form):
    snapshot = forms.CharField(widget=forms.HiddenInput)
    first_name = forms.CharField(label='الاسم الأول', max_length=150, widget=forms.TextInput(attrs={'autocomplete': 'given-name', 'dir': 'auto'}))
    last_name = forms.CharField(label='اسم العائلة', max_length=150, widget=forms.TextInput(attrs={'autocomplete': 'family-name', 'dir': 'auto'}))
    phone_country = forms.ChoiceField(label='رمز الدولة', choices=COUNTRIES)
    phone = forms.CharField(label='رقم الهاتف', max_length=40, required=False, widget=forms.TextInput(attrs={'type': 'tel', 'inputmode': 'tel', 'autocomplete': 'tel-national', 'dir': 'ltr', 'placeholder': '050 123 4567'}))
    avatar = forms.FileField(
        label='الصورة الشخصية',
        required=False,
        widget=forms.ClearableFileInput(attrs={'accept': 'image/png,image/jpeg,image/webp'}),
    )
    remove_avatar = forms.BooleanField(label='حذف الصورة الشخصية الحالية', required=False)

    def __init__(self, *args, user, profile, **kwargs):
        self.user = user
        self.profile = profile
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if field.required:
                field.error_messages['required'] = 'هذا الحقل مطلوب.'
            if isinstance(field, forms.ChoiceField):
                field.error_messages['invalid_choice'] = 'اختر دولة متاحة من القائمة.'
            if getattr(field, 'max_length', None):
                field.error_messages['max_length'] = f'الحد الأقصى {field.max_length} حرفًا.'

    def clean_first_name(self):
        return normalize_name(self.cleaned_data['first_name'])

    def clean_last_name(self):
        return normalize_name(self.cleaned_data['last_name'])

    def clean_avatar(self):
        upload = self.cleaned_data.get('avatar')
        if not upload:
            return None
        if upload.size > MAX_AVATAR_BYTES:
            raise ValidationError('حجم الصورة يجب ألا يتجاوز 5 ميجابايت.')
        pos = upload.tell() if hasattr(upload, 'tell') else 0
        header = upload.read(16)
        if hasattr(upload, 'seek'):
            upload.seek(pos)
        mime = detect_avatar_mime(header)
        if not mime:
            raise ValidationError('يرجى رفع صورة صالحة بصيغة PNG أو JPG أو WEBP.')
        upload._detected_mime = mime
        return upload

    def clean(self):
        cleaned = super().clean()
        country = cleaned.get('phone_country') or 'SA'
        raw_phone = (cleaned.get('phone') or '').strip()
        if raw_phone:
            digits = unicodedata.normalize('NFKC', raw_phone)
            try:
                parsed = phonenumbers.parse(digits, country)
            except phonenumbers.NumberParseException:
                self.add_error('phone', 'أدخل رقم هاتف جوال صحيحًا يطابق الدولة المختارة.')
            else:
                if not phonenumbers.is_valid_number_for_region(parsed, country):
                    self.add_error('phone', 'أدخل رقم هاتف جوال صحيحًا يطابق الدولة المختارة.')
                else:
                    cleaned['phone'] = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        else:
            cleaned['phone'] = ''
        return cleaned


class ProfilePasswordForm(forms.Form):
    snapshot = forms.CharField(widget=forms.HiddenInput)
    old_password = forms.CharField(label='كلمة المرور الحالية', strip=False, max_length=1024, widget=password_widget('current-password'))
    new_password1 = forms.CharField(label='كلمة المرور الجديدة', strip=False, max_length=128, widget=password_widget('new-password'))
    new_password2 = forms.CharField(label='تأكيد كلمة المرور الجديدة', strip=False, max_length=128, widget=password_widget('new-password'))

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.error_messages.update(
                required='هذا الحقل مطلوب.',
                max_length=f"الحد الأقصى {getattr(field, 'max_length', 128)} حرفًا.",
            )

    @sensitive_variables('password')
    def clean_old_password(self):
        password = self.cleaned_data.get('old_password', '')
        if not check_password(password, self.user.password):
            raise ValidationError('كلمة المرور الحالية غير صحيحة.', code='wrong_current_password')
        return password

    @sensitive_variables('password', 'confirm')
    def clean(self):
        cleaned = super().clean()
        password = cleaned.get('new_password1')
        confirm = cleaned.get('new_password2')
        if password and confirm and password != confirm:
            self.add_error('new_password2', 'كلمتا المرور غير متطابقتين.')
        if password:
            issues = []
            if len(password) < minimum_password_length():
                issues.append(f'يجب أن تتكون كلمة المرور من {minimum_password_length()} حرفًا على الأقل.')
            for condition, message in [
                (bool(re.search('[A-Z]', password)), 'أضف حرفًا إنجليزيًا كبيرًا واحدًا على الأقل.'),
                (bool(re.search('[a-z]', password)), 'أضف حرفًا إنجليزيًا صغيرًا واحدًا على الأقل.'),
                (bool(re.search('[0-9]', password)), 'أضف رقمًا واحدًا على الأقل.'),
                (any((not c.isalnum() and not c.isspace() and not unicodedata.category(c).startswith(('C', 'M')) for c in password)), 'أضف رمزًا خاصًا واحدًا على الأقل مثل ! أو @ أو #.'),
                (not any((c.isspace() or unicodedata.category(c).startswith('C') for c in password)), 'لا تستخدم مسافات أو محارف تحكم في كلمة المرور.'),
            ]:
                if not condition:
                    issues.append(message)
            if check_password(password, self.user.password):
                issues.append('اختر كلمة مرور جديدة تختلف عن الحالية.')
            validators = password_validation.get_default_password_validators() or _FALLBACK_VALIDATORS
            with override('ar'):
                try:
                    password_validation.validate_password(password, self.user, password_validators=validators)
                except ValidationError as exc:
                    for msg in exc.messages:
                        if msg not in issues:
                            issues.append(msg)
            for issue in issues:
                self.add_error('new_password1', issue)
        return cleaned
