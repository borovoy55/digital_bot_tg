from __future__ import annotations

from aiogram.exceptions import TelegramBadRequest
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message


async def answer_or_edit(
    target: Message | CallbackQuery,
    text: str,
    reply_markup: InlineKeyboardMarkup | None = None,
) -> None:
    if isinstance(target, CallbackQuery):
        if target.message:
            try:
                await target.message.edit_text(text, reply_markup=reply_markup)
                return
            except TelegramBadRequest:
                await target.message.answer(text, reply_markup=reply_markup)
                return
        await target.answer(text, show_alert=True)
        return
    await target.answer(text, reply_markup=reply_markup)


def money(value: object, currency: str) -> str:
    return f"{value} {currency}"
