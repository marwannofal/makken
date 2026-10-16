"""Shared server-side filters for the eight editable settings registers."""
import re
import unicodedata
from urllib.parse import urlencode

from django.db.models import Q
from django.http import HttpResponseRedirect
from django.urls import reverse

CONFIG = {
    "levels": {"text": ["name"]},
    "regions": {"text": ["name"]},
    "entities": {"text": ["name"], "choices": ["entity_type", "branch"]},
    "specializations": {"text": ["name", "sector__name"]},
    "sectors": {"text": ["name", "specializations__name"]},
    "expense_items": {"text": ["name"]},
    "training_programs": {"text": ["name", "expense_items__name"], "choices": ["category"], "booleans": {"تدريبي": {"is_training": True}, "تشغيلي": {"is_operational": True}}},
    "sponsorship_shapes": {"text": ["name", "description"], "booleans": {"نعم": {"is_employment": True}, "لا": {"is_employment": False}, "توظيف": {"is_employment": True}, "غير توظيف": {"is_employment": False}}},
}
STATUS_TERMS = {"نشط": True, "غير نشط": False, "فعال": True, "غير فعال": False, "active": True, "inactive": False}


def values(request):
    q = " ".join(unicodedata.normalize("NFKC", request.GET.get("q", "")[:200]).split())
    status = request.GET.get("status", "")
    if status not in {"0", "1"}:
        status = ""
    return q, status


def context(request):
    q, status = values(request)
    params = {}
    if q:
        params["q"] = q
    if status:
        params["status"] = status
    page = request.GET.get("page", "")
    if page.isascii() and page.isdecimal() and len(page) <= 9 and int(page) > 1:
        params["page"] = page
    return {"settings_filter_q": q, "settings_filter_status": status, "settings_filter_active": bool(q or status), "settings_filter_query": urlencode(params)}


def redirect(request, view_name):
    query = context(request)["settings_filter_query"]
    return HttpResponseRedirect(reverse(view_name) + ("?" + query if query else ""))


def apply(request, queryset):
    model = queryset.model
    config = CONFIG[model._meta.app_label]
    q, status = values(request)
    if status:
        queryset = queryset.filter(is_active=status == "1")
    if not q:
        return queryset
    choices = [(field, list(model._meta.get_field(field).flatchoices)) for field in config.get("choices", [])]
    booleans = {**{key: {"is_active": value} for key, value in STATUS_TERMS.items()}, **config.get("booleans", {})}
    phrases = {str(label) for _, options in choices for _, label in options if " " in str(label)}
    phrases.update(key for key in booleans if " " in key)
    pattern = "|".join(r"(?<!\w)" + re.escape(label) + r"(?!\w)" for label in sorted(phrases, key=len, reverse=True))
    terms = re.findall("(?:" + pattern + r")|\S+" if pattern else r"\S+", q, re.I)[:12]
    for term in terms:
        condition = Q()
        for field in config["text"]:
            condition |= Q(**{field + "__icontains": term})
        for field, options in choices:
            exact = [value for value, label in options if str(label).casefold() == term.casefold()]
            found = exact or [value for value, label in options if term.casefold() in str(label).casefold()]
            if found:
                condition |= Q(**{field + "__in": found})
        for label, selected in booleans.items():
            if label.casefold() == term.casefold():
                condition |= Q(**selected)
        queryset = queryset.filter(condition)
    return queryset.distinct()
