"""Code-owned route boundaries; database-owned role and user configuration.

A future module registers its route policy here and wraps its views with
module_view. Unknown routes remain denied. Adding a role never needs code.
"""
from dataclasses import dataclass, replace

CRUD = ('view', 'create', 'edit', 'delete', 'change_status')


@dataclass(frozen=True)
class ModuleDefinition:
    key: str
    title: str
    route_name: str
    operations: tuple


MODULES = (
    ModuleDefinition('home', 'الرئيسية', 'makken_home', ('view',)),
    ModuleDefinition('dashboard', 'مركز المؤشرات والتحليلات', 'core:dashboard', ('view',)),
    ModuleDefinition('flex_analytics', 'المؤشرات والتحليلات المرنة', 'flex_analytics:index', ('view', 'create', 'edit', 'delete')),
    ModuleDefinition('care_states', 'حالات التطور', 'care_states:index', ('view', 'edit')),
    ModuleDefinition('levels', 'المستويات', 'levels:index', CRUD),
    ModuleDefinition('regions', 'المناطق', 'regions:index', CRUD),
    ModuleDefinition('entities', 'الكيانات', 'entities:index', CRUD),
    ModuleDefinition('specializations', 'التخصصات', 'specializations:index', CRUD),
    ModuleDefinition('sectors', 'القطاعات', 'sectors:index', CRUD),
    ModuleDefinition('expense_items', 'بنود الصرف', 'expense_items:index', CRUD),
    ModuleDefinition('agreement_clauses', 'بنود الاتفاقية', 'agreement_clauses:index', CRUD),
    ModuleDefinition('training_programs', 'برامج التدريب', 'training_programs:index', CRUD),
    ModuleDefinition('sponsorship_shapes', 'أشكال الرعاية', 'sponsorship_shapes:index', CRUD),
    ModuleDefinition('partnerships', 'الشراكات', 'partnerships:index', (*CRUD, 'export')),
    ModuleDefinition('market_needs', 'بطاقات حاجة السوق ومتابعة الرعاية', 'market_needs:index', (*CRUD, 'export')),
    ModuleDefinition('service_providers', 'مزودو الخدمات', 'service_providers:index', CRUD),
    ModuleDefinition('approved_programs', 'البرامج المعتمدة وفقًا للتخصص', 'program_execution:index', ('view',)),
    ModuleDefinition('provider_assignments', 'اختيار مزودي تنفيذ البرامج', 'program_execution:assignments', ('view', 'create', 'edit', 'change_status')),
    ModuleDefinition('user_activity', 'سجل نشاط المستخدمين', 'access_control:activity', ('view',)),
    ModuleDefinition('work_assignments', 'إسناد المهام', 'makken_mail:work_index', ('view', 'create', 'edit')),
    ModuleDefinition('agreement_classifications', 'تصنيف الاتفاقية', 'agreement_clauses:classifications', CRUD),
    ModuleDefinition('departments', 'إدارة الإدارات', 'accounts:departments', CRUD),
    ModuleDefinition('partnership_types', 'أنواع الشراكة', 'partnership_types', CRUD),
    ModuleDefinition('partnerships_all', 'جميع الشراكات', 'partnerships:all_index', ('view',)),
    ModuleDefinition('agreement_inquiries', 'الاستعلامات', 'partnerships:agreement_inquiries', ('view',)),
    ModuleDefinition('partnership_achievement', 'إنجاز الشراكات', 'partnerships:achievement_report', ('view',)),
    ModuleDefinition('sponsor_requests', 'طلبات الرعاة الخارجيين', 'partnerships:sponsor_requests', ('view', 'edit')),
)
# BEGIN MAKKEN FORMAT EXPORT RIGHTS v1
TABLE_EXPORT_OPERATIONS = ('export_xlsx', 'export_pdf')
MODULES = tuple(
    replace(row, operations=tuple(dict.fromkeys((*row.operations, *TABLE_EXPORT_OPERATIONS))))
    for row in MODULES
)
# END MAKKEN FORMAT EXPORT RIGHTS v1

DEFINITIONS = {row.key: row for row in MODULES}
SETTINGS_MODULES = frozenset({'levels','regions','entities','specializations','sectors','expense_items','agreement_clauses','training_programs','sponsorship_shapes'})
PUBLIC_ROUTES = frozenset({'accounts:login','accounts:login_slash','accounts:logout','accounts:logout_slash','partnerships:public_sponsor_register','partnerships:public_sponsor_thanks','set_language','makken_i18n_catalog'})
SELF_ROUTES = frozenset({'accounts:profile','access_control:landing','access_control:no_access','makken_mail:work_index','makken_mail:work_detail'})


def codename(module, operation):
    return f'{operation}_{module}'
