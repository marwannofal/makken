"""Public CSP-safe JavaScript catalog view for Makken English UI runtime localization."""
from __future__ import annotations

import json

from django.contrib.auth.decorators import login_not_required
from django.http import HttpResponse
from django.views.decorators.http import require_GET

from .i18n_catalog import get_js_catalog


@login_not_required
@require_GET
def i18n_js_catalog(request):
    """Serve the Arabic->English UI dictionary as an external JS script (CSP script-src 'self')."""
    payload = json.dumps(get_js_catalog(), ensure_ascii=False, separators=(",", ":"))
    body = f"window.MAKKEN_I18N_EN = {payload};\n"
    response = HttpResponse(body, content_type="application/javascript; charset=utf-8")
    response["Cache-Control"] = "public, max-age=3600"
    return response
