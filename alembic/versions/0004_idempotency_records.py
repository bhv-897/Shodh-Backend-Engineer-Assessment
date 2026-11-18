"""Persist submission idempotency keys."""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE idempotency_records (
      id BIGINT NOT NULL AUTO_INCREMENT,
      user_id BIGINT NOT NULL,
      contest_id BIGINT NOT NULL,
      idempotency_key VARCHAR(128) NOT NULL,
      request_fingerprint CHAR(64) NOT NULL,
      submission_id BIGINT NOT NULL,
      created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      PRIMARY KEY (id),
      UNIQUE KEY uq_idempotency_user_contest_key (user_id,contest_id,idempotency_key),
      UNIQUE KEY uq_idempotency_submission (submission_id),
      KEY ix_idempotency_contest_created (contest_id,created_at,id),
      CONSTRAINT fk_idempotency_user FOREIGN KEY (user_id) REFERENCES users(id),
      CONSTRAINT fk_idempotency_contest FOREIGN KEY (contest_id) REFERENCES contests(id),
      CONSTRAINT fk_idempotency_submission FOREIGN KEY (submission_id) REFERENCES submissions(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS idempotency_records")
