"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-16 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(length=255), nullable=True),
        sa.Column("first_name", sa.String(length=255), nullable=True),
        sa.Column("last_name", sa.String(length=255), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_activity_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
        *timestamps(),
        sa.UniqueConstraint("telegram_id", name="uq_users_telegram_id"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])
    op.create_index("ix_users_username", "users", ["username"])

    op.create_table(
        "admins",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("role", sa.String(length=64), nullable=False, server_default="admin"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *timestamps(),
        sa.UniqueConstraint("telegram_id", name="uq_admins_telegram_id"),
    )
    op.create_index("ix_admins_telegram_id", "admins", ["telegram_id"])

    op.create_table(
        "categories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        *timestamps(),
        sa.UniqueConstraint("title", name="uq_categories_title"),
    )
    op.create_index("ix_categories_is_active", "categories", ["is_active"])
    op.create_index("ix_categories_sort_order", "categories", ["sort_order"])

    op.create_table(
        "subcategories",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        *timestamps(),
        sa.UniqueConstraint("category_id", "title", name="uq_subcategory_category_title"),
    )
    op.create_index("ix_subcategories_category_id", "subcategories", ["category_id"])
    op.create_index("ix_subcategories_is_active", "subcategories", ["is_active"])
    op.create_index("ix_subcategories_sort_order", "subcategories", ["sort_order"])

    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("subcategory_id", sa.Integer(), sa.ForeignKey("subcategories.id"), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="RUB"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        *timestamps(),
        sa.CheckConstraint("price >= 0", name="ck_products_price_non_negative"),
    )
    op.create_index("ix_products_category_id", "products", ["category_id"])
    op.create_index("ix_products_subcategory_id", "products", ["subcategory_id"])
    op.create_index("ix_products_title", "products", ["title"])
    op.create_index("ix_products_is_active", "products", ["is_active"])
    op.create_index("ix_products_sort_order", "products", ["sort_order"])
    op.create_index(
        "ix_products_category_subcategory_active",
        "products",
        ["category_id", "subcategory_id", "is_active"],
    )

    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("category_id", sa.Integer(), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("subcategory_id", sa.Integer(), sa.ForeignKey("subcategories.id"), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("payment_provider", sa.String(length=64), nullable=False, server_default="telegram"),
        sa.Column("payment_payload", sa.String(length=128), nullable=True),
        sa.Column("provider_invoice_id", sa.String(length=255), nullable=True),
        sa.Column("telegram_payment_charge_id", sa.String(length=255), nullable=True),
        sa.Column("provider_payment_charge_id", sa.String(length=255), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        *timestamps(),
        sa.UniqueConstraint("payment_payload", name="uq_orders_payment_payload"),
    )
    op.create_index("ix_orders_user_id", "orders", ["user_id"])
    op.create_index("ix_orders_product_id", "orders", ["product_id"])
    op.create_index("ix_orders_category_id", "orders", ["category_id"])
    op.create_index("ix_orders_subcategory_id", "orders", ["subcategory_id"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_orders_user_status", "orders", ["user_id", "status"])
    op.create_index("ix_orders_created_status", "orders", ["created_at", "status"])

    op.create_table(
        "digital_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="available"),
        sa.Column("order_id", sa.Integer(), nullable=True),
        sa.Column("sold_to_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("uploaded_by_admin_id", sa.Integer(), sa.ForeignKey("admins.id"), nullable=True),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
        sa.UniqueConstraint("product_id", "value", name="uq_digital_items_product_value"),
        sa.UniqueConstraint("order_id", name="uq_digital_items_order_id"),
    )
    op.create_index("ix_digital_items_product_id", "digital_items", ["product_id"])
    op.create_index("ix_digital_items_status", "digital_items", ["status"])
    op.create_index("ix_digital_items_product_status", "digital_items", ["product_id", "status"])
    op.create_index("ix_digital_items_sold_to_status", "digital_items", ["sold_to_user_id", "status"])

    op.create_foreign_key(
        "fk_digital_items_order_id", "digital_items", "orders", ["order_id"], ["id"]
    )

    op.create_table(
        "payments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.id"), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default="telegram"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="succeeded"),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("telegram_payment_charge_id", sa.String(length=255), nullable=True),
        sa.Column("provider_payment_charge_id", sa.String(length=255), nullable=True),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        *timestamps(),
        sa.UniqueConstraint("telegram_payment_charge_id", name="uq_payments_telegram_charge"),
        sa.UniqueConstraint("provider_payment_charge_id", name="uq_payments_provider_charge"),
    )
    op.create_index("ix_payments_order_id", "payments", ["order_id"])

    op.create_table(
        "user_bans",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("admin_id", sa.Integer(), sa.ForeignKey("admins.id"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
    )
    op.create_index("ix_user_bans_user_id", "user_bans", ["user_id"])
    op.create_index("ix_user_bans_is_active", "user_bans", ["is_active"])

    op.create_table(
        "broadcasts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_id", sa.Integer(), sa.ForeignKey("admins.id"), nullable=True),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="draft"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        *timestamps(),
    )

    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=128), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("value_text", sa.Text(), nullable=True),
        *timestamps(),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("admin_id", sa.Integer(), sa.ForeignKey("admins.id"), nullable=True),
        sa.Column("actor_telegram_id", sa.BigInteger(), nullable=True),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("entity_type", sa.String(length=128), nullable=False),
        sa.Column("entity_id", sa.String(length=128), nullable=True),
        sa.Column("old_values", sa.JSON(), nullable=True),
        sa.Column("new_values", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_audit_logs_admin_id", "audit_logs", ["admin_id"])
    op.create_index("ix_audit_logs_actor_telegram_id", "audit_logs", ["actor_telegram_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_logs_entity_type", "audit_logs", ["entity_type"])
    op.create_index("ix_audit_logs_entity_id", "audit_logs", ["entity_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("settings")
    op.drop_table("broadcasts")
    op.drop_table("user_bans")
    op.drop_table("payments")
    op.drop_constraint("fk_digital_items_order_id", "digital_items", type_="foreignkey")
    op.drop_table("digital_items")
    op.drop_table("orders")
    op.drop_table("products")
    op.drop_table("subcategories")
    op.drop_table("categories")
    op.drop_table("admins")
    op.drop_table("users")
