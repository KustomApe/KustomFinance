from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION ledger_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '登録済みの仕訳は変更・削除できません。取消仕訳を登録してください';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ledger_journal_immutable BEFORE UPDATE OR DELETE ON ledger_journal
    FOR EACH ROW EXECUTE FUNCTION ledger_immutable();
CREATE TRIGGER ledger_journalline_immutable BEFORE UPDATE OR DELETE ON ledger_journalline
    FOR EACH ROW EXECUTE FUNCTION ledger_immutable();

-- 貸借一致と明細の存在をコミット時に検証する
CREATE OR REPLACE FUNCTION ledger_check_balance() RETURNS trigger AS $$
DECLARE
    jid bigint;
    dr numeric;
    cr numeric;
    n integer;
BEGIN
    IF TG_TABLE_NAME = 'ledger_journal' THEN
        jid := NEW.id;
    ELSE
        jid := NEW.journal_id;
    END IF;
    SELECT COALESCE(SUM(amount) FILTER (WHERE side = 'D'), 0),
           COALESCE(SUM(amount) FILTER (WHERE side = 'C'), 0),
           COUNT(*)
      INTO dr, cr, n
      FROM ledger_journalline WHERE journal_id = jid;
    IF n < 2 THEN
        RAISE EXCEPTION '仕訳 % には2行以上の明細が必要です', jid;
    END IF;
    IF dr <> cr THEN
        RAISE EXCEPTION '仕訳 % の貸借が一致しません（借方 % / 貸方 %）', jid, dr, cr;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

CREATE CONSTRAINT TRIGGER ledger_journal_balanced AFTER INSERT ON ledger_journal
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ledger_check_balance();
CREATE CONSTRAINT TRIGGER ledger_journalline_balanced AFTER INSERT ON ledger_journalline
    DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION ledger_check_balance();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS ledger_journalline_balanced ON ledger_journalline;
DROP TRIGGER IF EXISTS ledger_journal_balanced ON ledger_journal;
DROP TRIGGER IF EXISTS ledger_journalline_immutable ON ledger_journalline;
DROP TRIGGER IF EXISTS ledger_journal_immutable ON ledger_journal;
DROP FUNCTION IF EXISTS ledger_check_balance();
DROP FUNCTION IF EXISTS ledger_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [("ledger", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE_SQL)]
