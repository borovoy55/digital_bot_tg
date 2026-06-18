from __future__ import annotations

import enum
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class DigitalItemStatus(str, enum.Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    SOLD = "sold"
    DELETED = "deleted"


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    PAID = "paid"
    CANCELLED = "cancelled"
    ERROR = "error"
    REFUNDED = "refunded"


class PaymentStatus(str, enum.Enum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


class BroadcastStatus(str, enum.Enum):
    DRAFT = "draft"
    RUNNING = "running"
    FINISHED = "finished"
    FAILED = "failed"


class TimestampMixin:
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, index=True)
    first_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    registered_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_activity_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    orders: Mapped[List["Order"]] = relationship(back_populates="user")
    bans: Mapped[List["UserBan"]] = relationship(back_populates="user")


class Admin(Base, TimestampMixin):
    __tablename__ = "admins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(64), default="admin", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Category(Base, TimestampMixin):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False, index=True)

    subcategories: Mapped[List["Subcategory"]] = relationship(back_populates="category")
    products: Mapped[List["Product"]] = relationship(back_populates="category")


class Subcategory(Base, TimestampMixin):
    __tablename__ = "subcategories"
    __table_args__ = (UniqueConstraint("category_id", "title", name="uq_subcategory_category_title"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False, index=True)

    category: Mapped["Category"] = relationship(back_populates="subcategories")
    products: Mapped[List["Product"]] = relationship(back_populates="subcategory")


class Product(Base, TimestampMixin):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("price >= 0", name="ck_products_price_non_negative"),
        Index("ix_products_category_subcategory_active", "category_id", "subcategory_id", "is_active"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False, index=True)
    subcategory_id: Mapped[int] = mapped_column(
        ForeignKey("subcategories.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="RUB")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=100, nullable=False, index=True)

    category: Mapped["Category"] = relationship(back_populates="products")
    subcategory: Mapped["Subcategory"] = relationship(back_populates="products")
    digital_items: Mapped[List["DigitalItem"]] = relationship(back_populates="product")
    orders: Mapped[List["Order"]] = relationship(back_populates="product")


class DigitalItem(Base, TimestampMixin):
    __tablename__ = "digital_items"
    __table_args__ = (
        UniqueConstraint("product_id", "value", name="uq_digital_items_product_value"),
        Index("ix_digital_items_product_status", "product_id", "status"),
        Index("ix_digital_items_sold_to_status", "sold_to_user_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=DigitalItemStatus.AVAILABLE.value, nullable=False, index=True
    )
    order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("orders.id", use_alter=True, name="fk_digital_items_order_id"),
        nullable=True,
        unique=True,
    )
    sold_to_user_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True)
    uploaded_by_admin_id: Mapped[Optional[int]] = mapped_column(ForeignKey("admins.id"), nullable=True)
    sold_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)

    product: Mapped["Product"] = relationship(back_populates="digital_items")
    order: Mapped[Optional["Order"]] = relationship(
        back_populates="issued_item",
        foreign_keys=[order_id],
    )


class Order(Base, TimestampMixin):
    __tablename__ = "orders"
    __table_args__ = (
        Index("ix_orders_user_status", "user_id", "status"),
        Index("ix_orders_created_status", "created_at", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("categories.id"), nullable=False, index=True)
    subcategory_id: Mapped[int] = mapped_column(
        ForeignKey("subcategories.id"), nullable=False, index=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), default=OrderStatus.PENDING.value, nullable=False, index=True
    )
    payment_provider: Mapped[str] = mapped_column(String(64), default="telegram", nullable=False)
    payment_payload: Mapped[Optional[str]] = mapped_column(String(128), unique=True, nullable=True)
    provider_invoice_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    telegram_payment_charge_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    provider_payment_charge_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    paid_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship(back_populates="orders")
    product: Mapped["Product"] = relationship(back_populates="orders")
    issued_item: Mapped[Optional["DigitalItem"]] = relationship(
        back_populates="order",
        foreign_keys="DigitalItem.order_id",
        uselist=False,
    )
    payments: Mapped[List["Payment"]] = relationship(back_populates="order")


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("telegram_payment_charge_id", name="uq_payments_telegram_charge"),
        UniqueConstraint("provider_payment_charge_id", name="uq_payments_provider_charge"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="telegram")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=PaymentStatus.SUCCEEDED.value)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    telegram_payment_charge_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    provider_payment_charge_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    raw_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    order: Mapped["Order"] = relationship(back_populates="payments")


class UserBan(Base, TimestampMixin):
    __tablename__ = "user_bans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    admin_id: Mapped[Optional[int]] = mapped_column(ForeignKey("admins.id"), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    ended_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship(back_populates="bans")


class Broadcast(Base, TimestampMixin):
    __tablename__ = "broadcasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[Optional[int]] = mapped_column(ForeignKey("admins.id"), nullable=True)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    product_id: Mapped[Optional[int]] = mapped_column(ForeignKey("products.id"), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default=BroadcastStatus.DRAFT.value, nullable=False)
    sent_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_at: Mapped[Optional[DateTime]] = mapped_column(DateTime(timezone=True), nullable=True)


class Setting(Base, TimestampMixin):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    value_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admin_id: Mapped[Optional[int]] = mapped_column(ForeignKey("admins.id"), nullable=True, index=True)
    actor_telegram_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    entity_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    old_values: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    new_values: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[DateTime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
