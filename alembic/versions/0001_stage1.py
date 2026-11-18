"""Stage 1 contest backend schema."""
from alembic import op
from app.db import Base
from app import models  # noqa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # The metadata declarations are the hand-maintained schema source. Build tables
    # first, then attach the intentional submission/attempt circular FK.
    Base.metadata.create_all(bind=op.get_bind())
    op.execute("ALTER TABLE submissions ADD CONSTRAINT fk_submissions_authoritative_attempt FOREIGN KEY (authoritative_attempt_id, id) REFERENCES judge_attempts (id, submission_id)")
    op.execute("""CREATE TRIGGER trg_published_version_no_update BEFORE UPDATE ON problem_versions FOR EACH ROW
      BEGIN IF OLD.published_at IS NOT NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='PUBLISHED_VERSION_IMMUTABLE'; END IF; END""")
    op.execute("""CREATE TRIGGER trg_published_version_no_delete BEFORE DELETE ON problem_versions FOR EACH ROW
      BEGIN IF OLD.published_at IS NOT NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='PUBLISHED_VERSION_IMMUTABLE'; END IF; END""")
    op.execute("""CREATE TRIGGER trg_active_suite_case_insert BEFORE INSERT ON test_cases FOR EACH ROW
      BEGIN IF (SELECT status FROM test_suites WHERE id=NEW.test_suite_id)='active' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ACTIVE_SUITE_IMMUTABLE'; END IF; END""")
    op.execute("""CREATE TRIGGER trg_active_suite_case_update BEFORE UPDATE ON test_cases FOR EACH ROW
      BEGIN IF (SELECT status FROM test_suites WHERE id=OLD.test_suite_id)='active' OR (SELECT status FROM test_suites WHERE id=NEW.test_suite_id)='active' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ACTIVE_SUITE_IMMUTABLE'; END IF; END""")
    op.execute("""CREATE TRIGGER trg_active_suite_case_delete BEFORE DELETE ON test_cases FOR EACH ROW
      BEGIN IF (SELECT status FROM test_suites WHERE id=OLD.test_suite_id)='active' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ACTIVE_SUITE_IMMUTABLE'; END IF; END""")
    op.execute("""CREATE TRIGGER trg_contest_organizer_role BEFORE INSERT ON contests FOR EACH ROW
      BEGIN IF NOT EXISTS (SELECT 1 FROM organization_memberships WHERE organization_id=NEW.organization_id AND user_id=NEW.organizer_id AND role IN ('owner','organizer')) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='INVALID_CONTEST_ORGANIZER'; END IF; END""")
    op.execute("""CREATE TRIGGER trg_contest_organizer_role_update BEFORE UPDATE ON contests FOR EACH ROW
      BEGIN IF NOT EXISTS (SELECT 1 FROM organization_memberships WHERE organization_id=NEW.organization_id AND user_id=NEW.organizer_id AND role IN ('owner','organizer')) THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='INVALID_CONTEST_ORGANIZER'; END IF; END""")
    op.execute("""CREATE TRIGGER trg_submission_snapshot BEFORE UPDATE ON submissions FOR EACH ROW
      BEGIN IF OLD.contest_participant_id<>NEW.contest_participant_id OR OLD.contest_id<>NEW.contest_id OR OLD.contest_problem_id<>NEW.contest_problem_id OR OLD.problem_version_id<>NEW.problem_version_id OR OLD.test_suite_id<>NEW.test_suite_id OR OLD.source_code<>NEW.source_code OR OLD.language<>NEW.language OR OLD.runtime_config_snapshot<>NEW.runtime_config_snapshot OR OLD.submitted_at<>NEW.submitted_at THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='SUBMISSION_SNAPSHOT_IMMUTABLE'; END IF; END""")
    op.execute("""CREATE TRIGGER trg_submission_no_delete BEFORE DELETE ON submissions FOR EACH ROW
      BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='SUBMISSION_IMMUTABLE'; END""")

def downgrade():
    for trigger in ["trg_submission_no_delete","trg_submission_snapshot","trg_contest_organizer_role_update","trg_contest_organizer_role","trg_active_suite_case_delete","trg_active_suite_case_update","trg_active_suite_case_insert","trg_published_version_no_delete","trg_published_version_no_update"]:
        op.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    op.execute("ALTER TABLE submissions DROP FOREIGN KEY fk_submissions_authoritative_attempt")
    Base.metadata.drop_all(bind=op.get_bind())
