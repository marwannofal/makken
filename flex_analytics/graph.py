"""Intelligent Relationship Graph Engine for Makken Analytics.

Discovers approved join paths between analytics-enabled entities, detects
cycles and ambiguity, flags to-many fan-out risk, and blocks unrelated
entity combinations with a clear Arabic explanation.
"""
from collections import deque
from dataclasses import dataclass
from .semantic import ENTITY_REGISTRY, user_can_view_entity


UNRELATED_MESSAGE_AR = (
    'لا يمكن إضافة هذا الكيان إلى الجدول لعدم وجود علاقة مع مصادر البيانات المحددة.'
)
MAX_JOIN_DEPTH = 3


@dataclass(frozen=True)
class RelationEdge:
    source: str
    target: str
    lookup: str
    cardinality: str  # 'to_one' or 'to_many'
    label_ar: str


# Explicit approved bidirectional edges verified against real Makken models.py
APPROVED_EDGES = (
    # Market Needs
    RelationEdge('market_needs', 'sectors', 'sector', 'to_one', 'القطاع'),
    RelationEdge('sectors', 'market_needs', 'need', 'to_many', 'احتياجات السوق'),

    RelationEdge('market_needs', 'specializations', 'specialization', 'to_one', 'التخصص'),
    RelationEdge('specializations', 'market_needs', 'need', 'to_many', 'احتياجات السوق'),

    RelationEdge('market_needs', 'regions', 'regions', 'to_many', 'المناطق'),
    RelationEdge('regions', 'market_needs', 'market_needs', 'to_many', 'احتياجات السوق'),

    RelationEdge('market_needs', 'training_programs', 'program', 'to_one', 'البرنامج التدريبي'),
    RelationEdge('training_programs', 'market_needs', 'need', 'to_many', 'احتياجات السوق'),

    RelationEdge('market_needs', 'sponsorships', 'sponsorships', 'to_many', 'الرعايات'),
    RelationEdge('sponsorships', 'market_needs', 'need', 'to_one', 'حاجة السوق'),

    RelationEdge('market_needs', 'expense_lines', 'expense_lines', 'to_many', 'بنود الصرف'),
    RelationEdge('expense_lines', 'market_needs', 'need', 'to_one', 'حاجة السوق'),

    RelationEdge('market_needs', 'need_executions', 'execution', 'to_one', 'حالة التنفيذ'),
    RelationEdge('need_executions', 'market_needs', 'need', 'to_one', 'حاجة السوق'),

    # Expense Lines
    RelationEdge('expense_lines', 'expense_items', 'expense_item', 'to_one', 'بند الصرف'),
    RelationEdge('expense_items', 'expense_lines', 'expenseline', 'to_many', 'بنود صرف الاحتياجات'),

    RelationEdge('expense_lines', 'sponsorship_shapes', 'sponsorship_shape', 'to_one', 'شكل الرعاية'),
    RelationEdge('sponsorship_shapes', 'expense_lines', 'expenseline', 'to_many', 'بنود صرف الاحتياجات'),

    # Sponsorships
    RelationEdge('sponsorships', 'partnerships', 'partnership', 'to_one', 'الجهة الراعية'),
    RelationEdge('partnerships', 'sponsorships', 'market_sponsorships', 'to_many', 'الرعايات'),

    RelationEdge('sponsorships', 'levels', 'level', 'to_one', 'مستوى الرعاية'),
    RelationEdge('levels', 'sponsorships', 'sponsorship', 'to_many', 'الرعايات'),

    # Program Execution
    RelationEdge('need_executions', 'service_providers', 'provider_links__provider', 'to_many', 'مزودو التدريب'),
    RelationEdge('service_providers', 'need_executions', 'execution_links__execution', 'to_many', 'عمليات التنفيذ'),

    RelationEdge('need_executions', 'partnerships', 'employer_links__partnership', 'to_many', 'جهات التوظيف'),
    RelationEdge('partnerships', 'need_executions', 'execution_links__execution', 'to_many', 'عمليات التوظيف'),

    # Partnerships
    RelationEdge('partnerships', 'entities', 'entity', 'to_one', 'الكيان'),
    RelationEdge('entities', 'partnerships', 'partnerships', 'to_many', 'الشراكات'),

    RelationEdge('partnerships', 'regions', 'administrative_regions', 'to_many', 'المناطق الإدارية'),
    RelationEdge('regions', 'partnerships', 'administrative_partnerships', 'to_many', 'الشراكات'),

    RelationEdge('partnerships', 'departments', 'concerned_departments', 'to_many', 'الإدارات المعنية'),
    RelationEdge('departments', 'partnerships', 'partnerships', 'to_many', 'الشراكات'),

    RelationEdge('partnerships', 'partnership_offerings', 'offerings', 'to_many', 'عروض الرعاية'),
    RelationEdge('partnership_offerings', 'partnerships', 'partnership', 'to_one', 'الشراكة'),

    RelationEdge('partnerships', 'agreements', 'agreements', 'to_many', 'الاتفاقيات'),
    RelationEdge('agreements', 'partnerships', 'partnership', 'to_one', 'الشراكة'),

    RelationEdge('partnerships', 'clause_assignments', 'clause_assignments', 'to_many', 'بنود الاتفاقيات'),
    RelationEdge('clause_assignments', 'partnerships', 'partnership', 'to_one', 'الشراكة'),

    # Partnership Offerings
    RelationEdge('partnership_offerings', 'sectors', 'sector', 'to_one', 'القطاع'),
    RelationEdge('sectors', 'partnership_offerings', 'partnership_offerings', 'to_many', 'عروض الرعاية'),

    RelationEdge('partnership_offerings', 'specializations', 'specializations', 'to_many', 'التخصصات'),
    RelationEdge('specializations', 'partnership_offerings', 'partnership_offerings', 'to_many', 'عروض الرعاية'),

    RelationEdge('partnership_offerings', 'sponsorship_shapes', 'sponsorship_shape', 'to_one', 'شكل الرعاية'),
    RelationEdge('sponsorship_shapes', 'partnership_offerings', 'partnership_offerings', 'to_many', 'عروض الرعاية'),

    # Sponsor Registration Requests
    RelationEdge('sponsor_requests', 'entities', 'entity', 'to_one', 'الكيان'),
    RelationEdge('entities', 'sponsor_requests', 'sponsor_requests', 'to_many', 'طلبات الرعاة'),

    RelationEdge('sponsor_requests', 'regions', 'administrative_regions', 'to_many', 'المناطق'),
    RelationEdge('regions', 'sponsor_requests', 'sponsor_requests', 'to_many', 'طلبات الرعاة'),

    RelationEdge('sponsor_requests', 'sectors', 'sector', 'to_one', 'القطاع'),
    RelationEdge('sectors', 'sponsor_requests', 'sponsor_requests', 'to_many', 'طلبات الرعاة'),

    RelationEdge('sponsor_requests', 'sponsorship_shapes', 'sponsorship_shape', 'to_one', 'شكل الرعاية'),
    RelationEdge('sponsorship_shapes', 'sponsor_requests', 'sponsor_requests', 'to_many', 'طلبات الرعاة'),

    RelationEdge('sponsor_requests', 'partnerships', 'created_partnership', 'to_one', 'الشراكة المنشأة'),

    # Service Providers & Coverage
    RelationEdge('service_providers', 'training_programs', 'program', 'to_one', 'البرنامج'),
    RelationEdge('training_programs', 'service_providers', 'service_providers', 'to_many', 'مزودو الخدمة'),

    RelationEdge('service_providers', 'provider_coverage', 'coverage', 'to_many', 'التغطية الجغرافية'),
    RelationEdge('provider_coverage', 'service_providers', 'provider', 'to_one', 'مزود الخدمة'),

    RelationEdge('provider_coverage', 'regions', 'region', 'to_one', 'المنطقة'),
    RelationEdge('regions', 'provider_coverage', 'service_provider_coverage', 'to_many', 'تغطية المزودين'),

    RelationEdge('provider_coverage', 'specializations', 'specializations', 'to_many', 'التخصصات'),
    RelationEdge('specializations', 'provider_coverage', 'provider_coverage', 'to_many', 'تغطية المزودين'),

    # Specializations -> Sectors
    RelationEdge('specializations', 'sectors', 'sector', 'to_one', 'القطاع'),
    RelationEdge('sectors', 'specializations', 'specializations', 'to_many', 'التخصصات'),

    # Training Programs -> Expense Items
    RelationEdge('training_programs', 'expense_items', 'expense_items', 'to_many', 'بنود الصرف'),
    RelationEdge('expense_items', 'training_programs', 'training_programs', 'to_many', 'البرامج التدريبية'),

    # Agreements -> Clause Assignments
    RelationEdge('agreements', 'clause_assignments', 'clause_assignments', 'to_many', 'بنود الاتفاقية'),
    RelationEdge('clause_assignments', 'agreements', 'agreement', 'to_one', 'الاتفاقية'),
)


