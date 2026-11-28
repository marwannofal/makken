from decimal import Decimal, InvalidOperation
from django import template
from core.dashboard_data import money

register=template.Library()


@register.filter
def dash_money(value):
    return money(value)


@register.filter
def progress_tone(value):
    """Return mk-pct-high (>=50%) or mk-pct-low (<50%) for progress percentages."""
    if value is None or value == '':
        return ''
    try:
        num = Decimal(str(value).replace('%', '').strip())
    except (TypeError, ValueError, InvalidOperation):
        return ''
    return 'mk-pct-high' if num >= Decimal('50') else 'mk-pct-low'
