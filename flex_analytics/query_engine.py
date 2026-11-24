"""Universal Safe ORM Query Engine for المؤشرات والتحليلات المرنة.

Executes validated Django ORM queries for tables, charts, custom metrics,
filters, drill-downs, and exports with strict RBAC, regional scoping,
relationship-graph verification, and fan-out protection. Zero raw SQL.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
from statistics import median as py_median

from django.core.cache import cache
from django.db.models import Avg, Count, Max, Min, Q, Sum
from django.db.models.functions import TruncDay, TruncMonth, TruncQuarter, TruncWeek, TruncYear
from django.utils import timezone

from access_control.regions import RegionalPolicy
from .graph import UNRELATED_MESSAGE_AR, resolve_join_path
from .semantic import (
    BLOCKED_FIELD_NAMES,
    ENTITY_REGISTRY,
    apply_calculated_annotations,
    get_field_map,
    scoped_queryset,
    user_can_view_entity,
)


MAX_RAW_ROWS = 500
MAX_GROUP_ROWS = 200
MAX_EXPORT_ROWS = 5000
CACHE_TTL_SECONDS = 30

TRUNC_MAP = {
    'day': TruncDay,
    'week': TruncWeek,
    'month': TruncMonth,
    'quarter': TruncQuarter,
    'year': TruncYear,
}

ALLOWED_AGGS = {'count', 'count_distinct', 'sum', 'avg', 'min', 'max', 'median'}
ALLOWED_OPS = {'eq', 'neq', 'contains', 'gt', 'gte', 'lt', 'lte', 'in', 'between', 'is_null', 'not_null'}


class QueryValidationError(ValueError):
    """Raised when an analytics query specification is invalid or unsafe."""


def _to_json_value(val, choices_map=None):
    if val is None:
        return None
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, (datetime, date)):
        return val.isoformat()
    if isinstance(val, bool):
        return val
    if choices_map and str(val) in choices_map:
        return choices_map[str(val)]
    return val


def _choice_map_for(entity_key, field_name):
    fmeta = get_field_map(entity_key).get(field_name)
    if not fmeta or not fmeta.get('choices'):
        return {}
    return {c['value']: c['label'] for c in fmeta['choices']}


def _resolve_field_lookup(base_entity, entity_key, field_name, user, preferred_lookup=None):
    """Validate entity + field access and return (orm_lookup, field_meta, has_to_many)."""
    entity_key = entity_key or base_entity
    if entity_key not in ENTITY_REGISTRY:
        raise QueryValidationError(f'مصدر البيانات غير معروف: {entity_key}')
    if not user_can_view_entity(user, entity_key):
        raise PermissionError(f'لا تملك صلاحية عرض مصدر البيانات: {ENTITY_REGISTRY[entity_key].label_ar}')
    if not field_name or field_name in BLOCKED_FIELD_NAMES:
        raise QueryValidationError('الحقل المحدد غير مسموح به أو غير صالح.')
    fmap = get_field_map(entity_key)
    if field_name not in fmap:
        raise QueryValidationError(f'الحقل "{field_name}" غير متاح في {ENTITY_REGISTRY[entity_key].label_ar}.')
    fmeta = fmap[field_name]
    if entity_key == base_entity:
        return field_name, fmeta, False
    if fmeta.get('is_calculated'):
        raise QueryValidationError('الحقول المحسوبة متاحة فقط للكيان الأساسي المختار.')
    join_info = resolve_join_path(base_entity, entity_key, user, preferred_lookup=preferred_lookup)
    if not join_info['compatible']:
        raise QueryValidationError(UNRELATED_MESSAGE_AR)
    return f"{join_info['lookup_prefix']}__{field_name}", fmeta, join_info['has_to_many']


def _coerce_value(val, data_type):
    if val is None or val == '':
        return None
    if data_type == 'boolean':
        if isinstance(val, bool):
            return val
        return str(val).lower() in {'1', 'true', 'yes', 'نعم'}
    if data_type == 'integer':
        try:
            return int(val)
        except (TypeError, ValueError):
            raise QueryValidationError(f'قيمة رقمية صحيحة غير صالحة: {val}')
    if data_type in {'decimal', 'currency', 'percentage'}:
        try:
            return Decimal(str(val))
        except Exception:
            raise QueryValidationError(f'قيمة رقمية غير صالحة: {val}')
    return val


def _build_q_from_filter_node(base_entity, node, user):
    """Recursively build a safe Django Q object from a validated filter tree."""
    if not isinstance(node, dict):
        return Q()
    if 'conditions' in node:
        logic = str(node.get('logic', 'AND')).upper()
        combined = Q()
        first = True
        for child in node.get('conditions', []):
            cq = _build_q_from_filter_node(base_entity, child, user)
            if first:
                combined = cq
                first = False
            elif logic == 'OR':
                combined |= cq
            else:
                combined &= cq
        return combined

    entity_key = node.get('entity') or base_entity
    field_name = node.get('field')
    op = str(node.get('op', 'eq')).lower()
    value = node.get('value')
    if not field_name or op not in ALLOWED_OPS:
        return Q()

    lookup, fmeta, _ = _resolve_field_lookup(base_entity, entity_key, field_name, user)
    dtype = fmeta['data_type']

    if op == 'is_null':
        return Q(**{f'{lookup}__isnull': True})
    if op == 'not_null':
        return Q(**{f'{lookup}__isnull': False})
    if op == 'in':
        vals = value if isinstance(value, list) else [v.strip() for v in str(value).split(',') if v.strip()]
        coerced = [_coerce_value(v, dtype) for v in vals]
        return Q(**{f'{lookup}__in': coerced}) if coerced else Q()
    if op == 'between':
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return Q()
        lo = _coerce_value(value[0], dtype)
        hi = _coerce_value(value[1], dtype)
        q = Q()
        if lo is not None:
            q &= Q(**{f'{lookup}__gte': lo})
        if hi is not None:
            q &= Q(**{f'{lookup}__lte': hi})
        return q

    coerced = _coerce_value(value, dtype)
    if coerced is None:
        return Q()
    if op == 'eq':
        return Q(**{lookup: coerced})
    if op == 'neq':
        return ~Q(**{lookup: coerced})
    if op == 'contains':
        return Q(**{f'{lookup}__icontains': str(coerced)})
    if op in {'gt', 'gte', 'lt', 'lte'}:
        return Q(**{f'{lookup}__{op}': coerced})
    return Q()


def apply_global_filters(qs, base_entity, global_filters, user):
    """Apply dashboard/section-level filters safely only when semantically compatible."""
    if not isinstance(global_filters, dict) or not global_filters:
        return qs, []
    applied = []
    edef = ENTITY_REGISTRY[base_entity]
    fmap = get_field_map(base_entity)

    # 1. Date range filter
    date_from = global_filters.get('date_from')
    date_to = global_filters.get('date_to')
    preset = global_filters.get('date_preset')
    if preset and not (date_from or date_to):
        today = timezone.localdate()
        if preset == '7d':
            date_from = (today - timedelta(days=7)).isoformat()
        elif preset == '30d':
            date_from = (today - timedelta(days=30)).isoformat()
        elif preset == '90d':
            date_from = (today - timedelta(days=90)).isoformat()
        elif preset == '365d':
            date_from = (today - timedelta(days=365)).isoformat()
        elif preset == 'ytd':
            date_from = date(today.year, 1, 1).isoformat()

    date_field = edef.default_date_field
    if date_field and date_field in fmap and (date_from or date_to):
        is_dt = fmap[date_field]['data_type'] == 'datetime'
        suffix = '__date' if is_dt else ''
        if date_from:
            qs = qs.filter(**{f'{date_field}{suffix}__gte': date_from})
            applied.append('date_from')
        if date_to:
            qs = qs.filter(**{f'{date_field}{suffix}__lte': date_to})
            applied.append('date_to')

    # 2. Region filter (if compatible via graph)
    region_id = global_filters.get('region_id')
    if region_id:
        try:
            rid = int(region_id)
            if base_entity == 'regions':
                qs = qs.filter(pk=rid)
                applied.append('region_id')
            else:
                jinfo = resolve_join_path(base_entity, 'regions', user)
                if jinfo['compatible']:
                    qs = qs.filter(**{f"{jinfo['lookup_prefix']}__id": rid}).distinct()
                    applied.append('region_id')
        except (TypeError, ValueError):
            pass

    # 3. Sector filter (if compatible via graph)
    sector_id = global_filters.get('sector_id')
    if sector_id:
        try:
            sid = int(sector_id)
            if base_entity == 'sectors':
                qs = qs.filter(pk=sid)
                applied.append('sector_id')
            else:
                jinfo = resolve_join_path(base_entity, 'sectors', user)
                if jinfo['compatible']:
                    qs = qs.filter(**{f"{jinfo['lookup_prefix']}__id": sid}).distinct()
                    applied.append('sector_id')
        except (TypeError, ValueError):
            pass

    # 4. Active status toggle
    active_only = global_filters.get('active_only')
    if active_only in (True, 'true', '1') and 'is_active' in fmap:
        qs = qs.filter(is_active=True)
        applied.append('active_only')

    # 5. Free-text search on default label field
    search_text = str(global_filters.get('search') or '').strip()
    if search_text and edef.default_label_field in fmap and fmap[edef.default_label_field]['data_type'] == 'string':
        qs = qs.filter(**{f'{edef.default_label_field}__icontains': search_text})
        applied.append('search')

    return qs, applied


def _make_agg_expr(agg_name, lookup, has_to_many=False):
    if agg_name == 'count':
        return Count(lookup, distinct=has_to_many)
    if agg_name == 'count_distinct':
        return Count(lookup, distinct=True)
    if agg_name == 'sum':
        return Sum(lookup)
    if agg_name == 'avg':
        return Avg(lookup)
    if agg_name == 'min':
        return Min(lookup)
    if agg_name == 'max':
        return Max(lookup)
    raise QueryValidationError(f'عملية التجميع غير مدعومة: {agg_name}')


def _cache_key(user, spec, global_filters):
    rpol = RegionalPolicy(user)
    sig = 'all' if rpol.unrestricted else ','.join(str(x) for x in sorted(rpol.ids))
    raw = json.dumps({'u': user.pk, 'r': sig, 's': spec, 'g': global_filters or {}}, sort_keys=True, default=str)
    return 'flex_q_' + hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]


def execute_table_query(user, spec, global_filters=None, *, for_export=False, use_cache=True):
    """Execute a raw, grouped, pivot, or top_n custom table query safely."""
    base_entity = spec.get('base_entity')
    if not base_entity or base_entity not in ENTITY_REGISTRY:
        raise QueryValidationError('يرجى اختيار مصدر بيانات أساسي صالح للجدول.')
    if not user_can_view_entity(user, base_entity):
        raise PermissionError(f'لا تملك صلاحية عرض {ENTITY_REGISTRY[base_entity].label_ar}.')

    ckey = _cache_key(user, spec, global_filters) if (use_cache and not for_export) else None
    if ckey:
        cached = cache.get(ckey)
        if cached is not None:
            return cached

    mode = str(spec.get('mode', 'raw')).lower()
    if mode not in {'raw', 'grouped', 'pivot', 'top_n'}:
        mode = 'raw'

    columns = spec.get('columns') or []
    if not columns:
        # Sensible default columns for the chosen entity
        f_list = list(get_field_map(base_entity).values())[:5]
        columns = [{'entity': base_entity, 'field': f['name'], 'label': f['label_ar']} for f in f_list]

    qs = scoped_queryset(base_entity, user)
    # Collect calculated fields needed on base entity
    calc_needed = set()
    for col in columns:
        if (col.get('entity') or base_entity) == base_entity:
            fmap = get_field_map(base_entity)
            fn = col.get('field')
            if fn in fmap and fmap[fn].get('is_calculated'):
                calc_needed.add(fn)
    if calc_needed:
        qs = apply_calculated_annotations(qs, base_entity, calc_needed)

    qs, applied_globals = apply_global_filters(qs, base_entity, global_filters, user)
    if spec.get('filters'):
        qs = qs.filter(_build_q_from_filter_node(base_entity, spec['filters'], user))

    page = max(1, int(spec.get('page', 1) or 1))
    page_size = min(MAX_EXPORT_ROWS if for_export else MAX_RAW_ROWS, max(1, int(spec.get('page_size', 25) or 25)))
    top_n = spec.get('top_n')
    if top_n:
        try:
            top_n = min(MAX_GROUP_ROWS, max(1, int(top_n)))
        except (TypeError, ValueError):
            top_n = None

    any_to_many = False
    col_defs = []
    for idx, col in enumerate(columns):
        ek = col.get('entity') or base_entity
        fn = col.get('field')
        lookup, fmeta, is_m = _resolve_field_lookup(base_entity, ek, fn, user, col.get('join_path'))
        if is_m:
            any_to_many = True
        agg = str(col.get('aggregation') or '').lower()
        if agg and agg not in ALLOWED_AGGS:
            raise QueryValidationError(f'عملية التجميع غير صالحة: {agg}')
        col_defs.append({
            'id': col.get('id') or f'c_{idx}',
            'entity': ek,
            'field': fn,
            'lookup': lookup,
            'label': col.get('label') or fmeta['label_ar'],
            'data_type': fmeta['data_type'],
            'unit': col.get('unit') or fmeta.get('unit', ''),
            'aggregation': agg,
            'date_granularity': col.get('date_granularity') or '',
            'choices_map': _choice_map_for(ek, fn),
            'has_to_many': is_m,
            'show_pct_of_total': bool(col.get('show_pct_of_total')),
        })

    if mode == 'raw' and not any(c['aggregation'] for c in col_defs):
        if any_to_many:
            qs = qs.distinct()
        total_count = qs.count()
        sort_cfg = spec.get('sort') or []
        order_by = []
        for s in sort_cfg:
            cid = s.get('col_id') or s.get('field')
            direction = '-' if str(s.get('dir', 'asc')).lower() == 'desc' else ''
            match = next((c for c in col_defs if c['id'] == cid or c['field'] == cid), None)
            if match:
                order_by.append(f"{direction}{match['lookup']}")
        if not order_by:
            order_by = ['-pk']
        qs = qs.order_by(*order_by)
        offset = 0 if for_export else (page - 1) * page_size
        limit = top_n if top_n else page_size
        slice_qs = qs.values(*[c['lookup'] for c in col_defs])[offset:offset + limit]
        rows = []
        for raw_row in slice_qs:
            rows.append({
                c['id']: _to_json_value(raw_row.get(c['lookup']), c['choices_map'])
                for c in col_defs
            })
        result = {
            'mode': 'raw',
            'base_entity': base_entity,
            'columns': [
                {'id': c['id'], 'label': c['label'], 'data_type': c['data_type'], 'unit': c['unit'], 'entity': c['entity'], 'field': c['field']}
                for c in col_defs
            ],
            'rows': rows,
            'total_count': total_count,
            'page': page,
            'page_size': page_size,
            'fan_out_protected': any_to_many,
            'applied_global_filters': applied_globals,
        }
    else:
        # Grouped / Top-N / Summary aggregation mode
        dims = [c for c in col_defs if not c['aggregation']]
        measures = [c for c in col_defs if c['aggregation']]
        if not measures:
            # Automatically add record count measure if user grouped without explicit measure
            measures = [{
                'id': 'record_count',
                'entity': base_entity,
                'field': 'id',
                'lookup': 'id',
                'label': 'عدد السجلات',
                'data_type': 'integer',
                'unit': '',
                'aggregation': 'count',
                'choices_map': {},
                'has_to_many': any_to_many,
                'show_pct_of_total': False,
            }]
            col_defs.append(measures[0])

        group_fields = []
        for d in dims:
            gran = d.get('date_granularity')
            if gran in TRUNC_MAP and d['data_type'] in {'date', 'datetime'}:
                alias = f"grp_{d['id']}"
                qs = qs.annotate(**{alias: TRUNC_MAP[gran](d['lookup'])})
                d['_value_key'] = alias
                group_fields.append(alias)
            else:
                d['_value_key'] = d['lookup']
                group_fields.append(d['lookup'])

        annotations = {}
        median_measures = []
        for m in measures:
            alias = f"agg_{m['id']}"
            m['_value_key'] = alias
            if m['aggregation'] == 'median':
                median_measures.append(m)
                annotations[alias] = Avg(m['lookup'])
            else:
                annotations[alias] = _make_agg_expr(m['aggregation'], m['lookup'], has_to_many=any_to_many or m['has_to_many'])

        if group_fields:
            grouped_qs = qs.values(*group_fields).annotate(**annotations)
        else:
            agg_row = qs.aggregate(**annotations)
            grouped_qs = [agg_row]

        # Sorting for grouped results
        if group_fields:
            sort_cfg = spec.get('sort') or []
            order_by = []
            for s in sort_cfg:
                cid = s.get('col_id') or s.get('field')
                direction = '-' if str(s.get('dir', 'desc')).lower() == 'desc' else ''
                match = next((c for c in col_defs if c['id'] == cid or c['field'] == cid), None)
                if match and match.get('_value_key'):
                    order_by.append(f"{direction}{match['_value_key']}")
            if not order_by and measures:
                order_by = [f"-{measures[0]['_value_key']}"]
            grouped_qs = grouped_qs.order_by(*order_by)
            limit = top_n or (MAX_EXPORT_ROWS if for_export else MAX_GROUP_ROWS)
            raw_rows = list(grouped_qs[:limit])
        else:
            raw_rows = list(grouped_qs)

        # Compute exact median if requested
        if median_measures and raw_rows and not group_fields:
            for m in median_measures:
                vals = [float(v) for v in qs.values_list(m['lookup'], flat=True) if v is not None]
                raw_rows[0][m['_value_key']] = round(py_median(vals), 2) if vals else 0

        # Format rows + totals
        totals = {}
        for m in measures:
            vals = [float(r.get(m['_value_key']) or 0) for r in raw_rows]
            totals[m['id']] = round(sum(vals), 2)

        rows = []
        for r in raw_rows:
            out_row = {}
            for c in col_defs:
                v = r.get(c['_value_key'])
                if c in dims:
                    out_row[c['id']] = _to_json_value(v, c['choices_map'])
                else:
                    num = float(v) if v is not None else 0.0
                    out_row[c['id']] = round(num, 2)
                    if c.get('show_pct_of_total'):
                        tot = totals.get(c['id'], 0)
                        out_row[f"{c['id']}_pct"] = round((num / tot * 100.0), 1) if tot else 0.0
            rows.append(out_row)

        out_cols = []
        for c in col_defs:
            out_cols.append({
                'id': c['id'],
                'label': c['label'],
                'data_type': 'integer' if c['aggregation'] in {'count', 'count_distinct'} else c['data_type'],
                'unit': '' if c['aggregation'] in {'count', 'count_distinct'} else c['unit'],
                'entity': c['entity'],
                'field': c['field'],
                'aggregation': c['aggregation'],
            })
            if c.get('show_pct_of_total'):
                out_cols.append({
                    'id': f"{c['id']}_pct",
                    'label': f"{c['label']} (%)",
                    'data_type': 'percentage',
                    'unit': '%',
                    'entity': c['entity'],
                    'field': c['field'],
                    'aggregation': 'pct_of_total',
                })

        result = {
            'mode': mode,
            'base_entity': base_entity,
            'columns': out_cols,
            'rows': rows,
            'totals': totals,
            'total_count': len(rows),
            'page': 1,
            'page_size': len(rows),
            'fan_out_protected': any_to_many,
            'applied_global_filters': applied_globals,
        }

    if ckey:
        cache.set(ckey, result, CACHE_TTL_SECONDS)
    return result


def execute_chart_query(user, spec, global_filters=None, *, use_cache=True):
    """Execute a safe chart query returning labels, datasets, and summary stats."""
    base_entity = spec.get('base_entity')
    if not base_entity or base_entity not in ENTITY_REGISTRY:
        raise QueryValidationError('يرجى اختيار مصدر بيانات أساسي للرسم البياني.')
    if not user_can_view_entity(user, base_entity):
        raise PermissionError(f'لا تملك صلاحية عرض {ENTITY_REGISTRY[base_entity].label_ar}.')

    ckey = _cache_key(user, spec, global_filters) if use_cache else None
    if ckey:
        cached = cache.get(ckey)
        if cached is not None:
            return cached

    dim_cfg = spec.get('dimension') or {}
    dim_entity = dim_cfg.get('entity') or base_entity
    dim_field = dim_cfg.get('field') or ENTITY_REGISTRY[base_entity].default_label_field
    dim_gran = dim_cfg.get('date_granularity') or ''

    measures_cfg = spec.get('measures') or [
        {'entity': base_entity, 'field': 'id', 'aggregation': 'count', 'label': 'العدد'}
    ]

    columns = [{
        'id': 'dim',
        'entity': dim_entity,
        'field': dim_field,
        'label': dim_cfg.get('label') or get_field_map(dim_entity).get(dim_field, {}).get('label_ar', dim_field),
        'date_granularity': dim_gran,
    }]
    for idx, m in enumerate(measures_cfg):
        columns.append({
            'id': f'm_{idx}',
            'entity': m.get('entity') or base_entity,
            'field': m.get('field') or 'id',
            'aggregation': m.get('aggregation') or 'count',
            'label': m.get('label') or '',
            'unit': m.get('unit') or '',
        })

    table_spec = {
        'base_entity': base_entity,
        'mode': 'grouped',
        'columns': columns,
        'filters': spec.get('filters'),
        'sort': spec.get('sort') or ([{'col_id': 'dim', 'dir': 'asc'}] if dim_gran else [{'col_id': 'm_0', 'dir': 'desc'}]),
        'top_n': spec.get('top_n') or 15,
    }
    res = execute_table_query(user, table_spec, global_filters=global_filters, use_cache=False)

    labels = [str(r.get('dim') if r.get('dim') is not None else 'غير محدد') for r in res['rows']]
    datasets = []
    for idx, m in enumerate(measures_cfg):
        mid = f'm_{idx}'
        col_meta = next((c for c in res['columns'] if c['id'] == mid), {})
        vals = [float(r.get(mid) or 0) for r in res['rows']]
        datasets.append({
            'id': mid,
            'label': m.get('label') or col_meta.get('label', 'القيمة'),
            'unit': col_meta.get('unit', ''),
            'data': vals,
            'total': round(sum(vals), 2),
            'avg': round(sum(vals) / len(vals), 2) if vals else 0,
            'max': max(vals) if vals else 0,
            'min': min(vals) if vals else 0,
        })

    out = {
        'chart_type': spec.get('chart_type', 'bar'),
        'base_entity': base_entity,
        'dimension': {
            'entity': dim_entity,
            'field': dim_field,
            'label': columns[0]['label'],
            'date_granularity': dim_gran,
        },
        'labels': labels,
        'datasets': datasets,
        'total_groups': len(labels),
        'fan_out_protected': res.get('fan_out_protected', False),
        'applied_global_filters': res.get('applied_global_filters', []),
    }
    if ckey:
        cache.set(ckey, out, CACHE_TTL_SECONDS)
    return out


def execute_drilldown(user, spec, filter_entity, filter_field, filter_value, global_filters=None):
    """Return authorized detail rows when a user clicks a chart bar/slice or table group."""
    base_entity = spec.get('base_entity')
    if not base_entity or base_entity not in ENTITY_REGISTRY:
        raise QueryValidationError('مصدر البيانات غير صالح.')
    if not user_can_view_entity(user, base_entity):
        raise PermissionError('لا تملك صلاحية عرض سجلات التفصيل.')

    # Reverse-map Arabic choice label back to stored enum value if applicable
    cmap = _choice_map_for(filter_entity or base_entity, filter_field)
    rev_map = {v: k for k, v in cmap.items()}
    actual_value = rev_map.get(str(filter_value), filter_value)

    drill_cond = {
        'entity': filter_entity or base_entity,
        'field': filter_field,
        'op': 'is_null' if filter_value in (None, '', 'غير محدد') else 'eq',
        'value': actual_value,
    }
    combined_filters = drill_cond
    if spec.get('filters'):
        combined_filters = {'logic': 'AND', 'conditions': [spec['filters'], drill_cond]}

    f_list = list(get_field_map(base_entity).values())[:7]
    raw_spec = {
        'base_entity': base_entity,
        'mode': 'raw',
        'columns': [{'entity': base_entity, 'field': f['name'], 'label': f['label_ar']} for f in f_list],
        'filters': combined_filters,
        'page': 1,
        'page_size': 50,
    }
    return execute_table_query(user, raw_spec, global_filters=global_filters, use_cache=False)
