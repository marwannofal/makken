"""Explicit audit allowlist; never persist request bodies, credentials or URLs.

Values are bounded at ingestion, escaped by templates and export generators.
Historical imports use the same policy. New business fields are opt-in.
"""
from datetime import date, datetime, timedelta, timezone as dt_timezone
from django.db.models import Exists, OuterRef
from .models import ActivityRegion, UserActivity
from .regions import RegionalPolicy

LABELS = {
    'name': 'الاسم', 'title': 'حاجة السوق', 'representative': 'اسم الممثل',
    'is_active': 'حالة السجل', 'scope': 'النطاق', 'financial_capacity': 'القدرة المالية',
    'starts_on': 'تاريخ بداية الشراكة', 'ends_on': 'تاريخ نهاية الشراكة',
    'entity': 'الكيان', 'entity_type': 'نوع الكيان', 'branch': 'فرع الكيان',
    'sector': 'القطاع', 'specialization': 'التخصص', 'regions': 'المناطق',
    'administrative_regions': 'المناطق الإدارية', 'coverage': 'تغطية المزود',
    'offerings': 'أشكال الرعاية والتخصصات', 'specializations': 'التخصصات',
    'sponsorship_shape': 'شكل الرعاية', 'description': 'الوصف', 'color': 'اللون',
    'state': 'حالة التطور', 'development_state': 'حالة التطور',
    'program': 'البرنامج التدريبي', 'program_name': 'اسم البرنامج',
    'category': 'تصنيف البرنامج', 'program_category': 'تصنيف البرنامج',
    'is_training': 'تدريبي', 'is_operational': 'تشغيلي', 'training_type': 'نوع التدريب',
    'provider_type': 'نوع المزود', 'beneficiaries': 'عدد المستفيدين',
    'duration': 'المدة', 'duration_unit': 'وحدة المدة', 'source': 'مصدر الحاجة',
    'observed_on': 'تاريخ الرصد', 'total_cost': 'التكلفة الإجمالية',
    'requested_support': 'الدعم المطلوب', 'approved_support': 'الدعم المعتمد',
    'status': 'الحالة', 'amount': 'المبلغ', 'notes': 'الملاحظات',
    'rejection_reason': 'سبب الرفض', 'percent': 'نسبة الدعم', 'level': 'المستوى',
    'level_name': 'المستوى', 'allocations': 'توزيع الدعم', 'lines': 'بنود الصرف',
    'organization': 'الجهة', 'providers': 'مزودو الخدمات', 'employers': 'جهات التوظيف',
    'completed_at': 'تاريخ اكتمال التنفيذ', 'reason': 'السبب',
    'roles': 'الأدوار', 'pages': 'الصفحات', 'page_scope': 'نطاق الصفحات',
    'region_scope': 'نطاق المناطق', 'allowed_regions': 'المناطق المسموحة',
    'full_name': 'اسم المستخدم', 'username': 'اسم المستخدم',
    'first_name': 'الاسم الأول', 'last_name': 'اسم العائلة',
    'is_superuser': 'مدير نظام أعلى', 'email_changed': 'تغيير البريد الإلكتروني',
    'password_changed': 'تغيير كلمة المرور', 'phone_changed': 'تغيير الهاتف',
    'region_id': 'رقم المنطقة', 'coverage_id': 'رقم التغطية',
    'permissions': 'الصلاحيات', 'direct_permissions': 'الصلاحيات المباشرة',
    'overrides': 'استثناءات الصلاحيات', 'module_id': 'الصفحة', 'operation': 'العملية', 'effect': 'القرار',
    'entered_at': 'تاريخ الدخول إلى الحالة', 'development_state_at': 'تاريخ حالة التطور',
    'is_employment': 'رعاية توظيف', 'expense_items': 'بنود الصرف',
    'agreement_clauses': 'بنود الاتفاقية', 'clause': 'بند الاتفاقية',
    'responsibility': 'المسؤولية', 'progress': 'نسبة الإنجاز', 'agreement_number': 'رقم الاتفاقية',
    'agreement_title': 'عنوان الاتفاقية', 'agreement_signed_on': 'تاريخ توقيع الاتفاقية',
    'agreement_expires_on': 'تاريخ انتهاء الاتفاقية', 'agreement_status': 'حالة الاتفاقية',
    'agreement_responsible': 'الموظف المسؤول عن الاتفاقية', 'agreement_team_count': 'عدد أعضاء فريقي الاتفاقية',
    'attachment_count': 'عدد المرفقات', 'preliminary_agreement_type': 'نوع الاتفاق المبدئي',
}
VALUES = {'capability': 'قدرة', 'willingness': 'رغبة', 'care': 'رعاية',
          'new': 'جديد', 'working': 'جاري العمل', 'complete': 'مكتمل',
          'running': 'تحت التنفيذ', 'approved': 'معتمد', 'rejected': 'مرفوض',
          'local': 'محلي', 'global': 'عالمي', 'government': 'حكومي', 'private': 'أهلي',
          'nongovernment': 'غير حكومي', 'all': 'الكل', 'selected': 'محدد',
          'day': 'يوم', 'month': 'شهر', 'year': 'سنة'}


