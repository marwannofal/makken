"""Explicit account fields; never accept a target user ID or privilege fields."""
import re
import hashlib
import unicodedata
import phonenumbers
from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.contrib.auth.hashers import check_password
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils.translation import override
from django.views.decorators.debug import sensitive_variables
from .models import UserProfile
COUNTRY_CODES = ['SA', 'JO', *sorted(phonenumbers.SUPPORTED_REGIONS - {'SA', 'JO', 'IL'})]
COUNTRIES = [(code, f'{code} +{phonenumbers.country_code_for_region(code)}') for code in COUNTRY_CODES]
_FALLBACK_VALIDATORS = [password_validation.UserAttributeSimilarityValidator(), password_validation.MinimumLengthValidator(12), password_validation.CommonPasswordValidator(), password_validation.NumericPasswordValidator()]

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

def password_widget(autocomplete):
    return forms.PasswordInput(attrs={'autocomplete': autocomplete, 'dir': 'ltr'}, render_value=False)

class ProfileDetailsForm(forms.Form):
    snapshot = forms.CharField(widget=forms.HiddenInput)
    first_name = forms.CharField(label='الاسم الأول', max_length=150, widget=forms.TextInput(attrs={'autocomplete': 'given-name', 'dir': 'auto'}))
    last_name = forms.CharField(label='اسم العائلة', max_length=150, widget=forms.TextInput(attrs={'autocomplete': 'family-name', 'dir': 'auto'}))
    email = forms.EmailField(label='البريد الإلكتروني', max_length=254, error_messages={'invalid': 'أدخل بريدًا إلكترونيًا صحيحًا.'}, widget=forms.EmailInput(attrs={'autocomplete': 'email', 'dir': 'ltr', 'autocapitalize': 'none', 'spellcheck': 'false'}))
    email_confirm = forms.EmailField(label='تأكيد البريد الإلكتروني', required=False, max_length=254, error_messages={'invalid': 'أدخل بريدًا إلكترونيًا صحيحًا.'}, widget=forms.EmailInput(attrs={'autocomplete': 'off', 'dir': 'ltr', 'autocapitalize': 'none', 'spellcheck': 'false', 'placeholder': 'أعد كتابة البريد الجديد عند تغييره'}))
    phone_country = forms.ChoiceField(label='رمز الدولة', choices=COUNTRIES)
    phone = forms.CharField(label='رقم الهاتف', max_length=40, widget=forms.TextInput(attrs={'type': 'tel', 'inputmode': 'tel', 'autocomplete': 'tel-national', 'dir': 'ltr', 'placeholder': '050 123 4567'}))
    current_password = forms.CharField(label='كلمة المرور الحالية', required=False, strip=False, max_length=1024, widget=password_widget('current-password'))

    def __init__(self, *args, user, profile, **kwargs):
        self.user, self.profile, self.sensitive_changed = (user, profile, False)
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.update(id='profile-details-snapshot' if name == 'snapshot' else 'profile-' + name, **{'aria-describedby': 'error-' + name})
            field.error_messages['required'] = 'هذا الحقل مطلوب.'
            field.error_messages['invalid_choice'] = 'اختر دولة متاحة من القائمة.'
            if getattr(field, 'max_length', None):
                field.error_messages['max_length'] = f'الحد الأقصى {field.max_length} حرفًا.'
            if getattr(field, 'max_length', None):
                field.widget.attrs['maxlength'] = field.max_length

    def clean_first_name(self):
        return normalize_name(self.cleaned_data['first_name'])

    def clean_last_name(self):
        return normalize_name(self.cleaned_data['last_name'])

    def clean_email(self):
        email = normalize_email(self.cleaned_data['email'])
        User = get_user_model()
        other = User._default_manager.exclude(pk=self.user.pk)
        if other.filter(Q(email__iexact=email) | Q(**{User.USERNAME_FIELD + '__iexact': email})).exists() or UserProfile.objects.filter(email_key=email_key(email)).exclude(user_id=self.user.pk).exists():
            raise ValidationError('هذا البريد غير متاح. استخدم بريدًا آخر.')
        return email

    @sensitive_variables()
    def clean(self):
        data = super().clean()
        country, raw = (data.get('phone_country'), data.get('phone'))
        if country and raw:
            normalized = ''.join((str(int(c)) if c.isdecimal() else c for c in raw))
            try:
                if not re.fullmatch('[+\\d\\s().-]+', normalized):
                    raise ValueError
                number = phonenumbers.parse(normalized, country)
                if number.extension or not phonenumbers.is_valid_number_for_region(number, country) or phonenumbers.number_type(number) not in {phonenumbers.PhoneNumberType.MOBILE, phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE}:
                    raise ValueError
                data['phone'] = phonenumbers.format_number(number, phonenumbers.PhoneNumberFormat.E164)
            except (ValueError, phonenumbers.NumberParseException):
                self.add_error('phone', 'أدخل رقم هاتف جوال صحيحًا يطابق الدولة المختارة.')
        email = data.get('email')
        email_changed = email is not None and email != normalize_email(self.user.email or '')
        confirmation = data.get('email_confirm', '')
        if email and (email_changed or confirmation) and (normalize_email(confirmation) != email):
            self.add_error('email_confirm', 'أعد إدخال البريد الإلكتروني نفسه لتأكيد تغييره.')
        phone_changed = 'phone' in data and (data['phone'] != self.profile.phone or data.get('phone_country') != self.profile.phone_country)
        self.sensitive_changed = email_changed or phone_changed
        if self.sensitive_changed:
            current = data.get('current_password')
            if not current:
                self.add_error('current_password', ValidationError('أدخل كلمة المرور الحالية لتأكيد تغيير البريد أو رقم الهاتف.', code='required'))
            elif not check_password(current, self.user.password):
                self.add_error('current_password', ValidationError('كلمة المرور الحالية غير صحيحة.', code='wrong_current_password'))
        return data

