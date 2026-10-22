"""Read only the HTML tables returned by the caller's already-authorized view.

No model lookup, external URL, or permission bypass is used here. These helpers
are intentionally independent of app-specific models and navigation.
"""
from dataclasses import dataclass, field
from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, urlsplit

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
IGNORE = {'script', 'style', 'svg', 'template'}
ACTIONS = {'الإجراء', 'الإجراءات', 'اجراء', 'إجراء', 'العمليات', 'إجراءات', 'تحكم', 'actions', 'action', 'اختيار', 'تحديد'}


class ExportError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


@dataclass(eq=False)
class Node:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    parent: object = None

    def walk(self, tag=None):
        for child in self.children:
            if isinstance(child, Node):
                if tag is None or child.tag == tag:
                    yield child
                yield from child.walk(tag)

    def closest(self, tags):
        node = self.parent
        while node:
            if node.tag in tags:
                return node
            node = node.parent
        return None

    def text(self):
        if self.tag in IGNORE or self.attrs.get('aria-hidden') == 'true':
            return ''
        if self.tag in {'input', 'select', 'textarea'} or 'data-mk-values-control' in self.attrs:
            return ''
        if 'hidden' in self.attrs and 'mk-cell-value-overflow' not in self.attrs.get('class', '').split():
            return ''
        parts = []
        for child in self.children:
            parts.append(child.text() if isinstance(child, Node) else child)
        text = ''.join(parts)
        if self.tag in {'div', 'p', 'br', 'li', 'small', 'bdi', 'span', 'dt', 'dd', 'summary', 'time'}:
            return ' ' + text + ' '
        return text


def clean(value):
    # Strip disallowed XML characters, preserve Arabic and intentional bidi marks.
    return re.sub(r'\s+', ' ', re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', value)).strip()


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node('document')
        self.stack = [self.root]
        self.feed(html)
        mains = [n for n in self.root.walk() if n.tag == 'main' or n.attrs.get('id') == 'main-content']
        self.main = mains[0] if mains else None
        self.tables = [] if self.main is None else [n for n in self.main.walk('table') if not n.closest({'dialog', 'template'})]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, dict(attrs), parent=self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack)-1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)

    def table(self, index):
        try:
            table = self.tables[index]
        except IndexError:
            raise ExportError('لم يُعثر على الجدول المطلوب. حدّث الصفحة ثم أعد المحاولة.') from None
        if table.attrs.get('data-no-export') is not None or any(
            n.tag in {'textarea', 'select'} or n.tag == 'input' and n.attrs.get('type', 'text') not in {'hidden', 'checkbox', 'radio', 'submit', 'button', 'color'}
            for n in table.walk()
        ):
            raise ExportError('احفظ النموذج أولًا ثم صدّر البيانات من صفحة السجل.')
        heads = [n for n in table.walk('thead') if n.closest({'table'}) is table]
        if not heads:
            raise ExportError('لا يحتوي هذا الجدول على رؤوس أعمدة قابلة للتصدير.')
        header_rows = [n for n in heads[0].walk('tr')]
        if len(header_rows) != 1:
            raise ExportError('يحتاج هذا الجدول ذو العناوين المركبة إلى إعداد تصدير خاص.')
        headers = [n for n in header_rows[0].children if isinstance(n, Node) and n.tag in {'td', 'th'}]
        if any(n.attrs.get('colspan', '1') != '1' or n.attrs.get('rowspan', '1') != '1' for n in headers):
            raise ExportError('يحتاج هذا الجدول ذو الخلايا المدمجة إلى إعداد تصدير خاص.')
        keep = [i for i, n in enumerate(headers) if clean(n.text()).lower().rstrip(':') not in ACTIONS and not re.search(r'(?:^|[\s_-])actions?(?:$|[\s_-])', n.attrs.get('class', '')) and 'action-cell' not in n.attrs.get('class', '').split()]
        if not keep:
            raise ExportError('لا توجد أعمدة بيانات قابلة للتصدير.')
        labels = [clean(headers[i].text()) for i in keep]
        rows = []
        bodies = [n for n in table.walk('tbody') if n.closest({'table'}) is table]
        candidates = [r for b in bodies for r in b.walk('tr') if r.closest({'table'}) is table]
        if not bodies:
            candidates = [r for r in table.walk('tr') if r.closest({'table'}) is table and not r.closest({'thead', 'tfoot'})]
        for row in candidates:
            if 'hidden' in row.attrs:
                continue
            cells = [n for n in row.children if isinstance(n, Node) and n.tag in {'td', 'th'}]
            if any(n.attrs.get('colspan', '1') != '1' or n.attrs.get('rowspan', '1') != '1' for n in cells):
                if len(cells) == 1 and (any(n.attrs.get('class', '').find('empty') >= 0 for n in cells[0].walk()) or not any(n.tag in {'a', 'button', 'input'} for n in cells[0].walk())):
                    continue  # Empty-state row, never an actual record.
                raise ExportError('تعذّر تصدير صف ذي خلايا مدمجة دون فقد بيانات.')
            if len(cells) != len(headers):
                raise ExportError('تغيّر ترتيب أعمدة الجدول. حدّث الصفحة وأعد المحاولة.')
            rows.append([cell_values(cells[i]) for i in keep])
        title = ''
        scope = table.closest({'section', 'article'}) or self.main
        headings = [n for n in scope.walk() if n.tag in {'h2', 'h3'} and not n.closest({'dialog'})]
        if headings:
            title = clean(headings[0].text())
        if not title:
            heading = next(iter(self.main.walk('h1')), None)
            title = clean(heading.text()) if heading else 'سجل مكّن'
        footers = []
        for footer in table.walk('tfoot'):
            if footer.closest({'table'}) is not table:
                continue
            for row in footer.walk('tr'):
                cells = []
                for cell in row.children:
                    if isinstance(cell, Node) and cell.tag in {'td', 'th'}:
                        span = cell.attrs.get('colspan', '1')
                        if not span.isdigit() or not 1 <= int(span) <= len(headers):
                            raise ExportError('تعذّر قراءة صف الإجمالي في الجدول.')
                        cells.append(cell_values(cell))
                        cells.extend([['']] * (int(span)-1))
                if len(cells) == len(headers):
                    footers.append([cells[i] for i in keep])
        return Table(labels, rows, title, table, footers)


