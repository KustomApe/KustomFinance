from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION audit_auditlog_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '操作ログは変更・削除できません';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_auditlog_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_auditlog
    FOR EACH ROW EXECUTE FUNCTION audit_auditlog_immutable();

CREATE TRIGGER audit_auditlog_no_truncate
    BEFORE TRUNCATE ON audit_auditlog
    FOR EACH STATEMENT EXECUTE FUNCTION audit_auditlog_immutable();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS audit_auditlog_no_truncate ON audit_auditlog;
DROP TRIGGER IF EXISTS audit_auditlog_no_update_delete ON audit_auditlog;
DROP FUNCTION IF EXISTS audit_auditlog_immutable();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE_SQL)]