class ProfilePasswordForm(forms.Form):
    snapshot = forms.CharField(widget=forms.HiddenInput)
    old_password = forms.CharField(label='كلمة المرور الحالية', strip=False, max_length=1024, widget=password_widget('current-password'))
    new_password1 = forms.CharField(label='كلمة المرور الجديدة', strip=False, max_length=128, widget=password_widget('new-password'))
    new_password2 = forms.CharField(label='تأكيد كلمة المرور الجديدة', strip=False, max_length=128, widget=password_widget('new-password'))

    def __init__(self, *args, user, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        for name, field in self.fields.items():
            field.widget.attrs.update(id='profile-password-snapshot' if name == 'snapshot' else 'profile-' + name, **{'aria-describedby': 'password-policy error-' + name})
            field.error_messages.update(required='هذا الحقل مطلوب.', max_length=f"الحد الأقصى {getattr(field, 'max_length', 128)} حرفًا.")
            if getattr(field, 'max_length', None):
                field.widget.attrs['maxlength'] = field.max_length

    @sensitive_variables()
    def clean_old_password(self):
        value = self.cleaned_data['old_password']
        if not check_password(value, self.user.password):
            raise ValidationError('كلمة المرور الحالية غير صحيحة.', code='wrong_current_password')
        return value

    @sensitive_variables()
    def clean(self):
        data = super().clean()
        password = data.get('new_password1')
        confirmation = data.get('new_password2')
        if password and confirmation and (password != confirmation):
            self.add_error('new_password2', 'كلمتا المرور غير متطابقتين.')
        if password:
            issues = []
            for condition, message in [(bool(re.search('[A-Z]', password)), 'أضف حرفًا إنجليزيًا كبيرًا واحدًا على الأقل.'), (bool(re.search('[a-z]', password)), 'أضف حرفًا إنجليزيًا صغيرًا واحدًا على الأقل.'), (bool(re.search('[0-9]', password)), 'أضف رقمًا واحدًا على الأقل.'), (any((not c.isalnum() and (not c.isspace()) and (not unicodedata.category(c).startswith(('C', 'M'))) for c in password)), 'أضف رمزًا خاصًا واحدًا على الأقل مثل ! أو @ أو #.'), (not any((c.isspace() or unicodedata.category(c).startswith('C') for c in password)), 'لا تستخدم مسافات أو محارف تحكم في كلمة المرور.')]:
                if not condition:
                    issues.append(message)
            if check_password(password, self.user.password):
                issues.append('اختر كلمة مرور جديدة تختلف عن الحالية.')
            configured = password_validation.get_default_password_validators()
            validators = [*configured, *[v for v in _FALLBACK_VALIDATORS if not any((type(c) is type(v) and (not isinstance(v, password_validation.MinimumLengthValidator) or c.min_length >= 12) for c in configured))]]
            with override('ar'):
                try:
                    password_validation.validate_password(password, user=self.user, password_validators=validators)
                except ValidationError as exc:
                    issues.extend((str(message) for message in exc.messages))
            if issues:
                self.add_error('new_password1', issues)
        return data
