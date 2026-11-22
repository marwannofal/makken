"""Site-wide centered numbered pill pagination + per-page (عدد السجلات) selector."""
from urllib.parse import urlencode

from django import template

from core.pagination import ALLOWED_PAGE_SIZES

register = template.Library()


@register.inclusion_tag("core/partials/pagination.html", takes_context=True)
def makken_pagination(
    context,
    page_obj,
    page_param="page",
    per_page_param=None,
    aria_label="ترقيم الصفحات",
    anchor="",
):
    if not page_obj or not getattr(page_obj, "paginator", None):
        return {"page_obj": None}
    if per_page_param is None:
        if page_param == "page":
            per_page_param = "per_page"
        elif page_param == "history_page":
            per_page_param = ""
        elif page_param.endswith("_page"):
            per_page_param = page_param[:-5] + "_per_page"
        else:
            per_page_param = f"{page_param}_per_page"

    request = context.get("request")
    base_pairs = []
    size_base_pairs = []
    if request is not None:
        for key, values in request.GET.lists():
            if key == "detail":
                continue
            for val in values:
                if key != page_param:
                    base_pairs.append((key, val))
                if key != page_param and key != per_page_param:
                    size_base_pairs.append((key, val))

    def build_url(number):
        pairs = [*base_pairs, (page_param, str(number))]
        return "?" + urlencode(pairs) + (anchor or "")

    def build_size_url(size):
        pairs = [*size_base_pairs, (per_page_param, str(size))]
        return "?" + urlencode(pairs) + (anchor or "")

    paginator = page_obj.paginator
    elided = paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1)
    ellipsis_marker = getattr(paginator, "ELLIPSIS", "…")
    page_items = []
    for entry in elided:
        if entry == ellipsis_marker:
            page_items.append({"type": "ellipsis"})
        else:
            num = int(entry)
            page_items.append({
                "type": "page",
                "number": num,
                "current": num == page_obj.number,
                "url": build_url(num),
            })

    current_per_page = paginator.per_page
    size_options = (
        [{"size": s, "selected": current_per_page == s, "url": build_size_url(s)} for s in ALLOWED_PAGE_SIZES]
        if per_page_param
        else []
    )

    return {
        "page_obj": page_obj,
        "page_param": page_param,
        "per_page_param": per_page_param,
        "aria_label": aria_label,
        "anchor": anchor or "",
        "prev_url": build_url(page_obj.previous_page_number()) if page_obj.has_previous() else "",
        "next_url": build_url(page_obj.next_page_number()) if page_obj.has_next() else "",
        "page_items": page_items,
        "current_per_page": current_per_page,
        "size_choices": ALLOWED_PAGE_SIZES,
        "size_options": size_options,
    }
