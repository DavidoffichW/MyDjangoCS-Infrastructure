from django.db import migrations

JOB_COMMAND_TRIGGER = """
CREATE TRIGGER workflows_job_command_immutable
BEFORE UPDATE OF workflow_id, admission_id, command_version, input_digest,
                 workflow_snapshot, input_values
ON workflows_job
WHEN OLD.workflow_id IS NOT NEW.workflow_id
  OR OLD.admission_id IS NOT NEW.admission_id
  OR OLD.command_version IS NOT NEW.command_version
  OR OLD.input_digest IS NOT NEW.input_digest
  OR OLD.workflow_snapshot IS NOT NEW.workflow_snapshot
  OR OLD.input_values IS NOT NEW.input_values
BEGIN
    SELECT RAISE(ABORT, 'admitted command is immutable');
END;
"""

ADMISSION_TRIGGER = """
CREATE TRIGGER workflows_admission_immutable
BEFORE UPDATE OF investigation_id, state_identity, computation_identity,
                 declaration, resource_envelope, authorization_state
ON workflows_admissionrecord
BEGIN
    SELECT RAISE(ABORT, 'admission records are immutable');
END;
"""

RESEARCH_RUN_TRIGGER = """
CREATE TRIGGER workflows_research_run_immutable
BEFORE UPDATE OF evidence_content_identity, evidence_provenance_identity,
                 manifest_identity, state_identity, evidence_artifact_id,
                 manifest_artifact_id, state_artifact_id
ON workflows_researchrun
BEGIN
    SELECT RAISE(ABORT, 'research-run authority fields are immutable');
END;
"""


class Migration(migrations.Migration):
    dependencies = [("workflows", "0004_scientific_invariants")]

    operations = [
        migrations.RunSQL(
            sql="DROP TRIGGER IF EXISTS workflows_job_command_immutable;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.RunSQL(
            sql=JOB_COMMAND_TRIGGER,
            reverse_sql="DROP TRIGGER IF EXISTS workflows_job_command_immutable;",
        ),
        migrations.RunSQL(
            sql=ADMISSION_TRIGGER,
            reverse_sql="DROP TRIGGER IF EXISTS workflows_admission_immutable;",
        ),
        migrations.RunSQL(
            sql=RESEARCH_RUN_TRIGGER,
            reverse_sql="DROP TRIGGER IF EXISTS workflows_research_run_immutable;",
        ),
    ]
