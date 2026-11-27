from django.db import migrations, models


def backfill_compound_duration_and_requested_support(apps, schema_editor):
    alias = schema_editor.connection.alias
    Need = apps.get_model("market_needs", "Need").objects.using(alias)
    for need in Need.all():
        dur = int(need.duration or 0)
        unit = need.duration_unit
        y = m = d = 0
        if unit == "year":
            y = min(max(dur, 1), 12)
        elif unit == "month":
            if dur <= 12:
                m = max(dur, 1)
            else:
                y = min(dur // 12, 12)
                m = dur % 12
        else:
            if dur <= 31:
                d = max(dur, 1)
            else:
                m = min(dur // 30, 12)
                d = min(dur % 30, 31)
                if m == 0 and d == 0:
                    d = 1
        need.duration_years = y
        need.duration_months = m
        need.duration_days = d
        update_fields = ["duration_years", "duration_months", "duration_days"]
        if need.total_cost and need.requested_support != need.total_cost:
            need.requested_support = need.total_cost
            update_fields.append("requested_support")
        need.save(update_fields=update_fields)


class Migration(migrations.Migration):
    dependencies = [
        ("market_needs", "0006_need_working_status_label"),
    ]

    operations = [
        migrations.AddField(
            model_name="need",
            name="duration_days",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="أيام"),
        ),
        migrations.AddField(
            model_name="need",
            name="duration_months",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="أشهر"),
        ),
        migrations.AddField(
            model_name="need",
            name="duration_years",
            field=models.PositiveSmallIntegerField(default=0, verbose_name="سنوات"),
        ),
        migrations.RunPython(backfill_compound_duration_and_requested_support, migrations.RunPython.noop),
    ]
