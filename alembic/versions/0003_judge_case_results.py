"""Persist safe per-test-case judge outcomes."""
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE judge_case_results (
      id BIGINT NOT NULL AUTO_INCREMENT,
      judge_attempt_id BIGINT NOT NULL,
      test_case_id BIGINT NOT NULL,
      ordinal INT NOT NULL,
      verdict VARCHAR(32) NOT NULL,
      execution_time_ms INT NULL,
      created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      PRIMARY KEY (id),
      UNIQUE KEY uq_case_result_attempt_ordinal (judge_attempt_id,ordinal),
      CONSTRAINT ck_case_result_ordinal CHECK (ordinal > 0),
      CONSTRAINT ck_case_result_verdict CHECK (verdict IN ('ACCEPTED','WRONG_ANSWER','COMPILATION_ERROR','TIME_LIMIT_EXCEEDED','RUNTIME_ERROR','JUDGE_INFRA_FAILURE')),
      CONSTRAINT fk_case_result_attempt FOREIGN KEY (judge_attempt_id) REFERENCES judge_attempts(id),
      CONSTRAINT fk_case_result_test_case FOREIGN KEY (test_case_id) REFERENCES test_cases(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS judge_case_results")
