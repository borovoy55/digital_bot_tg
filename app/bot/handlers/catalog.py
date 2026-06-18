from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import CatalogCb, MenuCb, ProductCb
from app.bot.keyboards import (
    categories_keyboard,
    product_keyboard,
    products_keyboard,
    subcategories_keyboard,
)
from app.bot.utils import answer_or_edit
from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.rate_limit import check_order_rate_limit
from app.payment_providers.base import InvoiceRequest
from app.payment_providers.telegram import TelegramPaymentsProvider
from app.services.catalog import (
    available_items_count,
    get_product_with_tree,
    list_categories,
    list_products,
    list_subcategories,
)
from app.services.orders import create_pending_order

router = Router()


@router.callback_query(MenuCb.filter(F.action == "cat"))
@router.callback_query(CatalogCb.filter(F.level == "cat"))
async def show_categories(callback: CallbackQuery, session: AsyncSession) -> None:
    page_number = 0
    if isinstance(callback.data, str) and callback.data.startswith("c:"):
        unpacked = CatalogCb.unpack(callback.data)
        page_number = unpacked.page
    page = await list_categories(session, page=page_number)
    await answer_or_edit(
        callback,
        f"Каталог · категории\nСтраница {page.page + 1}/{page.pages}",
        reply_markup=categories_keyboard(page),
    )
    await callback.answer()


@router.callback_query(CatalogCb.filter(F.level == "sub"))
async def show_subcategories(
    callback: CallbackQuery,
    callback_data: CatalogCb,
    session: AsyncSession,
) -> None:
    if callback_data.parent_id <= 0:
        await show_categories(callback, session)
        return
    page = await list_subcategories(
        session, category_id=callback_data.parent_id, page=callback_data.page
    )
    await answer_or_edit(
        callback,
        f"Подкатегории\nСтраница {page.page + 1}/{page.pages}",
        reply_markup=subcategories_keyboard(callback_data.parent_id, page),
    )
    await callback.answer()


@router.callback_query(CatalogCb.filter(F.level == "prod"))
async def show_products(
    callback: CallbackQuery,
    callback_data: CatalogCb,
    session: AsyncSession,
) -> None:
    page = await list_products(
        session, subcategory_id=callback_data.parent_id, page=callback_data.page
    )
    await answer_or_edit(
        callback,
        f"Товары\nСтраница {page.page + 1}/{page.pages}",
        reply_markup=products_keyboard(callback_data.parent_id, page),
    )
    await callback.answer()


@router.callback_query(ProductCb.filter(F.action == "view"))
async def show_product(
    callback: CallbackQuery,
    callback_data: ProductCb,
    session: AsyncSession,
) -> None:
    product = await get_product_with_tree(session, callback_data.product_id)
    available = await available_items_count(session, product.id)
    text = (
        f"{product.title}\n\n"
        f"{product.description or 'Описание не заполнено.'}\n\n"
        f"Цена: {product.price} {product.currency}\n"
        f"Доступно кодов: {available}"
    )
    await answer_or_edit(
        callback, text, reply_markup=product_keyboard(product.id, page=callback_data.page)
    )
    await callback.answer()


@router.callback_query(ProductCb.filter(F.action == "buy"))
async def buy_product(
    callback: CallbackQuery,
    callback_data: ProductCb,
    session: AsyncSession,
    redis: Redis,
    settings: Settings,
) -> None:
    if callback.from_user is None:
        return
    allowed = await check_order_rate_limit(
        redis,
        telegram_id=callback.from_user.id,
        limit=settings.order_rate_limit_per_hour,
    )
    if not allowed:
        await callback.answer("Слишком много заказов. Попробуйте позже.", show_alert=True)
        return
    try:
        order = await create_pending_order(
            session,
            settings=settings,
            telegram_id=callback.from_user.id,
            product_id=callback_data.product_id,
        )
        product = await get_product_with_tree(session, order.product_id)
        provider = TelegramPaymentsProvider(callback.bot, settings)
        await provider.create_invoice(
            InvoiceRequest(
                chat_id=callback.from_user.id,
                title=product.title,
                description=product.description or product.title,
                payload=order.payment_payload or "",
                currency=order.currency,
                amount=order.amount,
                order_id=order.id,
            )
        )
        await callback.answer("Счет сформирован.")
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
