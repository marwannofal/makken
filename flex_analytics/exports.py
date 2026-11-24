"""Authorized CSV, Excel (.xlsx), and PDF exports with formula-injection protection."""
import csv
from dataclasses import dataclass
from io import StringIO

from django.http import HttpResponse
from django.utils import timezone

from core.export_documents import pdf_bytes, xlsx_bytes
from .query_engine import execute_chart_query, execute_table_query


DANGEROUS_FORMULA_PREFIXES = ('=', '+', '-', '@', '\t', '\r')


def sanitize_spreadsheet_cell(val):
    """Prevent CSV/Excel formula injection (CWE-1236)."""
    if val is None:
        return ''
    text = str(val)
    if text and text[0] in DANGEROUS_FORMULA_PREFIXES:
        return "'" + text
    return text


@dataclass
class _ExportTable:
    title: str
    headers: list
    rows: list
    footers: list


def _extract_headers_and_rows(user, widget_type, config, title, global_filters):
    if widget_type == 'chart':
        res = execute_chart_query(user, config, global_filters=global_filters, use_cache=False)
        headers = [res['dimension']['label']] + [ds['label'] for ds in res['datasets']]
        rows = []
        for idx, lbl in enumerate(res['labels']):
            row = [lbl] + [ds['data'][idx] if idx < len(ds['data']) else 0 for ds in res['datasets']]
            rows.append(row)
        return headers, rows

    res = execute_table_query(user, config, global_filters=global_filters, for_export=True, use_cache=False)
    cols = res['columns']
    headers = [c['label'] for c in cols]
    rows = []
    for r in res['rows']:
        rows.append([r.get(c['id'], '') for c in cols])
    return headers, rows


def build_export_response(user, fmt, widget_type, config, title='تقرير تحليلي', global_filters=None):
    headers, rows = _extract_headers_and_rows(user, widget_type, config, title, global_filters)
    safe_title = (title or 'flex_analytics').strip()[:80]
    stamp = timezone.localtime().strftime('%Y%m%d_%H%M')

    if fmt == 'csv':
        buf = StringIO()
        buf.write('\ufeff')  # UTF-8 BOM for Arabic Excel compatibility
        writer = csv.writer(buf)
        writer.writerow([sanitize_spreadsheet_cell(h) for h in headers])
        for row in rows:
            writer.writerow([sanitize_spreadsheet_cell(v) for v in row])
        resp = HttpResponse(buf.getvalue(), content_type='text/csv; charset=utf-8')
        resp['Content-Disposition'] = f'attachment; filename="makken_analytics_{stamp}.csv"'
        return resp

    export_table = _ExportTable(
        title=safe_title,
        headers=[sanitize_spreadsheet_cell(h) for h in headers],
        rows=[[[sanitize_spreadsheet_cell(v)] for v in row] for row in rows],
        footers=[],
    )
    created = timezone.localtime()
    filters_desc = []
    if global_filters:
        for k, v in global_filters.items():
            if v:
                filters_desc.append((str(k), str(v)))

    if fmt == 'xlsx':
        data = xlsx_bytes(export_table, filters_desc, created)
        resp = HttpResponse(
            data,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        )
        resp['Content-Disposition'] = f'attachment; filename="makken_analytics_{stamp}.xlsx"'
        return resp

    if fmt == 'pdf':
        data = pdf_bytes(export_table, filters_desc, created)
        resp = HttpResponse(data, content_type='application/pdf')
        resp['Content-Disposition'] = f'attachment; filename="makken_analytics_{stamp}.pdf"'
        return resp

    raise ValueError('صيغة التصدير غير مدعومة.')
