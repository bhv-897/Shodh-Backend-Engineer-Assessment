"""Cover leaderboard submission reads with the authoritative attempt id."""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.drop_index("ix_submissions_participant_problem_submitted", table_name="submissions")
    op.create_index(
        "ix_submissions_participant_problem_submitted",
        "submissions",
        ["contest_participant_id", "contest_problem_id", "submitted_at", "id", "authoritative_attempt_id"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_submissions_participant_problem_submitted", table_name="submissions")
    op.create_index(
        "ix_submissions_participant_problem_submitted",
        "submissions",
        ["contest_participant_id", "contest_problem_id", "submitted_at", "id"],
        unique=False,
    )
