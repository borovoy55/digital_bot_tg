from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.callbacks import MenuCb
from app.bot.keyboards import main_menu
from app.bot.utils import answer_or_edit
from app.core.config import Settings
from app.services.menu import DEFAULT_TEXTS, get_button_text, get_menu_button, get_menu_buttons
from app.services.settings import get_setting_text, maintenance_enabled
from app.services.users import get_or_create_user

router = Router()


def _user_mention(user_id: int, name: str) -> str:
    safe_name = escape(name)
    return f'<b><a href="tg://user?id={user_id}">{safe_name}</a></b>'


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
        await message.answer("🛠 Бот временно на техобслуживании.")
        return
    username = message.from_user.first_name or message.from_user.username or "друг"
    mention = _user_mention(message.from_user.id, username)
    default_welcome = (
        "Привет, {username}!\n\n"
        "Рады видеть тебя в магазине цифровых товаров. Здесь можно купить подарочные карты Apple "
        "по приятным ценам и сразу получить код после оплаты.\n\n"
        "Хороших покупок! ✨"
    )
    welcome = await get_setting_text(session, "welcome_text", default_welcome)
    welcome = escape(welcome).replace("{username}", mention)
    await message.answer(
        welcome,
        parse_mode="HTML",
        reply_markup=main_menu(await get_menu_buttons(session, visible_only=True)),
    )


@router.callback_query(MenuCb.filter(F.action == "home"))
async def menu_home(callback: CallbackQuery, session: AsyncSession, settings: Settings) -> None:
    if await maintenance_enabled(session, settings.maintenance_mode):
        await callback.answer("🛠 Бот временно на техобслуживании.", show_alert=True)
        return
    await answer_or_edit(
        callback,
        "🏠 Главное меню",
        reply_markup=main_menu(await get_menu_buttons(session, visible_only=True)),
    )
    await callback.answer()


@router.callback_query(MenuCb.filter(F.action.startswith("b_")))
async def menu_text(callback: CallbackQuery, callback_data: MenuCb, session: AsyncSession) -> None:
    button_id = callback_data.action.removeprefix("b_")
    try:
        button = await get_menu_button(session, button_id)
        text = await get_button_text(session, button)
    except Exception:
        key = f"{button_id}_text"
        text = await get_setting_text(session, key, DEFAULT_TEXTS.get(key, "Раздел пока не заполнен."))
    await answer_or_edit(
        callback,
        text,
        reply_markup=main_menu(await get_menu_buttons(session, visible_only=True)),
    )
    await callback.answer()


@router.callback_query(MenuCb.filter(F.action.in_({"support", "faq", "rules"})))
async def legacy_menu_text(callback: CallbackQuery, callback_data: MenuCb, session: AsyncSession) -> None:
    key = f"{callback_data.action}_text"
    text = await get_setting_text(session, key, DEFAULT_TEXTS.get(key, "Раздел пока не заполнен."))
    await answer_or_edit(
        callback,
        text,
        reply_markup=main_menu(await get_menu_buttons(session, visible_only=True)),
    )
    await callback.answer()
