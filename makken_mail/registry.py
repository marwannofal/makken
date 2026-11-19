"""Only application-owned event codes can dispatch an email."""
from dataclasses import dataclass
from access_control.registry import DEFINITIONS


@dataclass(frozen=True)
class EventType:
    label: str
    category: str
    # A recipient at the time the event occurred; these are not permissions.
    defaults: tuple = ()
    work: bool = False
    assignment_only: bool = False

PARTNERSHIP_EXPIRY = 'partnerships.expiry_reminder'


ACCOUNT_EVENTS = {
    'account.login': EventType('تسجيل دخول ناجح', 'الحسابات', ('actor',)),
    'account.logout': EventType('تسجيل خروج', 'الحسابات'),
    'account.created': EventType('إنشاء حساب مستخدم', 'الحسابات', ('actor', 'subject')),
    'account.edited': EventType('تعديل حساب مستخدم أو صلاحياته', 'الحسابات', ('actor', 'subject')),
    'account.status': EventType('تغيير حالة حساب مستخدم', 'الحسابات', ('actor', 'subject')),
    'account.password': EventType('تغيير أو إعادة ضبط كلمة المرور', 'الحسابات', ('actor', 'subject')),
    'account.profile': EventType('تحديث الملف الشخصي', 'الحسابات', ('actor',)),
    'account.deleted': EventType('حذف حساب مستخدم', 'الحسابات', ('actor',)),
    'account.regions_assigned': EventType('تعيين أو تحديث نطاق المناطق للموظف', 'الحسابات', ('subject',)),
}
WORK_EVENTS = {
    'work.created': EventType('إسناد عمل جديد', 'إسناد الأعمال', ('employee', 'manager'), True),
    'work.reassigned': EventType('تغيير الموظف أو المدير المسؤول', 'إسناد الأعمال', ('employee', 'manager'), True),
    'work.progress': EventType('تحديث حالة العمل أو تقدّمه', 'إسناد الأعمال', ('employee', 'manager'), True),
    'work.edited': EventType('تعديل تفاصيل العمل', 'إسناد الأعمال', ('employee', 'manager'), True),
}
BUSINESS_EVENTS = {
    PARTNERSHIP_EXPIRY: EventType('تذكير بقرب انتهاء الشراكة', 'الشراكات', ('employee',), True, assignment_only=True),
    'agreement.clause_progress': EventType('تحديث إنجاز بند الاتفاقية', 'متابعة الاتفاقيات', (), True),
    'sponsorship.added': EventType('إضافة جهة مرشحة للرعاية', 'متابعة الرعاية', (), True),
    'sponsorship.approved': EventType('اعتماد مساهمة رعاية', 'متابعة الرعاية', ('employee', 'manager'), True),
    'sponsorship.rejected': EventType('رفض جهة مرشحة للرعاية', 'متابعة الرعاية', ('employee', 'manager'), True),
    'sponsorship.contact': EventType('تسجيل نتيجة التواصل مع الراعي', 'متابعة الرعاية', ('employee', 'manager'), True),
    'sponsorship.allocation': EventType('توزيع دعم على بنود الصرف', 'متابعة الرعاية', ('employee', 'manager'), True),
    'sponsorship.development': EventType('تحديث حالة تطور جهة مرتبطة برعاية', 'متابعة الرعاية', (), True),
}
ACTIONS = {'create': 'إنشاء', 'update': 'تعديل', 'status': 'تغيير حالة', 'delete': 'حذف',
           'view': 'مشاهدة', 'download': 'تنزيل مرفق', 'export_xlsx': 'تصدير Excel',
           'export_pdf': 'تصدير PDF', 'denied': 'محاولة وصول غير مسموحة'}
LINKABLE_MODULES = {'partnerships', 'market_needs', 'provider_assignments', 'service_providers'}
MODULES = {key: value.title for key, value in DEFINITIONS.items()}
MODULES.update({'accounts': 'الحساب الشخصي', 'access_control': 'إدارة المستخدمين والصلاحيات'})
CATALOG = {**ACCOUNT_EVENTS, **WORK_EVENTS, **BUSINESS_EVENTS}
CATALOG.update({
    f'{module}.{action}': EventType(f'{label} · {title}', title, (), module in LINKABLE_MODULES)
    for module, title in MODULES.items() for action, label in ACTIONS.items()
    if f'{module}.{action}' not in CATALOG
})

SPONSORSHIP_ACTIONS = {
    'إضافة جهة مرشحة': 'sponsorship.added',
    'اعتماد مساهمة': 'sponsorship.approved',
    'رفض جهة مرشحة': 'sponsorship.rejected',
    'تسجيل نتيجة التواصل': 'sponsorship.contact',
    'توزيع مساهمة سابقة على بنود الصرف': 'sponsorship.allocation',
    'انتقال الجهة إلى رعاية': 'sponsorship.development',
}


def activity_code(event, sponsorship_id=None):
    if event.module == 'partnerships' and event.description == 'تحديث إنجاز بند الاتفاقية':
        return 'agreement.clause_progress'
    if sponsorship_id and event.description in SPONSORSHIP_ACTIONS:
        return SPONSORSHIP_ACTIONS[event.description]
    if event.target_model in {'auth.user', 'accounts.userprofile'} or event.module == 'accounts':
        if event.action in {'login', 'logout'}:
            return 'account.' + event.action
        if event.action == 'create':
            return 'account.created'
        if event.action == 'delete':
            return 'account.deleted'
        if event.action == 'status':
            return 'account.status'
        if event.action == 'update':
            if event.description == 'إعادة تعيين كلمة المرور' or event.after.get('password_changed'):
                return 'account.password'
            return 'account.profile' if event.module == 'accounts' else 'account.edited'
    return f'{event.module}.{event.action}'
