"""Internal export pages must not emit the outer request's finished signal."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
from django.core.signals import request_finished
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase
from core.table_exports import TableExportMiddleware


class ExportResponseLifecycleTests(SimpleTestCase):
    def setUp(self):
        self.finished = Mock()
        request_finished.connect(self.finished, weak=False, dispatch_uid="makken-export-lifecycle-test")
        self.addCleanup(request_finished.disconnect, dispatch_uid="makken-export-lifecycle-test")
        self.responses = []
        self.closers = []

    def page(self, request):
        number = int(request.GET.get("page", "1"))
        response = HttpResponse(f'<main id="main-content"><section><h2>السجلات</h2><table><thead><tr><th>اسم</th></tr></thead><tbody><tr><td>سجل {number}</td></tr></tbody></table><nav class="pagination"><a href="?page=2">2</a><a href="?page=3">3</a></nav></section></main>')
        closer = Mock()
        response._resource_closers.append(closer)
        self.responses.append(response); self.closers.append(closer)
        return response

    def export(self, page=1):
        request = RequestFactory().get("/records/", {"page": page, "_mk_export": "xlsx", "_mk_table": "0"})
        request.user = SimpleNamespace(is_authenticated=True)
        with patch("access_control.exports.export_access", return_value={"xlsx": True}), patch("core.table_exports.xlsx_bytes", return_value=b"PK-test"):
            return TableExportMiddleware(self.page)(request)

    def test_multiple_pages_release_resources_without_ending_request(self):
        result = self.export()
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(self.responses), 3)
        self.finished.assert_not_called()
        for response, closer in zip(self.responses, self.closers):
            closer.assert_called_once_with()
            self.assertTrue(response.closed)
            self.assertEqual(response._resource_closers, [])
        # The real outgoing response still ends the request exactly once.
        result.close()
        self.finished.assert_called_once()

    def test_export_from_later_page_releases_discarded_initial_and_first_pages(self):
        result = self.export(page=3)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(len(self.responses), 4)
        self.finished.assert_not_called()
        for closer in self.closers:
            closer.assert_called_once_with()

    def test_failed_export_releases_initial_page_without_finish_signal(self):
        with patch("core.table_exports.TableExportMiddleware.collect", side_effect=RuntimeError("simulated error")), self.assertLogs("core.table_exports", level="ERROR"):
            result = self.export()
        self.assertEqual(result.status_code, 500)
        self.closers[0].assert_called_once_with()
        self.finished.assert_not_called()

    def test_resource_failure_does_not_skip_remaining_cleanup(self):
        response = HttpResponse("test")
        first = Mock(side_effect=OSError("closed resource")); second = Mock()
        response._resource_closers.extend([first, second])
        TableExportMiddleware.release_internal_response(response)
        TableExportMiddleware.release_internal_response(response)
        first.assert_called_once_with(); second.assert_called_once_with()
        self.finished.assert_not_called()
