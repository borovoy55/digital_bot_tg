from __future__ import annotations

from decimal import Decimal, InvalidOperation

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.bot.callbacks import AdminCb
from app.bot.keyboards import (
    admin_back,
    admin_categories_keyboard,
    admin_category_keyboard,
    admin_category_select_keyboard,
    admin_digital_item_keyboard,
    admin_digital_items_keyboard,
    admin_digital_product_keyboard,
    admin_digital_search_keyboard,
    admin_empty_product_tree_keyboard,
    admin_menu,
    admin_menu_button_keyboard,
    admin_menu_buttons_keyboard,
    admin_order_keyboard,
    admin_orders_keyboard,
    admin_product_cancel_keyboard,
    admin_product_confirm_keyboard,
    admin_product_keyboard,
    admin_product_skip_keyboard,
    admin_products_keyboard,
    admin_settings_keyboard,
    admin_subcategories_keyboard,
    admin_subcategory_keyboard,
    admin_subcategory_select_keyboard,
    admin_user_keyboard,
    admin_users_keyboard,
)
from app.bot.utils import answer_or_edit
from app.core.config import Settings
from app.core.exceptions import AccessDenied, AppError, ValidationError
from app.core.security import parse_items_csv, parse_items_text
from app.db.models import Category, DigitalItem, Order, Product, Subcategory, User
from app.services.admin import (
    create_category,
    create_product,
    create_subcategory,
    dashboard_stats,
    get_order_detail,
    get_user_purchase_stats,
    list_recent_orders,
    list_users_page,
    set_entity_active,
    soft_delete_entity,
    update_entity_sort_order,
    update_entity_title,
    update_order_comment,
    update_order_status,
    update_product_currency,
    update_product_description,
    update_product_price,
)
from app.services.broadcasts import create_broadcast, run_broadcast
from app.services.catalog import (
    available_items_count,
    get_product_with_tree,
    list_categories,
    list_subcategories,
    paginate,
    paginate_items,
    product_nominal_sort_key,
)
from app.services.digital_items import (
    delete_digital_item,
    export_digital_items_csv,
    import_digital_items,
    list_digital_items_page,
    search_digital_items,
    update_digital_item_value,
)
from app.services.menu import (
    DEFAULT_TEXTS,
    create_text_menu_button,
    delete_menu_button,
    get_button_text,
    get_menu_button,
    get_menu_buttons,
    update_menu_button,
)
from app.services.settings import get_setting_text, set_setting_text
from app.services.users import require_admin, set_user_block

router = Router()


class ProductCreateState(StatesGroup):
    title = State()
    description = State()
    price = State()
    currency = State()
    sort_order = State()
    confirm = State()


class ProductEditState(StatesGroup):
    value = State()


class CategoryCreateState(StatesGroup):
    title = State()


class CategoryEditState(StatesGroup):
    value = State()


class SubcategoryCreateState(StatesGroup):
    title = State()


class SubcategoryEditState(StatesGroup):
    value = State()


class DigitalItemUploadState(StatesGroup):
    values = State()


class DigitalItemSearchState(StatesGroup):
    query = State()


class DigitalItemEditState(StatesGroup):
    value = State()


class MenuButtonCreateState(StatesGroup):
    label = State()
    content = State()


class MenuButtonEditState(StatesGroup):
    value = State()


class SettingTextEditState(StatesGroup):
    value = State()


class BroadcastState(StatesGroup):
    target = State()
    text = State()


async def _admin(session: AsyncSession, settings: Settings, message_or_callback: Message | CallbackQuery):
    user = message_or_callback.from_user
    if user is None:
        raise AccessDenied("admin access required")
    return await require_admin(session, settings, user.id)


def _parse_price(raw: str) -> Decimal:
    try:
        price = Decimal(raw.replace(",", ".").strip())
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError("Цена должна быть числом, например 199.00") from exc
    if price < 0:
        raise ValidationError("Цена не может быть отрицательной.")
    return price


def _parse_sort_order(raw: str) -> int:
    try:
        return int(raw.strip())
    except ValueError as exc:
        raise ValidationError("Сортировка должна быть целым числом.") from exc


async def _products_page(session: AsyncSession, *, page: int):
    stmt = select(Product).options(selectinload(Product.category), selectinload(Product.subcategory))
    products = list(await session.scalars(stmt))
    products.sort(key=product_nominal_sort_key)
    return paginate_items(products, page=page)


async def _categories_page(session: AsyncSession, *, page: int):
    stmt = select(Category).order_by(Category.sort_order.asc(), Category.id.asc())
    return await paginate(session, stmt, page=page)


async def _subcategories_page(session: AsyncSession, *, page: int, category_id: int = 0):
    stmt = select(Subcategory).order_by(Subcategory.sort_order.asc(), Subcategory.id.asc())
    if category_id:
        stmt = stmt.where(Subcategory.category_id == category_id)
    return await paginate(session, stmt, page=page)


def _category_card_text(category: Category) -> str:
    return "\n".join(
        [
            f"📁 Категория #{category.id}",
            f"✏️ Название: {category.title}",
            f"📌 Статус: {'активна' if category.is_active else 'отключена'}",
            f"🔢 Сортировка: {category.sort_order}",
        ]
    )


def _subcategory_card_text(subcategory: Subcategory) -> str:
    return "\n".join(
        [
            f"🗂 Подкатегория #{subcategory.id}",
            f"📁 Категория ID: {subcategory.category_id}",
            f"✏️ Название: {subcategory.title}",
            f"📌 Статус: {'активна' if subcategory.is_active else 'отключена'}",
            f"🔢 Сортировка: {subcategory.sort_order}",
        ]
    )


async def _product_card_text(session: AsyncSession, product: Product) -> str:
    available = await available_items_count(session, product.id)
    category_title = product.category.title if product.category else f"#{product.category_id}"
    subcategory_title = (
        product.subcategory.title if product.subcategory else f"#{product.subcategory_id}"
    )
    description = product.description or "-"
    return "\n".join(
        [
            f"📦 Товар #{product.id}",
            f"✏️ Название: {product.title}",
            f"📁 Категория: {category_title}",
            f"🗂 Подкатегория: {subcategory_title}",
            f"💰 Цена: {product.price} {product.currency}",
            f"🔑 Доступных кодов: {available}",
            f"📌 Статус: {'активен' if product.is_active else 'отключен'}",
            f"🔢 Сортировка: {product.sort_order}",
            "",
            "📝 Описание:",
            description,
        ]
    )


async def _show_product_card(
    target: Message | CallbackQuery,
    session: AsyncSession,
    *,
    product_id: int,
    page: int = 0,
) -> None:
    product = await get_product_with_tree(session, product_id)
    await answer_or_edit(
        target,
        await _product_card_text(session, product),
        reply_markup=admin_product_keyboard(product, page=page),
    )


def _order_status_label(status: str) -> str:
    labels = {
        "pending": "⏳ ожидает",
        "paid": "✅ оплачен",
        "cancelled": "🚫 отменен",
        "error": "⚠️ ошибка",
        "refunded": "↩️ возврат",
    }
    return labels.get(status, status)


def _user_label(user: User) -> str:
    name = f"@{user.username}" if user.username else "без username"
    full_name = " ".join(part for part in [user.first_name, user.last_name] if part)
    if full_name:
        name += f" · {full_name}"
    return name


def _format_user_purchase_stats(stats: object) -> str:
    user = stats.user
    lines = [
        f"👤 Пользователь #{user.id}",
        f"telegram_id: {user.telegram_id}",
        f"Имя: {_user_label(user)}",
        f"Статус: {'🚫 заблокирован' if user.is_blocked else '✅ активен'}",
        f"Регистрация: {user.registered_at}",
        f"Последняя активность: {user.last_activity_at}",
        "",
        "📊 Покупки",
        f"🧾 Всего заказов: {stats.orders_total}",
        f"✅ Оплачено: {stats.orders_success}",
        f"⏳ Ожидает оплаты: {stats.orders_pending}",
        f"🚫 Отменено: {stats.orders_cancelled}",
        f"⚠️ Ошибок: {stats.orders_error}",
        f"↩️ Возвратов: {stats.orders_refunded}",
        f"🔑 Куплено кодов: {stats.purchased_items}",
        f"💰 Сумма покупок: {stats.total_spent}",
        f"📈 Средний чек: {stats.average_check:.2f}",
        "",
        "🧾 Последние заказы:",
    ]
    if not stats.last_orders:
        lines.append("Заказов пока нет.")
        return "\n".join(lines)
    for order in stats.last_orders:
        assert isinstance(order, Order)
        product_title = order.product.title if order.product else f"product_id={order.product_id}"
        lines.append(
            f"#{order.id} · {_order_status_label(order.status)} · {order.amount} {order.currency} · "
            f"{order.quantity} шт. · {product_title}"
        )
    return "\n".join(lines)


