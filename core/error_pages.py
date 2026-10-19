"""Standalone HTML error handling; no authentication or database queries."""
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from django.conf import settings
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.views import defaults
from django.views.csrf import csrf_failure as default_csrf_failure
from .error_content import CATALOG, TRANSIENT, page_context


def wants_html(request):
    accept = request.headers.get("Accept", "")
    destination = request.headers.get("Sec-Fetch-Dest", "")
    return not (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in accept and "text/html" not in accept
        or destination and destination not in {"document", "iframe", "empty"}
    ) and (not accept or "text/html" in accept or "*/*" in accept)


def retry_seconds(value=None):
    if not value:
        return 20
    try:
        wait = int(value)
    except (ValueError, TypeError):
        try:
            wait = int((parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()) + 1
        except (ValueError, TypeError, OverflowError):
            return 20
    return max(20, wait)


def error_response(request, code, *, csrf=False, retry_after=None):
    seconds = retry_seconds(retry_after)
    base = getattr(settings, "MAKKEN_ERROR_ASSET_BASE", settings.STATIC_URL + "core/errors/")
    context = page_context(code, asset_base=base, method=request.method, seconds=seconds, csrf=csrf)
    # Omitting request intentionally avoids auth/context processors and DB access.
    html = render_to_string("core/errors/error.html", context)
    response = HttpResponse(html, status=code)
    response["Cache-Control"] = "no-store, private, max-age=0"
    response["X-Robots-Tag"] = "noindex, nofollow"
    response["X-Content-Type-Options"] = "nosniff"
    response["X-Frame-Options"] = "DENY"
    response["Referrer-Policy"] = "same-origin"
    response["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; img-src 'self' data:; font-src 'self' https://fonts.gstatic.com; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
    if code in TRANSIENT:
        response["Retry-After"] = str(seconds)
    return response


def bad_request(request, exception=None):
    return error_response(request, 400) if wants_html(request) else defaults.bad_request(request, exception)


def permission_denied(request, exception=None):
    return error_response(request, 403) if wants_html(request) else defaults.permission_denied(request, exception)


def page_not_found(request, exception=None):
    return error_response(request, 404) if wants_html(request) else defaults.page_not_found(request, exception)


def server_error(request):
    return error_response(request, 500) if wants_html(request) else defaults.server_error(request)


def csrf_failure(request, reason=""):
    return error_response(request, 403, csrf=True) if wants_html(request) else default_csrf_failure(request, reason=reason)


class FriendlyErrorMiddleware:
    """Handle generic error bodies, preserving form dialogs, JSON and streams."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if response.status_code not in CATALOG or not wants_html(request) or getattr(response, "streaming", False):
            return response
        content_type = response.get("Content-Type", "").split(";")[0].strip()
        if content_type != "text/html":
            return response
        content = response.content.lower()
        if b"<html" in content or b"<!doctype" in content:
            return response
        friendly = error_response(request, response.status_code, retry_after=response.get("Retry-After"))
        for header in ("Allow", "WWW-Authenticate", "Retry-After"):
            if header in response and header != "Retry-After":
                friendly[header] = response[header]
        friendly.cookies.update(response.cookies)
        return friendly
