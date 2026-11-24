"""100+ Real Predefined Business KPIs + Safe Custom KPI Builder for Makken.

Every KPI is computed dynamically from real Makken Django models via the
RBAC + regionally scoped semantic layer. Zero fake/placeholder numbers.
"""
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal

from django.db.models import Avg, Count, F, Max, Q, Sum
from django.utils import timezone

from .query_engine import QueryValidationError, _build_q_from_filter_node, apply_global_filters
from .semantic import ENTITY_REGISTRY, apply_calculated_annotations, get_field_map, scoped_queryset, user_can_view_entity


@dataclass(frozen=True)
class KPIDef:
    key: str
    title_ar: str
    title_en: str
    category_ar: str
    entity_key: str
    unit: str  # '', 'ر.س', '%', 'مستفيد', 'يوم'
    format_type: str  # 'integer', 'currency', 'percent', 'decimal'
    trend_semantics: str  # 'positive', 'negative', 'neutral'
    description_ar: str
    calc_kind: str  # 'count', 'sum', 'avg', 'max', 'ratio_pct', 'custom'
    field: str = 'id'
    filter_kwargs: tuple = ()
    denom_filter_kwargs: tuple = ()
    denom_field: str = ''
    distinct: bool = False
    days_window: int = 0
    date_field: str = ''
    special: str = ''


