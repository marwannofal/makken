import re
from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from .models import WorkStatus
from .registry import CATALOG
from .smtp import clean_host
from .targets import WORK_TARGETS, can_read_record, record

User = get_user_model()
SELECT = {'data-market-select': ''}
NUMBER = {'min': 0, 'max': 100, 'inputmode': 'numeric'}
USER_FIELD = User.USERNAME_FIELD


def active_users():
    return User.objects.filter(is_active=True).order_by('first_name', 'last_name', USER_FIELD)


class PersonField(forms.ModelChoiceField):
    def label_from_instance(self, user):
        name = user.get_full_name() or user.get_username()
        return f'{name} · {user.get_username()}' if name != user.get_username() else name


class PeopleField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, user):
        return PersonField.label_from_instance(self, user)


class ArabicForm(forms.Form):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.error_messages.update(required='هذا الحقل مطلوب.', invalid='أدخل قيمة صحيحة.',
                                        invalid_choice='الاختيار غير متاح.', max_length='القيمة أطول من الحد المسموح.')
            if isinstance(field, forms.DateField):
                field.error_messages['invalid'] = 'أدخل تاريخًا صالحًا.'


class SMTPForm(ArabicForm):
    revision = forms.IntegerField(widget=forms.HiddenInput(), min_value=1)
    host = forms.CharField(label='خادم SMTP', max_length=253, required=False, widget=forms.TextInput(attrs={'dir': 'ltr', 'placeholder': 'smtp.example.com'}))
    port = forms.TypedChoiceField(label='المنفذ', coerce=int, choices=[(587, '587'), (465, '465'), (2525, '2525'), (25, '25')])
    security = forms.ChoiceField(label='تشفير الاتصال', choices=[('starttls', 'STARTTLS'), ('tls', 'TLS المباشر')])
    username = forms.CharField(label='اسم مستخدم SMTP', max_length=254, required=False, widget=forms.TextInput(attrs={'dir': 'ltr', 'autocomplete': 'off'}))
    password = forms.CharField(label='كلمة مرور SMTP', max_length=1024, required=False, strip=False,
                               widget=forms.PasswordInput(attrs={'dir': 'ltr', 'autocomplete': 'new-password'}),
                               help_text='اتركها فارغة للاحتفاظ بكلمة المرور المحفوظة.')
    clear_password = forms.BooleanField(label='حذف كلمة المرور المحفوظة', required=False)
    sender = forms.EmailField(label='عنوان المرسل', max_length=254, required=False, widget=forms.EmailInput(attrs={'dir': 'ltr'}))
    sender_name = forms.CharField(label='اسم المرسل', max_length=100)
    enabled = forms.BooleanField(label='تشغيل إرسال الإشعارات', required=False)

    def __init__(self, *args, config, **kwargs):
        self.config = config
        super().__init__(*args, **kwargs)

    def clean_host(self):
        v = self.cleaned_data['host']
        return clean_host(v) if v else ''

    def clean(self):
        data = super().clean()
        for field in ('username', 'sender_name', 'password'):
            if re.search(r'[\x00-\x1f\x7f]', data.get(field, '')):
                self.add_error(field, 'القيمة تحتوي على أحرف غير مسموحة.')
        if data.get('clear_password') and data.get('password'):
            self.add_error('password', 'اختر حفظ كلمة مرور أو حذفها فقط.')
        if data.get('enabled'):
            if not data.get('host'):
                self.add_error('host', 'أدخل خادم البريد قبل تفعيل الإرسال.')
            if not data.get('sender'):
                self.add_error('sender', 'أدخل عنوان المرسل قبل تفعيل الإرسال.')
            if data.get('username') and not (data.get('password') or (self.config.secret and not data.get('clear_password'))):
                self.add_error('password', 'المصادقة تتطلب كلمة مرور.')
        if data.get('port') == 465 and data.get('security') != 'tls':
            self.add_error('security', 'اختر TLS المباشر للمنفذ 465.')
        return data


