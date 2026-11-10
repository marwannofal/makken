from django import template
from core.dashboard_data import money

register=template.Library()


@register.filter
def dash_money(value):
    return money(value)
