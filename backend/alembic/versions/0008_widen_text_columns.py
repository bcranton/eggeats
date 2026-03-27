"""widen text columns: review_queue.reason and mentions.raw_business_name

Revision ID: 0008
Revises: 0007
Create Date: 2026-03-27
"""
from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # review_queue.reason: varchar(255) → Text (LLM generates long reason strings)
    op.alter_column(
        "review_queue",
        "reason",
        existing_type=sa.String(255),
        type_=sa.Text(),
        existing_nullable=False,
    )
    # review_queue.suggested_correction: varchar(255) → Text
    op.alter_column(
        "review_queue",
        "suggested_correction",
        existing_type=sa.String(255),
        type_=sa.Text(),
        existing_nullable=True,
    )
    # mentions.raw_business_name: varchar(255) → Text
    op.alter_column(
        "mentions",
        "raw_business_name",
        existing_type=sa.String(255),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "review_queue",
        "reason",
        existing_type=sa.Text(),
        type_=sa.String(255),
        existing_nullable=False,
    )
    op.alter_column(
        "review_queue",
        "suggested_correction",
        existing_type=sa.Text(),
        type_=sa.String(255),
        existing_nullable=True,
    )
    op.alter_column(
        "mentions",
        "raw_business_name",
        existing_type=sa.Text(),
        type_=sa.String(255),
        existing_nullable=False,
    )
