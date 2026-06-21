from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import re

from sqlalchemy import Select, and_, func, select
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


@dataclass(frozen=True)
class PublicProduct:
    product: Product
    available: int


NOMINAL_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(KZT|RUB|USD|EUR|INR|TRY|USDT)\b", re.IGNORECASE)


def _product_nominal(product: Product) -> Decimal:
    match = NOMINAL_RE.search(product.title)
    if not match:
        return Decimal("Infinity")
    try:
        return Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:
        return Decimal("Infinity")


def product_nominal_sort_key(product: Product) -> tuple[object, ...]:
    category = product.category
    subcategory = product.subcategory
    return (
        category.sort_order if category else 0,
        category.title.lower() if category else "",
        subcategory.sort_order if subcategory else 0,
        subcategory.title.lower() if subcategory else "",
        _product_nominal(product),
        product.currency,
        product.sort_order,
        product.title.lower(),
        product.id,
    )


def paginate_items(items: Sequence[object], *, page: int, page_size: int = PAGE_SIZE) -> Page:
    page = max(page, 0)
    total = len(items)
    pages = max((total + page_size - 1) // page_size, 1)
    start = page * page_size
    return Page(items=list(items[start:start + page_size]), page=page, total=total, pages=pages)


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
        .options(selectinload(Product.category), selectinload(Product.subcategory))
    )
    if active_only:
        stmt = stmt.where(Product.is_active.is_(True))
    products = list(await session.scalars(stmt))
    products.sort(key=product_nominal_sort_key)
    return paginate_items(products, page=page)


def _public_products_stmt() -> Select:
    stock = (
        select(DigitalItem.product_id, func.count(DigitalItem.id).label("available"))
        .where(DigitalItem.status == DigitalItemStatus.AVAILABLE.value)
        .group_by(DigitalItem.product_id)
        .subquery()
    )
    return (
        select(Product, func.coalesce(stock.c.available, 0).label("available"))
        .join(Product.category)
        .join(Product.subcategory)
        .outerjoin(stock, stock.c.product_id == Product.id)
        .where(
            and_(
                Product.is_active.is_(True),
                Category.is_active.is_(True),
                Subcategory.is_active.is_(True),
            )
        )
        .options(selectinload(Product.category), selectinload(Product.subcategory))
    )


async def list_public_products(session: AsyncSession) -> list[PublicProduct]:
    rows = await session.execute(_public_products_stmt())
    items = [PublicProduct(product=product, available=int(available or 0)) for product, available in rows.all()]
    items.sort(key=lambda item: product_nominal_sort_key(item.product))
    return items


async def list_public_products_page(session: AsyncSession, *, page: int = 0, page_size: int = PAGE_SIZE) -> Page:
    items = await list_public_products(session)
    return paginate_items(items, page=page, page_size=page_size)


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


async def ensure_product_can_be_bought(session: AsyncSession, product_id: int, *, quantity: int = 1) -> Product:
    if quantity < 1:
        raise ValidationError("quantity must be positive")
    product = await get_product_with_tree(session, product_id)
    if not product.is_active:
        raise ValidationError("product is disabled")
    if not product.category.is_active:
        raise ValidationError("category is disabled")
    if not product.subcategory.is_active:
        raise ValidationError("subcategory is disabled")
    if await available_items_count(session, product_id) < quantity:
        raise ValidationError("no available digital items")
    return product
