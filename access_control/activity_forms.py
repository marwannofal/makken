from datetime import datetime, time, timedelta
from django import forms
from .models import ActivityAction
from .activity_data import audit_timezone
from .registry import DEFINITIONS


class ActivityFilterForm(forms.Form):
    q = forms.CharField(label='البحث في السجل', required=False, max_length=200,
                        widget=forms.TextInput(attrs={'type':'search', 'placeholder':'المستخدم، الصفحة، السجل، العملية…'}))
    actor = forms.TypedChoiceField(label='المستخدم المنفذ', required=False, coerce=int,
                                  widget=forms.Select(attrs={'data-market-select':''}))
    region = forms.TypedChoiceField(label='المنطقة', required=False, coerce=int,
                                   widget=forms.Select(attrs={'data-market-select':''}))
    module = forms.ChoiceField(label='الصفحة / القسم', required=False,
                              widget=forms.Select(attrs={'data-market-select':''}))
    action = forms.ChoiceField(label='العملية', required=False, choices=[('', 'جميع العمليات'), *ActivityAction.choices])
    outcome = forms.ChoiceField(label='النتيجة', required=False,
                               choices=[('', 'جميع النتائج'), ('success','ناجحة'), ('denied','مرفوضة')])
    date_from = forms.DateField(label='من تاريخ', required=False, input_formats=['%Y-%m-%d'],
                                widget=forms.DateInput(attrs={'type':'date'}))
    time_from = forms.TimeField(label='من الساعة', required=False, input_formats=['%H:%M','%H:%M:%S'],
                                widget=forms.TimeInput(attrs={'type':'time', 'step':'1'}))
    date_to = forms.DateField(label='إلى تاريخ', required=False, input_formats=['%Y-%m-%d'],
                              widget=forms.DateInput(attrs={'type':'date'}))
    time_to = forms.TimeField(label='إلى الساعة', required=False, input_formats=['%H:%M','%H:%M:%S'],
                              widget=forms.TimeInput(attrs={'type':'time', 'step':'1'}))

    def __init__(self, *args, actors=(), regions=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['actor'].choices = [('', 'جميع المستخدمين'), *actors]
        self.fields['region'].choices = [('', 'جميع المناطق المسموحة'), *regions]
        self.fields['module'].choices = [('', 'جميع الأقسام'),
            *[(k,v.title) for k,v in DEFINITIONS.items()], ('accounts','الحساب الشخصي والدخول'),
            ('access_control','إدارة الوصول')]
        for field in self.fields.values():
            field.error_messages.update(required='هذا الحقل مطلوب.', invalid='أدخل قيمة صحيحة لهذا الحقل.',
                                        invalid_choice='اختر قيمة من القائمة المسموحة.',
                                        max_length='أدخل نصًا لا يتجاوز %(limit_value)s حرفًا.')

    def clean(self):
        data = super().clean()
        tz = audit_timezone()
        for suffix in ['from','to']:
            d, t = data.get('date_'+suffix), data.get('time_'+suffix)
            if t is not None and d is None:
                self.add_error('date_'+suffix, 'حدد التاريخ مع الساعة لتعيين بداية أو نهاية الفترة.')
            if d:
                bound = datetime.combine(d, t or time.min, tzinfo=tz)
                if suffix == 'to':
                    bound += timedelta(seconds=1) if t else timedelta(days=1)
                data['bound_'+suffix] = bound
        if data.get('bound_from') and data.get('bound_to') and data['bound_from'] >= data['bound_to']:
            self.add_error('date_to', 'يجب أن تكون نهاية الفترة بعد بدايتها.')
        return data