def _build_kpi_registry():
    items = [
        # === 1. احتياجات السوق والتمويل (24 KPIs) ===
        KPIDef('needs_total', 'إجمالي احتياجات السوق', 'Total Market Needs', 'الاحتياجات والتمويل', 'market_needs', '', 'integer', 'neutral', 'إجمالي بطاقات احتياجات السوق المسجلة', 'count'),
        KPIDef('needs_active', 'احتياجات السوق النشطة', 'Active Market Needs', 'الاحتياجات والتمويل', 'market_needs', '', 'integer', 'positive', 'الاحتياجات النشطة حاليًا', 'count', filter_kwargs=(('is_active', True),)),
        KPIDef('needs_inactive', 'احتياجات السوق غير النشطة', 'Inactive Market Needs', 'الاحتياجات والتمويل', 'market_needs', '', 'integer', 'neutral', 'الاحتياجات المؤرشفة أو غير النشطة', 'count', filter_kwargs=(('is_active', False),)),
        KPIDef('needs_new', 'احتياجات جديدة', 'New Needs', 'الاحتياجات والتمويل', 'market_needs', '', 'integer', 'neutral', 'بطاقات الاحتياج بحالة جديد', 'count', filter_kwargs=(('status', 'new'),)),
        KPIDef('needs_working', 'احتياجات جاري العمل عليها', 'Working Needs', 'الاحتياجات والتمويل', 'market_needs', '', 'integer', 'neutral', 'الاحتياجات في مرحلة تأمين الرعاة', 'count', filter_kwargs=(('status', 'working'),)),
        KPIDef('needs_complete', 'احتياجات مكتملة الدعم', 'Fully Funded Needs', 'الاحتياجات والتمويل', 'market_needs', '', 'integer', 'positive', 'الاحتياجات التي اكتمل دعمها', 'count', filter_kwargs=(('status', 'complete'),)),
        KPIDef('needs_rejected', 'احتياجات مرفوضة', 'Rejected Needs', 'الاحتياجات والتمويل', 'market_needs', '', 'integer', 'negative', 'الاحتياجات التي تم رفضها', 'count', filter_kwargs=(('status', 'rejected'),)),
        KPIDef('needs_completion_rate', 'نسبة اكتمال دعم الاحتياجات', 'Need Completion Rate', 'الاحتياجات والتمويل', 'market_needs', '%', 'percent', 'positive', 'نسبة الاحتياجات مكتملة الدعم من الإجمالي', 'ratio_pct', filter_kwargs=(('status', 'complete'),)),
        KPIDef('needs_rejection_rate', 'نسبة رفض الاحتياجات', 'Need Rejection Rate', 'الاحتياجات والتمويل', 'market_needs', '%', 'percent', 'negative', 'نسبة الاحتياجات المرفوضة من الإجمالي', 'ratio_pct', filter_kwargs=(('status', 'rejected'),)),
        KPIDef('needs_total_cost', 'إجمالي تكلفة الاحتياجات', 'Total Needs Cost', 'الاحتياجات والتمويل', 'market_needs', 'ر.س', 'currency', 'neutral', 'مجموع التكلفة الإجمالية لجميع الاحتياجات', 'sum', field='total_cost'),
        KPIDef('needs_requested_support', 'إجمالي الدعم المطلوب', 'Total Requested Support', 'الاحتياجات والتمويل', 'market_needs', 'ر.س', 'currency', 'neutral', 'إجمالي مبالغ الدعم المطلوبة', 'sum', field='requested_support'),
        KPIDef('needs_approved_support', 'إجمالي الدعم المعتمد', 'Total Approved Support', 'الاحتياجات والتمويل', 'market_needs', 'ر.س', 'currency', 'positive', 'إجمالي مبالغ الدعم المعتمدة من الرعاة', 'sum', field='approved_support'),
        KPIDef('needs_funding_gap', 'فجوة التمويل الإجمالية', 'Total Funding Gap', 'الاحتياجات والتمويل', 'market_needs', 'ر.س', 'currency', 'negative', 'الفرق بين الدعم المطلوب والمعتمد', 'custom', special='needs_funding_gap'),
        KPIDef('needs_coverage_pct', 'نسبة تغطية التمويل الإجمالية', 'Overall Funding Coverage %', 'الاحتياجات والتمويل', 'market_needs', '%', 'percent', 'positive', 'الدعم المعتمد مقسومًا على الدعم المطلوب', 'custom', special='needs_coverage_pct'),
        KPIDef('needs_avg_cost', 'متوسط تكلفة الاحتياج', 'Average Need Cost', 'الاحتياجات والتمويل', 'market_needs', 'ر.س', 'currency', 'neutral', 'متوسط التكلفة الإجمالية لكل بطاقة احتياج', 'avg', field='total_cost'),
        KPIDef('needs_avg_requested', 'متوسط الدعم المطلوب', 'Average Requested Support', 'الاحتياجات والتمويل', 'market_needs', 'ر.س', 'currency', 'neutral', 'متوسط الدعم المطلوب لكل احتياج', 'avg', field='requested_support'),
        KPIDef('needs_avg_approved', 'متوسط الدعم المعتمد', 'Average Approved Support', 'الاحتياجات والتمويل', 'market_needs', 'ر.س', 'currency', 'positive', 'متوسط الدعم المعتمد لكل احتياج', 'avg', field='approved_support'),
        KPIDef('needs_total_beneficiaries', 'إجمالي المستفيدين المستهدفين', 'Total Target Beneficiaries', 'الاحتياجات والتمويل', 'market_needs', 'مستفيد', 'integer', 'positive', 'مجموع أعداد المستفيدين عبر الاحتياجات', 'sum', field='beneficiaries'),
        KPIDef('needs_complete_beneficiaries', 'مستفيدو الاحتياجات مكتملة الدعم', 'Funded Beneficiaries', 'الاحتياجات والتمويل', 'market_needs', 'مستفيد', 'integer', 'positive', 'عدد المستفيدين في البرامج مكتملة الدعم', 'sum', field='beneficiaries', filter_kwargs=(('status', 'complete'),)),
        KPIDef('needs_avg_beneficiaries', 'متوسط المستفيدين لكل احتياج', 'Avg Beneficiaries per Need', 'الاحتياجات والتمويل', 'market_needs', 'مستفيد', 'decimal', 'positive', 'متوسط عدد المستفيدين في كل بطاقة', 'avg', field='beneficiaries'),
        KPIDef('needs_cost_per_beneficiary', 'متوسط التكلفة لكل مستفيد', 'Cost per Beneficiary', 'الاحتياجات والتمويل', 'market_needs', 'ر.س', 'currency', 'negative', 'إجمالي التكلفة مقسومًا على إجمالي المستفيدين', 'custom', special='needs_cost_per_beneficiary'),
        KPIDef('needs_operational_count', 'احتياجات البرامج التشغيلية', 'Operational Training Needs', 'الاحتياجات والتمويل', 'market_needs', '', 'integer', 'positive', 'الاحتياجات المرتبطة ببرامج تشغيلية', 'count', filter_kwargs=(('training_type', 'operational'),)),
        KPIDef('needs_training_count', 'احتياجات البرامج التدريبية', 'Standard Training Needs', 'الاحتياجات والتمويل', 'market_needs', '', 'integer', 'neutral', 'الاحتياجات المرتبطة ببرامج تدريبية', 'count', filter_kwargs=(('training_type', 'training'),)),
        KPIDef('needs_last_30d', 'الاحتياجات المرصودة آخر 30 يومًا', 'Needs Observed (30d)', 'الاحتياجات والتمويل', 'market_needs', '', 'integer', 'positive', 'عدد الاحتياجات المرصودة خلال 30 يومًا', 'count', days_window=30, date_field='observed_on'),

        # === 2. الرعايات وبنود الصرف (16 KPIs) ===
        KPIDef('spon_total', 'إجمالي سجلات الرعاية', 'Total Sponsorships', 'الرعايات والتمويل', 'sponsorships', '', 'integer', 'neutral', 'إجمالي عروض وقرارات الرعاية', 'count'),
        KPIDef('spon_approved', 'الرعايات المعتمدة', 'Approved Sponsorships', 'الرعايات والتمويل', 'sponsorships', '', 'integer', 'positive', 'عدد الرعايات المعتمدة', 'count', filter_kwargs=(('status', 'approved'),)),
        KPIDef('spon_new', 'الرعايات قيد الدراسة', 'Pending Sponsorships', 'الرعايات والتمويل', 'sponsorships', '', 'integer', 'neutral', 'الرعايات الجديدة بانتظار القرار', 'count', filter_kwargs=(('status', 'new'),)),
        KPIDef('spon_rejected', 'الرعايات المرفوضة', 'Rejected Sponsorships', 'الرعايات والتمويل', 'sponsorships', '', 'integer', 'negative', 'عدد الرعايات المرفوضة', 'count', filter_kwargs=(('status', 'rejected'),)),
        KPIDef('spon_approval_rate', 'نسبة اعتماد الرعايات', 'Sponsorship Approval Rate', 'الرعايات والتمويل', 'sponsorships', '%', 'percent', 'positive', 'نسبة الرعايات المعتمدة من الإجمالي', 'ratio_pct', filter_kwargs=(('status', 'approved'),)),
        KPIDef('spon_rejection_rate', 'نسبة رفض الرعايات', 'Sponsorship Rejection Rate', 'الرعايات والتمويل', 'sponsorships', '%', 'percent', 'negative', 'نسبة الرعايات المرفوضة من الإجمالي', 'ratio_pct', filter_kwargs=(('status', 'rejected'),)),
        KPIDef('spon_approved_amount', 'إجمالي مبالغ الرعايات المعتمدة', 'Approved Sponsorship Amount', 'الرعايات والتمويل', 'sponsorships', 'ر.س', 'currency', 'positive', 'مجموع مبالغ الرعايات المعتمدة', 'sum', field='amount', filter_kwargs=(('status', 'approved'),)),
        KPIDef('spon_avg_amount', 'متوسط مبلغ الرعاية المعتمدة', 'Average Approved Sponsorship', 'الرعايات والتمويل', 'sponsorships', 'ر.س', 'currency', 'positive', 'متوسط مبلغ الرعاية الواحدة المعتمدة', 'avg', field='amount', filter_kwargs=(('status', 'approved'),)),
        KPIDef('spon_max_amount', 'أعلى مبلغ رعاية معتمدة', 'Highest Approved Sponsorship', 'الرعايات والتمويل', 'sponsorships', 'ر.س', 'currency', 'positive', 'أكبر قيمة رعاية معتمدة', 'max', field='amount', filter_kwargs=(('status', 'approved'),)),
        KPIDef('spon_distinct_needs', 'الاحتياجات المدعومة برعاية', 'Funded Distinct Needs', 'الرعايات والتمويل', 'sponsorships', '', 'integer', 'positive', 'عدد الاحتياجات الفريدة التي حصلت على رعاية معتمدة', 'count', field='need_id', filter_kwargs=(('status', 'approved'),), distinct=True),
        KPIDef('spon_distinct_partners', 'الجهات الراعية الفاعلة', 'Active Sponsor Organizations', 'الرعايات والتمويل', 'sponsorships', '', 'integer', 'positive', 'عدد الشراكات الفريدة ذات الرعايات المعتمدة', 'count', field='partnership_id', filter_kwargs=(('status', 'approved'),), distinct=True),
        KPIDef('spon_decided_30d', 'قرارات الرعاية آخر 30 يومًا', 'Sponsorships Decided (30d)', 'الرعايات والتمويل', 'sponsorships', '', 'integer', 'positive', 'عدد الرعايات التي اتُخذ قرار بشأنها خلال 30 يومًا', 'count', days_window=30, date_field='decided_at'),
        KPIDef('spon_created_30d', 'رعايات جديدة آخر 30 يومًا', 'New Sponsorships (30d)', 'الرعايات والتمويل', 'sponsorships', '', 'integer', 'positive', 'الرعايات المضافة خلال 30 يومًا', 'count', days_window=30, date_field='created_at'),
        KPIDef('exp_lines_total', 'إجمالي بنود الصرف المسجلة', 'Total Expense Lines', 'الرعايات والتمويل', 'expense_lines', '', 'integer', 'neutral', 'عدد بنود الصرف المرتبطة بالاحتياجات', 'count'),
        KPIDef('exp_lines_amount', 'إجمالي قيمة بنود الصرف', 'Total Expense Lines Value', 'الرعايات والتمويل', 'expense_lines', 'ر.س', 'currency', 'neutral', 'مجموع مبالغ بنود الصرف في الاحتياجات', 'sum', field='amount'),
        KPIDef('exp_lines_avg', 'متوسط قيمة بند الصرف', 'Average Expense Line Value', 'الرعايات والتمويل', 'expense_lines', 'ر.س', 'currency', 'neutral', 'متوسط المبلغ لكل بند صرف', 'avg', field='amount'),

        # === 3. الشراكات والجهات (22 KPIs) ===
        KPIDef('part_total', 'إجمالي الشراكات والجهات', 'Total Partnerships', 'الشراكات والاتفاقيات', 'partnerships', '', 'integer', 'positive', 'إجمالي الجهات المسجلة في منظومة الشراكات', 'count'),
        KPIDef('part_active', 'الشراكات النشطة', 'Active Partnerships', 'الشراكات والاتفاقيات', 'partnerships', '', 'integer', 'positive', 'عدد الشراكات النشطة حاليًا', 'count', filter_kwargs=(('is_active', True),)),
        KPIDef('part_inactive', 'الشراكات غير النشطة', 'Inactive Partnerships', 'الشراكات والاتفاقيات', 'partnerships', '', 'integer', 'negative', 'عدد الشراكات المعطلة أو غير النشطة', 'count', filter_kwargs=(('is_active', False),)),
        KPIDef('part_active_rate', 'نسبة نشاط الشراكات', 'Partnership Active Rate', 'الشراكات والاتفاقيات', 'partnerships', '%', 'percent', 'positive', 'نسبة الشراكات النشطة من الإجمالي', 'ratio_pct', filter_kwargs=(('is_active', True),)),
        KPIDef('part_local', 'الشراكات المحلية', 'Local Partnerships', 'الشراكات والاتفاقيات', 'partnerships', '', 'integer', 'neutral', 'الشراكات ذات النطاق المحلي', 'count', filter_kwargs=(('scope', 'local'),)),
        KPIDef('part_global', 'الشراكات العالمية', 'Global Partnerships', 'الشراكات والاتفاقيات', 'partnerships', '', 'integer', 'positive', 'الشراكات ذات النطاق العالمي', 'count', filter_kwargs=(('scope', 'global'),)),
        KPIDef('part_local_share', 'نسبة الشراكات المحلية', 'Local Partnerships Share', 'الشراكات والاتفاقيات', 'partnerships', '%', 'percent', 'neutral', 'نسبة الشراكات المحلية من الإجمالي', 'ratio_pct', filter_kwargs=(('scope', 'local'),)),
        KPIDef('part_stage_capability', 'جهات في مرحلة القدرة', 'Capability Stage Partners', 'الشراكات والاتفاقيات', 'partnerships', '', 'integer', 'neutral', 'الجهات المصنفة في مرحلة القدرة', 'count', filter_kwargs=(('development_state_id', 'capability'),)),
        KPIDef('part_stage_willingness', 'جهات في مرحلة الرغبة', 'Willingness Stage Partners', 'الشراكات والاتفاقيات', 'partnerships', '', 'integer', 'positive', 'الجهات التي وصلت لمرحلة الرغبة', 'count', filter_kwargs=(('development_state_id', 'willingness'),)),
        KPIDef('part_stage_care', 'جهات في مرحلة الرعاية', 'Care Stage Partners', 'الشراكات والاتفاقيات', 'partnerships', '', 'integer', 'positive', 'الجهات التي وصلت لمرحلة الرعاية الفعلية', 'count', filter_kwargs=(('development_state_id', 'care'),)),
        KPIDef('part_care_conversion', 'معدل التحويل لمرحلة الرعاية', 'Care Conversion Rate', 'الشراكات والاتفاقيات', 'partnerships', '%', 'percent', 'positive', 'نسبة الشراكات في مرحلة الرعاية من الإجمالي', 'ratio_pct', filter_kwargs=(('development_state_id', 'care'),)),
        KPIDef('part_total_capacity', 'إجمالي القدرة المالية للشركاء', 'Total Financial Capacity', 'الشراكات والاتفاقيات', 'partnerships', 'ر.س', 'currency', 'positive', 'مجموع القدرة المالية المسجلة للشركاء النشطين', 'sum', field='financial_capacity', filter_kwargs=(('is_active', True),)),
        KPIDef('part_avg_capacity', 'متوسط القدرة المالية للشريك', 'Avg Partner Financial Capacity', 'الشراكات والاتفاقيات', 'partnerships', 'ر.س', 'currency', 'positive', 'متوسط القدرة المالية للجهة الشريكة', 'avg', field='financial_capacity', filter_kwargs=(('is_active', True),)),
        KPIDef('part_max_capacity', 'أعلى قدرة مالية لشريك', 'Max Partner Financial Capacity', 'الشراكات والاتفاقيات', 'partnerships', 'ر.س', 'currency', 'positive', 'أعلى قدرة مالية مسجلة لجهة واحدة', 'max', field='financial_capacity'),
        KPIDef('part_with_agreement_no', 'شراكات برقم اتفاقية معتمد', 'Partnerships with Agreement #', 'الشراكات والاتفاقيات', 'partnerships', '', 'integer', 'positive', 'عدد الشراكات التي تحمل رقم اتفاقية رسمي', 'count', filter_kwargs=(('agreement_number__isnull', False),)),
        KPIDef('part_auto_renewal', 'شراكات بتجديد تلقائي', 'Auto-Renewal Partnerships', 'الشراكات والاتفاقيات', 'partnerships', '', 'integer', 'neutral', 'الشراكات التي تتجدد تلقائيًا', 'count', filter_kwargs=(('renewal_rule', 'automatic'),)),
        KPIDef('part_prior_renewal', 'شراكات بتجديد بموافقة مسبقة', 'Prior-Approval Renewal', 'الشراكات والاتفاقيات', 'partnerships', '', 'integer', 'neutral', 'الشراكات التي يتطلب تجديدها موافقة مسبقة', 'count', filter_kwargs=(('renewal_rule', 'prior_approval'),)),
        KPIDef('part_expiring_90d', 'شراكات تنتهي خلال 90 يومًا', 'Partnerships Expiring (90d)', 'الشراكات والاتفاقيات', 'partnerships', '', 'integer', 'negative', 'الشراكات النشطة التي ينتهي تاريخها خلال 90 يومًا', 'custom', special='part_expiring_90d'),
        KPIDef('part_expired', 'شراكات منتهية المدة', 'Expired Partnerships', 'الشراكات والاتفاقيات', 'partnerships', '', 'integer', 'negative', 'الشراكات التي تجاوزت تاريخ النهاية', 'custom', special='part_expired'),
        KPIDef('part_new_30d', 'شراكات جديدة آخر 30 يومًا', 'New Partnerships (30d)', 'الشراكات والاتفاقيات', 'partnerships', '', 'integer', 'positive', 'الشراكات المسجلة خلال آخر 30 يومًا', 'count', days_window=30, date_field='created_at'),
        KPIDef('part_offerings_total', 'إجمالي عروض الرعاية', 'Total Partnership Offerings', 'الشراكات والاتفاقيات', 'partnership_offerings', '', 'integer', 'positive', 'عدد مجالات وعروض الرعاية المسجلة للشركاء', 'count'),
        KPIDef('part_offerings_employment', 'عروض رعاية التوظيف', 'Employment Sponsorship Offerings', 'الشراكات والاتفاقيات', 'partnership_offerings', '', 'integer', 'positive', 'عروض الرعاية ذات شكل رعاية التوظيف', 'count', filter_kwargs=(('sponsorship_shape__is_employment', True), ('is_active', True))),

        # === 4. طلبات الرعاة الخارجيين (8 KPIs) ===
        KPIDef('sreq_total', 'إجمالي طلبات الرعاة الخارجيين', 'Total External Sponsor Requests', 'طلبات الرعاة', 'sponsor_requests', '', 'integer', 'neutral', 'جميع طلبات التسجيل الواردة من البوابة الخارجية', 'count'),
        KPIDef('sreq_new', 'طلبات رعاة بانتظار المراجعة', 'Pending Sponsor Requests', 'طلبات الرعاة', 'sponsor_requests', '', 'integer', 'negative', 'الطلبات الجديدة التي لم تُراجع بعد', 'count', filter_kwargs=(('status', 'new'),)),
        KPIDef('sreq_approved', 'طلبات رعاة معتمدة', 'Approved Sponsor Requests', 'طلبات الرعاة', 'sponsor_requests', '', 'integer', 'positive', 'الطلبات المعتمدة والمحوّلة لشراكات', 'count', filter_kwargs=(('status', 'approved'),)),
        KPIDef('sreq_rejected', 'طلبات رعاة مرفوضة', 'Rejected Sponsor Requests', 'طلبات الرعاة', 'sponsor_requests', '', 'integer', 'negative', 'الطلبات المرفوضة', 'count', filter_kwargs=(('status', 'rejected'),)),
        KPIDef('sreq_approval_rate', 'نسبة قبول طلبات الرعاة', 'Sponsor Request Approval Rate', 'طلبات الرعاة', 'sponsor_requests', '%', 'percent', 'positive', 'نسبة الطلبات المعتمدة من الإجمالي', 'ratio_pct', filter_kwargs=(('status', 'approved'),)),
        KPIDef('sreq_total_capacity', 'القدرة المالية لطلبات الرعاة', 'Requested Sponsor Capacity', 'طلبات الرعاة', 'sponsor_requests', 'ر.س', 'currency', 'positive', 'مجموع القدرة المالية المصرح بها في الطلبات', 'sum', field='financial_capacity'),
        KPIDef('sreq_new_30d', 'طلبات رعاة جديدة (30 يومًا)', 'New Sponsor Requests (30d)', 'طلبات الرعاة', 'sponsor_requests', '', 'integer', 'positive', 'الطلبات الواردة خلال آخر 30 يومًا', 'count', days_window=30, date_field='created_at'),
        KPIDef('sreq_overdue_7d', 'طلبات رعاة متأخرة (+7 أيام)', 'Overdue Sponsor Requests (>7d)', 'طلبات الرعاة', 'sponsor_requests', '', 'integer', 'negative', 'طلبات جديدة مضى عليها أكثر من 7 أيام دون مراجعة', 'custom', special='sreq_overdue_7d'),

        # === 5. تنفيذ البرامج ومزودو الخدمة (16 KPIs) ===
        KPIDef('exec_total', 'إجمالي ملفات تنفيذ البرامج', 'Total Program Executions', 'تنفيذ البرامج', 'need_executions', '', 'integer', 'neutral', 'إجمالي البرامج المعتمدة الداخلة في التنفيذ', 'count'),
        KPIDef('exec_new', 'برامج تنفيذ جديدة', 'New Executions', 'تنفيذ البرامج', 'need_executions', '', 'integer', 'neutral', 'البرامج بانتظار بدء التنفيذ', 'count', filter_kwargs=(('status', 'new'),)),
        KPIDef('exec_in_progress', 'برامج تحت التنفيذ', 'In-Progress Executions', 'تنفيذ البرامج', 'need_executions', '', 'integer', 'positive', 'البرامج الجارية حاليًا', 'count', filter_kwargs=(('status', 'in_progress'),)),
        KPIDef('exec_complete', 'برامج مكتملة التنفيذ', 'Completed Executions', 'تنفيذ البرامج', 'need_executions', '', 'integer', 'positive', 'البرامج التي اكتمل تنفيذها بالكامل', 'count', filter_kwargs=(('status', 'complete'),)),
        KPIDef('exec_completion_rate', 'نسبة إكمال تنفيذ البرامج', 'Execution Completion Rate', 'تنفيذ البرامج', 'need_executions', '%', 'percent', 'positive', 'نسبة البرامج المكتملة من إجمالي ملفات التنفيذ', 'ratio_pct', filter_kwargs=(('status', 'complete'),)),
        KPIDef('exec_completed_30d', 'برامج اكتمل تنفيذها (30 يومًا)', 'Executions Completed (30d)', 'تنفيذ البرامج', 'need_executions', '', 'integer', 'positive', 'البرامج المكتملة خلال آخر 30 يومًا', 'count', filter_kwargs=(('status', 'complete'),), days_window=30, date_field='completed_at'),
        KPIDef('prov_total', 'إجمالي مزودي خدمات التدريب', 'Total Service Providers', 'تنفيذ البرامج', 'service_providers', '', 'integer', 'positive', 'إجمالي مزودي التدريب المسجلين', 'count'),
        KPIDef('prov_active', 'مزودو التدريب النشطون', 'Active Service Providers', 'تنفيذ البرامج', 'service_providers', '', 'integer', 'positive', 'عدد المزودين النشطين حاليًا', 'count', filter_kwargs=(('is_active', True),)),
        KPIDef('prov_government', 'مزودو التدريب الحكوميون', 'Government Providers', 'تنفيذ البرامج', 'service_providers', '', 'integer', 'neutral', 'الوحدات التدريبية الحكومية', 'count', filter_kwargs=(('provider_type', 'government'),)),
        KPIDef('prov_private', 'مزودو التدريب الأهليون', 'Private Providers', 'تنفيذ البرامج', 'service_providers', '', 'integer', 'neutral', 'الوحدات التدريبية الأهلية', 'count', filter_kwargs=(('provider_type', 'private'),)),
        KPIDef('prov_private_share', 'نسبة المزودين الأهليين', 'Private Providers Share', 'تنفيذ البرامج', 'service_providers', '%', 'percent', 'neutral', 'نسبة الوحدات الأهلية من إجمالي المزودين', 'ratio_pct', filter_kwargs=(('provider_type', 'private'),)),
        KPIDef('prov_local', 'مزودون بنطاق محلي', 'Local Scope Providers', 'تنفيذ البرامج', 'service_providers', '', 'integer', 'neutral', 'مزودو التدريب ذوو النطاق المحلي', 'count', filter_kwargs=(('scope', 'local'),)),
        KPIDef('prov_global', 'مزودون بنطاق عالمي', 'Global Scope Providers', 'تنفيذ البرامج', 'service_providers', '', 'integer', 'positive', 'مزودو التدريب ذوو النطاق العالمي', 'count', filter_kwargs=(('scope', 'global'),)),
        KPIDef('prov_converted', 'مزودون محوّلون لشراكات', 'Providers Converted to Partnerships', 'تنفيذ البرامج', 'service_providers', '', 'integer', 'positive', 'مزودو الخدمة الذين تم تحويلهم إلى شراكات', 'count', filter_kwargs=(('converted_partnership__isnull', False),)),
        KPIDef('prov_coverage_total', 'سجلات التغطية الجغرافية للمزودين', 'Provider Coverage Records', 'تنفيذ البرامج', 'provider_coverage', '', 'integer', 'positive', 'عدد سجلات التغطية المناطقية للمزودين', 'count', filter_kwargs=(('is_active', True),)),
        KPIDef('prov_regions_covered', 'المناطق المغطاة بمزودي تدريب', 'Regions Covered by Providers', 'تنفيذ البرامج', 'provider_coverage', '', 'integer', 'positive', 'عدد المناطق الفريدة المغطاة بمزودي تدريب نشطين', 'count', field='region_id', filter_kwargs=(('is_active', True),), distinct=True),

        # === 6. الاتفاقيات وبنودها (10 KPIs) ===
        KPIDef('agr_total', 'إجمالي الاتفاقيات المسجلة', 'Total Agreements', 'الاتفاقيات والبنود', 'agreements', '', 'integer', 'positive', 'إجمالي الاتفاقيات المرتبطة بالشراكات', 'count'),
        KPIDef('agr_new_30d', 'اتفاقيات جديدة آخر 30 يومًا', 'New Agreements (30d)', 'الاتفاقيات والبنود', 'agreements', '', 'integer', 'positive', 'الاتفاقيات المنشأة خلال 30 يومًا', 'count', days_window=30, date_field='created_at'),
        KPIDef('clause_total', 'إجمالي بنود الاتفاقيات المسندة', 'Total Assigned Clauses', 'الاتفاقيات والبنود', 'clause_assignments', '', 'integer', 'neutral', 'عدد بنود الاتفاقيات قيد المتابعة', 'count'),
        KPIDef('clause_avg_progress', 'متوسط إنجاز بنود الاتفاقيات', 'Average Clause Progress %', 'الاتفاقيات والبنود', 'clause_assignments', '%', 'percent', 'positive', 'متوسط نسبة الإنجاز عبر جميع البنود', 'avg', field='progress'),
        KPIDef('clause_completed', 'بنود مكتملة الإنجاز (100%)', 'Completed Clauses (100%)', 'الاتفاقيات والبنود', 'clause_assignments', '', 'integer', 'positive', 'البنود التي بلغ إنجازها 100%', 'count', filter_kwargs=(('progress', 100),)),
        KPIDef('clause_unstarted', 'بنود لم تبدأ (0%)', 'Unstarted Clauses (0%)', 'الاتفاقيات والبنود', 'clause_assignments', '', 'integer', 'negative', 'البنود التي ما تزال نسبة إنجازها 0%', 'count', filter_kwargs=(('progress', 0),)),
        KPIDef('clause_completion_rate', 'نسبة اكتمال البنود', 'Clause Completion Rate', 'الاتفاقيات والبنود', 'clause_assignments', '%', 'percent', 'positive', 'نسبة البنود المكتملة 100% من الإجمالي', 'ratio_pct', filter_kwargs=(('progress', 100),)),
        KPIDef('clause_inst_resp', 'بنود بمسؤولية المؤسسة', 'Institution-Owned Clauses', 'الاتفاقيات والبنود', 'clause_assignments', '', 'integer', 'neutral', 'البنود المسندة لمسؤولية المؤسسة', 'count', filter_kwargs=(('responsibility', 'institution'),)),
        KPIDef('clause_partner_resp', 'بنود بمسؤولية الجهة', 'Partner-Owned Clauses', 'الاتفاقيات والبنود', 'clause_assignments', '', 'integer', 'neutral', 'البنود المسندة لمسؤولية الجهة الشريكة', 'count', filter_kwargs=(('responsibility', 'partner'),)),
        KPIDef('clause_shared_resp', 'بنود بمسؤولية مشتركة', 'Shared-Responsibility Clauses', 'الاتفاقيات والبنود', 'clause_assignments', '', 'integer', 'neutral', 'البنود ذات المسؤولية المشتركة', 'count', filter_kwargs=(('responsibility', 'shared'),)),

        # === 7. المهام والتكليفات (8 KPIs) ===
        KPIDef('work_total', 'إجمالي المهام والتكليفات', 'Total Work Assignments', 'المهام والمتابعة', 'work_assignments', '', 'integer', 'neutral', 'إجمالي المهام المسندة في النظام', 'count'),
        KPIDef('work_new', 'مهام جديدة', 'New Work Assignments', 'المهام والمتابعة', 'work_assignments', '', 'integer', 'neutral', 'المهام الجديدة التي لم تبدأ', 'count', filter_kwargs=(('status', 'new'),)),
        KPIDef('work_running', 'مهام قيد العمل', 'Running Work Assignments', 'المهام والمتابعة', 'work_assignments', '', 'integer', 'positive', 'المهام الجاري تنفيذها حاليًا', 'count', filter_kwargs=(('status', 'running'),)),
        KPIDef('work_complete', 'مهام مكتملة', 'Completed Work Assignments', 'المهام والمتابعة', 'work_assignments', '', 'integer', 'positive', 'المهام المنجزة بالكامل', 'count', filter_kwargs=(('status', 'complete'),)),
        KPIDef('work_cancelled', 'مهام ملغاة', 'Cancelled Work Assignments', 'المهام والمتابعة', 'work_assignments', '', 'integer', 'neutral', 'المهام الملغاة', 'count', filter_kwargs=(('status', 'cancelled'),)),
        KPIDef('work_completion_rate', 'نسبة إنجاز المهام', 'Work Completion Rate', 'المهام والمتابعة', 'work_assignments', '%', 'percent', 'positive', 'نسبة المهام المكتملة من الإجمالي', 'ratio_pct', filter_kwargs=(('status', 'complete'),)),
        KPIDef('work_avg_progress', 'متوسط تقدم المهام', 'Average Work Progress %', 'المهام والمتابعة', 'work_assignments', '%', 'percent', 'positive', 'متوسط نسبة التقدم للمهام النشطة', 'avg', field='progress'),
        KPIDef('work_overdue', 'مهام متأخرة عن موعدها', 'Overdue Work Assignments', 'المهام والمتابعة', 'work_assignments', '', 'integer', 'negative', 'المهام المفتوحة التي تجاوزت تاريخ الاستحقاق', 'custom', special='work_overdue'),

        # === 8. البيانات المرجعية والحوكمة (10 KPIs) ===
        KPIDef('ref_regions_active', 'المناطق الإدارية النشطة', 'Active Regions', 'البيانات المرجعية والحوكمة', 'regions', '', 'integer', 'neutral', 'عدد المناطق الإدارية المفعلة', 'count', filter_kwargs=(('is_active', True),)),
        KPIDef('ref_sectors_active', 'القطاعات النشطة', 'Active Sectors', 'البيانات المرجعية والحوكمة', 'sectors', '', 'integer', 'neutral', 'عدد القطاعات المعتمدة والنشطة', 'count', filter_kwargs=(('is_active', True),)),
        KPIDef('ref_specs_active', 'التخصصات النشطة', 'Active Specializations', 'البيانات المرجعية والحوكمة', 'specializations', '', 'integer', 'neutral', 'عدد التخصصات النشطة', 'count', filter_kwargs=(('is_active', True),)),
        KPIDef('ref_programs_active', 'البرامج التدريبية النشطة', 'Active Training Programs', 'البيانات المرجعية والحوكمة', 'training_programs', '', 'integer', 'positive', 'عدد البرامج التدريبية المعتمدة والنشطة', 'count', filter_kwargs=(('is_active', True),)),
        KPIDef('ref_programs_operational', 'البرامج التشغيلية النشطة', 'Active Operational Programs', 'البيانات المرجعية والحوكمة', 'training_programs', '', 'integer', 'positive', 'البرامج التي تدعم المسار التشغيلي', 'count', filter_kwargs=(('is_active', True), ('is_operational', True))),
        KPIDef('ref_entities_active', 'الكيانات النشطة', 'Active Entities', 'البيانات المرجعية والحوكمة', 'entities', '', 'integer', 'neutral', 'عدد الكيانات المصنفة والنشطة', 'count', filter_kwargs=(('is_active', True),)),
        KPIDef('ref_shapes_active', 'أشكال الرعاية النشطة', 'Active Sponsorship Shapes', 'البيانات المرجعية والحوكمة', 'sponsorship_shapes', '', 'integer', 'neutral', 'عدد أشكال الرعاية المعتمدة', 'count', filter_kwargs=(('is_active', True),)),
        KPIDef('ref_departments_active', 'الإدارات والوحدات النشطة', 'Active Departments', 'البيانات المرجعية والحوكمة', 'departments', '', 'integer', 'neutral', 'عدد الإدارات والوحدات التنظيمية النشطة', 'count', filter_kwargs=(('is_active', True),)),
        KPIDef('gov_activity_30d', 'إجمالي عمليات المستخدمين (30 يومًا)', 'User Actions (30d)', 'البيانات المرجعية والحوكمة', 'user_activity', '', 'integer', 'neutral', 'عدد العمليات المسجلة في سجل النشاط خلال 30 يومًا', 'count', days_window=30, date_field='created_at'),
        KPIDef('gov_denied_30d', 'محاولات وصول مرفوضة (30 يومًا)', 'Denied Access Attempts (30d)', 'البيانات المرجعية والحوكمة', 'user_activity', '', 'integer', 'negative', 'العمليات المرفوضة أمنيًا خلال آخر 30 يومًا', 'count', filter_kwargs=(('outcome', 'denied'),), days_window=30, date_field='created_at'),
    ]
    return {k.key: k for k in items}


