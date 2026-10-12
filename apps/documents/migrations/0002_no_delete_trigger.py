from django.db import migrations

SQL = """
CREATE OR REPLACE FUNCTION documents_no_delete() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '証憑は削除できません';
END;
$$ LANGUAGE plpgsql;
CREATE TRIGGER documents_document_no_delete BEFORE DELETE ON documents_document
    FOR EACH ROW EXECUTE FUNCTION documents_no_delete();
"""
REVERSE = """
DROP TRIGGER IF EXISTS documents_document_no_delete ON documents_document;
DROP FUNCTION IF EXISTS documents_no_delete();
"""


class Migration(migrations.Migration):
    dependencies = [("documents", "0001_initial")]
    operations = [migrations.RunSQL(SQL, REVERSE)]
