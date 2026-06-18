from __future__ import annotations

from aiogram import Router
from aiogram.types import CallbackQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import PurchasesCb
from app.bot.keyboards import purchases_keyboard
from app.bot.utils import answer_or_edit
from app.db.models import OrderStatus
from app.services.orders import list_user_orders

router = Router()


@router.callback_query(PurchasesCb.filter())
async def my_purchases(
    callback: CallbackQuery,
    session: AsyncSession,
) -> None:
    orders = await list_user_orders(session, telegram_id=callback.from_user.id, limit=20)
    if not orders:
        await answer_or_edit(callback, "Покупок пока нет.", reply_markup=purchases_keyboard())
        await callback.answer()
        return
    parts = ["Мои покупки"]
    for order in orders:
        issued = order.issued_item.value if order.issued_item else "-"
        if order.status != OrderStatus.PAID.value:
            issued = "-"
        parts.append(
            "\n".join(
                [
                    f"#{order.id} · {order.created_at:%Y-%m-%d %H:%M}",
                    f"Товар: {order.product.title}",
                    f"Цена: {order.amount} {order.currency}",
                    f"Статус: {order.status}",
                    f"Код: `{issued}`",
                ]
            )
        )
    await answer_or_edit(callback, "\n\n".join(parts), reply_markup=purchases_keyboard())
    await callback.answer()
