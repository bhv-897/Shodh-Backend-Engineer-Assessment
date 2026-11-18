"""Frozen Stage 1 MySQL 8 schema and database invariants."""
from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

TABLES = [
    """CREATE TABLE users (
      id BIGINT NOT NULL AUTO_INCREMENT, email VARCHAR(320) NOT NULL, name VARCHAR(160) NOT NULL,
      password_hash VARCHAR(255) NOT NULL, created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      PRIMARY KEY (id), UNIQUE KEY uq_users_email (email)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""",
    """CREATE TABLE organizations (
      id BIGINT NOT NULL AUTO_INCREMENT, name VARCHAR(200) NOT NULL,
      created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), PRIMARY KEY (id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""",
    """CREATE TABLE organization_memberships (
      id BIGINT NOT NULL AUTO_INCREMENT, organization_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
      role VARCHAR(16) NOT NULL, created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), PRIMARY KEY (id),
      UNIQUE KEY uq_membership_org_user (organization_id,user_id), KEY ix_memberships_user_org (user_id,organization_id), KEY ix_memberships_org_id (organization_id,id),
      CONSTRAINT ck_membership_role CHECK (role IN ('owner','organizer','member')),
      CONSTRAINT fk_membership_org FOREIGN KEY (organization_id) REFERENCES organizations(id),
      CONSTRAINT fk_membership_user FOREIGN KEY (user_id) REFERENCES users(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""",
    """CREATE TABLE problems (
      id BIGINT NOT NULL AUTO_INCREMENT, organization_id BIGINT NOT NULL, title VARCHAR(255) NOT NULL,
      created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), PRIMARY KEY (id),
      UNIQUE KEY uq_problem_id_org (id,organization_id), KEY ix_problems_org_id (organization_id,id),
      CONSTRAINT fk_problem_org FOREIGN KEY (organization_id) REFERENCES organizations(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""",
    """CREATE TABLE problem_versions (
      id BIGINT NOT NULL AUTO_INCREMENT, problem_id BIGINT NOT NULL, version_number INT NOT NULL,
      statement TEXT NOT NULL, execution_limits JSON NOT NULL, runtime_configuration JSON NOT NULL,
      published_at DATETIME(6) NULL, created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), PRIMARY KEY (id),
      UNIQUE KEY uq_version_problem_number (problem_id,version_number), UNIQUE KEY uq_version_id_problem (id,problem_id),
      KEY ix_problem_versions_problem_published (problem_id,published_at,version_number),
      CONSTRAINT fk_version_problem FOREIGN KEY (problem_id) REFERENCES problems(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""",
    """CREATE TABLE test_suites (
      id BIGINT NOT NULL AUTO_INCREMENT, problem_version_id BIGINT NOT NULL, version_number INT NOT NULL,
      status VARCHAR(16) NOT NULL DEFAULT 'draft', created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), PRIMARY KEY (id),
      UNIQUE KEY uq_suite_version_number (problem_version_id,version_number), UNIQUE KEY uq_suite_id_version (id,problem_version_id),
      KEY ix_test_suites_version_status (problem_version_id,status,version_number),
      CONSTRAINT ck_test_suite_status CHECK (status IN ('draft','active','retired')),
      CONSTRAINT fk_suite_version FOREIGN KEY (problem_version_id) REFERENCES problem_versions(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""",
    """CREATE TABLE test_cases (
      id BIGINT NOT NULL AUTO_INCREMENT, test_suite_id BIGINT NOT NULL, identifier VARCHAR(100) NOT NULL,
      input_data TEXT NOT NULL, expected_output TEXT NOT NULL, is_hidden BOOLEAN NOT NULL DEFAULT FALSE,
      points INT NOT NULL DEFAULT 0, PRIMARY KEY (id), UNIQUE KEY uq_case_suite_identifier (test_suite_id,identifier),
      KEY ix_test_cases_suite_id (test_suite_id,id), CONSTRAINT ck_test_case_points CHECK (points >= 0),
      CONSTRAINT fk_case_suite FOREIGN KEY (test_suite_id) REFERENCES test_suites(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""",
    """CREATE TABLE contests (
      id BIGINT NOT NULL AUTO_INCREMENT, organization_id BIGINT NOT NULL, organizer_id BIGINT NOT NULL,
      title VARCHAR(255) NOT NULL, start_time DATETIME(6) NOT NULL, end_time DATETIME(6) NOT NULL,
      status VARCHAR(16) NOT NULL DEFAULT 'draft', scoring_mode VARCHAR(32) NOT NULL DEFAULT 'icpc',
      penalty_minutes_per_wrong INT NOT NULL DEFAULT 20, created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), PRIMARY KEY (id),
      UNIQUE KEY uq_contest_id_org (id,organization_id), KEY ix_contests_org_status_id (organization_id,status,id),
      KEY ix_contests_status_start_id (status,start_time,id), CONSTRAINT ck_contest_time CHECK (end_time > start_time),
      CONSTRAINT fk_contest_org FOREIGN KEY (organization_id) REFERENCES organizations(id),
      CONSTRAINT fk_contest_organizer_member FOREIGN KEY (organization_id,organizer_id) REFERENCES organization_memberships(organization_id,user_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""",
    """CREATE TABLE contest_participants (
      id BIGINT NOT NULL AUTO_INCREMENT, contest_id BIGINT NOT NULL, user_id BIGINT NOT NULL,
      status VARCHAR(20) NOT NULL DEFAULT 'registered', registered_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), PRIMARY KEY (id),
      UNIQUE KEY uq_participant_contest_user (contest_id,user_id), UNIQUE KEY uq_participant_id_contest (id,contest_id),
      KEY ix_participants_contest_status_registered (contest_id,status,registered_at,id),
      CONSTRAINT ck_participant_status CHECK (status IN ('registered','withdrawn','disqualified')),
      CONSTRAINT fk_participant_contest FOREIGN KEY (contest_id) REFERENCES contests(id),
      CONSTRAINT fk_participant_user FOREIGN KEY (user_id) REFERENCES users(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""",
    """CREATE TABLE contest_problems (
      id BIGINT NOT NULL AUTO_INCREMENT, contest_id BIGINT NOT NULL, organization_id BIGINT NOT NULL,
      problem_id BIGINT NOT NULL, problem_version_id BIGINT NOT NULL, test_suite_id BIGINT NOT NULL,
      display_order INT NOT NULL, points INT NOT NULL, PRIMARY KEY (id),
      UNIQUE KEY uq_contest_problem (contest_id,problem_id), UNIQUE KEY uq_contest_display_order (contest_id,display_order),
      UNIQUE KEY uq_contest_pin_composite (id,contest_id,problem_version_id,test_suite_id),
      KEY ix_contest_problems_contest_order (contest_id,display_order,id),
      CONSTRAINT fk_contest_problem_contest_org FOREIGN KEY (contest_id,organization_id) REFERENCES contests(id,organization_id),
      CONSTRAINT fk_contest_problem_org_problem FOREIGN KEY (problem_id,organization_id) REFERENCES problems(id,organization_id),
      CONSTRAINT fk_contest_problem_version FOREIGN KEY (problem_version_id,problem_id) REFERENCES problem_versions(id,problem_id),
      CONSTRAINT fk_contest_problem_suite FOREIGN KEY (test_suite_id,problem_version_id) REFERENCES test_suites(id,problem_version_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""",
    """CREATE TABLE submissions (
      id BIGINT NOT NULL AUTO_INCREMENT, contest_participant_id BIGINT NOT NULL, contest_id BIGINT NOT NULL,
      contest_problem_id BIGINT NOT NULL, problem_version_id BIGINT NOT NULL, test_suite_id BIGINT NOT NULL,
      source_code MEDIUMTEXT NOT NULL, language VARCHAR(32) NOT NULL, runtime_config_snapshot JSON NOT NULL,
      status VARCHAR(20) NOT NULL DEFAULT 'queued', authoritative_attempt_id BIGINT NULL,
      submitted_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), PRIMARY KEY (id), UNIQUE KEY uq_submission_id_contest (id,contest_id),
      KEY ix_submissions_contest_submitted_id (contest_id,submitted_at,id),
      KEY ix_submissions_participant_problem_submitted (contest_participant_id,contest_problem_id,submitted_at,id),
      CONSTRAINT fk_submission_participant_contest FOREIGN KEY (contest_participant_id,contest_id) REFERENCES contest_participants(id,contest_id),
      CONSTRAINT fk_submission_contest_pin FOREIGN KEY (contest_problem_id,contest_id,problem_version_id,test_suite_id) REFERENCES contest_problems(id,contest_id,problem_version_id,test_suite_id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""",
    """CREATE TABLE judge_attempts (
      id BIGINT NOT NULL AUTO_INCREMENT, submission_id BIGINT NOT NULL, attempt_number INT NOT NULL, reason VARCHAR(16) NOT NULL,
      requested_by_user_id BIGINT NULL, status VARCHAR(16) NOT NULL DEFAULT 'queued', worker_id VARCHAR(128) NULL,
      lease_token VARCHAR(128) NULL, lease_expires_at DATETIME(6) NULL, retry_count INT NOT NULL DEFAULT 0,
      started_at DATETIME(6) NULL, completed_at DATETIME(6) NULL, created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), PRIMARY KEY (id),
      UNIQUE KEY uq_attempt_number (submission_id,attempt_number), UNIQUE KEY uq_attempt_id_submission (id,submission_id),
      KEY ix_attempts_submission_status (submission_id,status,attempt_number),
      CONSTRAINT ck_attempt_reason CHECK (reason IN ('initial','rejudge')),
      CONSTRAINT fk_attempt_submission FOREIGN KEY (submission_id) REFERENCES submissions(id),
      CONSTRAINT fk_attempt_requested_user FOREIGN KEY (requested_by_user_id) REFERENCES users(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""",
    """CREATE TABLE verdicts (
      id BIGINT NOT NULL AUTO_INCREMENT, judge_attempt_id BIGINT NOT NULL, verdict VARCHAR(32) NOT NULL,
      score INT NOT NULL DEFAULT 0, execution_time_ms INT NULL, memory_used_kb INT NULL, public_message TEXT NULL,
      private_diagnostics TEXT NULL, created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), PRIMARY KEY (id),
      UNIQUE KEY uq_verdict_attempt (judge_attempt_id), KEY ix_verdict_type_attempt (verdict,judge_attempt_id),
      CONSTRAINT ck_verdict_type CHECK (verdict IN ('ACCEPTED','WRONG_ANSWER','COMPILATION_ERROR','TIME_LIMIT_EXCEEDED','MEMORY_LIMIT_EXCEEDED','RUNTIME_ERROR','JUDGE_INFRA_FAILURE')),
      CONSTRAINT ck_verdict_score CHECK (score >= 0), CONSTRAINT fk_verdict_attempt FOREIGN KEY (judge_attempt_id) REFERENCES judge_attempts(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""",
]

