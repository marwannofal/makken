from django import template
from access_control.exports import export_access

register = template.Library()


@register.simple_tag(takes_context=True)
def table_export_access(context):
    request = context.get('request')
    return export_access(request) if request else {'xlsx': False, 'pdf': False}
