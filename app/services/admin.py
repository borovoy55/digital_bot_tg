from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError, ValidationError
from app.core.security import MAX_DESCRIPTION_LENGTH, MAX_TITLE_LENGTH, validate_text
from app.db.models import (
    Category,
    DigitalItem,
    DigitalItemStatus,
    Order,
    OrderStatus,
    Product,
    Subcategory,
    User,
)
from app.services.audit import write_audit_log


@dataclass(frozen=True)
class DashboardStats:
    total_revenue: Decimal
    today_revenue: Decimal
    week_revenue: Decimal
    month_revenue: Decimal
    orders_total: int
    orders_success: int
    orders_cancelled: int
    orders_error: int
    average_check: Decimal
    top_products: list[tuple[str, int, Decimal]]
    top_categories: list[tuple[str, int, Decimal]]
    top_buyers: list[tuple[int, str | None, Decimal]]
    available_items: int
    sold_items: int


async def dashboard_stats(session: AsyncSession) -> DashboardStats:
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week = now - timedelta(days=7)
    month = now - timedelta(days=30)

    async def revenue_since(start: datetime | None) -> Decimal:
        stmt = select(func.coalesce(func.sum(Order.amount), 0)).where(
            Order.status == OrderStatus.PAID.value
        )
        if start is not None:
            stmt = stmt.where(Order.paid_at >= start)
        return Decimal(await session.scalar(stmt) or 0)

    orders_total = int(await session.scalar(select(func.count(Order.id))) or 0)
    orders_success = int(
        await session.scalar(select(func.count(Order.id)).where(Order.status == OrderStatus.PAID.value))
        or 0
    )
    orders_cancelled = int(
        await session.scalar(
            select(func.count(Order.id)).where(Order.status == OrderStatus.CANCELLED.value)
        )
        or 0
    )
    orders_error = int(
        await session.scalar(select(func.count(Order.id)).where(Order.status == OrderStatus.ERROR.value))
        or 0
    )
    total_revenue = await revenue_since(None)
    average_check = total_revenue / orders_success if orders_success else Decimal("0")

    top_products_rows = await session.execute(
        select(Product.title, func.count(Order.id), func.coalesce(func.sum(Order.amount), 0))
        .join(Order, Order.product_id == Product.id)
        .where(Order.status == OrderStatus.PAID.value)
        .group_by(Product.title)
        .order_by(desc(func.count(Order.id)))
        .limit(5)
    )
    top_categories_rows = await session.execute(
        select(Category.title, func.count(Order.id), func.coalesce(func.sum(Order.amount), 0))
        .join(Order, Order.category_id == Category.id)
        .where(Order.status == OrderStatus.PAID.value)
        .group_by(Category.title)
        .order_by(desc(func.count(Order.id)))
        .limit(5)
    )
    top_buyers_rows = await session.execute(
        select(User.telegram_id, User.username, func.coalesce(func.sum(Order.amount), 0))
        .join(Order, Order.user_id == User.id)
        .where(Order.status == OrderStatus.PAID.value)
        .group_by(User.telegram_id, User.username)
        .order_by(desc(func.sum(Order.amount)))
        .limit(5)
    )
    available_items = int(
        await session.scalar(
            select(func.count(DigitalItem.id)).where(
                DigitalItem.status == DigitalItemStatus.AVAILABLE.value
            )
        )
        or 0
    )
    sold_items = int(
        await session.scalar(
            select(func.count(DigitalItem.id)).where(DigitalItem.status == DigitalItemStatus.SOLD.value)
        )
        or 0
    )
    return DashboardStats(
        total_revenue=total_revenue,
        today_revenue=await revenue_since(today),
        week_revenue=await revenue_since(week),
        month_revenue=await revenue_since(month),
        orders_total=orders_total,
        orders_success=orders_success,
        orders_cancelled=orders_cancelled,
        orders_error=orders_error,
        average_check=average_check,
        top_products=[(r[0], int(r[1]), Decimal(r[2])) for r in top_products_rows],
        top_categories=[(r[0], int(r[1]), Decimal(r[2])) for r in top_categories_rows],
        top_buyers=[(int(r[0]), r[1], Decimal(r[2])) for r in top_buyers_rows],
        available_items=available_items,
        sold_items=sold_items,
    )


