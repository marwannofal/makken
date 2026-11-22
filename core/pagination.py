"""Site-wide pagination helpers and validated page-size resolution."""

ALLOWED_PAGE_SIZES = (10, 20, 50, 100)


def resolve_page_size(request, default=15, param="per_page"):
    """Return a validated page size from GET[param], falling back to default."""
    if request is None:
        return default
    raw = str(request.GET.get(param, "")).strip()
    if raw.isascii() and raw.isdigit():
        value = int(raw)
        if value in ALLOWED_PAGE_SIZES:
            return value
    return default
