"""Semantic Layer & Metadata Discovery over real Makken Django models.

Provides an explicit, RBAC-aware, sensitive-field-filtered analytics registry
with Arabic/English business labels, semantic data types, allowed aggregations,
calculated fields, and regional scoping enforcement.
"""
from dataclasses import dataclass, field as dc_field
from django.apps import apps
from django.db.models import Case, DecimalField, ExpressionWrapper, F, FloatField, Q, Value, When
from django.db.models.functions import NullIf
from access_control.policy import AccessPolicy
from access_control.regions import RegionalPolicy, scoped as regional_scoped


BLOCKED_FIELD_NAMES = frozenset({
    'password', 'secret', 'token', 'api_key', 'private_key', 'session_key',
    'name_key', 'email_key', 'email_digest', 'request_key', 'last_request',
    'last_digest', 'source_key', 'password_failures', 'failure_window_started_at',
    'password_locked_until', 'must_change_password', 'diploma_catalog',
    'before', 'after', 'snapshot', 'evidence', 'search_states', 'search_scopes',
    'offerings', 'file',
})

AGG_BY_TYPE = {
    'string': ['count', 'count_distinct'],
    'enum': ['count', 'count_distinct'],
    'boolean': ['count', 'count_distinct'],
    'date': ['count', 'count_distinct', 'min', 'max'],
    'datetime': ['count', 'count_distinct', 'min', 'max'],
    'integer': ['count', 'count_distinct', 'sum', 'avg', 'min', 'max', 'median'],
    'decimal': ['count', 'count_distinct', 'sum', 'avg', 'min', 'max', 'median'],
    'currency': ['count', 'count_distinct', 'sum', 'avg', 'min', 'max', 'median'],
    'percentage': ['count', 'count_distinct', 'avg', 'min', 'max', 'median'],
}

CURRENCY_FIELDS = frozenset({
    'total_cost', 'requested_support', 'approved_support', 'amount',
    'financial_capacity', 'funding_gap', 'cost_per_beneficiary',
})
PERCENT_FIELDS = frozenset({'progress', 'coverage_pct'})


@dataclass(frozen=True)
class CalculatedFieldDef:
    name: str
    label_ar: str
    label_en: str
    data_type: str
    unit: str = ''
    description_ar: str = ''


@dataclass(frozen=True)
class EntityDef:
    key: str
    model_label: str
    label_ar: str
    label_en: str
    category_ar: str
    module_key: str
    default_date_field: str = 'created_at'
    default_label_field: str = 'name'
    is_regional: bool = False
    region_scope_path: str = ''
    extra_fields: tuple = ()
    calculated_fields: tuple = ()
    field_labels: dict = dc_field(default_factory=dict)


