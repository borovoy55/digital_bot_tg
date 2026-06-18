from __future__ import annotations

from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, Message
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import AdminCb
from app.bot.keyboards import admin_back, admin_menu, admin_order_keyboard, admin_orders_keyboard
from app.bot.utils import answer_or_edit
from app.core.config import Settings
from app.core.exceptions import AccessDenied, AppError, ValidationError
from app.core.security import parse_items_csv, parse_items_text
from app.db.models import Category, DigitalItem, Product, Subcategory, User
from app.services.admin import (
    create_category,
    create_product,
    create_subcategory,
    dashboard_stats,
    get_order_detail,
    list_recent_orders,
    set_entity_active,
    soft_delete_entity,
    update_entity_sort_order,
    update_entity_title,
    update_order_comment,
    update_order_status,
    update_product_price,
)
from app.services.broadcasts import create_broadcast, run_broadcast
from app.services.digital_items import (
    delete_digital_item,
    export_digital_items_csv,
    import_digital_items,
    search_digital_items,
    update_digital_item_value,
)
from app.services.settings import set_setting_text
from app.services.users import require_admin, set_user_block

router = Router()


async def _admin(session: AsyncSession, settings: Settings, message_or_callback: Message | CallbackQuery):
    user = message_or_callback.from_user
    if user is None:
        raise AccessDenied("admin access required")
    return await require_admin(session, settings, user.id)