KPI_REGISTRY = _build_kpi_registry()


def list_kpi_catalog(user):
    """Return RBAC-filtered catalog of all predefined KPIs."""
    out = []
    for kdef in KPI_REGISTRY.values():
        if not user_can_view_entity(user, kdef.entity_key):
            continue
        out.append({
            'key': kdef.key,
            'title_ar': kdef.title_ar,
            'title_en': kdef.title_en,
            'category_ar': kdef.category_ar,
            'entity_key': kdef.entity_key,
            'entity_label_ar': ENTITY_REGISTRY[kdef.entity_key].label_ar,
            'unit': kdef.unit,
            'format_type': kdef.format_type,
            'trend_semantics': kdef.trend_semantics,
            'description_ar': kdef.description_ar,
        })
    return out


def _eval_kpi_on_qs(kdef, qs):
    today = timezone.localdate()
    now = timezone.now()

    if kdef.calc_kind == 'custom':
        if kdef.special == 'needs_funding_gap':
            agg = qs.aggregate(req=Sum('requested_support'), app=Sum('approved_support'))
            req = float(agg['req'] or 0)
            app = float(agg['app'] or 0)
            return round(max(0.0, req - app), 2)
        if kdef.special == 'needs_coverage_pct':
            agg = qs.aggregate(req=Sum('requested_support'), app=Sum('approved_support'))
            req = float(agg['req'] or 0)
            app = float(agg['app'] or 0)
            return round((app / req * 100.0), 1) if req > 0 else 0.0
        if kdef.special == 'needs_cost_per_beneficiary':
            agg = qs.aggregate(cost=Sum('total_cost'), ben=Sum('beneficiaries'))
            cost = float(agg['cost'] or 0)
            ben = float(agg['ben'] or 0)
            return round(cost / ben, 2) if ben > 0 else 0.0
        if kdef.special == 'part_expiring_90d':
            return qs.filter(is_active=True, ends_on__gte=today, ends_on__lte=today + timedelta(days=90)).count()
        if kdef.special == 'part_expired':
            return qs.filter(ends_on__lt=today).count()
        if kdef.special == 'sreq_overdue_7d':
            return qs.filter(status='new', created_at__lt=now - timedelta(days=7)).count()
        if kdef.special == 'work_overdue':
            return qs.filter(status__in=['new', 'running'], due_on__lt=today).count()
        return 0

    work_qs = qs
    if kdef.days_window and kdef.date_field:
        fmap = get_field_map(kdef.entity_key)
        is_dt = fmap.get(kdef.date_field, {}).get('data_type') == 'datetime'
        cutoff = now - timedelta(days=kdef.days_window) if is_dt else today - timedelta(days=kdef.days_window)
        work_qs = work_qs.filter(**{f'{kdef.date_field}__gte': cutoff})

    if kdef.calc_kind == 'ratio_pct':
        denom_qs = work_qs.filter(**dict(kdef.denom_filter_kwargs)) if kdef.denom_filter_kwargs else work_qs
        num_qs = work_qs.filter(**dict(kdef.filter_kwargs)) if kdef.filter_kwargs else work_qs
        denom = denom_qs.count()
        if denom == 0:
            return 0.0
        return round((num_qs.count() / denom) * 100.0, 1)

    if kdef.filter_kwargs:
        work_qs = work_qs.filter(**dict(kdef.filter_kwargs))

    if kdef.calc_kind == 'count':
        if kdef.distinct:
            return work_qs.aggregate(v=Count(kdef.field, distinct=True))['v'] or 0
        return work_qs.count()
    if kdef.calc_kind == 'sum':
        val = work_qs.aggregate(v=Sum(kdef.field))['v']
        return round(float(val or 0), 2)
    if kdef.calc_kind == 'avg':
        val = work_qs.aggregate(v=Avg(kdef.field))['v']
        return round(float(val or 0), 2)
    if kdef.calc_kind == 'max':
        val = work_qs.aggregate(v=Max(kdef.field))['v']
        return round(float(val or 0), 2)
    return 0


