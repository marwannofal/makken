"""Branded Arabic export writers. Values are data, never formulas or HTML."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html import escape
from io import BytesIO
import math
from pathlib import Path
import re
from textwrap import wrap
from xml.etree.ElementTree import Element, SubElement, tostring
from zipfile import ZipFile, ZIP_DEFLATED

from .export_tables import ExportError

TEAL = '24B3AF'
DARK = '155F60'
NS = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'


def numeric_value(header, values):
    """Only known numeric columns; names, phone numbers and codes remain text."""
    if len(values) != 1 or any(word in header for word in ['هاتف', 'جوال', 'اتصال', 'رقم', 'بريد', 'اسم', 'عنوان']):
        return None
    if not any(word in header for word in ['المبلغ', 'تكلفة', 'التكلفة', 'قيمة', 'الدعم المعتمد', 'عدد المستفيدين', 'القدرة المالية', 'نسبة', 'النسبة', '%', 'المتبقي']):
        return None
    text = values[0].translate(str.maketrans('٠١٢٣٤٥٦٧٨٩٫٬', '0123456789.,'))
    text = re.sub(r'ريال(?: سعودي)?|ر\.س\.?|SAR|﷼|\s|,', '', text, flags=re.I)
    percent = '%' in text or '٪' in text or 'نسبة' in header or '%' in header
    text = text.replace('%', '').replace('٪', '')
    if not re.fullmatch(r'-?\d+(?:\.\d+)?', text) or len(text.replace('.', '').replace('-', '')) > 15:
        return None
    try:
        value = Decimal(text)
        if not value.is_finite():
            return None
        return (value / 100, 'percent') if percent else (value, 'integer' if 'عدد' in header and value == value.to_integral() else 'number')
    except InvalidOperation:
        return None


def xml_bytes(element):
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' + tostring(element, encoding='utf-8')


def col_name(index):
    result = ''
    while index >= 0:
        index, remain = divmod(index, 26)
        result = chr(65+remain)+result
        index -= 1
    return result


def xlsx_bytes(table, filters, created):
    """Native OOXML with two RTL sheets; no optional Excel runtime dependency."""
    output = BytesIO()
    details = []
    links = []
    main_rows = []
    for index, row in enumerate(table.rows, 1):
        cells = []
        for column, values in enumerate(row):
            whole = '\n'.join(values)
            long = len(values) > 3 or len(whole) > 220
            if long:
                start = len(details)+8
                for ordinal, value in enumerate(values, 1):
                    chunks = [value[i:i+1500] for i in range(0, len(value), 1500)] or ['—']
                    for part, chunk in enumerate(chunks, 1):
                        details.append([str(index), row[0][0][:240], table.headers[column], str(ordinal)+(f' / جزء {part}' if len(chunks)>1 else ''), chunk])
                # Main sheet stays readable, every value is in the linked detail sheet.
                preview = '\n'.join(v[:65]+('…' if len(v)>65 else '') for v in values[:3])+'\nجميع القيم في ورقة التفاصيل ('+str(len(values))+')'
                cells.append((preview, 7))
                links.append((f'{col_name(column)}{index+7}', f"'التفاصيل'!A{start}"))
            else:
                number = numeric_value(table.headers[column], values)
                cells.append((number[0], 5 if number[1] == 'percent' else 10 if number[1] == 'integer' else 4) if number else (whole, 2 if index % 2 else 3))
        main_rows.append(cells)
    for row in table.footers:
        cells = []
        for column, values in enumerate(row):
            number = numeric_value(table.headers[column], values)
            cells.append((number[0], 9 if number[1] == 'percent' else 8) if number else ('\n'.join(values), 1))
        main_rows.append(cells)
    if len(details) > 100000:
        raise ExportError('حجم التفاصيل كبير جدًا. ضيّق نتائج البحث ثم أعد التصدير.', 413)

    def sheet(headers, rows, title, detail=False):
        root = Element('worksheet', {'xmlns': NS})
        views = SubElement(root, 'sheetViews')
        view = SubElement(views, 'sheetView', {'workbookViewId': '0', 'rightToLeft': '1', 'showGridLines': '0'})
        SubElement(view, 'pane', {'ySplit': '7', 'topLeftCell': 'A8', 'activePane': 'bottomLeft', 'state': 'frozen'})
        SubElement(view, 'selection', {'pane': 'bottomLeft', 'activeCell': 'A8', 'sqref': 'A8'})
        SubElement(root, 'sheetFormatPr', {'defaultRowHeight': '25'})
        cols = SubElement(root, 'cols')
        for index, label in enumerate(headers, 1):
            width = 12 if label in {'#', 'رقم السجل', 'ترتيب القيمة'} else (65 if detail and index == 5 else min(38, max(20, len(label)+5)))
            SubElement(cols, 'col', {'min': str(index), 'max': str(index), 'width': str(width), 'customWidth': '1'})
        data = SubElement(root, 'sheetData')
        merges = []

        def make_row(number, values, height=None):
            attrs = {'r': str(number)}
            if height:
                attrs.update(ht=str(height), customHeight='1')
            node = SubElement(data, 'row', attrs)
            for index, (value, style) in enumerate(values):
                attrs = {'r': f'{col_name(index)}{number}', 's': str(style)}
                if isinstance(value, Decimal):
                    c = SubElement(node, 'c', attrs)
                    SubElement(c, 'v').text = str(value)
                else:
                    attrs['t'] = 'inlineStr'
                    c = SubElement(node, 'c', attrs)
                    t = SubElement(SubElement(c, 'is'), 't', {'{http://www.w3.org/XML/1998/namespace}space': 'preserve'})
                    t.text = str(value)
        for number, text, style, height in [(1, 'مكّن | '+title, 0, 42), (2, 'تاريخ التصدير: '+created, 6, 28), (3, 'الفلاتر: '+filters, 6, 48), (4, 'عدد السجلات: '+str(len(table.rows)), 6, 25), (5, 'القيم المالية بالريال السعودي. التفاصيل الكاملة للقوائم الطويلة في ورقة «التفاصيل».', 6, 32)]:
            make_row(number, [(text, style)], height)
            if len(headers)>1:
                merges.append(f'A{number}:{col_name(len(headers)-1)}{number}')
        make_row(7, [(h, 1) for h in headers], 44)
        for number, values in enumerate(rows, 8):
            lines = max((min(10, str(value).count('\n')+math.ceil(len(str(value))/32)) for value, _ in values), default=1)
            make_row(number, values, min(220, max(34, lines*19)))
        SubElement(root, 'autoFilter', {'ref': f'A7:{col_name(len(headers)-1)}{max(7,len(rows)+7)}'})
        merged = SubElement(root, 'mergeCells', {'count': str(len(merges))})
        for ref in merges:
            SubElement(merged, 'mergeCell', {'ref': ref})
        if links and not detail:
            hyper = SubElement(root, 'hyperlinks')
            for ref, location in links:
                SubElement(hyper, 'hyperlink', {'ref': ref, 'location': location, 'display': 'عرض التفاصيل'})
        SubElement(root, 'printOptions', {'horizontalCentered': '1'})
        SubElement(root, 'pageMargins', {'left': '0.3', 'right': '0.3', 'top': '0.5', 'bottom': '0.5', 'header': '0.2', 'footer': '0.2'})
        SubElement(root, 'pageSetup', {'paperSize': '9', 'orientation': 'landscape'})
        foot = SubElement(root, 'headerFooter')
        SubElement(foot, 'oddFooter').text = '&Cمكّن | صفحة &P من &N'
        return xml_bytes(root)

    styles = f'''<styleSheet xmlns="{NS}"><numFmts count="2"><numFmt numFmtId="164" formatCode="#,##0.00"/><numFmt numFmtId="165" formatCode="0.00%"/></numFmts><fonts count="4"><font><sz val="18"/><color rgb="FF{DARK}"/><name val="Cairo"/><b/></font><font><sz val="11"/><color rgb="FFFFFFFF"/><name val="Cairo"/><b/></font><font><sz val="11"/><color rgb="FF244647"/><name val="Cairo"/></font><font><sz val="11"/><color rgb="FF087875"/><name val="Cairo"/><u/></font></fonts><fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF{TEAL}"/><bgColor indexed="64"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFF0F9F8"/><bgColor indexed="64"/></patternFill></fill></fills><borders count="2"><border/><border><bottom style="hair"><color rgb="FFD7EAE7"/></bottom></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="2" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="11">'''
    for font, fill, border, num in [(0,0,0,0),(1,2,0,0),(2,0,1,0),(2,3,1,0),(2,0,1,164),(2,0,1,165),(2,0,0,0),(3,3,1,0),(1,2,0,164),(1,2,0,165),(2,0,1,3)]:
        styles += f'<xf numFmtId="{num}" fontId="{font}" fillId="{fill}" borderId="{border}" xfId="0" applyAlignment="1" applyNumberFormat="1"><alignment horizontal="right" vertical="center" wrapText="1" readingOrder="2"/></xf>'
    styles += '</cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
    detail_headers = ['رقم السجل', 'السجل', 'العمود', 'ترتيب القيمة', 'القيمة الكاملة']
    detail_rows = [[(v, 2 if i%2 else 3) for v in row] for i,row in enumerate(details,1)]
    if not detail_rows:
        detail_rows = [[('—', 2), ('لا توجد قوائم طويلة؛ جميع القيم كاملة في ورقة القائمة.', 2), ('—', 2), ('—', 2), ('—', 2)]]
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '''<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/><Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>''')
        archive.writestr('_rels/.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr('xl/workbook.xml', f'<workbook xmlns="{NS}" xmlns:r="{REL}"><bookViews><workbookView/></bookViews><sheets><sheet name="القائمة" sheetId="1" r:id="rId1"/><sheet name="التفاصيل" sheetId="2" r:id="rId2"/></sheets><definedNames><definedName name="_xlnm.Print_Titles" localSheetId="0">\'القائمة\'!$7:$7</definedName><definedName name="_xlnm.Print_Titles" localSheetId="1">\'التفاصيل\'!$7:$7</definedName></definedNames></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/><Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>')
        archive.writestr('xl/styles.xml', styles)
        archive.writestr('xl/worksheets/sheet1.xml', sheet(table.headers, main_rows, table.title))
        archive.writestr('xl/worksheets/sheet2.xml', sheet(detail_headers, detail_rows, 'تفاصيل '+table.title, True))
    return output.getvalue()


def pdf_chunks(values, width=30, max_lines=6):
    lines = []
    for value in values:
        lines.extend(wrap(value, width=width, break_long_words=True, break_on_hyphens=False) or ['—'])
    return ['\n'.join(lines[i:i+max_lines]) for i in range(0,len(lines),max_lines)] or ['—']


def pdf_html(table, filters, created, logo=False):
    columns = len(table.headers)
    paper = 'A3' if columns > 9 else 'A4'
    width = max(12, min(38, int((145 if paper == 'A4' else 210)/max(1, columns))))
    physical = []
    for number, row in enumerate(table.rows, 1):
        chunks = [pdf_chunks(values, width) for values in row]
        parts = max(map(len, chunks), default=1)
        for part in range(parts):
            values = [c[part] if part<len(c) else '' for c in chunks]
            if part and not values[0]:
                values[0] = 'تتمة السجل '+str(number)
            physical.append('<tr'+(' class="continued"' if part else '')+'>'+''.join('<td>'+escape(v).replace('\n','<br>')+'</td>' for v in values)+'</tr>')
            if len(physical)>3000:
                raise ExportError('عدد تفاصيل PDF كبير جدًا. استخدم Excel أو ضيّق الفلاتر.', 413)
    for row in table.footers:
        physical.append('<tr class="total">'+''.join('<td>'+escape('، '.join(v))+'</td>' for v in row)+'</tr>')
    body = ''.join(physical) or '<tr><td colspan="'+str(columns)+'">لا توجد سجلات مطابقة للفلاتر.</td></tr>'
    return f'''<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><title>{escape(table.title)} | مكّن</title><style>
@font-face{{font-family:Cairo;src:url('makken-asset:regular');font-weight:400}}
@font-face{{font-family:Cairo;src:url('makken-asset:bold');font-weight:700}}
@page{{size:{paper} landscape;margin:15mm 10mm 18mm;@bottom-center{{content:'مكّن | صفحة ' counter(page) ' من ' counter(pages);font:9pt Cairo;color:#{DARK}}}}}
*{{box-sizing:border-box}}body{{font:9pt/1.65 Cairo;color:#244647;direction:rtl}}.brand{{border-bottom:3px solid #{TEAL};padding-bottom:10px;margin-bottom:15px}}.brand img{{width:190px;height:auto;float:left}}.brand b{{font-size:26pt;color:#{TEAL}}}h1{{font-size:18pt;line-height:1.6;margin:5px 0;color:#{DARK}}}.meta{{color:#547370;font-size:9pt;margin:5px 0}}.summary{{padding:10px 13px;background:#eff9f7;border-right:3px solid #{TEAL};margin:12px 0}}table{{border-collapse:collapse;width:100%;table-layout:fixed;direction:rtl}}thead{{display:table-header-group}}th{{background:#{TEAL};color:white;font-weight:700;line-height:1.5;padding:10px 6px;border:1px solid #1e9f9b}}td{{padding:8px 6px;border:1px solid #deeeea;vertical-align:top;text-align:right;overflow-wrap:anywhere}}tr:nth-child(even) td{{background:#f1f9f7}}tr{{break-inside:avoid}}.continued td{{border-top-style:dashed}}.total td{{background:#{TEAL};color:#fff;font-weight:700}}.hint{{margin-top:12px;font-size:8pt;color:#547370}}
</style></head><body><div class="brand">{('<img src="makken-asset:logo" alt="شعار المؤسسة">' if logo else '')}<b>مكّن</b><h1>{escape(table.title)}</h1><p class="meta">تاريخ التصدير: <bdi>{escape(created)}</bdi></p></div><div class="summary"><strong>عدد السجلات: {len(table.rows):,}</strong><br>{escape(filters)}</div><table><thead><tr>{''.join('<th>'+escape(h)+'</th>' for h in table.headers)}</tr></thead><tbody>{body}</tbody></table><p class="hint">القيم المالية بالريال السعودي. تظهر القوائم الطويلة في أسطر متابعة للحفاظ على جميع البيانات. يعكس التقرير البيانات وقت استخراج الصفحات.</p></body></html>'''


def pdf_bytes(table, filters, created):
    from django.contrib.staticfiles import finders
    from weasyprint import HTML
    from weasyprint.text.fonts import FontConfiguration
    from weasyprint.urls import URLFetcherResponse
    fonts = Path(__file__).resolve().parent / 'static/core/exports/fonts'
    logo_path = finders.find('accounts/images/header-logo.svg')
    assets = {'makken-asset:regular': (fonts/'Cairo-Regular.ttf', 'font/ttf'),
              'makken-asset:bold': (fonts/'Cairo-Bold.ttf', 'font/ttf')}
    if logo_path:
        assets['makken-asset:logo'] = (Path(logo_path), 'image/svg+xml')

    def fetch(url, *args, **kwargs):
        if url not in assets:
            raise ValueError('External PDF resources are disabled')
        path, mime = assets[url]
        return URLFetcherResponse(url, body=path.read_bytes(), headers={'Content-Type': mime})

    if not all(path.is_file() for path, _ in assets.values()):
        raise ExportError('تعذّر تحميل خط التقرير. تواصل مع مسؤول النظام.', 503)
    html = pdf_html(table, filters, created, bool(logo_path))
    return HTML(string=html, url_fetcher=fetch).write_pdf(font_config=FontConfiguration())
