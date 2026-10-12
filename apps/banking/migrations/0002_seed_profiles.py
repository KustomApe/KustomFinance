from django.db import migrations


def seed(apps, schema_editor):
    ImportProfile = apps.get_model("banking", "ImportProfile")
    ImportProfile.objects.get_or_create(
        name="汎用（日付・摘要・出金・入金・残高）",
        defaults={"skip_rows": 1, "date_column": 1, "description_column": 2, "withdrawal_column": 3,
                  "deposit_column": 4, "balance_column": 5, "amount_column": 0},
    )
    ImportProfile.objects.get_or_create(
        name="汎用（日付・摘要・金額±・残高）",
        defaults={"skip_rows": 1, "date_column": 1, "description_column": 2, "withdrawal_column": 0,
                  "deposit_column": 0, "balance_column": 4, "amount_column": 3},
    )


class Migration(migrations.Migration):
    dependencies = [("banking", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
