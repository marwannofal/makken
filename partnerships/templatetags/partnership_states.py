"""Render the current development state using its configured color."""
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