ENTITY_REGISTRY = {
    'market_needs': EntityDef(
        key='market_needs',
        model_label='market_needs.Need',
        label_ar='احتياجات السوق',
        label_en='Market Needs',
        category_ar='الاحتياجات والتمويل',
        module_key='market_needs',
        default_date_field='observed_on',
        default_label_field='title',
        is_regional=True,
        calculated_fields=(
            CalculatedFieldDef('funding_gap', 'فجوة التمويل', 'Funding Gap', 'currency', 'ر.س', 'الدعم المطلوب ناقص الدعم المعتمد'),
            CalculatedFieldDef('coverage_pct', 'نسبة تغطية الدعم %', 'Support Coverage %', 'percentage', '%', 'نسبة الدعم المعتمد إلى المطلوب'),
            CalculatedFieldDef('cost_per_beneficiary', 'متوسط التكلفة لكل مستفيد', 'Cost per Beneficiary', 'currency', 'ر.س', 'إجمالي التكلفة مقسومًا على عدد المستفيدين'),
        ),
        field_labels={
            'id': 'رقم البطاقة',
            'title': 'حاجة السوق',
            'status': 'حالة الحاجة',
            'beneficiaries': 'عدد المستفيدين',
            'total_cost': 'التكلفة الإجمالية',
            'requested_support': 'الدعم المطلوب',
            'approved_support': 'الدعم المعتمد',
            'duration': 'المدة الزمنية',
            'duration_unit': 'وحدة المدة',
            'training_type': 'نوع التدريب',
            'program_name': 'البرنامج التدريبي',
            'program_category': 'تصنيف البرنامج',
            'source': 'مصدر الحاجة',
            'observed_on': 'تاريخ الرصد',
            'is_active': 'نشط',
            'created_at': 'تاريخ الإنشاء',
            'updated_at': 'آخر تحديث',
        },
    ),
    'sponsorships': EntityDef(
        key='sponsorships',
        model_label='market_needs.Sponsorship',
        label_ar='الرعايات والتمويل',
        label_en='Sponsorships',
        category_ar='الاحتياجات والتمويل',
        module_key='market_needs',
        default_date_field='created_at',
        default_label_field='level_name',
        is_regional=True,
        field_labels={
            'id': 'رقم الرعاية',
            'status': 'حالة الرعاية',
            'amount': 'مبلغ الرعاية',
            'level_name': 'مستوى الرعاية',
            'created_at': 'تاريخ الإنشاء',
            'decided_at': 'تاريخ القرار',
            'updated_at': 'آخر تحديث',
        },
    ),
    'expense_lines': EntityDef(
        key='expense_lines',
        model_label='market_needs.ExpenseLine',
        label_ar='بنود الصرف للاحتياجات',
        label_en='Need Expense Lines',
        category_ar='الاحتياجات والتمويل',
        module_key='market_needs',
        default_date_field='',
        default_label_field='id',
        is_regional=True,
        region_scope_path='need',
        field_labels={
            'id': 'رقم البند',
            'amount': 'قيمة البند',
            'position': 'الترتيب',
        },
    ),
    'need_executions': EntityDef(
        key='need_executions',
        model_label='market_needs.NeedExecution',
        label_ar='تنفيذ البرامج المعتمدة',
        label_en='Program Executions',
        category_ar='تنفيذ البرامج',
        module_key='approved_programs',
        default_date_field='created_at',
        default_label_field='status',
        is_regional=True,
        field_labels={
            'id': 'رقم التنفيذ',
            'status': 'حالة التنفيذ',
            'created_at': 'تاريخ الإنشاء',
            'updated_at': 'آخر تحديث',
            'completed_at': 'تاريخ الإكمال',
        },
    ),
    'partnerships': EntityDef(
        key='partnerships',
        model_label='partnerships.Partnership',
        label_ar='الشراكات والجهات',
        label_en='Partnerships',
        category_ar='الشراكات والاتفاقيات',
        module_key='partnerships',
        default_date_field='created_at',
        default_label_field='name',
        is_regional=True,
        field_labels={
            'id': 'رقم الشراكة',
            'name': 'اسم الجهة',
            'representative': 'الممثل عن الجهة',
            'scope': 'النطاق',
            'financial_capacity': 'القدرة المالية',
            'is_active': 'نشط',
            'preliminary_agreement_type': 'نوع الاتفاق المبدئي',
            'agreement_number': 'رقم الاتفاقية',
            'signing_city': 'مدينة التوقيع',
            'headquarters_city': 'مدينة المقر',
            'signed_on': 'تاريخ التوقيع',
            'starts_on': 'بداية الشراكة',
            'ends_on': 'نهاية الشراكة',
            'duration_months': 'مدة الاتفاقية (أشهر)',
            'renewal_rule': 'نوع التجديد',
            'created_at': 'تاريخ التسجيل',
            'updated_at': 'آخر تحديث',
        },
    ),
    'partnership_offerings': EntityDef(
        key='partnership_offerings',
        model_label='partnerships.PartnershipOffering',
        label_ar='عروض ومجالات الرعاية',
        label_en='Partnership Offerings',
        category_ar='الشراكات والاتفاقيات',
        module_key='partnerships',
        default_date_field='',
        default_label_field='id',
        is_regional=True,
        region_scope_path='partnership',
        field_labels={
            'id': 'رقم العرض',
            'is_active': 'نشط',
            'position': 'الترتيب',
        },
    ),
    'sponsor_requests': EntityDef(
        key='sponsor_requests',
        model_label='partnerships.SponsorRegistrationRequest',
        label_ar='طلبات الرعاة الخارجيين',
        label_en='Sponsor Registration Requests',
        category_ar='الشراكات والاتفاقيات',
        module_key='sponsor_requests',
        default_date_field='created_at',
        default_label_field='name',
        is_regional=True,
        region_scope_path='administrative_regions',
        field_labels={
            'id': 'رقم الطلب',
            'reference_code': 'الرمز المرجعي',
            'name': 'اسم الجهة',
            'scope': 'النطاق',
            'financial_capacity': 'القدرة المالية',
            'status': 'حالة الطلب',
            'reviewed_at': 'تاريخ المراجعة',
            'created_at': 'تاريخ التقديم',
        },
    ),
    'service_providers': EntityDef(
        key='service_providers',
        model_label='service_providers.ServiceProvider',
        label_ar='مزودو خدمات التدريب',
        label_en='Service Providers',
        category_ar='تنفيذ البرامج',
        module_key='service_providers',
        default_date_field='created_at',
        default_label_field='name',
        is_regional=True,
        field_labels={
            'id': 'رقم المزود',
            'name': 'اسم مزود الخدمة',
            'representative': 'الممثل',
            'provider_type': 'نوع المزود',
            'scope': 'النطاق',
            'is_active': 'نشط',
            'converted_at': 'تاريخ التحويل لشراكة',
            'created_at': 'تاريخ التسجيل',
            'updated_at': 'آخر تحديث',
        },
    ),
    'provider_coverage': EntityDef(
        key='provider_coverage',
        model_label='service_providers.ProviderCoverage',
        label_ar='التغطية الجغرافية للمزودين',
        label_en='Provider Coverage',
        category_ar='تنفيذ البرامج',
        module_key='service_providers',
        default_date_field='',
        default_label_field='id',
        is_regional=True,
        region_scope_path='provider',
        field_labels={
            'id': 'رقم التغطية',
            'is_active': 'نشط',
        },
    ),
    'training_programs': EntityDef(
        key='training_programs',
        model_label='training_programs.TrainingProgram',
        label_ar='البرامج التدريبية',
        label_en='Training Programs',
        category_ar='البيانات المرجعية',
        module_key='training_programs',
        default_date_field='created_at',
        default_label_field='name',
        field_labels={
            'id': 'رقم البرنامج',
            'name': 'اسم البرنامج',
            'category': 'تصنيف البرنامج',
            'is_training': 'تدريبي',
            'is_operational': 'تشغيلي',
            'is_active': 'نشط',
            'created_at': 'تاريخ الإنشاء',
        },
    ),
    'agreements': EntityDef(
        key='agreements',
        model_label='agreement_clauses.Agreement',
        label_ar='الاتفاقيات',
        label_en='Agreements',
        category_ar='الشراكات والاتفاقيات',
        module_key='partnerships',
        default_date_field='created_at',
        default_label_field='title',
        is_regional=True,
        region_scope_path='partnership',
        field_labels={
            'id': 'رقم الاتفاقية',
            'title': 'عنوان الاتفاقية',
            'created_at': 'تاريخ الإنشاء',
        },
    ),
    'clause_assignments': EntityDef(
        key='clause_assignments',
        model_label='agreement_clauses.ClauseAssignment',
        label_ar='بنود الاتفاقيات وإنجازها',
        label_en='Clause Assignments',
        category_ar='الشراكات والاتفاقيات',
        module_key='partnerships',
        default_date_field='updated_at',
        default_label_field='id',
        is_regional=True,
        region_scope_path='partnership',
        field_labels={
            'id': 'رقم الإسناد',
            'responsibility': 'المسؤولية',
            'progress': 'نسبة الإنجاز %',
            'updated_at': 'آخر تحديث',
        },
    ),
    'work_assignments': EntityDef(
        key='work_assignments',
        model_label='makken_mail.WorkAssignment',
        label_ar='المهام والتكليفات',
        label_en='Work Assignments',
        category_ar='التشغيل والمتابعة',
        module_key='work_assignments',
        default_date_field='created_at',
        default_label_field='title',
        field_labels={
            'id': 'رقم المهمة',
            'title': 'عنوان المهمة',
            'status': 'حالة المهمة',
            'progress': 'نسبة الإنجاز %',
            'due_on': 'تاريخ الاستحقاق',
            'target_model': 'الكيان المستهدف',
            'created_at': 'تاريخ الإنشاء',
            'updated_at': 'آخر تحديث',
        },
    ),
    'regions': EntityDef(
        key='regions',
        model_label='regions.Region',
        label_ar='المناطق الإدارية',
        label_en='Regions',
        category_ar='البيانات المرجعية',
        module_key='regions',
        default_date_field='created_at',
        default_label_field='name',
        is_regional=True,
        field_labels={'id': 'رقم المنطقة', 'name': 'المنطقة', 'is_active': 'نشط', 'created_at': 'تاريخ الإنشاء'},
    ),
    'sectors': EntityDef(
        key='sectors',
        model_label='sectors.Sector',
        label_ar='القطاعات',
        label_en='Sectors',
        category_ar='البيانات المرجعية',
        module_key='sectors',
        default_date_field='created_at',
        default_label_field='name',
        field_labels={'id': 'رقم القطاع', 'name': 'القطاع', 'is_active': 'نشط', 'created_at': 'تاريخ الإنشاء'},
    ),
    'specializations': EntityDef(
        key='specializations',
        model_label='specializations.Specialization',
        label_ar='التخصصات',
        label_en='Specializations',
        category_ar='البيانات المرجعية',
        module_key='specializations',
        default_date_field='created_at',
        default_label_field='name',
        field_labels={'id': 'رقم التخصص', 'name': 'التخصص', 'is_active': 'نشط', 'created_at': 'تاريخ الإنشاء'},
    ),
    'entities': EntityDef(
        key='entities',
        model_label='entities.Entity',
        label_ar='الكيانات',
        label_en='Entities',
        category_ar='البيانات المرجعية',
        module_key='entities',
        default_date_field='created_at',
        default_label_field='name',
        field_labels={'id': 'رقم الكيان', 'name': 'اسم الكيان', 'entity_type': 'نوع الكيان', 'branch': 'فرع الكيان', 'is_active': 'نشط'},
    ),
    'sponsorship_shapes': EntityDef(
        key='sponsorship_shapes',
        model_label='sponsorship_shapes.SponsorshipShape',
        label_ar='أشكال الرعاية',
        label_en='Sponsorship Shapes',
        category_ar='البيانات المرجعية',
        module_key='sponsorship_shapes',
        default_date_field='created_at',
        default_label_field='name',
        field_labels={'id': 'رقم الشكل', 'name': 'شكل الرعاية', 'is_employment': 'رعاية توظيف', 'is_active': 'نشط'},
    ),
    'expense_items': EntityDef(
        key='expense_items',
        model_label='expense_items.ExpenseItem',
        label_ar='بنود الصرف المرجعية',
        label_en='Expense Items',
        category_ar='البيانات المرجعية',
        module_key='expense_items',
        default_date_field='created_at',
        default_label_field='name',
        field_labels={'id': 'رقم البند', 'name': 'بند الصرف', 'is_active': 'نشط'},
    ),
    'levels': EntityDef(
        key='levels',
        model_label='levels.Level',
        label_ar='مستويات الرعاية',
        label_en='Care Levels',
        category_ar='البيانات المرجعية',
        module_key='levels',
        default_date_field='created_at',
        default_label_field='name',
        field_labels={'id': 'رقم المستوى', 'name': 'المستوى', 'is_active': 'نشط'},
    ),
    'departments': EntityDef(
        key='departments',
        model_label='accounts.Department',
        label_ar='الإدارات والوحدات',
        label_en='Departments',
        category_ar='البيانات المرجعية',
        module_key='departments',
        default_date_field='created_at',
        default_label_field='name',
        field_labels={'id': 'رقم الإدارة', 'name': 'اسم الإدارة', 'kind': 'نوع الإدارة', 'is_active': 'نشط'},
    ),
    'user_activity': EntityDef(
        key='user_activity',
        model_label='access_control.UserActivity',
        label_ar='سجل نشاط المستخدمين',
        label_en='User Activity',
        category_ar='الحوكمة والتدقيق',
        module_key='user_activity',
        default_date_field='created_at',
        default_label_field='description',
        field_labels={
            'id': 'رقم الحدث',
            'actor_name': 'المستخدم',
            'module': 'الوحدة',
            'action': 'الإجراء',
            'description': 'الوصف',
            'scope': 'النطاق',
            'outcome': 'النتيجة',
            'http_status': 'رمز الاستجابة',
            'created_at': 'التاريخ والوقت',
        },
    ),
}


