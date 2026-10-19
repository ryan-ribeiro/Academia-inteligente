"""Require client submission before reviewing an initial AI draft."""

import sqlalchemy as sa

from alembic import op

revision = "20261017_34"
down_revision = "20261013_33"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "training_plan_version",
        sa.Column("submitted_for_review_at", sa.DateTime(timezone=True), nullable=True),
    )
    # Instructor-authored drafts and explicitly accepted adaptations already
    # belong to professional review. Initial AI drafts still need client consent.
    op.execute(
        "UPDATE training_plan_version SET submitted_for_review_at = created_at "
        "WHERE origin = 'instructor' OR id IN ("
        "SELECT resulting_version_id FROM training_adaptation_proposal "
        "WHERE client_reviewed_at IS NOT NULL AND resulting_version_id IS NOT NULL)"
    )


def downgrade():
    op.drop_column("training_plan_version", "submitted_for_review_at")
