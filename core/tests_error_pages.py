"""Database-free error response tests; URLs are used only with ROOT_URLCONF override."""
# MAKKEN RBAC ERROR TEST COMPAT v2
from django.conf import settings as _rbac_test_settings
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http import HttpResponse, HttpResponseNotAllowed, JsonResponse, StreamingHttpResponse
from django.test import Client, RequestFactory, SimpleTestCase, override_settings
from django.urls import path
from .error_content import CATALOG, TRANSIENT
from .error_pages import FriendlyErrorMiddleware, error_response, retry_seconds


def broken(request):
    raise RuntimeError("PRIVATE-EXCEPTION-CONTENT")


def forbidden(request):
    raise PermissionDenied("PRIVATE-FORBIDDEN-CONTENT")


def malformed(request):
    raise SuspiciousOperation("PRIVATE-BAD-REQUEST-CONTENT")


def limited(request):
    response = HttpResponse(status=429)
    response["Retry-After"] = "60"
    return response


def method(request):
    return HttpResponseNotAllowed(["POST"])


def form(request):
    return HttpResponse("OK")


urlpatterns = [path("broken/", broken), path("forbidden/", forbidden), path("bad/", malformed), path("limited/", limited), path("method/", method), path("form/", form)]
handler400 = "core.error_pages.bad_request"
handler403 = "core.error_pages.permission_denied"
handler404 = "core.error_pages.page_not_found"
handler500 = "core.error_pages.server_error"


@override_settings(DEBUG=False, ROOT_URLCONF=__name__, SECURE_SSL_REDIRECT=False, MAKKEN_ERROR_ASSET_BASE="/static/core/errors/", MIDDLEWARE=[entry for entry in _rbac_test_settings.MIDDLEWARE if entry != 'access_control.middleware.AccessBoundaryMiddleware'])
class ErrorPageTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.client = Client(raise_request_exception=False)

    def test_all_catalog_statuses_have_arabic_standalone_pages(self):
        for code in CATALOG:
            with self.subTest(code=code):
                response = error_response(self.factory.get("/"), code)
                self.assertEqual(response.status_code, code)
                self.assertContains(response, 'lang="ar" dir="rtl"', status_code=code)
                self.assertContains(response, "header-logo.svg", status_code=code)
                self.assertContains(response, 'data-retry-seconds="20"', status_code=code)
                self.assertContains(response, f'data-auto-refresh="{int(code in TRANSIENT)}"', status_code=code)
                self.assertIn("no-store", response["Cache-Control"])
                self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])

    def test_post_never_auto_retries(self):
        for code in TRANSIENT:
            response = error_response(self.factory.post("/save/", {"secret": "PRIVATE"}), code)
            self.assertContains(response, 'data-auto-refresh="0"', status_code=code)
            self.assertNotContains(response, "PRIVATE", status_code=code)

    def test_django_handlers_preserve_status_and_hide_internal_data(self):
        for url, code in [("/bad/", 400), ("/forbidden/", 403), ("/missing/", 404), ("/broken/", 500)]:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, code)
                self.assertContains(response, "منصة مكّن", status_code=code)
                self.assertNotContains(response, "PRIVATE-", status_code=code)

    def test_csrf_failure_is_arabic_and_does_not_echo_reason(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post("/form/", {"secret": "PRIVATE"})
        self.assertContains(response, "انتهت صلاحية النموذج", status_code=403)
        self.assertContains(response, 'data-auto-refresh="0"', status_code=403)
        self.assertNotContains(response, "PRIVATE", status_code=403)

    def test_method_error_keeps_allow_header(self):
        response = self.client.get("/method/")
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response["Allow"], "POST")
        self.assertContains(response, "منصة مكّن", status_code=405)

    def test_rate_limit_respects_longer_retry_after(self):
        response = self.client.get("/limited/")
        self.assertEqual(response["Retry-After"], "60")
        self.assertContains(response, 'data-retry-seconds="60"', status_code=429)
        self.assertEqual(retry_seconds("invalid"), 20)
        self.assertEqual(retry_seconds("2"), 20)

    def test_existing_html_validation_dialogs_json_and_streams_are_preserved(self):
        responses = [
            HttpResponse('<!doctype html><html><body>Existing dialog</body></html>', status=400),
            HttpResponse('<html><body>Existing login lockout</body></html>', status=429),
            JsonResponse({"error": "Existing upload validation"}, status=400),
            StreamingHttpResponse(iter([b"protected"]), status=403),
            HttpResponse("Conflict dialog", status=409),
        ]
        for response in responses:
            with self.subTest(status=response.status_code):
                result = FriendlyErrorMiddleware(lambda _: response)(self.factory.get("/"))
                self.assertIs(result, response)
                if response.streaming:
                    self.assertEqual(b"".join(response.streaming_content), b"protected")

    def test_xhr_and_asset_failures_do_not_receive_full_error_page(self):
        for headers in [{"HTTP_X_REQUESTED_WITH": "XMLHttpRequest"}, {"HTTP_ACCEPT": "application/json"}, {"HTTP_SEC_FETCH_DEST": "script"}]:
            response = HttpResponse("existing", status=500)
            self.assertIs(FriendlyErrorMiddleware(lambda _: response)(self.factory.get("/", **headers)), response)

    def test_rendering_never_uses_database_or_request_context_processors(self):
        # SimpleTestCase forbids all database access. A failing context processor
        # confirms the template renders independently of authentication as well.
        from unittest.mock import patch
        with patch("django.template.context.RequestContext.bind_template", side_effect=AssertionError("request context used")):
            response = error_response(self.factory.get("/"), 500)
        self.assertEqual(response.status_code, 500)
