"""Add a minimal judge request outbox."""
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""CREATE TABLE outbox_events (
      id BIGINT NOT NULL AUTO_INCREMENT,
      judge_attempt_id BIGINT NOT NULL,
      event_type VARCHAR(64) NOT NULL,
      status VARCHAR(16) NOT NULL DEFAULT 'pending',
      created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
      published_at DATETIME(6) NULL,
      PRIMARY KEY (id),
      UNIQUE KEY uq_outbox_attempt_event (judge_attempt_id,event_type),
      KEY ix_outbox_status_id (status,id),
      CONSTRAINT ck_outbox_status CHECK (status IN ('pending','processing','published')),
      CONSTRAINT fk_outbox_attempt FOREIGN KEY (judge_attempt_id) REFERENCES judge_attempts(id)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci""")


def downgrade():
    op.execute("DROP TABLE IF EXISTS outbox_events")
