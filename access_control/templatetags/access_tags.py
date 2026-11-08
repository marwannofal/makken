from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from html.parser import HTMLParser
from access_control.policy import for_request
register=template.Library()


class AllowedNode(template.Node):
    def __init__(self,module,operation,yes,no,item=None):self.module=module;self.operation=operation;self.yes=yes;self.no=no;self.item=item
    def render(self,context):
        request=context.get('request')
        allowed=request and for_request(request).can(self.module.resolve(context),self.operation.resolve(context))
        if allowed and self.item is not None:
            allowed = region_writable(context, self.item.resolve(context))
        return (self.yes if allowed else self.no).render(context)


@register.tag('allowed')
def allowed(parser,token):
    bits=token.split_contents()
    if len(bits) not in {3,4}:raise template.TemplateSyntaxError('allowed requires module, operation and optional record')
    yes=parser.parse(('elseallowed','endallowed'));end=parser.next_token();no=template.NodeList()
    if end.contents=='elseallowed':no=parser.parse(('endallowed',));parser.delete_first_token()
    return AllowedNode(parser.compile_filter(bits[1]),parser.compile_filter(bits[2]),yes,no,parser.compile_filter(bits[3]) if len(bits)==4 else None)


@register.simple_tag(takes_context=True)
def access_can(context,module,operation='view'):
    request=context.get('request');return bool(request and for_request(request).can(module,operation))


@register.simple_tag(takes_context=True)
def access_any(context,module,*operations):
    request=context.get('request');return bool(request and any(for_request(request).can(module,op) for op in operations))


class LockedRadios(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=False);self.parts=[];self.hidden=[]
    def handle_starttag(self,tag,attrs):
        raw=self.get_starttag_text();data=dict(attrs)
        if tag=='input' and data.get('type') in {'radio','checkbox'}:
            raw=raw[:-1]+' disabled aria-disabled="true">'
            if 'checked' in data:self.hidden.append(format_html('<input type="hidden" data-ac-locked-status name="{}" value="{}">',data.get('name',''),data.get('value','')))
        self.parts.append(raw)
    def handle_startendtag(self,tag,attrs):self.handle_starttag(tag,attrs)
    def handle_endtag(self,tag):self.parts.append('</'+tag+'>')
    def handle_data(self,data):self.parts.append(data)
    def handle_entityref(self,name):self.parts.append('&'+name+';')
    def handle_charref(self,name):self.parts.append('&#'+name+';')
    def handle_comment(self,data):self.parts.append('<!--'+data+'-->')


class StatusNode(template.Node):
    def __init__(self,module,body):self.module=module;self.body=body
    def render(self,context):
        content=self.body.render(context);request=context.get('request')
        if request and for_request(request).can(self.module.resolve(context),'change_status'):return content
        parser=LockedRadios();parser.feed(content)
        return mark_safe(''.join(parser.parts)+''.join(parser.hidden))


@register.tag('guarded_status')
def guarded_status(parser,token):
    bits=token.split_contents();body=parser.parse(('endguarded_status',));parser.delete_first_token()
    return StatusNode(parser.compile_filter(bits[1]),body)


@register.simple_tag(takes_context=True)
def current_access(context):
    request=context.get('request');module=getattr(request.resolver_match.func,'_access_module',None) if request else None
    if not module:return {}
    policy=for_request(request)
    return {op:policy.can(module,op) for op in ['view','create','edit','delete','change_status','export','export_xlsx','export_pdf']}


@register.simple_tag(takes_context=True)
def region_writable(context, item):
    from access_control.regions import can_write, RegionalPolicy
    request = context.get('request')
    if not request or item is None:
        return False
    if hasattr(item, 'region_writable'):
        return bool(item.region_writable)
    if not hasattr(request, '_regional_policy'):
        request._regional_policy = RegionalPolicy(request.user)
    return can_write(request.user, item, policy=request._regional_policy)


@register.simple_tag(takes_context=True)
def regional_restricted(context):
    from access_control.regions import RegionalPolicy
    request = context.get('request')
    if not request:
        return True
    if not hasattr(request, '_regional_policy'):
        request._regional_policy = RegionalPolicy(request.user)
    return not request._regional_policy.unrestricted


@register.simple_tag(takes_context=True)
def regional_event(context, event):
    from access_control.regions import safe_event
    request=context.get('request')
    if not hasattr(request, '_regional_history_cache'):
        request._regional_history_cache={}
    return safe_event(event, request.user, request._regional_history_cache)
