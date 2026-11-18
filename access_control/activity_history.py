"""Normalize the three existing audit sources without inventing past views."""
from django.apps import apps
from .activity_data import sanitize, clean_text


def region_evidence(*payloads):
    from regions.models import Region
    ids, names = set(), set()
    for data in payloads:
        if not isinstance(data, dict):
            continue
        for key in ('regions', 'administrative_regions', 'allowed_regions'):
            value = data.get(key, [])
            if isinstance(value, str):
                names.update(n.strip() for n in value.split('،') if n.strip())
            elif isinstance(value, list):
                for v in value:
                    if type(v) is int or isinstance(v, str) and v.isascii() and v.isdigit():
                        ids.add(int(v))
                    elif isinstance(v, str):
                        names.add(v)
        for row in data.get('coverage', []) if isinstance(data.get('coverage'), list) else []:
            if isinstance(row, dict) and type(row.get('region')) is int:
                ids.add(row['region'])
        if type(data.get('region_id')) is int:
            ids.add(data['region_id'])
    result = dict(Region.objects.filter(pk__in=ids).values_list('pk', 'name'))
    result.update(dict(Region.objects.filter(name__in=names).values_list('pk','name')))
    return result


def normalized(data):
    data = dict(data) if isinstance(data, dict) else {}
    if isinstance(data.get('attachments'),list):
        data['attachment_count'] = len(data['attachments'])
    for key, label in [('حالة التنفيذ','status'), ('ملاحظات التنفيذ','notes'), ('تاريخ اكتمال التنفيذ','completed_at')]:
        if key in data:
            data[label] = data[key]
    # Existing execution evidence can include many unrelated organization
    # attributes. Preserve only selected parties' labels in this unified trail.
    for key, label in [('مزودو التدريب','providers'), ('جهات التوظيف','employers')]:
        if isinstance(data.get(key), list):
            data[label] = [v.get('name', v.get('provider_name', v.get('organization', 'جهة مختارة')))
                           for v in data[key] if isinstance(v, dict)]
    return sanitize(data)


def infer_action(description, before, after):
    if any(word in description for word in ('حذف', 'delete')):
        return 'delete'
    if any(word in description for word in ('إنشاء', 'إضافة', 'create')):
        return 'create'
    if any(word in description for word in ('حالة', 'اعتماد', 'رفض', 'انتقال', 'toggle', 'convert')):
        return 'status'
    return 'update'


def import_event(source, context=None, live=False):
    from .activity_capture import emit, regions_for
    from .models import UserActivity
    key = f'history:{source._meta.label_lower}:{source.pk}'
    if UserActivity.objects.filter(source_key=key).exists():
        return None
    label = source._meta.label_lower
    target, actor = None, source.actor
    description = source.action
    if label == 'market_needs.auditevent':
        target = source.need
        target_key = str(source.need_id or '')
        target_model = 'market_needs.need'
        target_label = source.need_number
        module = 'provider_assignments' if 'تنفيذ البرنامج' in description else 'market_needs'
    elif label == 'service_providers.provideraudit':
        target = source.provider
        target_key, target_model, target_label = str(source.provider_key), 'service_providers.serviceprovider', source.provider_name
        module = 'service_providers'
        description = {'create':'إضافة مزود خدمة', 'edit':'تعديل مزود خدمة', 'delete':'حذف مزود خدمة',
                       'toggle':'تغيير حالة مزود خدمة', 'convert':'تحويل مزود خدمة'}.get(description, description)
    else:
        target = source.target_user
        target_key = str(source.target_user_id or source.target_role_id or '')
        target_model = 'auth.user' if source.target_user_id else 'access_control.roleprofile'
        target_label, module = source.target_name, 'access_control'
    regions = region_evidence(source.before, source.after)
    if (context or live) and target is not None:
        regions.update(regions_for(target))
        if label == 'market_needs.auditevent' and source.sponsorship_id:
            regions.update(regions_for(source.sponsorship.partnership))
        if module == 'provider_assignments' and hasattr(target, 'execution'):
            execution = target.execution
            for link in execution.provider_links.select_related('provider'):
                regions.update(regions_for(link.provider))
            for link in execution.employer_links.select_related('partnership'):
                regions.update(regions_for(link.partnership))
    scope = 'global' if module == 'access_control' else 'regional' if regions else 'unknown'
    if context is None and not live and label == 'market_needs.auditevent' and (source.sponsorship_id or module == 'provider_assignments'):
        # Old evidence did not retain every counterparty's administrative
        # regions. Current assignments are not proof of their historic scope.
        scope = 'unknown'
    before, after = normalized(source.before), normalized(source.after)
    for name in ('email','phone'):
        if isinstance(source.before,dict) and isinstance(source.after,dict) and source.before.get(name) != source.after.get(name):
            after[name+'_changed'] = True
    if live and label == 'access_control.securityaudit' and description == 'تعديل المستخدم والصلاحيات' and source.before == source.after:
        live = False
    identity = {}
    if getattr(source,'actor_name',''):
        identity = {'actor_name':source.actor_name, 'actor_username':source.actor_name if actor else ''}
    return emit(actor=actor, **identity,
        module=module, action=infer_action(description, source.before, source.after),
        description=clean_text(description, 200), target_model=target_model,
        target_key=target_key, target_label=clean_text(str(target) if context and target else target_label, 300),
        before=before, after=after, regions=regions,
        scope=scope, context=context, live=live,
        sponsorship_id=getattr(source, 'sponsorship_id', None), source_key=key, created_at=source.created_at)


def import_history():
    count = 0
    for label in ('access_control.SecurityAudit', 'service_providers.ProviderAudit', 'market_needs.AuditEvent'):
        model = apps.get_model(label)
        for event in model.objects.select_related('actor').order_by('pk').iterator(chunk_size=200):
            if import_event(event) is not None:
                count += 1
    return count
