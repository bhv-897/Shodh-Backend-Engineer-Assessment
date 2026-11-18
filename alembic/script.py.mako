"""${message}"""
from alembic import op
import sqlalchemy as sa
${imports if imports else ""}
revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}
def upgrade():
    ${("\n    ".join(upgrade_ops.splitlines())) if upgrade_ops else "pass"}
def downgrade():
    ${("\n    ".join(downgrade_ops.splitlines())) if downgrade_ops else "pass"}
