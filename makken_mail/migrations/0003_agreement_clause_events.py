from django.db import migrations


def register(apps, schema_editor):
    rules = apps.get_model("makken_mail", "EventRule").objects.using(schema_editor.connection.alias)
    codes = ("create", "update", "status", "delete", "view", "download", "export_xlsx", "export_pdf", "denied")
    for code in ["agreement.clause_progress", *(f"agreement_clauses.{action}" for action in codes)]:
        rules.get_or_create(code=code)


class Migration(migrations.Migration):
    dependencies = [("makken_mail", "0002_initial_mail_rules"), ("access_control", "0008_agreement_clause_catalog")]
    operations = [migrations.RunPython(register, migrations.RunPython.noop)]