@router.message(Command("admin"))
async def admin_command(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        await _admin(session, settings, message)
    except AccessDenied:
        await message.answer("Нет доступа.")
        return
    await message.answer("Админ-панель", reply_markup=admin_menu())


@router.callback_query(AdminCb.filter(F.action == "home"))
async def admin_home(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    try:
        await _admin(session, settings, callback)
    except AccessDenied:
        await callback.answer("Нет доступа.", show_alert=True)
        return
    await answer_or_edit(callback, "Админ-панель", reply_markup=admin_menu())
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
            "Статистика",
            f"Общая выручка: {stats.total_revenue}",
            f"Сегодня: {stats.today_revenue}",
            f"7 дней: {stats.week_revenue}",
            f"30 дней: {stats.month_revenue}",
            f"Заказов всего: {stats.orders_total}",
            f"Успешных: {stats.orders_success}",
            f"Отмененных: {stats.orders_cancelled}",
            f"Ошибочных: {stats.orders_error}",
            f"Средний чек: {stats.average_check:.2f}",
            f"Кодов доступно: {stats.available_items}",
            f"Кодов продано: {stats.sold_items}",
            "",
            "Топ товаров:",
            *[f"{title}: {count} / {amount}" for title, count, amount in stats.top_products],
            "",
            "Топ категорий:",
            *[f"{title}: {count} / {amount}" for title, count, amount in stats.top_categories],
            "",
            "Топ покупателей:",
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
        text = "Последние заказы\n\n" + "\n".join(
            f"#{o.id} · {o.status} · {o.amount} {o.currency} · @{o.user.username or o.user.telegram_id}"
            for o in orders
        )
        await answer_or_edit(callback, text or "Заказов нет.", reply_markup=admin_orders_keyboard(o.id for o in orders))
    elif entity == "users":
        users = list(
            await session.scalars(select(User).order_by(User.last_activity_at.desc()).limit(15))
        )
        text = "Пользователи\n\n" + "\n".join(
            f"{u.id}: {u.telegram_id} @{u.username or '-'} blocked={u.is_blocked}" for u in users
        )
        await answer_or_edit(callback, text, reply_markup=admin_back())
    elif entity == "cats":
        cats = list(await session.scalars(select(Category).order_by(Category.sort_order, Category.id)))
        await answer_or_edit(
            callback,
            "Категории\n\n" + "\n".join(f"{c.id}: {c.title} active={c.is_active}" for c in cats),
            reply_markup=admin_back(),
        )
    elif entity == "subs":
        subs = list(await session.scalars(select(Subcategory).order_by(Subcategory.sort_order, Subcategory.id)))
        await answer_or_edit(
            callback,
            "Подкатегории\n\n"
            + "\n".join(f"{s.id}: cat={s.category_id} {s.title} active={s.is_active}" for s in subs),
            reply_markup=admin_back(),
        )
    elif entity == "products":
        products = list(await session.scalars(select(Product).order_by(Product.sort_order, Product.id)))
        await answer_or_edit(
            callback,
            "Товары\n\n"
            + "\n".join(
                f"{p.id}: cat={p.category_id} sub={p.subcategory_id} {p.title} "
                f"{p.price} {p.currency} active={p.is_active}"
                for p in products
            ),
            reply_markup=admin_back(),
        )
    elif entity == "items":
        rows = await session.execute(
            select(DigitalItem.product_id, DigitalItem.status, func.count(DigitalItem.id))
            .group_by(DigitalItem.product_id, DigitalItem.status)
            .order_by(DigitalItem.product_id)
        )
        await answer_or_edit(
            callback,
            "Остатки цифровых товаров\n\n"
            + "\n".join(f"product={p} {status}: {count}" for p, status, count in rows),
            reply_markup=admin_back(),
        )
    else:
        await answer_or_edit(callback, "Раздел пока пуст.", reply_markup=admin_back())
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
    item_value = order.issued_item.value if order.issued_item else "-"
    payment_id = order.payments[0].id if order.payments else "-"
    text = "\n".join(
        [
            f"Заказ #{order.id}",
            f"Пользователь: {order.user.id}",
            f"telegram_id: {order.user.telegram_id}",
            f"username: @{order.user.username or '-'}",
            f"Товар: {order.product.title}",
            f"category_id: {order.category_id}",
            f"subcategory_id: {order.subcategory_id}",
            f"Сумма: {order.amount} {order.currency}",
            f"Статус: {order.status}",
            f"Создан: {order.created_at}",
            f"Оплачен: {order.paid_at or '-'}",
            f"payment_id: {payment_id}",
            f"telegram_payment_charge_id: {order.telegram_payment_charge_id or '-'}",
            f"provider_payment_charge_id: {order.provider_payment_charge_id or '-'}",
            f"Код: `{item_value}`",
        ]
    )
    await answer_or_edit(
        callback,
        text,
        reply_markup=admin_order_keyboard(order.id, has_item=order.issued_item is not None),
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
        if order.issued_item is None:
            raise ValidationError("У заказа нет выданного кода.")
        await callback.bot.send_message(
            order.user.telegram_id,
            f"Повторная отправка цифрового товара по заказу #{order.id}:\n`{order.issued_item.value}`",
            parse_mode="Markdown",
        )
    except AppError as exc:
        await callback.answer(str(exc), show_alert=True)
        return
    await callback.answer("Код отправлен.")


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
        await message.answer("Статус заказа обновлен.")
    except (ValueError, IndexError, AppError):
        await message.answer("Формат: /admin_set_order_status order_id pending|paid|cancelled|error|refunded")


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
        await message.answer("Комментарий к заказу обновлен.")
    except (ValueError, IndexError, AppError):
        await message.answer("Формат: /admin_comment_order order_id комментарий")


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
        await message.answer(f"Категория создана: {category.id}")
    except (IndexError, AppError):
        await message.answer("Формат: /admin_create_category Название")


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
        await message.answer(f"Подкатегория создана: {subcategory.id}")
    except (ValueError, IndexError, AppError):
        await message.answer("Формат: /admin_create_subcategory category_id Название")


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
        await message.answer(f"Товар создан: {product.id}")
    except (ValueError, IndexError, AppError):
        await message.answer(
            "Формат: /admin_create_product category_id subcategory_id | Название | 100.00 | RUB | Описание"
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
        await message.answer("Статус изменен.")
    except (ValueError, IndexError, AppError):
        await message.answer("Формат: /admin_set_active category|subcategory|product id true|false")


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
        await message.answer("Название обновлено.")
    except (ValueError, IndexError, AppError):
        await message.answer("Формат: /admin_rename category|subcategory|product id Новое название")


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
        await message.answer("Сортировка обновлена.")
    except (ValueError, IndexError, AppError):
        await message.answer("Формат: /admin_sort category|subcategory|product id sort_order")


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
        await message.answer("Сущность отключена и отмечена в audit log.")
    except (ValueError, IndexError, AppError):
        await message.answer("Формат: /admin_delete_entity category|subcategory|product id")


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
        await message.answer("Цена обновлена.")
    except (ValueError, IndexError, AppError):
        await message.answer("Формат: /admin_update_price product_id 100.00")


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
                    "Импорт завершен",
                    f"Обработано: {result.processed + parse_errors}",
                    f"Добавлено: {result.added}",
                    f"Пропущено: {result.skipped}",
                    f"Дублей: {result.duplicates}",
                    f"Ошибок: {result.errors + parse_errors}",
                ]
            )
        )
    except (ValueError, IndexError, AppError):
        await message.answer("Формат: /admin_upload_items product_id\\ncode1\\ncode2 или документ .txt/.csv с caption")


@router.message(Command("admin_export_items"))
async def cmd_export_items(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        await _admin(session, settings, message)
        product_id = int(message.text.split(maxsplit=1)[1])
        content = await export_digital_items_csv(session, product_id=product_id)
        file = BufferedInputFile(content.encode("utf-8"), filename=f"product-{product_id}-items.csv")
        await message.answer_document(file)
    except (ValueError, IndexError, AppError):
        await message.answer("Формат: /admin_export_items product_id")


@router.message(Command("admin_search_items"))
async def cmd_search_items(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        await _admin(session, settings, message)
        query = message.text.split(maxsplit=1)[1]
        items = await search_digital_items(session, query=query, limit=20)
        if not items:
            await message.answer("Ничего не найдено.")
            return
        await message.answer(
            "Найденные коды\n\n"
            + "\n".join(
                f"{item.id}: product={item.product_id} status={item.status} value={item.value[:80]}"
                for item in items
            )
        )
    except (ValueError, IndexError, AppError):
        await message.answer("Формат: /admin_search_items часть_кода")


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
        await message.answer(f"Код обновлен: {item.id}")
    except (ValueError, IndexError, AppError):
        await message.answer("Формат: /admin_update_item item_id новое_значение")


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
        await message.answer("Код удален.")
    except (ValueError, IndexError, AppError):
        await message.answer("Формат: /admin_delete_item item_id")


@router.message(Command("admin_set_text"))
async def cmd_set_text(message: Message, session: AsyncSession, settings: Settings) -> None:
    try:
        admin = await _admin(session, settings, message)
        header, body = (message.text or "").split("\n", 1)
        key = header.split(maxsplit=1)[1].strip()
        if key not in {"support_text", "faq_text", "rules_text"}:
            raise ValidationError("unsupported setting key")
        await set_setting_text(
            session,
            key=key,
            value=body.strip(),
            actor_telegram_id=message.from_user.id,
            admin_id=admin.id if admin else None,
        )
        await message.answer("Текст обновлен.")
    except (IndexError, ValueError, AppError):
        await message.answer("Формат: /admin_set_text support_text|faq_text|rules_text\\nТекст")


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
        await message.answer("Готово.")
    except (ValueError, IndexError, AppError):
        await message.answer("Формат: /admin_block_user user_db_id причина")


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
            f"Рассылка завершена. Отправлено: {broadcast.sent_count}, ошибок: {broadcast.error_count}"
        )
    except (ValueError, IndexError, AppError):
        await message.answer("Формат: /admin_broadcast all|buyers|product:id\\nТекст")
