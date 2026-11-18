from .models import AgreementClause, NeedClause, ProgramClause


class LinkConflict(Exception):
    pass


def configure_picker(form, model, owner_id, lookup):
    field = form.fields["agreement_clauses"]
    current = list(model.objects.filter(**{lookup: owner_id}).values_list("clause_id", flat=True)) if owner_id else []
    field.limit(current=current)
    form.initial.setdefault("agreement_clauses", current)
    # Preserve links when older clients submit an editor that had no picker.
    if form.is_bound and "agreement_clause_picker" not in form.data and form.add_prefix("agreement_clauses") not in form.data:
        field.disabled = True


def program_names(program):
    return [link.clause.name for link in program.agreement_clause_links.all()] if program else []


def need_names(need):
    return [link.clause.name for link in need.agreement_clause_links.all()]


def save_links(owner, selected, model):
    field = "program" if model is ProgramClause else "need"
    links = model.objects.filter(**{field: owner})
    current = set(links.values_list("clause_id", flat=True))
    desired = {item.pk for item in selected}
    locked = {item.pk: item for item in AgreementClause.objects.select_for_update().filter(pk__in=desired).order_by("pk")}
    if set(locked) != desired or any(not locked[pk].is_active for pk in desired - current):
        raise LinkConflict("تغيّرت حالة أحد بنود الاتفاقية قبل الحفظ. أعد فتح النموذج.")
    if current != desired:
        links.exclude(clause_id__in=desired).delete()
        model.objects.bulk_create([model(**{field: owner, "clause_id": pk}) for pk in sorted(desired - current)])
