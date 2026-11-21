"""Arabic, read-only dashboard filters. Date ranges describe a need cohort."""
from datetime import date, datetime, time, timedelta
from django import forms
from django.utils import timezone
from access_control.activity_data import audit_timezone


class DashboardFilterForm(forms.Form):
    regions = forms.TypedMultipleChoiceField(label='المناطق', required=False, coerce=int,
        widget=forms.SelectMultiple(attrs={'data-market-select':''}))
    sector = forms.TypedChoiceField(label='القطاع', required=False, coerce=int,
        widget=forms.Select(attrs={'data-market-select':''}))
    specialization = forms.TypedChoiceField(label='التخصص', required=False, coerce=int,
        widget=forms.Select(attrs={'data-market-select':''}))
    program = forms.TypedChoiceField(label='البرنامج التدريبي', required=False, coerce=int,
        widget=forms.Select(attrs={'data-market-select':''}))
    training_type = forms.ChoiceField(label='نوع التدريب', required=False,
        choices=[('', 'جميع الأنواع'), ('تدريبي','تدريبي'), ('تشغيلي','تشغيلي')])
    activation = forms.ChoiceField(label='حالة البطاقة', required=False,
        choices=[('', 'جميع الحالات'), ('1','نشط'), ('0','غير نشط')])
    period = forms.ChoiceField(label='الفترة الزمنية', required=False, initial='all', choices=[
        ('all','جميع الفترات'), ('month','الشهر الحالي'), ('quarter','الربع الحالي'),
        ('year','السنة الحالية'), ('custom','فترة مخصصة')])
    date_from = forms.DateField(label='من تاريخ', required=False, input_formats=['%d/%m/%Y', '%Y-%m-%d'],
        widget=forms.DateInput(attrs={'type':'date'}))
    date_to = forms.DateField(label='إلى تاريخ', required=False, input_formats=['%d/%m/%Y', '%Y-%m-%d'],
        widget=forms.DateInput(attrs={'type':'date'}))

    def __init__(self, *args, choices, pairs=(), now=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.now = now or timezone.now()
        self.pairs = set(pairs)
        for name in ('regions','sector','specialization','program'):
            self.fields[name].choices = ([] if name=='regions' else [('', 'الكل')]) + list(choices.get(name, []))
        for field in self.fields.values():
            field.error_messages.update(invalid='أدخل قيمة صحيحة.',
                invalid_choice='اختر قيمة من القائمة المسموحة.', required='هذا الحقل مطلوب.')

    def clean(self):
        data = super().clean()
        if data.get('sector') and data.get('specialization') and (data['sector'],data['specialization']) not in self.pairs:
            self.add_error('specialization','اختر تخصصًا مرتبطًا بالقطاع المختار في البطاقات المتاحة.')
        period = data.get('period') or 'all'
        data['period'] = period
        start, end = data.get('date_from'), data.get('date_to')
        today = timezone.localtime(self.now, audit_timezone()).date()
        if period == 'custom':
            if not start:self.add_error('date_from','حدد بداية الفترة المخصصة.')
            if not end:self.add_error('date_to','حدد نهاية الفترة المخصصة.')
        elif start or end:
            self.add_error('period','اختر فترة مخصصة لاستخدام تواريخ البداية والنهاية.')
        elif period == 'month':
            start, end = today.replace(day=1), today
        elif period == 'quarter':
            start, end = today.replace(month=((today.month-1)//3)*3+1, day=1), today
        elif period == 'year':
            start, end = today.replace(month=1, day=1), today
        if start and end and start > end:
            self.add_error('date_to','نهاية الفترة يجب ألا تسبق بدايتها.')
        if end == date.max:
            self.add_error('date_to','اختر تاريخ نهاية أقدم من 9999-12-31.')
            end = None
        data['start'] = datetime.combine(start,time.min,audit_timezone()) if start else None
        data['end'] = datetime.combine(end+timedelta(days=1),time.min,audit_timezone()) if end else None
        return data


def during(query, field, data):
    if data.get('start'):
        query = query.filter(**{field+'__gte':data['start']})
    if data.get('end'):
        query = query.filter(**{field+'__lt':data['end']})
    return query