async def list_recent_orders(session: AsyncSession, *, limit: int = 10) -> list[Order]:
    rows = await session.scalars(
        select(Order)
        .options(
            selectinload(Order.user),
            selectinload(Order.product),
            selectinload(Order.issued_item),
            selectinload(Order.payments),
        )
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    return list(rows)


async def get_order_detail(session: AsyncSession, order_id: int) -> Order:
    order = await session.scalar(
        select(Order)
        .where(Order.id == order_id)
        .options(
            selectinload(Order.user),
            selectinload(Order.product),
            selectinload(Order.issued_item),
            selectinload(Order.payments),
        )
    )
    if order is None:
        raise NotFoundError("order not found")
    return order


def _normalize_currency(currency: str) -> str:
    normalized = currency.strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise ValidationError("currency must be an ISO-4217 code")
    return normalized


async def _ensure_product_tree(
    session: AsyncSession,
    *,
    category_id: int,
    subcategory_id: int,
) -> None:
    category = await session.get(Category, category_id)
    if category is None:
        raise NotFoundError("category not found")
    subcategory = await session.get(Subcategory, subcategory_id)
    if subcategory is None:
        raise NotFoundError("subcategory not found")
    if subcategory.category_id != category_id:
        raise ValidationError("subcategory does not belong to category")


async def create_category(
    session: AsyncSession,
    *,
    title: str,
    actor_telegram_id: int,
    admin_id: int | None = None,
    sort_order: int = 100,
) -> Category:
    category = Category(
        title=validate_text(title, field="title", max_length=MAX_TITLE_LENGTH),
        sort_order=sort_order,
    )
    session.add(category)
    await session.flush()
    await write_audit_log(
        session,
        action="category.create",
        entity_type="category",
        entity_id=category.id,
        admin_id=admin_id,
        actor_telegram_id=actor_telegram_id,
        new_values={"title": category.title, "sort_order": sort_order},
    )
    await session.commit()
    return category


async def create_subcategory(
    session: AsyncSession,
    *,
    category_id: int,
    title: str,
    actor_telegram_id: int,
    admin_id: int | None = None,
    sort_order: int = 100,
) -> Subcategory:
    subcategory = Subcategory(
        category_id=category_id,
        title=validate_text(title, field="title", max_length=MAX_TITLE_LENGTH),
        sort_order=sort_order,
    )
    session.add(subcategory)
    await session.flush()
    await write_audit_log(
        session,
        action="subcategory.create",
        entity_type="subcategory",
        entity_id=subcategory.id,
        admin_id=admin_id,
        actor_telegram_id=actor_telegram_id,
        new_values={"category_id": category_id, "title": subcategory.title, "sort_order": sort_order},
    )
    await session.commit()
    return subcategory


async def create_product(
    session: AsyncSession,
    *,
    category_id: int,
    subcategory_id: int,
    title: str,
    description: str,
    price: Decimal,
    currency: str,
    actor_telegram_id: int,
    admin_id: int | None = None,
    sort_order: int = 100,
) -> Product:
    if not price.is_finite() or price < 0:
        raise ValidationError("price must be non-negative")
    await _ensure_product_tree(session, category_id=category_id, subcategory_id=subcategory_id)
    normalized_currency = _normalize_currency(currency)
    product = Product(
        category_id=category_id,
        subcategory_id=subcategory_id,
        title=validate_text(title, field="title", max_length=MAX_TITLE_LENGTH),
        description=validate_text(
            description, field="description", max_length=MAX_DESCRIPTION_LENGTH, required=False
        ),
        price=price,
        currency=normalized_currency,
        sort_order=sort_order,
    )
    session.add(product)
    await session.flush()
    await write_audit_log(
        session,
        action="product.create",
        entity_type="product",
        entity_id=product.id,
        admin_id=admin_id,
        actor_telegram_id=actor_telegram_id,
        new_values={
            "category_id": category_id,
            "subcategory_id": subcategory_id,
            "title": product.title,
            "price": str(price),
            "currency": normalized_currency,
        },
    )
    await session.commit()
    return product


async def update_product_description(
    session: AsyncSession,
    *,
    product_id: int,
    description: str,
    actor_telegram_id: int,
    admin_id: int | None = None,
) -> Product:
    product = await session.get(Product, product_id, with_for_update=True)
    if product is None:
        raise NotFoundError("product not found")
    new_description = validate_text(
        description,
        field="description",
        max_length=MAX_DESCRIPTION_LENGTH,
        required=False,
    )
    old = {"description": product.description}
    product.description = new_description
    await write_audit_log(
        session,
        action="product.description_update",
        entity_type="product",
        entity_id=product.id,
        admin_id=admin_id,
        actor_telegram_id=actor_telegram_id,
        old_values=old,
        new_values={"description": new_description},
    )
    await session.commit()
    return product


async def update_product_currency(
    session: AsyncSession,
    *,
    product_id: int,
    currency: str,
    actor_telegram_id: int,
    admin_id: int | None = None,
) -> Product:
    normalized_currency = _normalize_currency(currency)
    product = await session.get(Product, product_id, with_for_update=True)
    if product is None:
        raise NotFoundError("product not found")
    old = {"currency": product.currency}
    product.currency = normalized_currency
    await write_audit_log(
        session,
        action="product.currency_update",
        entity_type="product",
        entity_id=product.id,
        admin_id=admin_id,
        actor_telegram_id=actor_telegram_id,
        old_values=old,
        new_values={"currency": normalized_currency},
    )
    await session.commit()
    return product


async def set_entity_active(
    session: AsyncSession,
    *,
    entity: str,
    entity_id: int,
    is_active: bool,
    actor_telegram_id: int,
    admin_id: int | None = None,
) -> None:
    model_map: dict[str, Any] = {
        "category": Category,
        "subcategory": Subcategory,
        "product": Product,
    }
    model = model_map.get(entity)
    if model is None:
        raise ValidationError("unsupported entity")
    obj = await session.get(model, entity_id, with_for_update=True)
    if obj is None:
        raise NotFoundError("entity not found")
    old = {"is_active": obj.is_active}
    obj.is_active = is_active
    await write_audit_log(
        session,
        action=f"{entity}.{'enable' if is_active else 'disable'}",
        entity_type=entity,
        entity_id=entity_id,
        admin_id=admin_id,
        actor_telegram_id=actor_telegram_id,
        old_values=old,
        new_values={"is_active": is_active},
    )
    await session.commit()


async def update_product_price(
    session: AsyncSession,
    *,
    product_id: int,
    price: Decimal,
    actor_telegram_id: int,
    admin_id: int | None = None,
) -> Product:
    if not price.is_finite() or price < 0:
        raise ValidationError("price must be non-negative")
    product = await session.get(Product, product_id, with_for_update=True)
    if product is None:
        raise NotFoundError("product not found")
    old = {"price": str(product.price)}
    product.price = price
    await write_audit_log(
        session,
        action="product.price_update",
        entity_type="product",
        entity_id=product.id,
        admin_id=admin_id,
        actor_telegram_id=actor_telegram_id,
        old_values=old,
        new_values={"price": str(price)},
    )
    await session.commit()
    return product


async def update_entity_title(
    session: AsyncSession,
    *,
    entity: str,
    entity_id: int,
    title: str,
    actor_telegram_id: int,
    admin_id: int | None = None,
) -> None:
    model_map: dict[str, Any] = {
        "category": Category,
        "subcategory": Subcategory,
        "product": Product,
    }
    model = model_map.get(entity)
    if model is None:
        raise ValidationError("unsupported entity")
    obj = await session.get(model, entity_id, with_for_update=True)
    if obj is None:
        raise NotFoundError("entity not found")
    new_title = validate_text(title, field="title", max_length=MAX_TITLE_LENGTH)
    old = {"title": obj.title}
    obj.title = new_title
    await write_audit_log(
        session,
        action=f"{entity}.update_title",
        entity_type=entity,
        entity_id=entity_id,
        admin_id=admin_id,
        actor_telegram_id=actor_telegram_id,
        old_values=old,
        new_values={"title": new_title},
    )
    await session.commit()


async def update_entity_sort_order(
    session: AsyncSession,
    *,
    entity: str,
    entity_id: int,
    sort_order: int,
    actor_telegram_id: int,
    admin_id: int | None = None,
) -> None:
    model_map: dict[str, Any] = {
        "category": Category,
        "subcategory": Subcategory,
        "product": Product,
    }
    model = model_map.get(entity)
    if model is None:
        raise ValidationError("unsupported entity")
    obj = await session.get(model, entity_id, with_for_update=True)
    if obj is None:
        raise NotFoundError("entity not found")
    old = {"sort_order": obj.sort_order}
    obj.sort_order = sort_order
    await write_audit_log(
        session,
        action=f"{entity}.sort_update",
        entity_type=entity,
        entity_id=entity_id,
        admin_id=admin_id,
        actor_telegram_id=actor_telegram_id,
        old_values=old,
        new_values={"sort_order": sort_order},
    )
    await session.commit()


async def soft_delete_entity(
    session: AsyncSession,
    *,
    entity: str,
    entity_id: int,
    actor_telegram_id: int,
    admin_id: int | None = None,
) -> None:
    await set_entity_active(
        session,
        entity=entity,
        entity_id=entity_id,
        is_active=False,
        actor_telegram_id=actor_telegram_id,
        admin_id=admin_id,
    )
    await write_audit_log(
        session,
        action=f"{entity}.delete",
        entity_type=entity,
        entity_id=entity_id,
        admin_id=admin_id,
        actor_telegram_id=actor_telegram_id,
        new_values={"soft_delete": True},
    )
    await session.commit()


async def update_order_status(
    session: AsyncSession,
    *,
    order_id: int,
    status: str,
    actor_telegram_id: int,
    admin_id: int | None = None,
) -> Order:
    allowed = {OrderStatus.PENDING.value, OrderStatus.PAID.value, OrderStatus.CANCELLED.value, OrderStatus.ERROR.value, OrderStatus.REFUNDED.value}
    if status not in allowed:
        raise ValidationError("unsupported order status")
    order = await session.get(Order, order_id, with_for_update=True)
    if order is None:
        raise NotFoundError("order not found")
    old = {"status": order.status}
    order.status = status
    await write_audit_log(
        session,
        action="order.status_update",
        entity_type="order",
        entity_id=order.id,
        admin_id=admin_id,
        actor_telegram_id=actor_telegram_id,
        old_values=old,
        new_values={"status": status},
    )
    await session.commit()
    return order


async def update_order_comment(
    session: AsyncSession,
    *,
    order_id: int,
    comment: str,
    actor_telegram_id: int,
    admin_id: int | None = None,
) -> Order:
    order = await session.get(Order, order_id, with_for_update=True)
    if order is None:
        raise NotFoundError("order not found")
    old = {"comment": order.comment}
    order.comment = validate_text(comment, field="comment", max_length=4096, required=False)
    await write_audit_log(
        session,
        action="order.comment_update",
        entity_type="order",
        entity_id=order.id,
        admin_id=admin_id,
        actor_telegram_id=actor_telegram_id,
        old_values=old,
        new_values={"comment": order.comment},
    )
    await session.commit()
    return order