def clean_text(value, limit=500):
    return ''.join(c for c in str(value) if c >= ' ' or c in '\n\t')[:limit]


def safe_value(value, depth=0):
    if depth > 3:
        return 'تفاصيل إضافية'
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [safe_value(v, depth+1) for v in value[:200]]
    if isinstance(value, dict):
        allowed = set(LABELS) | {'region', 'sector', 'shape', 'specialization', 'specializations', 'expense', 'id'}
        return {str(k): safe_value(v, depth+1) for k, v in value.items() if k in allowed}
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return clean_text(value)


def sanitize(data):
    return {key: safe_value(value) for key, value in data.items() if key in LABELS} if isinstance(data, dict) else {}


def display(value):
    if value is None or value == '':
        return '—'
    if value is True:
        return 'نعم'
    if value is False:
        return 'لا'
    if isinstance(value, list):
        return '، '.join(display(v) for v in value) or '—'
    if isinstance(value, dict):
        return ' · '.join(f'{LABELS.get(k, {"region":"المنطقة", "shape":"شكل الرعاية", "id":"الرقم"}.get(k,k))}: {display(v)}' for k,v in value.items()) or '—'
    from .registry import DEFINITIONS
    from .models import Operation
    if str(value) in DEFINITIONS:
        return DEFINITIONS[str(value)].title
    for module in DEFINITIONS.values():
        for operation in module.operations:
            if str(value) == operation+'_'+module.key:
                return module.title+' / '+dict(Operation.choices).get(operation, operation)
    return VALUES.get(str(value), {'grant':'منح', 'deny':'منع'}.get(str(value), str(value)))


def changes(event):
    before, after = sanitize(event.before), sanitize(event.after)
    return [{'label': LABELS[k], 'before': display(before.get(k)), 'after': display(after.get(k))}
            for k in sorted(before.keys() | after.keys()) if before.get(k) != after.get(k)]


def audit_timezone():
    # Fixed Saudi Arabia UTC+03 avoids MySQL named-timezone-table dependencies.
    # Filters are converted to UTC before querying, rather than using SQL time().
    return dt_timezone(timedelta(hours=3), 'توقيت الرياض UTC+03:00')


def visible_events(user):
    query = UserActivity.objects.all()
    policy = RegionalPolicy(user)
    if not policy.active:
        return query.none()
    if policy.unrestricted:
        return query
    inside = ActivityRegion.objects.filter(event_id=OuterRef('pk'), region_key__in=policy.ids)
    outside = ActivityRegion.objects.filter(event_id=OuterRef('pk')).exclude(region_key__in=policy.ids)
    # An audit may contain values from BEFORE an object moved regions. Require
    # all historical regions, not just overlap with the current object's scope.
    return query.filter(scope='regional').filter(Exists(inside)).filter(~Exists(outside))


def decorate_event(event):
    from .registry import DEFINITIONS
    event.module_title = DEFINITIONS[event.module].title if event.module in DEFINITIONS else {
        'accounts': 'الحساب الشخصي والدخول', 'access_control': 'إدارة الوصول'}.get(event.module, 'النظام')
    event.change_rows = changes(event)
    event.imported_history = bool(event.source_key and event.source_key.startswith('history:') and event.request_id is None)
    event.change_summary = '؛ '.join(f'{r["label"]}: {r["before"]} ← {r["after"]}' for r in event.change_rows) or 'لا توجد قيم معدّلة؛ حدث مشاهدة أو إجراء مسجّل.'
    return event
