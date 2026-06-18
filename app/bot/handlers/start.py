from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import MenuCb
from app.bot.keyboards import main_menu
from app.bot.utils import answer_or_edit
from app.core.config import Settings
from app.services.settings import get_setting_text, maintenance_enabled
from app.services.users import get_or_create_user

router = Router()


@router.message(CommandStart())
async def cmd_start(message: Message, session: AsyncSession, settings: Settings) -> None:
    if message.from_user is None:
        return
    await get_or_create_user(
        session,
        telegram_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        last_name=message.from_user.last_name,
    )
    if await maintenance_enabled(session, settings.maintenance_mode):
        await message.answer("Бот временно на техобслуживании.")
        return
    await message.answer("Главное меню", reply_markup=main_menu())


@router.callback_query(MenuCb.filter(F.action == "home"))
async def menu_home(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    if await maintenance_enabled(session, settings.maintenance_mode):
        await callback.answer("Бот временно на техобслуживании.", show_alert=True)
        return
    await answer_or_edit(callback, "Главное меню", reply_markup=main_menu())
    await callback.answer()


@router.callback_query(MenuCb.filter(F.action.in_({"support", "faq", "rules"})))
async def menu_text(callback: CallbackQuery, callback_data: MenuCb, session: AsyncSession) -> None:
    key_map = {
        "support": "support_text",
        "faq": "faq_text",
        "rules": "rules_text",
    }
    default_map = {
        "support": "Поддержка: напишите администратору.",
        "faq": "FAQ пока не заполнен.",
        "rules": "Правила пока не заполнены.",
    }
    text = await get_setting_text(
        session, key_map[callback_data.action], default_map[callback_data.action]
    )
    await answer_or_edit(callback, text, reply_markup=main_menu())
    await callback.answer()
