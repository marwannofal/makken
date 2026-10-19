"""Code-owned route boundaries; database-owned role and user configuration.

A future module registers its route policy here and wraps its views with
module_view. Unknown routes remain denied. Adding a role never needs code.
"""
from dataclasses import dataclass

CRUD = ('view', 'create', 'edit', 'delete', 'change_status')


@dataclass(frozen=True)
class ModuleDefinition:
    key: str
    title: str
    route_name: str
    operations: tuple


MODULES = (
    ModuleDefinition('dashboard', 'الرئيسية', 'makken_home', ('view',)),
    ModuleDefinition('care_states', 'حالات التطور', 'care_states:index', ('view', 'edit')),
    ModuleDefinition('levels', 'المستويات', 'levels:index', CRUD),
    ModuleDefinition('regions', 'المناطق', 'regions:index', CRUD),
    ModuleDefinition('entities', 'الكيانات', 'entities:index', CRUD),
    ModuleDefinition('specializations', 'التخصصات', 'specializations:index', CRUD),
    ModuleDefinition('sectors', 'القطاعات', 'sectors:index', CRUD),
    ModuleDefinition('expense_items', 'بنود الصرف', 'expense_items:index', CRUD),
    ModuleDefinition('training_programs', 'برامج التدريب', 'training_programs:index', CRUD),
    ModuleDefinition('sponsorship_shapes', 'أشكال الرعاية', 'sponsorship_shapes:index', CRUD),
    ModuleDefinition('partnerships', 'الشراكات', 'partnerships:index', (*CRUD, 'export')),
    ModuleDefinition('market_needs', 'بطاقات حاجة السوق ومتابعة الرعاية', 'market_needs:index', (*CRUD, 'export')),
    ModuleDefinition('service_providers', 'مزودو الخدمات', 'service_providers:index', CRUD),
)
DEFINITIONS = {row.key: row for row in MODULES}
SETTINGS_MODULES = frozenset({'levels','regions','entities','specializations','sectors','expense_items','training_programs','sponsorship_shapes'})
PUBLIC_ROUTES = frozenset({'accounts:login','accounts:login_slash','accounts:logout','accounts:logout_slash'})
SELF_ROUTES = frozenset({'accounts:profile','access_control:landing','access_control:no_access'})


def codename(module, operation):
    return f'{operation}_{module}'