async def _digital_product_text(session: AsyncSession, product: Product) -> str:
    rows = await session.execute(
        select(DigitalItem.status, func.count(DigitalItem.id))
        .where(DigitalItem.product_id == product.id)
        .group_by(DigitalItem.status)
    )
    counts = {status: count for status, count in rows}
    return "\n".join(
        [
            f"🔑 Цифровые товары · {product.title}",
            f"📦 product_id: {product.id}",
            f"✅ Доступно: {counts.get('available', 0)}",
            f"⏳ Зарезервировано: {counts.get('reserved', 0)}",
            f"🏷 Продано: {counts.get('sold', 0)}",
            f"🗑 Удалено: {counts.get('deleted', 0)}",
            "",
            "Можно загрузить коды списком: один код на строку. После оплаты бот выдаст покупателю нужное количество кодов автоматически.",
        ]
    )


def _digital_item_status_label(status: str) -> str:
    labels = {
        "available": "✅ доступен",
        "reserved": "⏳ зарезервирован",
        "sold": "🏷 продан",
        "deleted": "🗑 удален",
    }
    return labels.get(status, status)


def _short_code_value(value: str, *, limit: int = 52) -> str:
    compact = " ".join(value.split())
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit - 1]}…"


def _digital_items_page_text(product: Product, page: object) -> str:
    lines = [
        f"🔑 Коды · {product.title}",
        f"📦 product_id: {product.id}",
        f"Страница {page.page + 1}/{page.pages} · всего: {page.total}",
        "",
    ]
    if not page.items:
        lines.append("Коды пока не загружены.")
        return "\n".join(lines)
    for item in page.items:
        status = _digital_item_status_label(item.status)
        lines.append(f"#{item.id} · {status}")
        lines.append(_short_code_value(item.value))
        lines.append("")
    lines.append("Откройте код кнопкой ниже, чтобы посмотреть полностью, изменить или удалить.")
    return "\n".join(lines)


async def _show_digital_product(
    target: Message | CallbackQuery,
    session: AsyncSession,
    *,
    product_id: int,
    page: int = 0,
) -> None:
    product = await get_product_with_tree(session, product_id)
    await answer_or_edit(
        target,
        await _digital_product_text(session, product),
        reply_markup=admin_digital_product_keyboard(product.id, page=page),
    )


async def _show_digital_items_page(
    target: Message | CallbackQuery,
    session: AsyncSession,
    *,
    product_id: int,
    page: int = 0,
) -> None:
    product = await get_product_with_tree(session, product_id)
    items_page = await list_digital_items_page(session, product_id=product_id, page=page)
    await answer_or_edit(
        target,
        _digital_items_page_text(product, items_page),
        reply_markup=admin_digital_items_keyboard(items_page, product_id=product_id),
    )


async def _show_category_card(
    target: Message | CallbackQuery,
    session: AsyncSession,
    *,
    category_id: int,
    page: int = 0,
) -> None:
    category = await session.get(Category, category_id)
    if category is None:
        raise ValidationError("Категория не найдена.")
    await answer_or_edit(target, _category_card_text(category), reply_markup=admin_category_keyboard(category, page=page))


async def _show_subcategory_card(
    target: Message | CallbackQuery,
    session: AsyncSession,
    *,
    subcategory_id: int,
    page: int = 0,
) -> None:
    subcategory = await session.scalar(
        select(Subcategory).where(Subcategory.id == subcategory_id)
    )
    if subcategory is None:
        raise ValidationError("Подкатегория не найдена.")
    await answer_or_edit(
        target,
        _subcategory_card_text(subcategory),
        reply_markup=admin_subcategory_keyboard(subcategory, page=page),
    )


