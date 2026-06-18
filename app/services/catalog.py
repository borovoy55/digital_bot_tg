from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.exceptions import NotFoundError, ValidationError
from app.db.models import Category, DigitalItem, DigitalItemStatus, Product, Subcategory

PAGE_SIZE = 8


@dataclass(frozen=True)
class Page:
    items: Sequence[object]
    page: int
    total: int
    pages: int


async def paginate(session: AsyncSession, stmt: Select, *, page: int, page_size: int = PAGE_SIZE) -> Page:
    page = max(page, 0)
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = int(await session.scalar(count_stmt) or 0)
    pages = max((total + page_size - 1) // page_size, 1)
    rows = await session.scalars(stmt.limit(page_size).offset(page * page_size))
    return Page(items=list(rows), page=page, total=total, pages=pages)


async def list_categories(session: AsyncSession, *, page: int = 0, active_only: bool = True) -> Page:
    stmt = select(Category).order_by(Category.sort_order.asc(), Category.title.asc())
    if active_only:
        stmt = stmt.where(Category.is_active.is_(True))
    return await paginate(session, stmt, page=page)


async def list_subcategories(
    session: AsyncSession,
    *,
    category_id: int,
    page: int = 0,
    active_only: bool = True,
) -> Page:
    stmt = (
        select(Subcategory)
        .where(Subcategory.category_id == category_id)
        .order_by(Subcategory.sort_order.asc(), Subcategory.title.asc())
    )
    if active_only:
        stmt = stmt.where(Subcategory.is_active.is_(True))
    return await paginate(session, stmt, page=page)


async def list_products(
    session: AsyncSession,
    *,
    subcategory_id: int,
    page: int = 0,
    active_only: bool = True,
) -> Page:
    stmt = (
        select(Product)
        .where(Product.subcategory_id == subcategory_id)
        .order_by(Product.sort_order.asc(), Product.title.asc())
    )
    if active_only:
        stmt = stmt.where(Product.is_active.is_(True))
    return await paginate(session, stmt, page=page)


async def get_product_with_tree(session: AsyncSession, product_id: int) -> Product:
    product = await session.scalar(
        select(Product)
        .where(Product.id == product_id)
        .options(selectinload(Product.category), selectinload(Product.subcategory))
    )
    if product is None:
        raise NotFoundError("product not found")
    return product


async def available_items_count(session: AsyncSession, product_id: int) -> int:
    return int(
        await session.scalar(
            select(func.count(DigitalItem.id)).where(
                DigitalItem.product_id == product_id,
                DigitalItem.status == DigitalItemStatus.AVAILABLE.value,
            )
        )
        or 0
    )


async def ensure_product_can_be_bought(session: AsyncSession, product_id: int) -> Product:
    product = await get_product_with_tree(session, product_id)
    if not product.is_active:
        raise ValidationError("product is disabled")
    if not product.category.is_active:
        raise ValidationError("category is disabled")
    if not product.subcategory.is_active:
        raise ValidationError("subcategory is disabled")
    if await available_items_count(session, product_id) <= 0:
        raise ValidationError("no available digital items")
    return product