def evaluate_predefined_kpi(user, kpi_key, global_filters=None, *, target=None, thresholds=None):
    """Evaluate a predefined KPI with optional period comparison and target progress."""
    kdef = KPI_REGISTRY.get(kpi_key)
    if not kdef:
        raise QueryValidationError(f'مؤشر الأداء غير معروف: {kpi_key}')
    if not user_can_view_entity(user, kdef.entity_key):
        raise PermissionError(f'لا تملك صلاحية عرض المؤشر: {kdef.title_ar}')

    qs = scoped_queryset(kdef.entity_key, user)
    qs, applied_globals = apply_global_filters(qs, kdef.entity_key, global_filters, user)
    value = _eval_kpi_on_qs(kdef, qs)

    # Lightweight 30d vs prior 30d delta when entity has a date field and no manual date filter
    delta_pct = None
    edef = ENTITY_REGISTRY[kdef.entity_key]
    df = edef.default_date_field
    if df and not (global_filters or {}).get('date_from') and not kdef.days_window:
        fmap = get_field_map(kdef.entity_key)
        if df in fmap:
            is_dt = fmap[df]['data_type'] == 'datetime'
            now = timezone.now()
            today = timezone.localdate()
            c1 = now - timedelta(days=30) if is_dt else today - timedelta(days=30)
            c2 = now - timedelta(days=60) if is_dt else today - timedelta(days=60)
            cur_v = _eval_kpi_on_qs(kdef, qs.filter(**{f'{df}__gte': c1}))
            prev_v = _eval_kpi_on_qs(kdef, qs.filter(**{f'{df}__gte': c2, f'{df}__lt': c1}))
            if prev_v and prev_v != 0:
                delta_pct = round(((cur_v - prev_v) / abs(prev_v)) * 100.0, 1)

    status_tone = 'neutral'
    if thresholds and isinstance(thresholds, dict):
        warn = thresholds.get('warning')
        danger = thresholds.get('danger')
        good = thresholds.get('good')
        if danger is not None and value <= float(danger) and kdef.trend_semantics == 'positive':
            status_tone = 'danger'
        elif danger is not None and value >= float(danger) and kdef.trend_semantics == 'negative':
            status_tone = 'danger'
        elif warn is not None and ((kdef.trend_semantics == 'positive' and value <= float(warn)) or (kdef.trend_semantics == 'negative' and value >= float(warn))):
            status_tone = 'warning'
        elif good is not None and ((kdef.trend_semantics == 'positive' and value >= float(good)) or (kdef.trend_semantics == 'negative' and value <= float(good))):
            status_tone = 'success'

    target_pct = None
    if target is not None:
        try:
            t_num = float(target)
            if t_num > 0:
                target_pct = round(min(200.0, (float(value) / t_num) * 100.0), 1)
        except (TypeError, ValueError):
            pass

    return {
        'key': kdef.key,
        'title_ar': kdef.title_ar,
        'category_ar': kdef.category_ar,
        'entity_key': kdef.entity_key,
        'value': value,
        'unit': kdef.unit,
        'format_type': kdef.format_type,
        'trend_semantics': kdef.trend_semantics,
        'delta_pct': delta_pct,
        'target': target,
        'target_pct': target_pct,
        'status_tone': status_tone,
        'description_ar': kdef.description_ar,
        'applied_global_filters': applied_globals,
    }