def get_model(entity_key):
    edef = ENTITY_REGISTRY.get(entity_key)
    if not edef:
        return None
    return apps.get_model(edef.model_label)


def get_request_policy(user):
    pol = getattr(user, '_flex_access_policy', None)
    if pol is None:
        pol = AccessPolicy(user)
        try:
            setattr(user, '_flex_access_policy', pol)
        except Exception:
            pass
    return pol


def get_request_regional_policy(user):
    rpol = getattr(user, '_flex_regional_policy', None)
    if rpol is None:
        rpol = RegionalPolicy(user)
        try:
            setattr(user, '_flex_regional_policy', rpol)
        except Exception:
            pass
    return rpol


def user_can_view_entity(user, entity_key):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    edef = ENTITY_REGISTRY.get(entity_key)
    if not edef:
        return False
    if user.is_superuser:
        return True
    policy = get_request_policy(user)
    if policy.can(edef.module_key, 'view'):
        return True
    # Reference catalogs linked to accessible domain modules remain readable as dimensions
    if edef.module_key in {'regions', 'sectors', 'specializations', 'entities', 'sponsorship_shapes', 'expense_items', 'levels', 'training_programs'}:
        return any(policy.can(m, 'view') for m in ('flex_analytics', 'dashboard', 'market_needs', 'partnerships', 'service_providers'))
    return False