@router.message(Command("admin"))
async def admin_command(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        await _admin(session, settings, message)
    except AccessDenied:
        await message.answer("🚫 Нет доступа.")
        return
    await message.answer("🛠 Админ-панель", reply_markup=admin_menu())


@router.callback_query(AdminCb.filter(F.action == "home"))
async def admin_home(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    try:
        await _admin(session, settings, callback)
    except AccessDenied:
        await callback.answer("🚫 Нет доступа.", show_alert=True)
        return
    await answer_or_edit(callback, "🛠 Админ-панель", reply_markup=admin_menu())
    await callback.answer()


@router.callback_query(AdminCb.filter(F.action == "stats"))
async def admin_stats(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    try:
        await _admin(session, settings, callback)
        stats = await dashboard_stats(session)
    except AccessDenied:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    text = "\n".join(
        [
            "📊 Статистика",
            f"💰 Общая выручка: {stats.total_revenue}",
            f"📅 Сегодня: {stats.today_revenue}",
            f"🗓 7 дней: {stats.week_revenue}",
            f"📆 30 дней: {stats.month_revenue}",
            f"🧾 Заказов всего: {stats.orders_total}",
            f"✅ Успешных: {stats.orders_success}",
            f"🚫 Отмененных: {stats.orders_cancelled}",
            f"⚠️ Ошибочных: {stats.orders_error}",
            f"📈 Средний чек: {stats.average_check:.2f}",
            f"🔑 Кодов доступно: {stats.available_items}",
            f"🏷 Кодов продано: {stats.sold_items}",
            "",
            "🏆 Топ товаров:",
            *[f"{title}: {count} / {amount}" for title, count, amount in stats.top_products],
            "",
            "🏆 Топ категорий:",
            *[f"{title}: {count} / {amount}" for title, count, amount in stats.top_categories],
            "",
            "🏆 Топ покупателей:",
            *[f"{telegram_id} @{username or '-'}: {amount}" for telegram_id, username, amount in stats.top_buyers],
        ]
    )
    await answer_or_edit(callback, text, reply_markup=admin_back())
    await callback.answer()


@router.callback_query(AdminCb.filter(F.action == "list"))
async def admin_lists(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        await _admin(session, settings, callback)
    except AccessDenied:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    entity = callback_data.entity
    if entity == "orders":
        orders = await list_recent_orders(session, limit=10)
        text = "🧾 Последние заказы\n\n" + "\n".join(
            f"#{o.id} · {o.status} · {o.amount} {o.currency} · @{o.user.username or o.user.telegram_id}"
            for o in orders
        )
        await answer_or_edit(callback, text or "🧾 Заказов нет.", reply_markup=admin_orders_keyboard(o.id for o in orders))
    elif entity == "users":
        page = await list_users_page(session, page=callback_data.page)
        await answer_or_edit(
            callback,
            "👥 Пользователи\n\nВыберите пользователя, чтобы посмотреть статистику покупок.",
            reply_markup=admin_users_keyboard(page),
        )
    elif entity == "cats":
        page = await _categories_page(session, page=callback_data.page)
        await answer_or_edit(
            callback,
            "📁 Категории\n\nВыберите категорию для редактирования или создайте новую.",
            reply_markup=admin_categories_keyboard(page),
        )
    elif entity == "subs":
        category_id = callback_data.object_id
        page = await _subcategories_page(session, page=callback_data.page, category_id=category_id)
        title = "🗂 Подкатегории"
        if category_id:
            category = await session.get(Category, category_id)
            title = f"🗂 Подкатегории · {category.title if category else f'#{category_id}'}"
        await answer_or_edit(
            callback,
            f"{title}\n\nВыберите подкатегорию для редактирования или создайте новую.",
            reply_markup=admin_subcategories_keyboard(page, category_id=category_id),
        )
    elif entity == "products":
        page = await _products_page(session, page=callback_data.page)
        await answer_or_edit(
            callback,
            "📦 Товары\n\nВыберите товар для редактирования или создайте новый.",
            reply_markup=admin_products_keyboard(page),
        )
    elif entity == "items":
        rows = await session.execute(
            select(DigitalItem.product_id, DigitalItem.status, func.count(DigitalItem.id))
            .group_by(DigitalItem.product_id, DigitalItem.status)
            .order_by(DigitalItem.product_id)
        )
        await answer_or_edit(
            callback,
            "🔑 Остатки цифровых товаров\n\n"
            + "\n".join(f"📦 product={p} · {status}: {count}" for p, status, count in rows),
            reply_markup=admin_back(),
        )
    else:
        await answer_or_edit(callback, "📭 Раздел пока пуст.", reply_markup=admin_back())
    await callback.answer()


@router.callback_query(AdminCb.filter(F.action == "settings"))
async def admin_settings(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        await _admin(session, settings, callback)
    except AccessDenied:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await answer_or_edit(
        callback,
        "⚙️ Настройки\n\nВыберите текст или раздел для редактирования.",
        reply_markup=admin_settings_keyboard(),
    )
    await callback.answer()


@router.callback_query(AdminCb.filter(F.action == "stext"))
async def admin_setting_text_start(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    allowed = {"welcome_text", *DEFAULT_TEXTS.keys()}
    try:
        await _admin(session, settings, callback)
        if callback_data.entity not in allowed:
            raise ValidationError("Этот текст нельзя редактировать.")
        current = await get_setting_text(session, callback_data.entity, DEFAULT_TEXTS.get(callback_data.entity, ""))
        await state.set_state(SettingTextEditState.value)
        await state.update_data(key=callback_data.entity)
        await answer_or_edit(
            callback,
            f"📝 Текущий текст:\n\n{current}\n\nОтправьте новый текст одним сообщением.",
            reply_markup=admin_product_cancel_keyboard(),
        )
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.message(StateFilter(SettingTextEditState.value))
async def admin_setting_text_value(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        admin = await _admin(session, settings, message)
        data = await state.get_data()
        await set_setting_text(
            session,
            key=str(data["key"]),
            value=(message.text or "").strip(),
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await state.clear()
        await message.answer("✅ Текст обновлен.", reply_markup=admin_settings_keyboard())
    except (KeyError, AppError) as exc:
        await message.answer(str(exc))


@router.callback_query(AdminCb.filter(F.action == "menu"))
async def admin_menu_buttons(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        await _admin(session, settings, callback)
        buttons = await get_menu_buttons(session)
    except AccessDenied:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await answer_or_edit(
        callback,
        "🧩 Кнопки главного меню\n\nВыберите кнопку для настройки.",
        reply_markup=admin_menu_buttons_keyboard(buttons),
    )
    await callback.answer()


@router.callback_query(AdminCb.filter(F.action == "mbview"))
async def admin_menu_button_view(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        await _admin(session, settings, callback)
        button = await get_menu_button(session, callback_data.entity)
        content = await get_button_text(session, button) if button.kind == "text" else "-"
        text = "\n".join(
            [
                f"🧩 Кнопка: {button.label}",
                f"id: {button.id}",
                f"Тип: {button.kind}",
                f"Статус: {'показывается' if button.visible else 'скрыта'}",
                f"Сортировка: {button.sort}",
                "",
                "Содержимое:",
                content[:1500],
            ]
        )
        await answer_or_edit(callback, text, reply_markup=admin_menu_button_keyboard(button))
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.callback_query(AdminCb.filter(F.action.in_({"mbedit", "mbtext", "mbsort"})))
async def admin_menu_button_edit_start(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    labels = {
        "mbedit": "новое название кнопки",
        "mbtext": "новое содержимое кнопки",
        "mbsort": "новый порядок сортировки",
    }
    try:
        await _admin(session, settings, callback)
        button = await get_menu_button(session, callback_data.entity)
        if callback_data.action == "mbtext" and button.kind != "text":
            raise ValidationError("У этой кнопки нет текстового содержимого.")
        await state.set_state(MenuButtonEditState.value)
        await state.update_data(button_id=button.id, field=callback_data.action)
        await answer_or_edit(callback, f"✏️ Введите {labels[callback_data.action]}.", reply_markup=admin_product_cancel_keyboard())
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.message(StateFilter(MenuButtonEditState.value))
async def admin_menu_button_edit_value(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        admin = await _admin(session, settings, message)
        data = await state.get_data()
        button_id = str(data["button_id"])
        field = str(data["field"])
        raw = (message.text or "").strip()
        button = await get_menu_button(session, button_id)
        if field == "mbedit":
            button = await update_menu_button(
                session,
                button_id=button_id,
                label=raw,
                actor_telegram_id=message.from_user.id,
                admin_id=admin.id if admin else None,
            )
        elif field == "mbsort":
            button = await update_menu_button(
                session,
                button_id=button_id,
                sort=_parse_sort_order(raw),
                actor_telegram_id=message.from_user.id,
                admin_id=admin.id if admin else None,
            )
        elif field == "mbtext":
            if not button.setting_key:
                raise ValidationError("У кнопки нет текстового содержимого.")
            await set_setting_text(
                session,
                key=button.setting_key,
                value=raw,
                actor_telegram_id=message.from_user.id,
                admin_id=admin.id if admin else None,
            )
        await state.clear()
        await message.answer("✅ Кнопка обновлена.", reply_markup=admin_menu_button_keyboard(button))
    except (KeyError, ValueError, AppError) as exc:
        await message.answer(str(exc))


@router.callback_query(AdminCb.filter(F.action == "mbtog"))
async def admin_menu_button_toggle(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        admin = await _admin(session, settings, callback)
        button = await get_menu_button(session, callback_data.entity)
        button = await update_menu_button(
            session,
            button_id=button.id,
            visible=not button.visible,
            actor_telegram_id=callback.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await answer_or_edit(callback, "✅ Видимость изменена.", reply_markup=admin_menu_button_keyboard(button))
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.callback_query(AdminCb.filter(F.action == "mbdel"))
async def admin_menu_button_delete(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        admin = await _admin(session, settings, callback)
        await delete_menu_button(
            session,
            button_id=callback_data.entity,
            actor_telegram_id=callback.from_user.id,
            admin_id=admin.id if admin else None,
        )
        buttons = await get_menu_buttons(session)
        await answer_or_edit(callback, "🗑 Кнопка удалена.", reply_markup=admin_menu_buttons_keyboard(buttons))
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.callback_query(AdminCb.filter(F.action == "mbnew"))
async def admin_menu_button_create_start(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, callback)
        await state.set_state(MenuButtonCreateState.label)
        await answer_or_edit(callback, "➕ Введите название новой кнопки.", reply_markup=admin_product_cancel_keyboard())
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.message(StateFilter(MenuButtonCreateState.label))
async def admin_menu_button_create_label(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, message)
        label = (message.text or "").strip()
        if not label:
            raise ValidationError("Название не может быть пустым.")
        await state.update_data(label=label)
        await state.set_state(MenuButtonCreateState.content)
        await message.answer("📝 Введите содержимое новой кнопки.", reply_markup=admin_product_cancel_keyboard())
    except AppError as exc:
        await message.answer(str(exc))


@router.message(StateFilter(MenuButtonCreateState.content))
async def admin_menu_button_create_content(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        admin = await _admin(session, settings, message)
        data = await state.get_data()
        button = await create_text_menu_button(
            session,
            label=str(data["label"]),
            content=(message.text or "").strip(),
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await state.clear()
        await message.answer("✅ Кнопка создана.", reply_markup=admin_menu_button_keyboard(button))
    except (KeyError, AppError) as exc:
        await message.answer(str(exc))


@router.callback_query(AdminCb.filter(F.action == "broadcast"))
async def admin_broadcast_start(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, callback)
        await state.set_state(BroadcastState.target)
        await answer_or_edit(
            callback,
            "📣 Введите аудиторию рассылки: all, buyers или product:id.",
            reply_markup=admin_product_cancel_keyboard(),
        )
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.message(StateFilter(BroadcastState.target))
async def admin_broadcast_target(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, message)
        target = (message.text or "").strip()
        if target not in {"all", "buyers"} and not target.startswith("product:"):
            raise ValidationError("Аудитория: all, buyers или product:id.")
        await state.update_data(target=target)
        await state.set_state(BroadcastState.text)
        await message.answer("📝 Введите текст рассылки.", reply_markup=admin_product_cancel_keyboard())
    except AppError as exc:
        await message.answer(str(exc))


@router.message(StateFilter(BroadcastState.text))
async def admin_broadcast_text(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        admin = await _admin(session, settings, message)
        data = await state.get_data()
        target_raw = str(data["target"])
        target_type = target_raw
        product_id: int | None = None
        if target_raw.startswith("product:"):
            target_type = "product"
            product_id = int(target_raw.split(":", 1)[1])
        broadcast = await create_broadcast(
            session,
            target_type=target_type,
            product_id=product_id,
            text=(message.text or "").strip(),
            admin_id=admin.id if admin else None,
        )
        broadcast = await run_broadcast(session, message.bot, broadcast.id)
        await state.clear()
        await message.answer(
            f"✅ Рассылка завершена. Отправлено: {broadcast.sent_count}, ошибок: {broadcast.error_count}",
            reply_markup=admin_menu(),
        )
    except (KeyError, ValueError, AppError) as exc:
        await message.answer(str(exc))


@router.callback_query(AdminCb.filter(F.action == "pview"))
async def admin_product_view(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        await _admin(session, settings, callback)
        await _show_product_card(
            callback,
            session,
            product_id=callback_data.object_id,
            page=callback_data.page,
        )
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.callback_query(AdminCb.filter(F.action == "pnew"))
async def admin_product_create_start(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, callback)
        await state.clear()
        page = await list_categories(session, page=callback_data.page, active_only=True)
        if page.total == 0:
            await answer_or_edit(
                callback,
                "📁 Для создания товара нужна хотя бы одна активная категория.",
                reply_markup=admin_empty_product_tree_keyboard(reason="category"),
            )
            await callback.answer()
            return
        await answer_or_edit(
            callback,
            "📦 Создание товара\n\n📁 Выберите категорию.",
            reply_markup=admin_category_select_keyboard(page, action="pcat", back_action="cancel"),
        )
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.callback_query(AdminCb.filter(F.action == "pcat"))
async def admin_product_create_category(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, callback)
        if callback_data.entity == "catp":
            page = await list_categories(session, page=callback_data.page, active_only=True)
            await answer_or_edit(
                callback,
                "📦 Создание товара\n\n📁 Выберите категорию.",
                reply_markup=admin_category_select_keyboard(page, action="pcat", back_action="cancel"),
            )
        else:
            category_id = callback_data.object_id
            await state.update_data(category_id=category_id)
            page = await list_subcategories(
                session,
                category_id=category_id,
                page=0,
                active_only=True,
            )
            if page.total == 0:
                await answer_or_edit(
                    callback,
                    "🗂 В выбранной категории нет активных подкатегорий.",
                    reply_markup=admin_empty_product_tree_keyboard(
                        reason="subcategory",
                        category_id=category_id,
                    ),
                )
                await callback.answer()
                return
            await answer_or_edit(
                callback,
                "📦 Создание товара\n\n🗂 Выберите подкатегорию.",
                reply_markup=admin_subcategory_select_keyboard(category_id, page, action="psub"),
            )
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.callback_query(AdminCb.filter(F.action == "psub"))
async def admin_product_create_subcategory(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, callback)
        if callback_data.entity.startswith("sub") and callback_data.entity != "sub":
            category_id = int(callback_data.entity.removeprefix("sub"))
            page = await list_subcategories(
                session,
                category_id=category_id,
                page=callback_data.page,
                active_only=True,
            )
            await answer_or_edit(
                callback,
                "📦 Создание товара\n\n🗂 Выберите подкатегорию.",
                reply_markup=admin_subcategory_select_keyboard(category_id, page, action="psub"),
            )
        else:
            await state.update_data(subcategory_id=callback_data.object_id)
            await state.set_state(ProductCreateState.title)
            await answer_or_edit(
                callback,
                "✏️ Введите название товара.",
                reply_markup=admin_product_cancel_keyboard(),
            )
    except (ValueError, AppError) as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.callback_query(AdminCb.filter(F.action == "pcancel"))
async def admin_product_flow_cancel(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, callback)
    except AccessDenied:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await state.clear()
    await answer_or_edit(callback, "❌ Действие отменено.", reply_markup=admin_menu())
    await callback.answer()


@router.message(StateFilter(ProductCreateState.title))
async def admin_product_create_title(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, message)
        title = (message.text or "").strip()
        if not title:
            raise ValidationError("Название не может быть пустым.")
        await state.update_data(title=title)
        await state.set_state(ProductCreateState.description)
        await message.answer(
            "📝 Введите описание товара или нажмите «Пропустить».",
            reply_markup=admin_product_skip_keyboard("desc"),
        )
    except AppError as exc:
        await message.answer(str(exc))


@router.message(StateFilter(ProductCreateState.description))
async def admin_product_create_description(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, message)
        description = (message.text or "").strip()
        await state.update_data(description="" if description == "-" else description)
        await state.set_state(ProductCreateState.price)
        await message.answer("💰 Введите цену, например 199.00.", reply_markup=admin_product_cancel_keyboard())
    except AppError as exc:
        await message.answer(str(exc))


@router.message(StateFilter(ProductCreateState.price))
async def admin_product_create_price(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, message)
        price = _parse_price(message.text or "")
        await state.update_data(price=str(price))
        await state.set_state(ProductCreateState.currency)
        await message.answer("💱 Введите валюту ISO-4217, например RUB.", reply_markup=admin_product_cancel_keyboard())
    except AppError as exc:
        await message.answer(str(exc))


@router.message(StateFilter(ProductCreateState.currency))
async def admin_product_create_currency(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, message)
        currency = (message.text or "").strip().upper()
        if len(currency) != 3 or not currency.isalpha():
            raise ValidationError("Валюта должна быть ISO-кодом из 3 букв, например RUB.")
        await state.update_data(currency=currency)
        await state.set_state(ProductCreateState.sort_order)
        await message.answer(
            "🔢 Введите порядок сортировки или нажмите «Пропустить».",
            reply_markup=admin_product_skip_keyboard("sort"),
        )
    except AppError as exc:
        await message.answer(str(exc))


@router.message(StateFilter(ProductCreateState.sort_order))
async def admin_product_create_sort_order(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, message)
        sort_order = _parse_sort_order(message.text or "")
        await state.update_data(sort_order=sort_order)
        await _show_product_create_confirm(message, state)
    except AppError as exc:
        await message.answer(str(exc))


@router.callback_query(AdminCb.filter(F.action == "pskip"))
async def admin_product_create_skip(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, callback)
        if callback_data.entity == "desc":
            await state.update_data(description="")
            await state.set_state(ProductCreateState.price)
            await answer_or_edit(
                callback,
                "💰 Введите цену, например 199.00.",
                reply_markup=admin_product_cancel_keyboard(),
            )
        elif callback_data.entity == "sort":
            await state.update_data(sort_order=100)
            await _show_product_create_confirm(callback, state)
        else:
            raise ValidationError("Нельзя пропустить этот шаг.")
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


async def _show_product_create_confirm(target: Message | CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ProductCreateState.confirm)
    data = await state.get_data()
    text = "\n".join(
        [
            "✅ Проверьте товар перед созданием:",
            f"📁 Категория ID: {data.get('category_id')}",
            f"🗂 Подкатегория ID: {data.get('subcategory_id')}",
            f"✏️ Название: {data.get('title')}",
            f"💰 Цена: {data.get('price')} {data.get('currency')}",
            f"🔢 Сортировка: {data.get('sort_order', 100)}",
            "",
            "📝 Описание:",
            data.get("description") or "-",
        ]
    )
    await answer_or_edit(target, text, reply_markup=admin_product_confirm_keyboard())


@router.callback_query(AdminCb.filter(F.action == "pconfirm"))
async def admin_product_create_confirm(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        admin = await _admin(session, settings, callback)
        data = await state.get_data()
        product = await create_product(
            session,
            category_id=int(data["category_id"]),
            subcategory_id=int(data["subcategory_id"]),
            title=str(data["title"]),
            description=str(data.get("description") or ""),
            price=Decimal(str(data["price"])),
            currency=str(data["currency"]),
            sort_order=int(data.get("sort_order") or 100),
            actor_telegram_id=callback.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await state.clear()
        await _show_product_card(callback, session, product_id=product.id)
    except (KeyError, ValueError, InvalidOperation, AppError) as exc:
        await callback.answer(str(exc), show_alert=True)
        return
        await callback.answer("✅ Товар создан.")


@router.callback_query(AdminCb.filter(F.action == "pedit"))
async def admin_product_edit_start(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    field_labels = {
        "title": "новое название",
        "desc": "новое описание или '-' чтобы очистить",
        "price": "новую цену, например 199.00",
        "curr": "новую валюту, например RUB",
        "sort": "новый порядок сортировки",
    }
    try:
        await _admin(session, settings, callback)
        if callback_data.entity not in field_labels:
            raise ValidationError("Поле не поддерживается.")
        await state.set_state(ProductEditState.value)
        await state.update_data(
            product_id=callback_data.object_id,
            field=callback_data.entity,
            page=callback_data.page,
        )
        await answer_or_edit(
            callback,
            f"✏️ Введите {field_labels[callback_data.entity]}.",
            reply_markup=admin_product_cancel_keyboard(),
        )
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.message(StateFilter(ProductEditState.value))
async def admin_product_edit_value(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        admin = await _admin(session, settings, message)
        data = await state.get_data()
        product_id = int(data["product_id"])
        field = str(data["field"])
        raw_value = (message.text or "").strip()
        if field == "title":
            await update_entity_title(
                session,
                entity="product",
                entity_id=product_id,
                title=raw_value,
                actor_telegram_id=message.from_user.id,
                admin_id=admin.id if admin else None,
            )
        elif field == "desc":
            await update_product_description(
                session,
                product_id=product_id,
                description="" if raw_value == "-" else raw_value,
                actor_telegram_id=message.from_user.id,
                admin_id=admin.id if admin else None,
            )
        elif field == "price":
            await update_product_price(
                session,
                product_id=product_id,
                price=_parse_price(raw_value),
                actor_telegram_id=message.from_user.id,
                admin_id=admin.id if admin else None,
            )
        elif field == "curr":
            await update_product_currency(
                session,
                product_id=product_id,
                currency=raw_value,
                actor_telegram_id=message.from_user.id,
                admin_id=admin.id if admin else None,
            )
        elif field == "sort":
            await update_entity_sort_order(
                session,
                entity="product",
                entity_id=product_id,
                sort_order=_parse_sort_order(raw_value),
                actor_telegram_id=message.from_user.id,
                admin_id=admin.id if admin else None,
            )
        else:
            raise ValidationError("Поле не поддерживается.")
        page = int(data.get("page") or 0)
        await state.clear()
        await _show_product_card(message, session, product_id=product_id, page=page)
    except (KeyError, ValueError, AppError) as exc:
        await message.answer(str(exc))


@router.callback_query(AdminCb.filter(F.action == "ptog"))
async def admin_product_toggle_active(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        admin = await _admin(session, settings, callback)
        product = await session.get(Product, callback_data.object_id)
        if product is None:
            raise ValidationError("Товар не найден.")
        await set_entity_active(
            session,
            entity="product",
            entity_id=product.id,
            is_active=not product.is_active,
            actor_telegram_id=callback.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await _show_product_card(callback, session, product_id=product.id, page=callback_data.page)
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("✅ Статус изменен.")


@router.callback_query(AdminCb.filter(F.action == "pdel"))
async def admin_product_delete(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        admin = await _admin(session, settings, callback)
        await soft_delete_entity(
            session,
            entity="product",
            entity_id=callback_data.object_id,
            actor_telegram_id=callback.from_user.id,
            admin_id=admin.id if admin else None,
        )
        page = await _products_page(session, page=callback_data.page)
        await answer_or_edit(
            callback,
            "🗑 Товар отключен и отмечен в audit log.\n\n📦 Выберите следующий товар.",
            reply_markup=admin_products_keyboard(page),
        )
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("🗑 Товар отключен.")


@router.callback_query(AdminCb.filter(F.action == "items"))
async def admin_digital_items_product(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        await _admin(session, settings, callback)
        await _show_digital_product(
            callback,
            session,
            product_id=callback_data.object_id,
            page=callback_data.page,
        )
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.callback_query(AdminCb.filter(F.action == "ilist"))
async def admin_digital_items_list(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        await _admin(session, settings, callback)
        await _show_digital_items_page(
            callback,
            session,
            product_id=callback_data.object_id,
            page=callback_data.page,
        )
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.callback_query(AdminCb.filter(F.action == "iupload"))
async def admin_digital_upload_start(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, callback)
        await state.set_state(DigitalItemUploadState.values)
        await state.update_data(product_id=callback_data.object_id, page=callback_data.page)
        await answer_or_edit(
            callback,
            "➕ Отправьте коды сообщением: один код на строку. Можно прислать .txt или .csv документ.",
            reply_markup=admin_product_cancel_keyboard(),
        )
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.message(StateFilter(DigitalItemUploadState.values))
async def admin_digital_upload_values(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        admin = await _admin(session, settings, message)
        data = await state.get_data()
        product_id = int(data["product_id"])
        if message.document:
            tg_file = await message.bot.get_file(message.document.file_id)
            downloaded = await message.bot.download_file(tg_file.file_path)
            body = downloaded.read().decode("utf-8")
            is_csv = (message.document.file_name or "").lower().endswith(".csv")
        else:
            body = message.text or ""
            is_csv = "," in body
        values, parse_errors = parse_items_csv(body) if is_csv else parse_items_text(body)
        result = await import_digital_items(
            session,
            product_id=product_id,
            raw_values=values,
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await state.clear()
        await message.answer(
            "\n".join(
                [
                    "✅ Импорт завершен",
                    f"📦 Обработано: {result.processed + parse_errors}",
                    f"➕ Добавлено: {result.added}",
                    f"⏭ Пропущено: {result.skipped}",
                    f"♻️ Дублей: {result.duplicates}",
                    f"⚠️ Ошибок: {result.errors + parse_errors}",
                ]
            )
        )
        await _show_digital_product(message, session, product_id=product_id, page=int(data.get("page") or 0))
    except (KeyError, ValueError, AppError) as exc:
        await message.answer(str(exc))


@router.callback_query(AdminCb.filter(F.action == "iexport"))
async def admin_digital_export(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        await _admin(session, settings, callback)
        content = await export_digital_items_csv(session, product_id=callback_data.object_id)
        file = BufferedInputFile(content.encode("utf-8"), filename=f"product-{callback_data.object_id}-items.csv")
        await callback.message.answer_document(file) if callback.message else None
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("📤 Экспорт готов.")


@router.callback_query(AdminCb.filter(F.action == "isearch"))
async def admin_digital_search_start(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, callback)
        await state.set_state(DigitalItemSearchState.query)
        await state.update_data(product_id=callback_data.object_id, page=callback_data.page)
        await answer_or_edit(callback, "🔎 Введите часть кода для поиска.", reply_markup=admin_product_cancel_keyboard())
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.message(StateFilter(DigitalItemSearchState.query))
async def admin_digital_search_query(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, message)
        data = await state.get_data()
        product_id = int(data["product_id"])
        items = await search_digital_items(
            session,
            query=(message.text or "").strip(),
            product_id=product_id,
            limit=20,
        )
        await state.clear()
        if not items:
            await message.answer("🔎 Ничего не найдено.", reply_markup=admin_digital_product_keyboard(product_id))
            return
        text = "🔎 Найденные коды\n\n" + "\n".join(
            f"#{item.id} · {item.status} · {item.value[:80]}" for item in items
        )
        await message.answer(
            text,
            reply_markup=admin_digital_search_keyboard(
                items,
                product_id=product_id,
                page=int(data.get("page") or 0),
            ),
        )
    except (KeyError, ValueError, AppError) as exc:
        await message.answer(str(exc))


@router.callback_query(AdminCb.filter(F.action == "iview"))
async def admin_digital_item_view(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        await _admin(session, settings, callback)
        item = await session.get(DigitalItem, callback_data.object_id)
        if item is None:
            raise ValidationError("Код не найден.")
        text = "\n".join(
            [
                f"🔑 Код #{item.id}",
                f"📦 product_id: {item.product_id}",
                f"📌 Статус: {item.status}",
                f"🧾 order_id: {item.order_id or '-'}",
                "",
                item.value,
            ]
        )
        await answer_or_edit(
            callback,
            text,
            reply_markup=admin_digital_item_keyboard(
                item.id,
                product_id=item.product_id,
                page=callback_data.page,
                can_modify=item.status == "available",
            ),
        )
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.callback_query(AdminCb.filter(F.action == "iedit"))
async def admin_digital_item_edit_start(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, callback)
        item = await session.get(DigitalItem, callback_data.object_id)
        if item is None:
            raise ValidationError("Код не найден.")
        await state.set_state(DigitalItemEditState.value)
        await state.update_data(item_id=item.id, product_id=item.product_id, page=callback_data.page)
        await answer_or_edit(callback, "✏️ Введите новое значение кода.", reply_markup=admin_product_cancel_keyboard())
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.message(StateFilter(DigitalItemEditState.value))
async def admin_digital_item_edit_value(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        admin = await _admin(session, settings, message)
        data = await state.get_data()
        item = await update_digital_item_value(
            session,
            item_id=int(data["item_id"]),
            value=message.text or "",
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await state.clear()
        await message.answer("✅ Код обновлен.")
        await _show_digital_items_page(message, session, product_id=item.product_id, page=int(data.get("page") or 0))
    except (KeyError, ValueError, AppError) as exc:
        await message.answer(str(exc))


@router.callback_query(AdminCb.filter(F.action == "idel"))
async def admin_digital_item_delete(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        admin = await _admin(session, settings, callback)
        item = await delete_digital_item(
            session,
            item_id=callback_data.object_id,
            actor_telegram_id=callback.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await _show_digital_items_page(callback, session, product_id=item.product_id, page=callback_data.page)
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("🗑 Код удален.")


@router.callback_query(AdminCb.filter(F.action == "cview"))
async def admin_category_view(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        await _admin(session, settings, callback)
        await _show_category_card(callback, session, category_id=callback_data.object_id, page=callback_data.page)
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.callback_query(AdminCb.filter(F.action == "cnew"))
async def admin_category_create_start(
    callback: CallbackQuery,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, callback)
        await state.clear()
        await state.set_state(CategoryCreateState.title)
        await answer_or_edit(callback, "📁 Введите название категории.", reply_markup=admin_product_cancel_keyboard())
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.message(StateFilter(CategoryCreateState.title))
async def admin_category_create_title(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        admin = await _admin(session, settings, message)
        title = (message.text or "").strip()
        category = await create_category(
            session,
            title=title,
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await state.clear()
        await _show_category_card(message, session, category_id=category.id)
    except AppError as exc:
        await message.answer(str(exc))


@router.callback_query(AdminCb.filter(F.action == "cedit"))
async def admin_category_edit_start(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    labels = {"title": "новое название категории", "sort": "новый порядок сортировки"}
    try:
        await _admin(session, settings, callback)
        if callback_data.entity not in labels:
            raise ValidationError("Поле не поддерживается.")
        await state.set_state(CategoryEditState.value)
        await state.update_data(
            category_id=callback_data.object_id,
            field=callback_data.entity,
            page=callback_data.page,
        )
        await answer_or_edit(callback, f"✏️ Введите {labels[callback_data.entity]}.", reply_markup=admin_product_cancel_keyboard())
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.message(StateFilter(CategoryEditState.value))
async def admin_category_edit_value(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        admin = await _admin(session, settings, message)
        data = await state.get_data()
        category_id = int(data["category_id"])
        field = str(data["field"])
        raw_value = (message.text or "").strip()
        if field == "title":
            await update_entity_title(
                session,
                entity="category",
                entity_id=category_id,
                title=raw_value,
                actor_telegram_id=message.from_user.id,
                admin_id=admin.id if admin else None,
            )
        elif field == "sort":
            await update_entity_sort_order(
                session,
                entity="category",
                entity_id=category_id,
                sort_order=_parse_sort_order(raw_value),
                actor_telegram_id=message.from_user.id,
                admin_id=admin.id if admin else None,
            )
        else:
            raise ValidationError("Поле не поддерживается.")
        page = int(data.get("page") or 0)
        await state.clear()
        await _show_category_card(message, session, category_id=category_id, page=page)
    except (KeyError, ValueError, AppError) as exc:
        await message.answer(str(exc))


@router.callback_query(AdminCb.filter(F.action == "ctog"))
async def admin_category_toggle_active(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        admin = await _admin(session, settings, callback)
        category = await session.get(Category, callback_data.object_id)
        if category is None:
            raise ValidationError("Категория не найдена.")
        await set_entity_active(
            session,
            entity="category",
            entity_id=category.id,
            is_active=not category.is_active,
            actor_telegram_id=callback.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await _show_category_card(callback, session, category_id=category.id, page=callback_data.page)
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("✅ Статус изменен.")


@router.callback_query(AdminCb.filter(F.action == "cdel"))
async def admin_category_delete(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        admin = await _admin(session, settings, callback)
        await soft_delete_entity(
            session,
            entity="category",
            entity_id=callback_data.object_id,
            actor_telegram_id=callback.from_user.id,
            admin_id=admin.id if admin else None,
        )
        page = await _categories_page(session, page=callback_data.page)
        await answer_or_edit(
            callback,
            "🗑 Категория отключена и отмечена в audit log.",
            reply_markup=admin_categories_keyboard(page),
        )
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("🗑 Категория отключена.")


@router.callback_query(AdminCb.filter(F.action == "sview"))
async def admin_subcategory_view(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        await _admin(session, settings, callback)
        await _show_subcategory_card(
            callback,
            session,
            subcategory_id=callback_data.object_id,
            page=callback_data.page,
        )
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.callback_query(AdminCb.filter(F.action == "snew"))
async def admin_subcategory_create_start(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, callback)
        await state.clear()
        category_id = callback_data.object_id
        if category_id:
            category = await session.get(Category, category_id)
            if category is None:
                raise ValidationError("Категория не найдена.")
            await state.update_data(category_id=category_id)
            await state.set_state(SubcategoryCreateState.title)
            await answer_or_edit(
                callback,
                f"🗂 Новая подкатегория для категории «{category.title}».\n\n✏️ Введите название подкатегории.",
                reply_markup=admin_product_cancel_keyboard(),
            )
        else:
            page = await list_categories(session, page=callback_data.page, active_only=False)
            if page.total == 0:
                await answer_or_edit(
                    callback,
                    "📁 Сначала создайте категорию.",
                    reply_markup=admin_empty_product_tree_keyboard(reason="category"),
                )
            else:
                await answer_or_edit(
                    callback,
                    "📁 Выберите категорию для новой подкатегории.",
                    reply_markup=admin_category_select_keyboard(
                        page,
                        action="scat",
                        back_action="list",
                        back_entity="subs",
                        back_text="К подкатегориям",
                    ),
                )
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.callback_query(AdminCb.filter(F.action == "scat"))
async def admin_subcategory_create_category(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        await _admin(session, settings, callback)
        if callback_data.entity == "catp":
            page = await list_categories(session, page=callback_data.page, active_only=False)
            await answer_or_edit(
                callback,
                "📁 Выберите категорию для новой подкатегории.",
                reply_markup=admin_category_select_keyboard(
                    page,
                    action="scat",
                    back_action="list",
                    back_entity="subs",
                    back_text="К подкатегориям",
                ),
            )
        else:
            category = await session.get(Category, callback_data.object_id)
            if category is None:
                raise ValidationError("Категория не найдена.")
            await state.update_data(category_id=category.id)
            await state.set_state(SubcategoryCreateState.title)
            await answer_or_edit(
                callback,
                f"🗂 Новая подкатегория для категории «{category.title}».\n\n✏️ Введите название подкатегории.",
                reply_markup=admin_product_cancel_keyboard(),
            )
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.message(StateFilter(SubcategoryCreateState.title))
async def admin_subcategory_create_title(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        admin = await _admin(session, settings, message)
        data = await state.get_data()
        subcategory = await create_subcategory(
            session,
            category_id=int(data["category_id"]),
            title=(message.text or "").strip(),
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await state.clear()
        await _show_subcategory_card(message, session, subcategory_id=subcategory.id)
    except (KeyError, ValueError, AppError) as exc:
        await message.answer(str(exc))


@router.callback_query(AdminCb.filter(F.action == "sedit"))
async def admin_subcategory_edit_start(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    labels = {"title": "новое название подкатегории", "sort": "новый порядок сортировки"}
    try:
        await _admin(session, settings, callback)
        if callback_data.entity not in labels:
            raise ValidationError("Поле не поддерживается.")
        await state.set_state(SubcategoryEditState.value)
        await state.update_data(
            subcategory_id=callback_data.object_id,
            field=callback_data.entity,
            page=callback_data.page,
        )
        await answer_or_edit(callback, f"✏️ Введите {labels[callback_data.entity]}.", reply_markup=admin_product_cancel_keyboard())
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.message(StateFilter(SubcategoryEditState.value))
async def admin_subcategory_edit_value(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    state: FSMContext,
) -> None:
    try:
        admin = await _admin(session, settings, message)
        data = await state.get_data()
        subcategory_id = int(data["subcategory_id"])
        field = str(data["field"])
        raw_value = (message.text or "").strip()
        if field == "title":
            await update_entity_title(
                session,
                entity="subcategory",
                entity_id=subcategory_id,
                title=raw_value,
                actor_telegram_id=message.from_user.id,
                admin_id=admin.id if admin else None,
            )
        elif field == "sort":
            await update_entity_sort_order(
                session,
                entity="subcategory",
                entity_id=subcategory_id,
                sort_order=_parse_sort_order(raw_value),
                actor_telegram_id=message.from_user.id,
                admin_id=admin.id if admin else None,
            )
        else:
            raise ValidationError("Поле не поддерживается.")
        page = int(data.get("page") or 0)
        await state.clear()
        await _show_subcategory_card(message, session, subcategory_id=subcategory_id, page=page)
    except (KeyError, ValueError, AppError) as exc:
        await message.answer(str(exc))


@router.callback_query(AdminCb.filter(F.action == "stog"))
async def admin_subcategory_toggle_active(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        admin = await _admin(session, settings, callback)
        subcategory = await session.get(Subcategory, callback_data.object_id)
        if subcategory is None:
            raise ValidationError("Подкатегория не найдена.")
        await set_entity_active(
            session,
            entity="subcategory",
            entity_id=subcategory.id,
            is_active=not subcategory.is_active,
            actor_telegram_id=callback.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await _show_subcategory_card(
            callback,
            session,
            subcategory_id=subcategory.id,
            page=callback_data.page,
        )
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("✅ Статус изменен.")


@router.callback_query(AdminCb.filter(F.action == "sdel"))
async def admin_subcategory_delete(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        admin = await _admin(session, settings, callback)
        subcategory = await session.get(Subcategory, callback_data.object_id)
        if subcategory is None:
            raise ValidationError("Подкатегория не найдена.")
        category_id = subcategory.category_id
        await soft_delete_entity(
            session,
            entity="subcategory",
            entity_id=subcategory.id,
            actor_telegram_id=callback.from_user.id,
            admin_id=admin.id if admin else None,
        )
        page = await _subcategories_page(session, page=callback_data.page, category_id=category_id)
        await answer_or_edit(
            callback,
            "🗑 Подкатегория отключена и отмечена в audit log.",
            reply_markup=admin_subcategories_keyboard(page, category_id=category_id),
        )
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("🗑 Подкатегория отключена.")


@router.callback_query(AdminCb.filter(F.action == "uview"))
async def admin_user_view(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        await _admin(session, settings, callback)
        stats = await get_user_purchase_stats(session, callback_data.object_id)
        await answer_or_edit(
            callback,
            _format_user_purchase_stats(stats),
            reply_markup=admin_user_keyboard(callback_data.object_id, page=callback_data.page),
        )
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer()


@router.callback_query(AdminCb.filter((F.action == "view") & (F.entity == "order")))
async def admin_order_view(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        await _admin(session, settings, callback)
        order = await get_order_detail(session, callback_data.object_id)
    except AccessDenied:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    item_values = [item.value for item in order.issued_items] if order.issued_items else []
    item_value = "\n".join(f"`{value}`" for value in item_values) if item_values else "-"
    payment_id = order.payments[0].id if order.payments else "-"
    text = "\n".join(
        [
            f"🧾 Заказ #{order.id}",
            f"👤 Пользователь: {order.user.id}",
            f"telegram_id: {order.user.telegram_id}",
            f"username: @{order.user.username or '-'}",
            f"📦 Товар: {order.product.title}",
            f"📁 category_id: {order.category_id}",
            f"🗂 subcategory_id: {order.subcategory_id}",
            f"🔢 Количество: {order.quantity}",
            f"💰 Сумма: {order.amount} {order.currency}",
            f"📌 Статус: {order.status}",
            f"🕒 Создан: {order.created_at}",
            f"✅ Оплачен: {order.paid_at or '-'}",
            f"payment_id: {payment_id}",
            f"telegram_payment_charge_id: {order.telegram_payment_charge_id or '-'}",
            f"provider_payment_charge_id: {order.provider_payment_charge_id or '-'}",
            f"🔑 Коды:\n{item_value}",
        ]
    )
    await answer_or_edit(
        callback,
        text,
        reply_markup=admin_order_keyboard(order.id, has_item=bool(order.issued_items)),
    )
    await callback.answer()


@router.callback_query(AdminCb.filter((F.action == "resend") & (F.entity == "order")))
async def admin_resend_code(
    callback: CallbackQuery,
    callback_data: AdminCb,
    session: AsyncSession,
    settings: Settings,
) -> None:
    try:
        await _admin(session, settings, callback)
        order = await get_order_detail(session, callback_data.object_id)
        if not order.issued_items:
            raise ValidationError("У заказа нет выданного кода.")
        values = "\n".join(f"`{item.value}`" for item in order.issued_items)
        await callback.bot.send_message(
            order.user.telegram_id,
            f"Повторная отправка цифровых товаров по заказу #{order.id}:\n{values}",
            parse_mode="Markdown",
        )
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("🔁 Код отправлен.")


@router.message(Command("admin_set_order_status"))
async def cmd_set_order_status(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        admin = await _admin(session, settings, message)
        _, order_id, status = message.text.split(maxsplit=2)
        await update_order_status(
            session,
            order_id=int(order_id),
            status=status,
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await message.answer("✅ Статус заказа обновлен.")
    except (ValueError, IndexError, AppError):
        await message.answer("ℹ️ Формат: /admin_set_order_status order_id pending|paid|cancelled|error|refunded")


@router.message(Command("admin_comment_order"))
async def cmd_comment_order(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        admin = await _admin(session, settings, message)
        _, order_id, comment = message.text.split(maxsplit=2)
        await update_order_comment(
            session,
            order_id=int(order_id),
            comment=comment,
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await message.answer("✅ Комментарий к заказу обновлен.")
    except (ValueError, IndexError, AppError):
        await message.answer("ℹ️ Формат: /admin_comment_order order_id комментарий")


@router.message(Command("admin_create_category"))
async def cmd_create_category(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        admin = await _admin(session, settings, message)
        title = message.text.split(maxsplit=1)[1]
        category = await create_category(
            session,
            title=title,
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await message.answer(f"✅📁 Категория создана: {category.id}")
    except (IndexError, AppError):
        await message.answer("ℹ️ Формат: /admin_create_category Название")


@router.message(Command("admin_create_subcategory"))
async def cmd_create_subcategory(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        admin = await _admin(session, settings, message)
        _, category_id, title = message.text.split(maxsplit=2)
        subcategory = await create_subcategory(
            session,
            category_id=int(category_id),
            title=title,
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await message.answer(f"✅🗂 Подкатегория создана: {subcategory.id}")
    except (ValueError, IndexError, AppError):
        await message.answer("ℹ️ Формат: /admin_create_subcategory category_id Название")


@router.message(Command("admin_create_product"))
async def cmd_create_product(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        admin = await _admin(session, settings, message)
        raw = message.text.split(maxsplit=1)[1]
        head, title, price, currency, description = [part.strip() for part in raw.split("|", 4)]
        category_id, subcategory_id = [int(part) for part in head.split()]
        product = await create_product(
            session,
            category_id=category_id,
            subcategory_id=subcategory_id,
            title=title,
            description=description,
            price=Decimal(price),
            currency=currency,
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await message.answer(f"✅📦 Товар создан: {product.id}")
    except (ValueError, IndexError, AppError):
        await message.answer(
            "ℹ️ Формат: /admin_create_product category_id subcategory_id | Название | 100.00 | RUB | Описание"
        )


@router.message(Command("admin_set_active"))
async def cmd_set_active(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        admin = await _admin(session, settings, message)
        _, entity, entity_id, active = message.text.split(maxsplit=3)
        await set_entity_active(
            session,
            entity=entity,
            entity_id=int(entity_id),
            is_active=active.lower() in {"1", "true", "yes", "on"},
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await message.answer("✅ Статус изменен.")
    except (ValueError, IndexError, AppError):
        await message.answer("ℹ️ Формат: /admin_set_active category|subcategory|product id true|false")


@router.message(Command("admin_rename"))
async def cmd_rename_entity(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        admin = await _admin(session, settings, message)
        _, entity, entity_id, title = message.text.split(maxsplit=3)
        await update_entity_title(
            session,
            entity=entity,
            entity_id=int(entity_id),
            title=title,
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await message.answer("✅ Название обновлено.")
    except (ValueError, IndexError, AppError):
        await message.answer("ℹ️ Формат: /admin_rename category|subcategory|product id Новое название")


@router.message(Command("admin_sort"))
async def cmd_sort_entity(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        admin = await _admin(session, settings, message)
        _, entity, entity_id, sort_order = message.text.split(maxsplit=3)
        await update_entity_sort_order(
            session,
            entity=entity,
            entity_id=int(entity_id),
            sort_order=int(sort_order),
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await message.answer("✅ Сортировка обновлена.")
    except (ValueError, IndexError, AppError):
        await message.answer("ℹ️ Формат: /admin_sort category|subcategory|product id sort_order")


@router.message(Command("admin_delete_entity"))
async def cmd_delete_entity(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        admin = await _admin(session, settings, message)
        _, entity, entity_id = message.text.split(maxsplit=2)
        await soft_delete_entity(
            session,
            entity=entity,
            entity_id=int(entity_id),
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await message.answer("🗑 Сущность отключена и отмечена в audit log.")
    except (ValueError, IndexError, AppError):
        await message.answer("ℹ️ Формат: /admin_delete_entity category|subcategory|product id")


@router.message(Command("admin_update_price"))
async def cmd_update_price(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        admin = await _admin(session, settings, message)
        _, product_id, price = message.text.split(maxsplit=2)
        await update_product_price(
            session,
            product_id=int(product_id),
            price=Decimal(price),
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await message.answer("✅ Цена обновлена.")
    except (ValueError, IndexError, AppError):
        await message.answer("ℹ️ Формат: /admin_update_price product_id 100.00")


@router.message(Command("admin_upload_items"))
async def cmd_upload_items(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        admin = await _admin(session, settings, message)
        raw_command = message.text or message.caption or ""
        if message.document:
            header = raw_command
            tg_file = await message.bot.get_file(message.document.file_id)
            downloaded = await message.bot.download_file(tg_file.file_path)
            body = downloaded.read().decode("utf-8")
            is_csv = (message.document.file_name or "").lower().endswith(".csv")
        else:
            header, body = raw_command.split("\n", 1)
            is_csv = "," in body
        product_id = int(header.split(maxsplit=1)[1])
        values, parse_errors = parse_items_csv(body) if is_csv else parse_items_text(body)
        result = await import_digital_items(
            session,
            product_id=product_id,
            raw_values=values,
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await message.answer(
            "\n".join(
                [
                    "✅ Импорт завершен",
                    f"📦 Обработано: {result.processed + parse_errors}",
                    f"➕ Добавлено: {result.added}",
                    f"⏭ Пропущено: {result.skipped}",
                    f"♻️ Дублей: {result.duplicates}",
                    f"⚠️ Ошибок: {result.errors + parse_errors}",
                ]
            )
        )
    except (ValueError, IndexError, AppError):
        await message.answer("ℹ️ Формат: /admin_upload_items product_id\\ncode1\\ncode2 или документ .txt/.csv с caption")


@router.message(Command("admin_export_items"))
async def cmd_export_items(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        await _admin(session, settings, message)
        product_id = int(message.text.split(maxsplit=1)[1])
        content = await export_digital_items_csv(session, product_id=product_id)
        file = BufferedInputFile(content.encode("utf-8"), filename=f"product-{product_id}-items.csv")
        await message.answer_document(file)
    except (ValueError, IndexError, AppError):
        await message.answer("ℹ️ Формат: /admin_export_items product_id")


@router.message(Command("admin_search_items"))
async def cmd_search_items(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        await _admin(session, settings, message)
        query = message.text.split(maxsplit=1)[1]
        items = await search_digital_items(session, query=query, limit=20)
        if not items:
            await message.answer("🔎 Ничего не найдено.")
            return
        await message.answer(
            "🔎 Найденные коды\n\n"
            + "\n".join(
                f"{item.id}: product={item.product_id} status={item.status} value={item.value[:80]}"
                for item in items
            )
        )
    except (ValueError, IndexError, AppError):
        await message.answer("ℹ️ Формат: /admin_search_items часть_кода")


@router.message(Command("admin_update_item"))
async def cmd_update_item(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        admin = await _admin(session, settings, message)
        _, item_id, value = message.text.split(maxsplit=2)
        item = await update_digital_item_value(
            session,
            item_id=int(item_id),
            value=value,
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await message.answer(f"✅🔑 Код обновлен: {item.id}")
    except (ValueError, IndexError, AppError):
        await message.answer("ℹ️ Формат: /admin_update_item item_id новое_значение")


@router.message(Command("admin_delete_item"))
async def cmd_delete_item(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        admin = await _admin(session, settings, message)
        item_id = int(message.text.split(maxsplit=1)[1])
        await delete_digital_item(
            session,
            item_id=item_id,
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await message.answer("🗑 Код удален.")
    except (ValueError, IndexError, AppError):
        await message.answer("ℹ️ Формат: /admin_delete_item item_id")


@router.message(Command("admin_set_text"))
async def cmd_set_text(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        admin = await _admin(session, settings, message)
        header, body = (message.text or "").split("\n", 1)
        key = header.split(maxsplit=1)[1].strip()
        if key not in {"welcome_text", "support_text", "faq_text", "rules_text", "privacy_text", "terms_text"}:
            raise ValidationError("unsupported setting key")
        await set_setting_text(
            session,
            key=key,
            value=body.strip(),
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await message.answer("✅ Текст обновлен.")
    except (IndexError, ValueError, AppError):
        await message.answer("ℹ️ Формат: /admin_set_text welcome_text|support_text|faq_text|rules_text|privacy_text|terms_text\\nТекст")


@router.message(Command("admin_block_user"))
async def cmd_block_user(message: Message, session: AsyncSession, settings: Settings) -> None:
    await _block_command(message, session, settings, blocked=True)


@router.message(Command("admin_unblock_user"))
async def cmd_unblock_user(message: Message, session: AsyncSession, settings: Settings) -> None:
    await _block_command(message, session, settings, blocked=False)


async def _block_command(
    message: Message,
    session: AsyncSession,
    settings: Settings,
    *,
    blocked: bool,
) -> None:
    try:
        admin = await _admin(session, settings, message)
        parts = (message.text or "").split(maxsplit=2)
        user_id = int(parts[1])
        reason = parts[2] if len(parts) > 2 else None
        await set_user_block(
            session,
            user_id=user_id,
            blocked=blocked,
            reason=reason,
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await message.answer("✅ Готово.")
    except (ValueError, IndexError, AppError):
        await message.answer("ℹ️ Формат: /admin_block_user user_db_id причина")


@router.message(Command("admin_broadcast"))
async def cmd_broadcast(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        admin = await _admin(session, settings, message)
        header, body = (message.text or "").split("\n", 1)
        target_raw = header.split(maxsplit=1)[1].strip()
        target_type = target_raw
        product_id: int | None = None
        if target_raw.startswith("product:"):
            target_type = "product"
            product_id = int(target_raw.split(":", 1)[1])
        broadcast = await create_broadcast(
            session,
            target_type=target_type,
            product_id=product_id,
            text=body.strip(),
            admin_id=admin.id if admin else None,
        )
        broadcast = await run_broadcast(session, message.bot, broadcast.id)
        await message.answer(
            f"✅ Рассылка завершена. Отправлено: {broadcast.sent_count}, ошибок: {broadcast.error_count}"
        )
    except (ValueError, IndexError, AppError):
        await message.answer("ℹ️ Формат: /admin_broadcast all|buyers|product:id\\nТекст")
