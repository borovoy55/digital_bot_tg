"""quantity orders and editable menu

Revision ID: 0002_quantity_menu_settings
Revises: 0001_initial
Create Date: 2026-06-19 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0002_quantity_menu_settings"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
    )
    op.drop_constraint("uq_digital_items_order_id", "digital_items", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint("uq_digital_items_order_id", "digital_items", ["order_id"])
    op.drop_column("orders", "quantity")