def accessible_entity_keys(user):
    return [k for k in ENTITY_REGISTRY if user_can_view_entity(user, k)]


def _infer_semantic_type(django_field):
    fname = django_field.name
    if fname in CURRENCY_FIELDS:
        return 'currency'
    if fname in PERCENT_FIELDS:
        return 'percentage'
    internal = django_field.get_internal_type()
    if getattr(django_field, 'choices', None):
        return 'enum'
    if internal in {'AutoField', 'BigAutoField', 'IntegerField', 'PositiveIntegerField', 'PositiveSmallIntegerField', 'SmallIntegerField', 'BigIntegerField', 'PositiveBigIntegerField'}:
        return 'integer'
    if internal in {'DecimalField', 'FloatField'}:
        return 'decimal'
    if internal == 'BooleanField':
        return 'boolean'
    if internal == 'DateField':
        return 'date'
    if internal == 'DateTimeField':
        return 'datetime'
    return 'string'


def get_entity_fields(entity_key):
    edef = ENTITY_REGISTRY.get(entity_key)
    if not edef:
        return []
    model = apps.get_model(edef.model_label)
    fields_out = []
    for f in model._meta.concrete_fields:
        if f.name in BLOCKED_FIELD_NAMES:
            continue
        if f.is_relation:
            # Expose readable label via FK display field when pointing to a simple lookup
            continue
        if f.get_internal_type() in {'JSONField', 'UUIDField', 'FileField', 'BinaryField'}:
            continue
        stype = _infer_semantic_type(f)
        label_ar = edef.field_labels.get(f.name) or str(getattr(f, 'verbose_name', f.name))
        choices = []
        if getattr(f, 'choices', None):
            choices = [{'value': str(v), 'label': str(lbl)} for v, lbl in f.choices]
        fields_out.append({
            'name': f.name,
            'label_ar': label_ar,
            'label_en': f.name.replace('_', ' ').title(),
            'data_type': stype,
            'is_numeric': stype in {'integer', 'decimal', 'currency', 'percentage'},
            'is_date': stype in {'date', 'datetime'},
            'is_calculated': False,
            'aggregations': AGG_BY_TYPE.get(stype, ['count', 'count_distinct']),
            'choices': choices,
            'unit': 'ر.س' if stype == 'currency' else ('%' if stype == 'percentage' else ''),
        })
    for calc in edef.calculated_fields:
        fields_out.append({
            'name': calc.name,
            'label_ar': calc.label_ar,
            'label_en': calc.label_en,
            'data_type': calc.data_type,
            'is_numeric': True,
            'is_date': False,
            'is_calculated': True,
            'aggregations': AGG_BY_TYPE.get(calc.data_type, ['avg', 'sum', 'min', 'max']),
            'choices': [],
            'unit': calc.unit,
            'description_ar': calc.description_ar,
        })
    return fields_out


