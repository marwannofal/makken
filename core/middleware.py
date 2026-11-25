"""Middleware for Makken English UI localization (zero-overhead no-op in default Arabic mode)."""
from __future__ import annotations

from html import escape
from html.parser import HTMLParser

from .i18n_catalog import translate_ui_text

_SKIP_CONTENT_TAGS = frozenset({"script", "style", "textarea", "pre", "code"})
_TRANSLATABLE_ATTRS = frozenset({"placeholder", "aria-label", "title", "alt", "data-label", "data-empty-text"})
_VOID_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})


class _HtmlEnglishLocalizer(HTMLParser):
    """Safe, structure-preserving HTML localizer that translates UI text nodes & UI attributes."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self._out: list[str] = []
        self._skip_depth = 0
        self._in_lang_switcher = 0

    def _format_attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> str:
        if not attrs:
            return ""
        input_type = ""
        if tag == "input":
            for k, v in attrs:
                if k == "type" and v:
                    input_type = v.lower()
                    break

        parts: list[str] = []
        for k, v in attrs:
            if v is None:
                parts.append(k)
                continue
            new_v = v
            if self._in_lang_switcher == 0:
                if k in _TRANSLATABLE_ATTRS:
                    new_v = translate_ui_text(v)
                elif tag == "input" and k == "value" and input_type in {"submit", "button"}:
                    new_v = translate_ui_text(v)
            parts.append(f'{k}="{escape(new_v, quote=True)}"')
        return " " + " ".join(parts)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = tag.lower()
        is_switcher = any(k == "data-lang-switcher" for k, _ in attrs)
        if is_switcher:
            self._in_lang_switcher += 1
        elif self._in_lang_switcher > 0 and tag_l not in _VOID_TAGS:
            self._in_lang_switcher += 1

        if tag_l in _SKIP_CONTENT_TAGS:
            self._skip_depth += 1

        self._out.append(f"<{tag}{self._format_attrs(tag_l, attrs)}>")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = tag.lower()
        self._out.append(f"<{tag}{self._format_attrs(tag_l, attrs)} />")

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        if tag_l in _SKIP_CONTENT_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if self._in_lang_switcher > 0:
            self._in_lang_switcher -= 1
        self._out.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0 or self._in_lang_switcher > 0:
            self._out.append(data)
        else:
            self._out.append(translate_ui_text(data))

    def handle_entityref(self, name: str) -> None:
        self._out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self._out.append(f"&#{name};")

    def handle_comment(self, data: str) -> None:
        self._out.append(f"<!--{data}-->")

    def handle_decl(self, decl: str) -> None:
        self._out.append(f"<!{decl}>")

    def handle_pi(self, data: str) -> None:
        self._out.append(f"<?{data}>")

    def get_html(self) -> str:
        return "".join(self._out)


def localize_html_to_english(html: str) -> str:
    parser = _HtmlEnglishLocalizer()
    parser.feed(html)
    parser.close()
    return parser.get_html()


class MakkenLocalizationMiddleware:
    """Translates HTML UI responses to English when the active session/cookie language is 'en'."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        lang = getattr(request, "LANGUAGE_CODE", "ar") or "ar"
        if not lang.lower().startswith("en"):
            return response

        if getattr(response, "streaming", False):
            return response

        content_type = response.get("Content-Type", "")
        if "text/html" not in content_type.lower():
            return response

        try:
            html = response.content.decode(response.charset or "utf-8")
        except Exception:
            return response

        localized = localize_html_to_english(html)
        response.content = localized.encode(response.charset or "utf-8")
        if response.has_header("Content-Length"):
            response["Content-Length"] = str(len(response.content))
        return response