def _build_adjacency(allowed_keys):
    adj = {k: [] for k in allowed_keys}
    for edge in APPROVED_EDGES:
        if edge.source in allowed_keys and edge.target in allowed_keys:
            adj[edge.source].append(edge)
    return adj


def find_shortest_paths(base_entity, target_entity, allowed_keys, max_depth=MAX_JOIN_DEPTH):
    """BFS returning all shortest cycle-free edge paths from base_entity to target_entity."""
    if base_entity not in allowed_keys or target_entity not in allowed_keys:
        return []
    if base_entity == target_entity:
        return [[]]
    adj = _build_adjacency(allowed_keys)
    queue = deque([(base_entity, [])])
    best_depth = None
    paths = []
    visited_depth = {base_entity: 0}

    while queue:
        node, path = queue.popleft()
        depth = len(path)
        if best_depth is not None and depth >= best_depth:
            continue
        if depth >= max_depth:
            continue
        for edge in adj.get(node, ()):
            nxt = edge.target
            if any(e.source == nxt or e.target == nxt for e in path):
                continue  # Cycle protection
            next_depth = depth + 1
            if nxt == target_entity:
                best_depth = next_depth
                paths.append(path + [edge])
                continue
            prev_best = visited_depth.get(nxt)
            if prev_best is None or next_depth <= prev_best:
                visited_depth[nxt] = next_depth
                queue.append((nxt, path + [edge]))
    return paths