def get_field_map(entity_key):
    return {f['name']: f for f in get_entity_fields(entity_key)}


def apply_calculated_annotations(qs, entity_key, requested_fields):
    """Attach safe ORM annotations for any requested calculated fields."""
    if entity_key == 'market_needs':
        if 'funding_gap' in requested_fields:
            qs = qs.annotate(
                funding_gap=ExpressionWrapper(
                    F('requested_support') - F('approved_support'),
                    output_field=DecimalField(max_digits=16, decimal_places=2),
                )
            )
        if 'coverage_pct' in requested_fields:
            qs = qs.annotate(
                coverage_pct=Case(
                    When(requested_support__gt=0, then=ExpressionWrapper(
                        F('approved_support') * Value(100.0) / NullIf(F('requested_support'), Value(0)),
                        output_field=FloatField(),
                    )),
                    default=Value(0.0),
                    output_field=FloatField(),
                )
            )
        if 'cost_per_beneficiary' in requested_fields:
            qs = qs.annotate(
                cost_per_beneficiary=Case(
                    When(beneficiaries__gt=0, then=ExpressionWrapper(
                        F('total_cost') / NullIf(F('beneficiaries'), Value(0)),
                        output_field=FloatField(),
                    )),
                    default=Value(0.0),
                    output_field=FloatField(),
                )
            )
    return qs


