"""Shared protection for referenced business records.

Only incoming business references block a record. A record's owned detail rows
and audit entries are not external usages: deleting an unreferenced draft may
still remove its own lines. Inactive and rejected usages count as references.
No relationship is automatically detached or deactivated by this policy.
"""
from django.apps import apps
from django.db import connections, router


TITLES = {
    'levels.level': 'المستوى', 'regions.region': 'المنطقة',
    'entities.entity': 'الكيان', 'specializations.specialization': 'التخصص',
    'sectors.sector': 'القطاع', 'expense_items.expenseitem': 'بند الصرف',
    'training_programs.trainingprogram': 'البرنامج التدريبي',
    'sponsorship_shapes.sponsorshipshape': 'شكل الرعاية',
    'partnerships.partnership': 'الجهة', 'market_needs.need': 'بطاقة حاجة السوق',
    'service_providers.serviceprovider': 'مزود الخدمة',
}
# Explicit business boundaries keep audit/owned-detail relations out of this rule.
REFERENCES = {
    'levels.level': [('market_needs.Sponsorship', 'level_id', 'متابعة الرعاية')],
    'regions.region': [('market_needs.NeedRegion', 'region_id', 'بطاقات حاجة السوق'),
                       ('service_providers.ProviderCoverage', 'region_id', 'مزودو الخدمات')],
    'entities.entity': [('partnerships.Partnership', 'entity_id', 'سجل الشراكات')],
    'specializations.specialization': [('partnerships.OfferingSpecialization', 'specialization_id', 'بنود الشراكات'),
                                       ('market_needs.Need', 'specialization_id', 'بطاقات حاجة السوق'),
                                       ('service_providers.CoverageSpecialization', 'specialization_id', 'تخصصات مزودي الخدمات')],
    'sectors.sector': [('specializations.Specialization', 'sector_id', 'التخصصات'),
                       ('partnerships.PartnershipOffering', 'sector_id', 'بنود الشراكات'),
                       ('market_needs.Need', 'sector_id', 'بطاقات حاجة السوق')],
    'expense_items.expenseitem': [('training_programs.ProgramExpenseItem', 'expense_item_id', 'برامج التدريب'),
                                 ('market_needs.ExpenseLine', 'expense_item_id', 'بنود بطاقات حاجة السوق')],
    'training_programs.trainingprogram': [('market_needs.Need', 'program_id', 'بطاقات حاجة السوق')],
    'sponsorship_shapes.sponsorshipshape': [('partnerships.PartnershipOffering', 'sponsorship_shape_id', 'بنود الشراكات'),
                                           ('market_needs.ExpenseLine', 'sponsorship_shape_id', 'بنود بطاقات حاجة السوق')],
    'partnerships.partnership': [('market_needs.Sponsorship', 'partnership_id', 'متابعة الرعاية'),
                                ('service_providers.ServiceProvider', 'converted_partnership_id', 'مزودو الخدمات المرتبطون سابقًا')],
    'market_needs.need': [('market_needs.Sponsorship', 'need_id', 'الجهات المرشحة ومتابعة الرعاية')],
    'service_providers.serviceprovider': [],
}


class DependencyBlocked(Exception):
    def __init__(self, item, operation, references):
        self.operation = operation
        self.references = references
        self.record_name = str(item)
        self.record_type = TITLES[item._meta.label_lower]
        action = 'حذف' if operation == 'delete' else 'إيقاف'
        message = f'لا يمكن {action} {self.record_type} «{self.record_name}» لارتباطه بسجلات أخرى: ' + '، '.join(references) + '.'
        super().__init__(message)


def references_for(item, using=None):
    if item is None or item.pk is None:
        return []
    using = using or item._state.db or router.db_for_write(type(item), instance=item)
    found = []
    for label, field, title in REFERENCES.get(item._meta.label_lower, []):
        try:
            model = apps.get_model(label)
        except LookupError:
            continue  # Optional module not installed in an older deployment.
        query = model._base_manager.using(using).filter(**{field: item.pk})
        if connections[using].in_atomic_block:
            # Current read on InnoDB: see links committed since a preview/snapshot.
            query = query.select_for_update()
        if query.exists():
            found.append(title)
    if item._meta.label_lower == 'service_providers.serviceprovider' and item.converted_partnership_id:
        found.append('سجل الشراكات المرتبط سابقًا')
    return found


def ensure_allowed(item, operation, active=None, using=None):
    """Preview and commit use the same policy; commit callers lock the parent."""
    if item is None or item.pk is None or item._meta.label_lower not in TITLES:
        return
    destructive = operation == 'delete' or (operation in {'edit', 'toggle', 'deactivate'} and item.is_active and active is False)
    if destructive:
        references = references_for(item, using)
        if references:
            raise DependencyBlocked(item, operation, references)


def blocked_context(error):
    return {'error': str(error), 'pending': None, 'dependency_block': {
        'message': str(error), 'record': error.record_name,
        'title': 'تعذّر حذف السجل' if error.operation == 'delete' else 'تعذّر إيقاف السجل',
        'references': error.references,
    }}