class TestEmailForm(ArabicForm):
    recipient = forms.EmailField(label='البريد الإلكتروني للتجربة', max_length=254,
                                 widget=forms.EmailInput(attrs={'dir': 'ltr', 'autocomplete': 'off'}))


class RuleForm(ArabicForm):
    revision = forms.IntegerField(widget=forms.HiddenInput(), min_value=1)
    enabled = forms.BooleanField(label='تفعيل هذا النوع', required=False)
    to_actor = forms.BooleanField(label='منفّذ الإجراء', required=False)
    to_subject = forms.BooleanField(label='صاحب الحساب المتأثر', required=False)
    to_employee = forms.BooleanField(label='الموظف المسند إليه العمل', required=False)
    to_manager = forms.BooleanField(label='مدير العمل', required=False)
    recipients = PeopleField(label='مستلمون إضافيون', queryset=User.objects.none(), required=False,
                             widget=forms.SelectMultiple(attrs={**SELECT, 'data-label': 'اختر المستخدمين'}))

    def __init__(self, *args, rule, **kwargs):
        super().__init__(*args, **kwargs)
        event_type = CATALOG[rule.code]
        if event_type.assignment_only:
            del self.fields['to_actor'], self.fields['recipients']
        else:
            self.fields['recipients'].queryset = User.objects.filter(
                Q(is_active=True) | Q(makken_email_rules=rule)
            ).distinct().order_by('first_name', 'last_name', USER_FIELD)
        if not event_type.work:
            del self.fields['to_employee'], self.fields['to_manager']
        if rule.code not in {'account.created', 'account.edited', 'account.status', 'account.password', 'account.deleted'}:
            del self.fields['to_subject']


class UserPreferenceForm(ArabicForm):
    selected = forms.MultipleChoiceField(label='أنواع يستقبلها المستخدم', required=False, widget=forms.SelectMultiple(
        attrs={**SELECT, 'data-label': 'اختر أنواع الإشعارات'}))
    muted = forms.MultipleChoiceField(label='أنواع لا يستقبلها المستخدم', required=False, widget=forms.MultipleHiddenInput())
    fingerprint = forms.CharField(widget=forms.HiddenInput(), max_length=64)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [(code, entry.label) for code, entry in CATALOG.items()]
        self.fields['selected'].choices = [(code, label) for code, label in choices if not CATALOG[code].assignment_only]
        self.fields['muted'].choices = choices

    def clean(self):
        clean = super().clean()
        if set(clean.get('selected', [])) & set(clean.get('muted', [])):
            self.add_error('muted', 'لا يمكن اختيار النوع نفسه للاستقبال والكتم معًا.')
        return clean


