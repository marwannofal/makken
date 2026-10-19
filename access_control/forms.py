import unicodedata
from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.translation import override
from accounts.profile_forms import ProfilePasswordForm, normalize_name
from .models import Module, RoleProfile, PageScope, Operation
from .registry import DEFINITIONS


class ArabicForm(forms.Form):
    snapshot=forms.CharField(widget=forms.HiddenInput)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        for field in self.fields.values():
            field.error_messages.update(max_length='القيمة أطول من الحد المسموح.', required='هذا الحقل مطلوب.',invalid_choice='اختر قيمة صحيحة من القائمة.',invalid_list='اختر القيم من القائمة.',invalid_pk_value='أحد السجلات المحددة غير متاح.')
            if isinstance(field,forms.EmailField):field.error_messages['invalid']='أدخل بريدًا إلكترونيًا صحيحًا.'
            field.widget.attrs.setdefault('class','ac-control')


class AdminPasswordForm(ProfilePasswordForm):
    def __init__(self,*args,user,**kwargs):
        super().__init__(*args,user=user,**kwargs)
        self.fields.pop('old_password')


class AccessFields(ArabicForm):
    page_scope=forms.ChoiceField(label='نطاق الوصول إلى الصفحات',choices=PageScope.choices,initial=PageScope.SELECTED)
    allowed_pages=forms.ModelMultipleChoiceField(label='الصفحات المسموح بها',queryset=Module.objects.all(),required=False,widget=forms.SelectMultiple(attrs={'data-market-select':'','data-label':'الصفحات المسموح بها'}))

    def clean(self):
        values=super().clean()
        if self.is_bound and any(key in self.data for key in ['is_superuser','is_staff','user_permissions','groups','password','last_login','date_joined','user_id','target_user']):
            raise forms.ValidationError('تضمن الطلب حقولًا غير مسموح بتعديلها.')
        return values


class UserForm(AccessFields):
    full_name=forms.CharField(label='الاسم الكامل',max_length=300)
    username=forms.CharField(label='اسم المستخدم',max_length=150)
    email=forms.EmailField(label='البريد الإلكتروني',max_length=254,widget=forms.EmailInput(attrs={'dir':'ltr','autocomplete':'off'}))
    is_active=forms.ChoiceField(label='حالة الحساب',choices=[('1','نشط'),('0','غير نشط')],initial='1')
    roles=forms.ModelMultipleChoiceField(label='الأدوار',queryset=RoleProfile.objects.select_related('group'),required=False,widget=forms.SelectMultiple(attrs={'data-market-select':'','data-label':'الأدوار'}))
    new_password1=forms.CharField(label='كلمة المرور',strip=False,max_length=128,widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}))
    new_password2=forms.CharField(label='تأكيد كلمة المرور',strip=False,max_length=128,widget=forms.PasswordInput(attrs={'autocomplete':'new-password'}))

    def __init__(self,*args,target=None,**kwargs):
        self.target=target
        super().__init__(*args,**kwargs)
        if target:
            self.fields.pop('new_password1');self.fields.pop('new_password2')
        for module in DEFINITIONS.values():
            for operation in module.operations:
                self.fields[f'override__{module.key}__{operation}']=forms.ChoiceField(label=Operation(operation).label,choices=[('inherit','من الأدوار'),('grant','منح مباشر'),('deny','منع صريح')],initial='inherit',required=False,error_messages={'invalid_choice':'اختر منحًا مباشرًا أو منعًا صريحًا أو الاعتماد على الأدوار.'},widget=forms.Select(attrs={'class':'ac-control ac-override'}))

    def clean_full_name(self):
        value=normalize_name(self.cleaned_data['full_name'])
        names=value.split(' ',1)
        if any(len(part)>150 for part in names):raise forms.ValidationError('الاسم الأول واسم العائلة يجب ألا يتجاوز كل منهما 150 حرفًا.')
        return value

    def clean_username(self):
        value=unicodedata.normalize('NFKC',self.cleaned_data['username']).strip()
        field=get_user_model()._meta.get_field(get_user_model().USERNAME_FIELD)
        with override('ar'):field.run_validators(value)
        if any(unicodedata.category(c).startswith('C') for c in value):raise forms.ValidationError('اسم المستخدم يحتوي محارف غير مسموح بها.')
        return value

    def clean_email(self):
        return self.cleaned_data['email'].strip().casefold()

    def clean(self):
        data=super().clean();User=get_user_model()
        query=User._default_manager.all()
        if self.target:query=query.exclude(pk=self.target.pk)
        for field in ['username','email']:
            value=data.get(field)
            if value and query.filter(Q(**{User.USERNAME_FIELD+'__iexact':value})|Q(**{User.get_email_field_name()+'__iexact':value})).exists():
                self.add_error(field,'اسم المستخدم أو البريد مستخدم بالفعل في حساب آخر.')
        if not self.target and data.get('new_password1'):
            candidate=User(**{User.USERNAME_FIELD:data.get('username',''),User.get_email_field_name():data.get('email','')})
            names=data.get('full_name','').split(' ',1);candidate.first_name=names[0];candidate.last_name=names[1] if len(names)>1 else ''
            check=AdminPasswordForm({'snapshot':'validated','new_password1':data.get('new_password1',''),'new_password2':data.get('new_password2','')},user=candidate)
            if not check.is_valid():
                for name,errors in check.errors.items():
                    if name in self.fields:self.add_error(name,errors)
        return data


class RoleForm(AccessFields):
    name=forms.CharField(label='اسم الدور',max_length=150)
    description=forms.CharField(label='وصف الدور',max_length=500,required=False,widget=forms.Textarea(attrs={'rows':3}))
    permissions=forms.MultipleChoiceField(label='صلاحيات الدور',required=False,widget=forms.CheckboxSelectMultiple)

    def __init__(self,*args,role=None,**kwargs):
        self.role=role;super().__init__(*args,**kwargs)
        self.fields['permissions'].choices=[(m.key+':'+op,m.title+' — '+Operation(op).label) for m in DEFINITIONS.values() for op in m.operations]

    def clean_name(self):
        from django.contrib.auth.models import Group
        value=' '.join(unicodedata.normalize('NFKC',self.cleaned_data['name']).split())
        if not value or any(unicodedata.category(c).startswith('C') or c in '<>' for c in value):raise forms.ValidationError('أدخل اسم دور صحيحًا.')
        query=Group.objects.filter(name__iexact=value)
        if self.role:query=query.exclude(pk=self.role.group_id)
        if query.exists():raise forms.ValidationError('اسم الدور مستخدم بالفعل.')
        return value

    def clean(self):
        data=super().clean();permissions=set(data.get('permissions',[]))
        for key in permissions:
            module,operation=key.split(':')
            if operation!='view' and module+':view' not in permissions:
                self.add_error('permissions','يجب منح العرض للصفحة قبل منح عملياتها الأخرى.');break
        return data