def resolve_join_path(base_entity, target_entity, user, preferred_lookup=None):
    """Resolve an approved ORM join lookup prefix between two entities for a user."""
    allowed = {k for k in ENTITY_REGISTRY if user_can_view_entity(user, k)}
    if base_entity == target_entity and base_entity in allowed:
        return {
            'compatible': True,
            'relation_type': 'self',
            'lookup_prefix': '',
            'depth': 0,
            'has_to_many': False,
            'ambiguous': False,
            'alternatives': [],
        }
    paths = find_shortest_paths(base_entity, target_entity, allowed)
    if not paths:
        return {
            'compatible': False,
            'relation_type': 'unrelated',
            'lookup_prefix': None,
            'depth': None,
            'has_to_many': False,
            'ambiguous': False,
            'message_ar': UNRELATED_MESSAGE_AR,
            'alternatives': [],
        }

    # Prefer paths with fewer to-many hops to reduce fan-out risk
    paths.sort(key=lambda p: (sum(1 for e in p if e.cardinality == 'to_many'), '__'.join(e.lookup for e in p)))
    chosen = paths[0]
    if preferred_lookup:
        for p in paths:
            if '__'.join(e.lookup for e in p) == preferred_lookup:
                chosen = p
                break

    prefix = '__'.join(e.lookup for e in chosen)
    has_to_many = any(e.cardinality == 'to_many' for e in chosen)
    alternatives = [
        {
            'lookup_prefix': '__'.join(e.lookup for e in p),
            'labels_ar': [e.label_ar for e in p],
            'has_to_many': any(e.cardinality == 'to_many' for e in p),
        }
        for p in paths
    ]
    return {
        'compatible': True,
        'relation_type': 'direct' if len(chosen) == 1 else 'indirect',
        'lookup_prefix': prefix,
        'depth': len(chosen),
        'has_to_many': has_to_many,
        'ambiguous': len(paths) > 1,
        'labels_ar': [e.label_ar for e in chosen],
        'alternatives': alternatives,
    }


def compatibility_for_selection(base_entity, user):
    """Return compatibility status for every accessible entity relative to base_entity."""
    allowed = [k for k in ENTITY_REGISTRY if user_can_view_entity(user, k)]
    if base_entity not in allowed:
        return {'base_entity': base_entity, 'compatible': [], 'unrelated': [], 'error': 'الكيان الأساسي غير متاح.'}

    compatible = []
    unrelated = []
    for key in allowed:
        edef = ENTITY_REGISTRY[key]
        info = resolve_join_path(base_entity, key, user)
        item = {
            'key': key,
            'label_ar': edef.label_ar,
            'label_en': edef.label_en,
            'category_ar': edef.category_ar,
            **info,
        }
        if info['compatible']:
            compatible.append(item)
        else:
            unrelated.append(item)
    return {
        'base_entity': base_entity,
        'compatible': compatible,
        'unrelated': unrelated,
        'unrelated_message_ar': UNRELATED_MESSAGE_AR,
    }


def serialize_graph(user):
    """Return full nodes & edges list for accessible entities."""
    allowed = {k for k in ENTITY_REGISTRY if user_can_view_entity(user, k)}
    nodes = [
        {
            'key': k,
            'label_ar': ENTITY_REGISTRY[k].label_ar,
            'category_ar': ENTITY_REGISTRY[k].category_ar,
        }
        for k in ENTITY_REGISTRY if k in allowed
    ]
    edges = [
        {
            'source': e.source,
            'target': e.target,
            'lookup': e.lookup,
            'cardinality': e.cardinality,
            'label_ar': e.label_ar,
        }
        for e in APPROVED_EDGES
        if e.source in allowed and e.target in allowed
    ]
    return {'nodes': nodes, 'edges': edges, 'max_depth': MAX_JOIN_DEPTH}
