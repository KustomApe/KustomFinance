from django.db import migrations

from apps.ledger.seed import ACCOUNTS, TAX_CATEGORIES


def seed(apps, schema_editor):
    TaxCategory = apps.get_model("ledger", "TaxCategory")
    Account = apps.get_model("ledger", "Account")
    taxes = {}
    for i, (code, name, kind, rate, reduced, pct) in enumerate(TAX_CATEGORIES):
        taxes[code], _ = TaxCategory.objects.get_or_create(
            code=code,
            defaults={"name": name, "kind": kind, "rate": rate, "is_reduced": reduced,
                      "deductible_percent": pct, "sort_order": i},
        )
    for code, name, section, tax, key in ACCOUNTS:
        Account.objects.get_or_create(
            code=code,
            defaults={"name": name, "section": section, "default_tax_category": taxes[tax], "system_key": key},
        )


class Migration(migrations.Migration):
    dependencies = [("ledger", "0002_triggers")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