class WorkForm(ArabicForm):
    revision = forms.IntegerField(widget=forms.HiddenInput(), required=False, min_value=1)
    title = forms.CharField(label='عنوان العمل', max_length=160)
    instructions = forms.CharField(label='تفاصيل العمل', max_length=3000, required=False, widget=forms.Textarea(attrs={'rows': 4}))
    assignees = PeopleField(
        label='الموظفون المسند إليهم',
        queryset=User.objects.none(),
        required=False,
        widget=forms.SelectMultiple(attrs={**SELECT, 'data-label': 'الموظفون المسند إليهم'}),
        help_text='يمكنك إسناد العمل لموظف واحد أو عدة موظفين.',
    )
    employee = PersonField(label='الموظف المسؤول', queryset=User.objects.none(), required=False, widget=forms.HiddenInput())
    manager = PersonField(label='مدير العمل', queryset=User.objects.none(), widget=forms.Select(attrs=SELECT))
    due_on = forms.DateField(label='تاريخ الاستحقاق', required=False, widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    target_model = forms.ChoiceField(label='ارتباط العمل', choices=[('', 'مهمة مستقلة'), *((k, v.label) for k, v in WORK_TARGETS.items())],
                                     required=False, widget=forms.Select(attrs={'data-target-kind': ''}))
    target_key = forms.IntegerField(label='رقم السجل المرتبط', min_value=1, max_value=2**63-1, required=False,
                                   widget=forms.NumberInput(attrs={'data-target-key': '', 'inputmode': 'numeric'}),
                                   help_text='اكتب الرقم أو ابحث عن السجل أدناه. اتركه فارغًا للمهمة المستقلة.')

    def __init__(self, *args, actor=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.actor = actor
        users = active_users()
        if actor and not actor.is_superuser:
            from django.db.models import Q
            from access_control.models import RegionScope
            from access_control.policy import AccessPolicy
            from access_control.regions import RegionalPolicy
            reg = RegionalPolicy(actor)
            if not reg.unrestricted:
                users = users.filter(
                    Q(is_superuser=True)
                    | Q(makken_access__region_scope=RegionScope.ALL)
                    | Q(makken_access__allowed_regions__in=reg.ids)
                ).distinct()
            policy = AccessPolicy(actor)
            self.fields['target_model'].choices = [
                ('', 'مهمة مستقلة'),
                *((k, v.label) for k, v in WORK_TARGETS.items() if policy.can(v.module)),
            ]
        self.fields['assignees'].queryset = users
        self.fields['employee'].queryset = users
        self.fields['manager'].queryset = users

    def clean(self):
        data = super().clean()
        selected = list(data.get('assignees') or [])
        legacy_emp = data.get('employee')
        if not selected and legacy_emp:
            selected = [legacy_emp]
        if not selected:
            self.add_error('assignees', 'اختر موظفًا واحدًا على الأقل لإسناد العمل.')
        else:
            data['assignees'] = selected
            data['employee'] = selected[0]

        manager = data.get('manager')
        if manager and any(person.pk == manager.pk for person in selected):
            self.add_error('manager', 'اختر مديرًا مختلفًا عن الموظفين المسند إليهم.')

        model, pk = data.get('target_model'), data.get('target_key')
        if bool(model) != bool(pk):
            self.add_error('target_key', 'اختر نوع السجل ورقمه معًا أو اتركهما للمهمة المستقلة.')
        elif model:
            item = record(model, pk)
            if item is None:
                self.add_error('target_key', 'السجل غير متاح.')
            else:
                if self.actor and not self.actor.is_superuser and not can_read_record(self.actor, item):
                    self.add_error('target_key', 'السجل خارج نطاق صلاحياتك أو مناطقك.')
                for person in selected:
                    if not can_read_record(person, item):
                        self.add_error('assignees', 'أحد الموظفين المختارين لا يملك صلاحية عرض السجل المرتبط ونطاقه.')
                        break
                if manager and not can_read_record(manager, item):
                    self.add_error('manager', 'مدير العمل لا يملك صلاحية عرض السجل المرتبط ونطاقه.')
        return data

class ProgressForm(ArabicForm):
    revision = forms.IntegerField(widget=forms.HiddenInput(), min_value=1)
    status = forms.ChoiceField(label='حالة العمل', choices=WorkStatus.choices)
    progress = forms.IntegerField(label='الإنجاز (%)', min_value=0, max_value=100, widget=forms.NumberInput(attrs=NUMBER))
    note = forms.CharField(label='ملاحظة المتابعة', max_length=1000, required=False, widget=forms.Textarea(attrs={'rows': 3}))

    def __init__(self, *args, administrator=False, **kwargs):
        super().__init__(*args, **kwargs)
        if not administrator:
            self.fields['status'].choices = [c for c in WorkStatus.choices if c[0] != 'cancelled']

    def clean(self):
        data = super().clean()
        if 'progress' in data and 'status' in data and (data['progress'] == 100) != (data['status'] == 'complete'):
            self.add_error('progress', 'الإنجاز 100% للحالة المكتملة فقط، ومنها لا بد أن يكون 100%.')
        return data
