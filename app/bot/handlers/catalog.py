from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter
from aiogram.types import CallbackQuery, Message
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import CatalogCb, MenuCb, ProductCb
from app.bot.keyboards import (
    buy_products_keyboard,
    main_menu,
    product_keyboard,
    quantity_input_keyboard,
    quantity_keyboard,
)
from app.bot.utils import answer_or_edit
from app.core.config import Settings
from app.core.exceptions import AppError
from app.core.rate_limit import check_order_rate_limit
from app.payment_providers.base import InvoiceRequest
from app.payment_providers.telegram import TelegramPaymentsProvider
from app.services.catalog import (
    PublicProduct,
    available_items_count,
    get_product_with_tree,
    list_public_products,
    list_public_products_page,
)
from app.services.menu import get_menu_buttons
from app.services.orders import create_pending_order

router = Router()
PRODUCTS_TEXT_LIMIT = 3900


def _format_price(value: object, currency: str) -> str:
    return f"{escape(str(value))} {escape(currency)}/шт"


def _append_limited(lines: list[str], additions: list[str], *, overflow_text: str) -> bool:
    next_text = "\n".join([*lines, *additions])
    if len(next_text) > PRODUCTS_TEXT_LIMIT:
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(overflow_text)
        return False
    lines.extend(additions)
    return True


def _format_products_text(items: list[PublicProduct]) -> str:
    if not items:
        return "🛒 Товары\n\nСейчас товары временно отсутствуют."
    lines = ["<b>🛒 Товары</b>", ""]
    current_subcategory_id: int | None = None
    for item in items:
        product = item.product
        if product.subcategory_id != current_subcategory_id:
            if current_subcategory_id is not None:
                lines.append("")
            current_subcategory_id = product.subcategory_id
            subcategory_title = product.subcategory.title if product.subcategory else "Другое"
            header = f"<b>— {escape(subcategory_title)} —</b>"
            if not _append_limited(
                lines,
                [header],
                overflow_text="Список большой. Для выбора товара нажмите «Купить».",
            ):
                break
        line = (
            f"<b>{escape(product.title)} | {_format_price(product.price, product.currency)} |</b> "
            f"Остаток: {item.available} шт."
        )
        if not _append_limited(
            lines,
            [line],
            overflow_text="Список большой. Для выбора товара нажмите «Купить».",
        ):
            break
    text = "\n".join(lines)
    return text


def _format_buy_products_text(page: object) -> str:
    items = list(page.items)
    if not items:
        return "💲 Выберите товар для покупки\n\nСейчас товары временно отсутствуют."

    lines = [
        "<b>💲 Выберите товар для покупки</b>",
        "Нажмите кнопку с нужной страной и номиналом ниже.",
        "",
    ]
    current_subcategory_id: int | None = None
    for item in items:
        product = item.product
        if product.subcategory_id != current_subcategory_id:
            if current_subcategory_id is not None:
                lines.append("")
            current_subcategory_id = product.subcategory_id
            subcategory_title = product.subcategory.title if product.subcategory else "Другое"
            header = f"<b>— {escape(subcategory_title)} —</b>"
            if not _append_limited(
                lines,
                [header],
                overflow_text="Список большой. Используйте кнопки ниже для выбора товара.",
            ):
                break

        item_lines = [
            f"<b>{escape(product.title)}</b>",
            f"💰 {_format_price(product.price, product.currency)}",
            f"📦 Остаток: {item.available} шт.",
        ]
        if not _append_limited(
            lines,
            item_lines,
            overflow_text="Список большой. Используйте кнопки ниже для выбора товара.",
        ):
            break

    if page.pages > 1:
        lines.extend(["", f"Страница {page.page + 1}/{page.pages}"])
    return "\n".join(lines)


class QuantityState(StatesGroup):
    value = State()


