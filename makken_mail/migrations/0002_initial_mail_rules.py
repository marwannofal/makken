from django.db import migrations


# Frozen event codes and shipping defaults. No recipient or SMTP data is seeded.
DEFAULTS = {'account.created': ('actor', 'subject'),
 'account.deleted': ('actor',),
 'account.edited': ('actor', 'subject'),
 'account.login': ('actor',),
 'account.password': ('actor', 'subject'),
 'account.profile': ('actor',),
 'account.status': ('actor', 'subject'),
 'sponsorship.allocation': ('employee', 'manager'),
 'sponsorship.approved': ('employee', 'manager'),
 'sponsorship.contact': ('employee', 'manager'),
 'sponsorship.rejected': ('employee', 'manager'),
 'work.created': ('employee', 'manager'),
 'work.edited': ('employee', 'manager'),
 'work.progress': ('employee', 'manager'),
 'work.reassigned': ('employee', 'manager')}
DISABLED_CODES = """
access_control.create
access_control.delete
access_control.denied
access_control.download
access_control.export_pdf
access_control.export_xlsx
access_control.status
access_control.update
access_control.view
account.logout
accounts.create
accounts.delete
accounts.denied
accounts.download
accounts.export_pdf
accounts.export_xlsx
accounts.status
accounts.update
accounts.view
approved_programs.create
approved_programs.delete
approved_programs.denied
approved_programs.download
approved_programs.export_pdf
approved_programs.export_xlsx
approved_programs.status
approved_programs.update
approved_programs.view
care_states.create
care_states.delete
care_states.denied
care_states.download
care_states.export_pdf
care_states.export_xlsx
care_states.status
care_states.update
care_states.view
dashboard.create
dashboard.delete
dashboard.denied
dashboard.download
dashboard.export_pdf
dashboard.export_xlsx
dashboard.status
dashboard.update
dashboard.view
entities.create
entities.delete
entities.denied
entities.download
entities.export_pdf
entities.export_xlsx
entities.status
entities.update
entities.view
expense_items.create
expense_items.delete
expense_items.denied
expense_items.download
expense_items.export_pdf
expense_items.export_xlsx
expense_items.status
expense_items.update
expense_items.view
levels.create
levels.delete
levels.denied
levels.download
levels.export_pdf
levels.export_xlsx
levels.status
levels.update
levels.view
market_needs.create
market_needs.delete
market_needs.denied
market_needs.download
market_needs.export_pdf
market_needs.export_xlsx
market_needs.status
market_needs.update
market_needs.view
partnerships.create
partnerships.delete
partnerships.denied
partnerships.download
partnerships.export_pdf
partnerships.export_xlsx
partnerships.status
partnerships.update
partnerships.view
provider_assignments.create
provider_assignments.delete
provider_assignments.denied
provider_assignments.download
provider_assignments.export_pdf
provider_assignments.export_xlsx
provider_assignments.status
provider_assignments.update
provider_assignments.view
regions.create
regions.delete
regions.denied
regions.download
regions.export_pdf
regions.export_xlsx
regions.status
regions.update
regions.view
sectors.create
sectors.delete
sectors.denied
sectors.download
sectors.export_pdf
sectors.export_xlsx
sectors.status
sectors.update
sectors.view
service_providers.create
service_providers.delete
service_providers.denied
service_providers.download
service_providers.export_pdf
service_providers.export_xlsx
service_providers.status
service_providers.update
service_providers.view
specializations.create
specializations.delete
specializations.denied
specializations.download
specializations.export_pdf
specializations.export_xlsx
specializations.status
specializations.update
specializations.view
sponsorship.added
sponsorship.development
sponsorship_shapes.create
sponsorship_shapes.delete
sponsorship_shapes.denied
sponsorship_shapes.download
sponsorship_shapes.export_pdf
sponsorship_shapes.export_xlsx
sponsorship_shapes.status
sponsorship_shapes.update
sponsorship_shapes.view
training_programs.create
training_programs.delete
training_programs.denied
training_programs.download
training_programs.export_pdf
training_programs.export_xlsx
training_programs.status
training_programs.update
training_programs.view
user_activity.create
user_activity.delete
user_activity.denied
user_activity.download
user_activity.export_pdf
user_activity.export_xlsx
user_activity.status
user_activity.update
user_activity.view
""".split()


def seed(apps, schema_editor):
    alias = schema_editor.connection.alias
    config = apps.get_model("makken_mail", "SMTPConfig")
    config.objects.using(alias).get_or_create(pk=1)
    rule = apps.get_model("makken_mail", "EventRule")
    for code in [*DEFAULTS, *DISABLED_CODES]:
        routes = DEFAULTS.get(code, ())
        rule.objects.using(alias).get_or_create(pk=code, defaults={
            "enabled": bool(routes), **{"to_" + route: True for route in routes},
        })


class Migration(migrations.Migration):
    dependencies = [("makken_mail", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