def _eval_single_metric(user, metric_cfg, global_filters=None):
    entity_key = metric_cfg.get('entity')
    if not entity_key or entity_key not in ENTITY_REGISTRY:
        raise QueryValidationError('يرجى اختيار مصدر بيانات للمؤشر المخصص.')
    if not user_can_view_entity(user, entity_key):
        raise PermissionError(f'لا تملك صلاحية عرض {ENTITY_REGISTRY[entity_key].label_ar}.')

    field_name = metric_cfg.get('field') or 'id'
    agg = str(metric_cfg.get('aggregation') or 'count').lower()
    fmap = get_field_map(entity_key)
    if field_name not in fmap:
        raise QueryValidationError(f'الحقل "{field_name}" غير متاح في {ENTITY_REGISTRY[entity_key].label_ar}.')

    qs = scoped_queryset(entity_key, user)
    if fmap[field_name].get('is_calculated'):
        qs = apply_calculated_annotations(qs, entity_key, {field_name})
    qs, _ = apply_global_filters(qs, entity_key, global_filters, user)
    if metric_cfg.get('filters'):
        qs = qs.filter(_build_q_from_filter_node(entity_key, metric_cfg['filters'], user))

    if agg == 'count':
        return float(qs.count())
    if agg == 'count_distinct':
        return float(qs.aggregate(v=Count(field_name, distinct=True))['v'] or 0)
    if agg == 'sum':
        return float(qs.aggregate(v=Sum(field_name))['v'] or 0)
    if agg == 'avg':
        return float(qs.aggregate(v=Avg(field_name))['v'] or 0)
    if agg == 'min':
        return float(qs.aggregate(v=Min(field_name))['v'] or 0)
    if agg == 'max':
        return float(qs.aggregate(v=Max(field_name))['v'] or 0)
    raise QueryValidationError(f'عملية التجميع غير مدعومة: {agg}')