TRIGGERS = [
    """CREATE TRIGGER trg_published_version_no_update BEFORE UPDATE ON problem_versions FOR EACH ROW
    BEGIN IF OLD.published_at IS NOT NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='PUBLISHED_VERSION_IMMUTABLE'; END IF; END""",
    """CREATE TRIGGER trg_published_version_no_delete BEFORE DELETE ON problem_versions FOR EACH ROW
    BEGIN IF OLD.published_at IS NOT NULL THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='PUBLISHED_VERSION_IMMUTABLE'; END IF; END""",
    """CREATE TRIGGER trg_active_suite_case_insert BEFORE INSERT ON test_cases FOR EACH ROW
    BEGIN IF (SELECT status FROM test_suites WHERE id=NEW.test_suite_id)='active' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ACTIVE_SUITE_IMMUTABLE'; END IF; END""",
    """CREATE TRIGGER trg_active_suite_case_update BEFORE UPDATE ON test_cases FOR EACH ROW
    BEGIN IF (SELECT status FROM test_suites WHERE id=OLD.test_suite_id)='active' OR (SELECT status FROM test_suites WHERE id=NEW.test_suite_id)='active' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ACTIVE_SUITE_IMMUTABLE'; END IF; END""",
    """CREATE TRIGGER trg_active_suite_case_delete BEFORE DELETE ON test_cases FOR EACH ROW
    BEGIN IF (SELECT status FROM test_suites WHERE id=OLD.test_suite_id)='active' THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='ACTIVE_SUITE_IMMUTABLE'; END IF; END""",
    """CREATE TRIGGER trg_membership_guard_update BEFORE UPDATE ON organization_memberships FOR EACH ROW
    BEGIN
      DECLARE lock_id BIGINT; DECLARE owners BIGINT; DECLARE organizer_contests BIGINT;
      SELECT id INTO lock_id FROM organizations WHERE id=OLD.organization_id FOR UPDATE;
      IF OLD.role='owner' AND NEW.role<>'owner' THEN
        SELECT COUNT(*) INTO owners FROM organization_memberships WHERE organization_id=OLD.organization_id AND role='owner';
        IF owners<=1 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='LAST_OWNER_REQUIRED'; END IF;
      END IF;
      IF OLD.role='organizer' AND NEW.role<>'organizer' THEN
        SELECT COUNT(*) INTO organizer_contests FROM contests WHERE organization_id=OLD.organization_id AND organizer_id=OLD.user_id AND status<>'archived';
        IF organizer_contests>0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='MEMBER_IS_CONTEST_ORGANIZER'; END IF;
      END IF;
    END""",
    """CREATE TRIGGER trg_membership_guard_delete BEFORE DELETE ON organization_memberships FOR EACH ROW
    BEGIN
      DECLARE lock_id BIGINT; DECLARE owners BIGINT; DECLARE organizer_contests BIGINT;
      SELECT id INTO lock_id FROM organizations WHERE id=OLD.organization_id FOR UPDATE;
      IF OLD.role='owner' THEN
        SELECT COUNT(*) INTO owners FROM organization_memberships WHERE organization_id=OLD.organization_id AND role='owner';
        IF owners<=1 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='LAST_OWNER_REQUIRED'; END IF;
      END IF;
      IF OLD.role='organizer' THEN
        SELECT COUNT(*) INTO organizer_contests FROM contests WHERE organization_id=OLD.organization_id AND organizer_id=OLD.user_id AND status<>'archived';
        IF organizer_contests>0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='MEMBER_IS_CONTEST_ORGANIZER'; END IF;
      END IF;
    END""",
    """CREATE TRIGGER trg_contest_organizer_role BEFORE INSERT ON contests FOR EACH ROW
    BEGIN
      DECLARE lock_id BIGINT; DECLARE role_count BIGINT;
      SELECT id INTO lock_id FROM organizations WHERE id=NEW.organization_id FOR UPDATE;
      SELECT COUNT(*) INTO role_count FROM organization_memberships WHERE organization_id=NEW.organization_id AND user_id=NEW.organizer_id AND role IN ('owner','organizer');
      IF role_count=0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='INVALID_CONTEST_ORGANIZER'; END IF;
    END""",
    """CREATE TRIGGER trg_contest_organizer_role_update BEFORE UPDATE ON contests FOR EACH ROW
    BEGIN
      DECLARE lock_id BIGINT; DECLARE role_count BIGINT;
      SELECT id INTO lock_id FROM organizations WHERE id=NEW.organization_id FOR UPDATE;
      SELECT COUNT(*) INTO role_count FROM organization_memberships WHERE organization_id=NEW.organization_id AND user_id=NEW.organizer_id AND role IN ('owner','organizer');
      IF role_count=0 THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='INVALID_CONTEST_ORGANIZER'; END IF;
    END""",
    """CREATE TRIGGER trg_submission_snapshot BEFORE UPDATE ON submissions FOR EACH ROW
    BEGIN IF OLD.contest_participant_id<>NEW.contest_participant_id OR OLD.contest_id<>NEW.contest_id OR OLD.contest_problem_id<>NEW.contest_problem_id OR OLD.problem_version_id<>NEW.problem_version_id OR OLD.test_suite_id<>NEW.test_suite_id OR OLD.source_code<>NEW.source_code OR OLD.language<>NEW.language OR OLD.runtime_config_snapshot<>NEW.runtime_config_snapshot OR OLD.submitted_at<>NEW.submitted_at THEN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='SUBMISSION_SNAPSHOT_IMMUTABLE'; END IF; END""",
    """CREATE TRIGGER trg_submission_no_delete BEFORE DELETE ON submissions FOR EACH ROW
    BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT='SUBMISSION_IMMUTABLE'; END""",
]

TRIGGER_NAMES = [
    "trg_submission_no_delete", "trg_submission_snapshot", "trg_contest_organizer_role_update",
    "trg_contest_organizer_role", "trg_membership_guard_delete", "trg_membership_guard_update",
    "trg_active_suite_case_delete", "trg_active_suite_case_update", "trg_active_suite_case_insert",
    "trg_published_version_no_delete", "trg_published_version_no_update",
]

def upgrade():
    for ddl in TABLES:
        op.execute(ddl)
    # Attach the circular authoritative attempt reference only after judge_attempts exists.
    op.execute("ALTER TABLE submissions ADD CONSTRAINT fk_submission_authoritative_attempt FOREIGN KEY (authoritative_attempt_id,id) REFERENCES judge_attempts(id,submission_id)")
    for ddl in TRIGGERS:
        op.execute(ddl)

def downgrade():
    for name in TRIGGER_NAMES:
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
    op.execute("ALTER TABLE submissions DROP FOREIGN KEY fk_submission_authoritative_attempt")
    for table in ("verdicts","judge_attempts","submissions","contest_problems","contest_participants","contests","test_cases","test_suites","problem_versions","problems","organization_memberships","organizations","users"):
        op.execute(f"DROP TABLE IF EXISTS {table}")