@dataclass
class Table:
    headers: list
    rows: list
    title: str
    node: Node = field(repr=False)
    footers: list = field(default_factory=list)


def cell_values(cell):
    """Keep complete source text, with real collection boundaries when present."""
    containers = [n for n in cell.walk() if n.tag in {'ul', 'ol'} or any(
        token == 'tags' or token.endswith('-tags') or token.endswith('_tags') for token in n.attrs.get('class', '').split()
    )]
    if len(containers) == 1:
        container = containers[0]
        items = [n for n in container.children if isinstance(n, Node) and n.tag not in IGNORE]
        # Only replace the cell's text if the wrapper accounts for all its text.
        values = [clean(n.text()) for n in items if clean(n.text())]
        if values and clean(cell.text()) == clean(container.text()):
            return values
    return [clean(cell.text()) or '—']


def pagination(table, path, query):
    """Find the closest table-owned pager, including independent followup_page."""
    scope = table.node.parent
    while scope and scope.tag != 'document':
        tables = [n for n in scope.walk('table') if not n.closest({'dialog', 'template'})]
        if len(tables) > 1:
            return None, []  # Never borrow another table's pagination.
        navs = [n for n in scope.walk() if n.tag == 'nav' and (
            'pag' in n.attrs.get('class', '').lower() or 'صفحات' in n.attrs.get('aria-label', '')
        )]
        # Settings pages place their pager directly AFTER the table's section.
        # Inspect following siblings only until another table/section starts.
        if not navs and scope.tag in {'section', 'article'} and scope.parent:
            siblings = scope.parent.children
            for sibling in siblings[siblings.index(scope)+1:]:
                if not isinstance(sibling, Node) or sibling.tag in {'dialog', 'template'}:
                    continue
                if sibling.tag == 'table' or any(sibling.walk('table')) or sibling.tag in {'section', 'article', 'h1', 'h2'}:
                    break
                candidates = [sibling, *sibling.walk()]
                navs.extend(n for n in candidates if n.tag == 'nav' and (
                    'pag' in n.attrs.get('class', '').lower() or 'صفحات' in n.attrs.get('aria-label', '')
                ))
                if navs:
                    break
        links = []
        keys = set()
        for nav in navs:
            for a in nav.walk('a'):
                url = urlsplit(a.attrs.get('href', ''))
                if url.scheme or url.netloc or url.path not in {'', path}:
                    continue
                params = parse_qs(url.query, keep_blank_values=True)
                for key, values in params.items():
                    if nav.attrs.get('data-page-key') and key != nav.attrs['data-page-key']:
                        continue
                    if re.fullmatch(r'(?:[a-zA-Z_]+_)?page', key) and len(values) == 1 and values[0].isdigit():
                        number = int(values[0])
                        if number > 0:
                            keys.add(key); links.append((key, number))
        if links:
            if len(keys) != 1:
                raise ExportError('توجد أكثر من آلية ترقيم لهذا الجدول؛ يلزم تحديدها قبل التصدير.')
            key = keys.pop()
            return key, sorted({n for k, n in links if k == key})
        if scope.tag == 'main' or scope.attrs.get('id') == 'main-content':
            return None, []
        scope = scope.parent
    return None, []


def filter_summary(page, query):
    labels = {}
    options = {}
    for node in page.root.walk('label'):
        target = node.attrs.get('for')
        if target:
            labels[target] = clean(node.text()).rstrip('* :')
    for node in page.root.walk():
        name = node.attrs.get('name')
        if node.tag == 'select' and name:
            options[name] = {o.attrs.get('value', ''): clean(o.text()) for o in node.walk('option')}
    fallback = {'q': 'البحث', 'status': 'حالة السجل', 'development_state': 'حالة التطور', 'states': 'حالات التطور', 'scopes': 'نطاق الكيان', 'funding_status': 'حالة الدعم', 'capacity_min': 'القدرة المالية من', 'capacity_max': 'القدرة المالية إلى'}
    result = []
    for key, values in query.lists():
        if key.startswith('_mk_') or re.fullmatch(r'(?:[a-zA-Z_]+_)?page', key) or key in {'csrfmiddlewaretoken', 'snapshot', 'token', 'edit', 'detail', 'record', 'operation', 'notice'}:
            continue
        values = [options.get(key, {}).get(v, v) for v in values if v]
        if values:
            label = labels.get('id_'+key) or fallback.get(key, key)
            result.append(label + ': ' + '، '.join(values))
    return ' | '.join(result) or 'جميع السجلات دون فلاتر إضافية'
