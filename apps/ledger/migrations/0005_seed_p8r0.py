from django.db import migrations


def add(apps, schema_editor):
    TaxCategory = apps.get_model("ledger", "TaxCategory")
    after = TaxCategory.objects.filter(code="P10-0").first()
    TaxCategory.objects.get_or_create(
        code="P8R-0",
        defaults={"name": "課税仕入8%軽減（控除不可）", "kind": "taxable_purchase", "rate": 8, "is_reduced": True,
                  "deductible_percent": 0, "sort_order": (after.sort_order if after else 11)},
    )


class Migration(migrations.Migration):
    dependencies = [("ledger", "0004_journalline_department_journalline_partner_and_more")]
    operations = [migrations.RunPython(add, migrations.RunPython.noop)]
