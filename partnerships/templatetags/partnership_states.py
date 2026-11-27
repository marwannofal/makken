"""Render the current development state using its configured color."""
from decimal import Decimal, InvalidOperation
import re
from django import template

register = template.Library()


@register.inclusion_tag('partnerships/_development_pill.html')
def development_pill(state):
    color = getattr(state, 'color', '')
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', color):
        color = '#74888B'
    # Choose the higher-contrast text color for every configurable background.
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
    luminance = sum(c * weight for c, weight in zip(linear, (.2126, .7152, .0722)))
    return {
        'state_label': state.get_state_display() if state else 'غير محددة',
        'state_color': color,
        'text_class': 'development-pill-dark' if luminance > .179 else 'development-pill-light',
    }


@register.filter
def sar_money(value):
    """Format SAR amount with thousand commas and 2 decimals regardless of Arabic locale."""
    if value is None or value == '':
        return '—'
    try:
        return format(Decimal(value), ',.2f')
    except (TypeError, ValueError, InvalidOperation):
        return str(value)


@register.filter
def partnership_status_tone(status_obj):
    """Return a semantic pill tone class for AgreementOption partnership status."""
    name = (getattr(status_obj, 'name', '') or str(status_obj or '')).strip()
    if any(k in name for k in ('مستمر', 'ساري', 'نشط', 'فعّال', 'فعال')):
        return 'is-active'
    if any(k in name for k in ('منتهي', 'مكتمل')):
        return 'is-ended'
    if any(k in name for k in ('معلق', 'موقوف', 'قيد')):
        return 'is-paused'
    if any(k in name for k in ('متعثر', 'ملغ', 'مرفوض')):
        return 'is-stalled'
    return 'is-neutral'
