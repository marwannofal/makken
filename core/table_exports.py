"""Shared, permission-preserving exports for server-rendered Makken table pages."""
from copy import copy
from datetime import datetime
import logging
from threading import BoundedSemaphore
from time import monotonic

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.utils.cache import patch_cache_control

from .export_documents import pdf_bytes, xlsx_bytes
from .export_tables import ExportError, Page, filter_summary, pagination

logger = logging.getLogger(__name__)
EXPORT_LOCK = BoundedSemaphore(1)
PARAMS = {'_mk_export', '_mk_table'}


class TableExportMiddleware:
    """Append LAST in MIDDLEWARE: existing authentication/RBAC run first.

    Only export a successful HTML page served to an authenticated user. Every
    additional page goes through the same inner view handler with the same user,
    session, path and filters. The request can never choose a different URL.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        format = request.GET.get('_mk_export')
        if format is None:
            return self.get_response(request)
        if request.method != 'GET':
            return self.error('التصدير متاح من صفحات العرض فقط.', 405)
        if format not in {'xlsx', 'pdf'}:
            return self.error('صيغة التصدير غير مدعومة.', 400)
        if getattr(getattr(request, 'user', None), 'is_authenticated', False):
            from access_control.exports import export_access
            if not export_access(request).get(format, False):
                label = 'Excel' if format == 'xlsx' else 'PDF'
                return self.error('لا تملك صلاحية تصدير '+label+' لهذه الصفحة.', 403)
        response = self.get_response(self.clone(request))
        if response.status_code != 200:
            return response
        if not getattr(getattr(request, 'user', None), 'is_authenticated', False):
            return self.error('سجّل الدخول أولًا لتصدير البيانات.', 403)
        try:
            raw_index = request.GET.get('_mk_table', '0')
            if not raw_index.isdigit() or int(raw_index) > 100:
                raise ExportError('رقم الجدول غير صالح.')
            index = int(raw_index)
            if not EXPORT_LOCK.acquire(blocking=False):
                raise ExportError('يوجد تقرير قيد التجهيز. انتظر قليلًا ثم أعد المحاولة.', 429)
            try:
                table, filters = self.collect(request, response, index, format)
                now = timezone.now()
                created = (timezone.localtime(now) if timezone.is_aware(now) else now).strftime('%Y/%m/%d %H:%M %Z')
                payload = xlsx_bytes(table, filters, created) if format == 'xlsx' else pdf_bytes(table, filters, created)
            finally:
                EXPORT_LOCK.release()
            mime = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' if format == 'xlsx' else 'application/pdf'
            result = HttpResponse(payload, content_type=mime)
            filename = 'مكّن - '+table.title[:70]+' - '+datetime.now().strftime('%Y%m%d-%H%M')+'.'+format
            result['Content-Disposition'] = content_disposition_header(True, filename)
            result['Content-Length'] = str(len(payload))
            result['X-Content-Type-Options'] = 'nosniff'
            patch_cache_control(result, private=True, no_store=True, no_cache=True, max_age=0)
            return result
        except ExportError as exc:
            return self.error(str(exc), exc.status)
        except Exception:
            logger.exception('Makken export failed for path %s', request.path)
            return self.error('تعذّر تجهيز التقرير. أعد المحاولة، وإذا تكرر الخطأ تواصل مع مسؤول النظام.', 500)

    @staticmethod
    def error(message, status):
        response = JsonResponse({'error': message}, status=status, json_dumps_params={'ensure_ascii': False})
        patch_cache_control(response, private=True, no_store=True)
        if status == 429:
            response['Retry-After'] = '20'
        return response

    @staticmethod
    def clone(request, page_key=None, page_number=None):
        cloned = copy(request)
        cloned.GET = request.GET.copy()
        for key in PARAMS:
            cloned.GET.pop(key, None)
        if page_key is not None:
            cloned.GET[page_key] = str(page_number)
        cloned.META = request.META.copy()
        cloned.META['QUERY_STRING'] = cloned.GET.urlencode()
        cloned._makken_export_internal = True
        return cloned

    @staticmethod
    def parse(response):
        if response.status_code != 200:
            raise ExportError('تغيّرت صلاحية الوصول أو البيانات أثناء التصدير. حدّث الصفحة ثم أعد المحاولة.', 409)
        if hasattr(response, 'render') and not getattr(response, 'is_rendered', True):
            response.render()
        if response.streaming or 'text/html' not in response.get('Content-Type', ''):
            raise ExportError('لا تحتوي الصفحة على جدول HTML قابل للتصدير.')
        if len(response.content)>8*1024*1024:
            raise ExportError('حجم الصفحة كبير جدًا للتصدير. ضيّق الفلاتر.', 413)
        return Page(response.content.decode(response.charset or 'utf-8'))

    def collect(self, request, response, index, format):
        start = monotonic()
        page = self.parse(response)
        table = page.table(index)
        filters = filter_summary(page, request.GET)
        if len(filters)>12000:
            raise ExportError('الفلاتر طويلة جدًا؛ اختصر البحث وأعد المحاولة.', 413)
        key, links = pagination(table, request.path, request.GET)
        limit = int(getattr(settings, 'MAKKEN_EXPORT_MAX_ROWS', 5000))
        if format == 'pdf':
            limit = min(limit, int(getattr(settings, 'MAKKEN_PDF_MAX_ROWS', 1000)))
        max_pages = int(getattr(settings, 'MAKKEN_EXPORT_MAX_PAGES', 200))
        max_seconds = int(getattr(settings, 'MAKKEN_EXPORT_COLLECTION_SECONDS', 20))
        def within_size_limit():
            if len(table.headers)>40 or sum(len(v) for row in table.rows for values in row for v in values)>12*1024*1024:
                raise ExportError('التقرير كبير جدًا. ضيّق الفلاتر ثم أعد المحاولة.', 413)
        within_size_limit()
        if key:
            # Start at the beginning regardless of the currently viewed page.
            try:
                current = int(request.GET.get(key, '1'))
            except ValueError:
                current = 0
            if current != 1:
                page = self.parse(self.get_response(self.clone(request, key, 1)))
                first = page.table(index)
                if first.headers != table.headers:
                    raise ExportError('تغيّرت أعمدة الجدول أثناء التصدير.', 409)
                table = first
                _, links = pagination(table, request.path, request.GET)
            current = 1
            pages = 1
            while True:
                if len(table.rows)>limit:
                    raise ExportError(f'يتجاوز التقرير الحد المسموح ({limit:,} سجل). ضيّق الفلاتر ثم أعد التصدير.', 413)
                next_pages = [n for n in links if n>current]
                if not next_pages:
                    break
                if pages >= max_pages or monotonic()-start>max_seconds:
                    raise ExportError('التقرير كبير ويحتاج وقتًا أطول. ضيّق الفلاتر ثم أعد التصدير.', 413)
                number = min(next_pages)
                next_response = self.get_response(self.clone(request, key, number))
                try:
                    next_page = self.parse(next_response)
                    other = next_page.table(index)
                    if other.headers != table.headers:
                        raise ExportError('تغيّرت أعمدة الجدول أثناء التصدير.', 409)
                    next_key, links = pagination(other, request.path, request.GET)
                    if next_key is not None and next_key != key:
                        raise ExportError('تغيّرت آلية ترقيم الصفحات أثناء التصدير.', 409)
                    table.rows.extend(other.rows)
                    within_size_limit()
                finally:
                    next_response.close()
                current = number
                pages += 1
        if len(table.rows)>limit:
            raise ExportError(f'يتجاوز التقرير الحد المسموح ({limit:,} سجل). ضيّق الفلاتر ثم أعد التصدير.', 413)
        cells = sum(sum(sum(len(v) for v in values) for values in row) for row in table.rows)
        if cells>12*1024*1024 or len(table.headers)>40:
            raise ExportError('التقرير كبير جدًا. ضيّق الفلاتر ثم أعد المحاولة.', 413)
        return table, filters