@router.callback_query(MenuCb.filter(F.action == "cat"))
@router.callback_query(CatalogCb.filter(F.level == "cat"))
async def show_catalog(callback: CallbackQuery, session: AsyncSession) -> None:
    items = await list_public_products(session)
    await answer_or_edit(
        callback,
        _format_products_text(items),
        reply_markup=main_menu(await get_menu_buttons(session, visible_only=True)),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(MenuCb.filter(F.action == "buy"))
@router.callback_query(CatalogCb.filter(F.level == "all"))
async def show_buy_products(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    page_number = 0
    if isinstance(callback.data, str) and callback.data.startswith("c:"):
        unpacked = CatalogCb.unpack(callback.data)
        page_number = unpacked.page
    page = await list_public_products_page(session, page=page_number)
    await answer_or_edit(
        callback,
        _format_buy_products_text(page),
        reply_markup=buy_products_keyboard(page),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(CatalogCb.filter(F.level == "sub"))
async def show_subcategories(
    callback: CallbackQuery,
    callback_data: CatalogCb,
    session: AsyncSession,
) -> None:
    await show_buy_products(callback, session)


@router.callback_query(CatalogCb.filter(F.level == "prod"))
async def show_products(
    callback: CallbackQuery,
    callback_data: CatalogCb,
    session: AsyncSession,
) -> None:
    await show_buy_products(callback, session)


@router.callback_query(ProductCb.filter(F.action == "view"))
async def show_product(
    callback: CallbackQuery,
    callback_data: ProductCb,
    session: AsyncSession,
) -> None:
    product = await get_product_with_tree(session, callback_data.product_id)
    available = await available_items_count(session, product.id)
    text = (
        f"📦 {product.title}\n\n"
        f"📝 {product.description or 'Описание не заполнено.'}\n\n"
        f"💰 Цена: {product.price} {product.currency}\n"
        f"🔑 Доступно кодов: {available}"
    )
    await answer_or_edit(
        callback,
        text,
        reply_markup=product_keyboard(
            product.id,
            page=callback_data.page,
        ),
    )
    await callback.answer()


@router.callback_query(ProductCb.filter(F.action == "buy"))
async def choose_quantity(
    callback: CallbackQuery,
    callback_data: ProductCb,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    await state.clear()
    product = await get_product_with_tree(session, callback_data.product_id)
    available = await available_items_count(session, product.id)
    if available <= 0:
        await callback.answer("Товар временно закончился.", show_alert=True)
        return
    text = (
        f"🛒 {product.title}\n\n"
        f"💰 Цена за 1 шт.: {product.price} {product.currency}\n"
        f"🔑 Доступно: {available}\n\n"
        "Выберите количество."
    )
    await answer_or_edit(
        callback,
        text,
        reply_markup=quantity_keyboard(product.id, quantity=1, available=available, page=callback_data.page),
    )
    await callback.answer()


@router.callback_query(ProductCb.filter(F.action.startswith("q")))
async def change_quantity(
    callback: CallbackQuery,
    callback_data: ProductCb,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if callback_data.action == "qinput":
        available = await available_items_count(session, callback_data.product_id)
        await state.set_state(QuantityState.value)
        await state.update_data(product_id=callback_data.product_id, page=callback_data.page, available=available)
        await answer_or_edit(
            callback,
            f"🔢 Введите количество от 1 до {available}.",
            reply_markup=quantity_input_keyboard(callback_data.product_id, page=callback_data.page),
        )
        await callback.answer()
        return
    try:
        quantity = int(callback_data.action.removeprefix("q"))
    except ValueError:
        await callback.answer()
        return
    product = await get_product_with_tree(session, callback_data.product_id)
    available = await available_items_count(session, product.id)
    quantity = min(max(quantity, 1), available)
    await answer_or_edit(
        callback,
        (
            f"🛒 {product.title}\n\n"
            f"💰 Цена за 1 шт.: {product.price} {product.currency}\n"
            f"🔑 Доступно: {available}\n"
            f"🧾 Итого: {product.price * quantity} {product.currency}"
        ),
        reply_markup=quantity_keyboard(product.id, quantity=quantity, available=available, page=callback_data.page),
    )
    await callback.answer()


@router.message(StateFilter(QuantityState.value))
async def quantity_input(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    try:
        quantity = int((message.text or "").strip())
    except ValueError:
        product_id = int(data["product_id"])
        page = int(data.get("page") or 0)
        await message.answer(
            "Введите целое число.",
            reply_markup=quantity_input_keyboard(product_id, page=page),
        )
        return
    product_id = int(data["product_id"])
    page = int(data.get("page") or 0)
    product = await get_product_with_tree(session, product_id)
    available = await available_items_count(session, product_id)
    if quantity < 1 or quantity > available:
        await message.answer(
            f"Можно выбрать от 1 до {available}.",
            reply_markup=quantity_input_keyboard(product_id, page=page),
        )
        return
    await state.clear()
    await message.answer(
        (
            f"🛒 {product.title}\n\n"
            f"💰 Цена за 1 шт.: {product.price} {product.currency}\n"
            f"🔑 Доступно: {available}\n"
            f"🧾 Итого: {product.price * quantity} {product.currency}"
        ),
        reply_markup=quantity_keyboard(product.id, quantity=quantity, available=available, page=page),
    )


@router.callback_query(ProductCb.filter(F.action.startswith("pay")))
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
        await callback.answer("⏳ Слишком много заказов. Попробуйте позже.", show_alert=True)
        return
    try:
        quantity = int(callback_data.action.removeprefix("pay"))
    except ValueError:
        await callback.answer("Некорректное количество.", show_alert=True)
        return
    try:
        order = await create_pending_order(
            session,
            settings=settings,
            telegram_id=callback.from_user.id,
            product_id=callback_data.product_id,
            quantity=quantity,
        )
        product = await get_product_with_tree(session, order.product_id)
        provider = TelegramPaymentsProvider(callback.bot, settings)
        await provider.create_invoice(
            InvoiceRequest(
                chat_id=callback.from_user.id,
                title=product.title,
                description=f"{product.description or product.title}\nКоличество: {order.quantity}",
                payload=order.payment_payload or "",
                currency=order.currency,
                amount=order.amount,
                order_id=order.id,
            )
        )
        await callback.answer("Счет сформирован.")
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)


@router.callback_query(ProductCb.filter(F.action == "noop"))
async def product_noop(callback: CallbackQuery) -> None:
    await callback.answer()