def evaluate_custom_kpi(user, spec, global_filters=None):
    """Evaluate a safe typed custom KPI (single, ratio, percentage, difference)."""
    formula_type = str(spec.get('formula_type') or 'single').lower()
    primary = spec.get('primary') or {
        'entity': spec.get('entity'),
        'field': spec.get('field', 'id'),
        'aggregation': spec.get('aggregation', 'count'),
        'filters': spec.get('filters'),
    }
    num = _eval_single_metric(user, primary, global_filters=global_filters)

    if formula_type == 'single':
        value = round(num, 2)
    else:
        secondary = spec.get('secondary')
        if not secondary:
            raise QueryValidationError('المؤشر المركب يتطلب مقياسًا ثانيًا (المقام أو المقارنة).')
        den = _eval_single_metric(user, secondary, global_filters=global_filters)
        if formula_type == 'difference':
            value = round(num - den, 2)
        elif formula_type == 'ratio':
            value = round(num / den, 2) if den != 0 else 0.0
        elif formula_type == 'percentage':
            value = round((num / den) * 100.0, 1) if den != 0 else 0.0
        else:
            raise QueryValidationError(f'نوع المعادلة غير مدعوم: {formula_type}')

    target = spec.get('target')
    target_pct = None
    if target is not None:
        try:
            t_num = float(target)
            if t_num > 0:
                target_pct = round(min(200.0, (float(value) / t_num) * 100.0), 1)
        except (TypeError, ValueError):
            pass

    return {
        'title_ar': spec.get('title') or 'مؤشر مخصص',
        'value': value,
        'unit': spec.get('unit') or ('%' if formula_type == 'percentage' else ''),
        'format_type': spec.get('format_type') or ('percent' if formula_type == 'percentage' else 'decimal'),
        'trend_semantics': spec.get('trend_semantics') or 'positive',
        'target': target,
        'target_pct': target_pct,
        'formula_type': formula_type,
        'description_ar': spec.get('description') or '',
    }
