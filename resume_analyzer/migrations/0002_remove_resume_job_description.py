from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('resume_analyzer', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE resume_analyzer_resume DROP COLUMN IF EXISTS job_description;",
            reverse_sql="ALTER TABLE resume_analyzer_resume ADD COLUMN job_description text NOT NULL DEFAULT '';",
        ),
    ]