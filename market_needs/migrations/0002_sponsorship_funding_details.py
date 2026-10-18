import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


def preserve_existing(apps, schema_editor):
    Sponsorship = apps.get_model("market_needs", "Sponsorship")
    AuditEvent = apps.get_model("market_needs", "AuditEvent")
    Level = apps.get_model("levels", "Level")
    bands = {row.funding_key: row for row in Level.objects.exclude(funding_key=None)}
    for record in Sponsorship.objects.select_related("need").iterator(chunk_size=500):
        event = AuditEvent.objects.filter(sponsorship_id=record.pk).order_by("-created_at", "-pk").first()
        record.updated_at = event.created_at if event else record.decided_at or record.created_at
        record.updated_by_id = event.actor_id if event else None
        if record.status == "approved" and record.amount > 0:
            total = record.need.total_cost
            key = "strategic" if record.amount == total else "gold" if record.amount * 100 >= total * 80 else "silver" if record.amount * 100 >= total * 60 else "bronze"
            record.level_id = bands[key].pk
            record.level_name = bands[key].name
        record.save(update_fields=["updated_at", "updated_by", "level", "level_name"])
    # Intentionally no allocation backfill: the old data does not say which
    # expense items received the approved money. Users reconcile it explicitly.


class Migration(migrations.Migration):
    dependencies = [("market_needs", "0001_initial"), ("levels", "0002_funding_key"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.AddField(model_name="sponsorship", name="level", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.PROTECT, to="levels.level")),
        migrations.AddField(model_name="sponsorship", name="level_name", field=models.CharField(blank=True, editable=False, max_length=100)),
        migrations.AddField(model_name="sponsorship", name="updated_by", field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="updated_market_sponsorships", to=settings.AUTH_USER_MODEL)),
        migrations.AddField(model_name="sponsorship", name="updated_at", field=models.DateTimeField(default=django.utils.timezone.now, editable=False, null=True)),
        migrations.CreateModel(name="SponsorshipAllocation", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("amount", models.DecimalField(decimal_places=2, max_digits=14)),
            ("expense_line", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="funding_allocations", to="market_needs.expenseline")),
            ("sponsorship", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="allocations", to="market_needs.sponsorship")),
        ], options={"ordering": ["expense_line__position", "pk"], "default_permissions": (), "constraints": [
            models.UniqueConstraint(fields=("sponsorship", "expense_line"), name="market_sponsor_line_unique"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="market_allocation_positive"),
        ]}),
        migrations.RunPython(preserve_existing, migrations.RunPython.noop),
    ]
