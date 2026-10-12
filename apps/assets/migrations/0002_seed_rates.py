from django.db import migrations

from apps.assets.rates import declining_rates, straight_line_rate


def seed(apps, schema_editor):
    DepreciationRate = apps.get_model("assets", "DepreciationRate")
    for n in range(2, 51):
        rate, revised, guarantee = declining_rates(n)
        DepreciationRate.objects.get_or_create(useful_life=n, defaults={
            "straight_line_rate": straight_line_rate(n), "declining_rate": rate,
            "revised_rate": revised, "guarantee_rate": guarantee,
        })


class Migration(migrations.Migration):
    dependencies = [("assets", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
