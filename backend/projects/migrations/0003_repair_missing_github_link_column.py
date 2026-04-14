from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("projects", "0002_project_github_installation_id_task_ai_suggested_and_more"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "ALTER TABLE projects_project "
                        "ADD COLUMN IF NOT EXISTS github_link varchar(200) NULL;"
                    ),
                    reverse_sql=(
                        "ALTER TABLE projects_project "
                        "DROP COLUMN IF EXISTS github_link;"
                    ),
                )
            ],
            state_operations=[],
        ),
    ]