def scoped_queryset(entity_key, user):
    """Return an RBAC + regionally scoped base queryset for an entity."""
    if not user_can_view_entity(user, entity_key):
        model = get_model(entity_key)
        return model.objects.none() if model else None
    edef = ENTITY_REGISTRY[entity_key]
    model = apps.get_model(edef.model_label)
    qs = model.objects.all()
    if not edef.is_regional:
        return qs
    policy = get_request_regional_policy(user)
    if not policy.active:
        return qs.none()
    if policy.unrestricted:
        return qs
    if not edef.region_scope_path:
        return regional_scoped(qs, policy=policy)
    if edef.region_scope_path == 'need':
        Need = apps.get_model('market_needs.Need')
        return qs.filter(need_id__in=regional_scoped(Need.objects.all(), policy=policy).values('pk'))
    if edef.region_scope_path == 'partnership':
        Partnership = apps.get_model('partnerships.Partnership')
        return qs.filter(partnership_id__in=regional_scoped(Partnership.objects.all(), policy=policy).values('pk'))
    if edef.region_scope_path == 'provider':
        ServiceProvider = apps.get_model('service_providers.ServiceProvider')
        return qs.filter(provider_id__in=regional_scoped(ServiceProvider.objects.all(), policy=policy).values('pk'))
    if edef.region_scope_path == 'administrative_regions':
        return qs.filter(administrative_regions__id__in=policy.ids).distinct()
    return qs


def serialize_metadata(user):
    """Return complete RBAC-filtered metadata payload for the frontend studio."""
    entities_payload = []
    for key, edef in ENTITY_REGISTRY.items():
        if not user_can_view_entity(user, key):
            continue
        entities_payload.append({
            'key': key,
            'label_ar': edef.label_ar,
            'label_en': edef.label_en,
            'category_ar': edef.category_ar,
            'module_key': edef.module_key,
            'default_date_field': edef.default_date_field,
            'default_label_field': edef.default_label_field,
            'is_regional': edef.is_regional,
            'fields': get_entity_fields(key),
        })
    return {
        'entities': entities_payload,
        'aggregations': [
            {'key': 'count', 'label_ar': 'العدد'},
            {'key': 'count_distinct', 'label_ar': 'العدد الفريد'},
            {'key': 'sum', 'label_ar': 'المجموع'},
            {'key': 'avg', 'label_ar': 'المتوسط'},
            {'key': 'min', 'label_ar': 'الحد الأدنى'},
            {'key': 'max', 'label_ar': 'الحد الأعلى'},
            {'key': 'median', 'label_ar': 'الوسيط'},
        ],
        'date_granularities': [
            {'key': 'day', 'label_ar': 'يومي'},
            {'key': 'week', 'label_ar': 'أسبوعي'},
            {'key': 'month', 'label_ar': 'شهري'},
            {'key': 'quarter', 'label_ar': 'ربع سنوي'},
            {'key': 'year', 'label_ar': 'سنوي'},
        ],
        'operators': [
            {'key': 'eq', 'label_ar': 'يساوي'},
            {'key': 'neq', 'label_ar': 'لا يساوي'},
            {'key': 'contains', 'label_ar': 'يحتوي على'},
            {'key': 'gt', 'label_ar': 'أكبر من'},
            {'key': 'gte', 'label_ar': 'أكبر من أو يساوي'},
            {'key': 'lt', 'label_ar': 'أصغر من'},
            {'key': 'lte', 'label_ar': 'أصغر من أو يساوي'},
            {'key': 'in', 'label_ar': 'ضمن القائمة'},
            {'key': 'between', 'label_ar': 'بين قيمتين'},
            {'key': 'is_null', 'label_ar': 'فارغ'},
            {'key': 'not_null', 'label_ar': 'غير فارغ'},
        ],
    }
