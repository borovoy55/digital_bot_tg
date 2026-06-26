from __future__ import annotations

from typing import Any

import structlog
from aiogram import Bot
from aiohttp import web
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.exceptions import AppError, SecurityError
from app.db.models import Order
from app.payment_providers.platega import PlategaPaymentsProvider

log = structlog.get_logger(__name__)


async def _send_paid_order(bot: Bot, session_factory: async_sessionmaker, result_order_id: int) -> None:
    async with session_factory() as session:
        order = await session.scalar(
            select(Order)
            .where(Order.id == result_order_id)
            .options(selectinload(Order.user), selectinload(Order.issued_items))
        )
        if order is None or order.user is None or not order.issued_items:
            raise AppError("paid order cannot be loaded for delivery")
        values = "\n".join(f"`{item.value}`" for item in order.issued_items)
        await bot.send_message(
            order.user.telegram_id,
            f"✅ Покупка оплачена.\n\n🔑 Ваши цифровые товары:\n{values}",
            parse_mode="Markdown",
        )


def create_platega_callback_handler(
    *,
    bot: Bot,
    settings: Settings,
    session_factory: async_sessionmaker,
) -> Any:
    provider = PlategaPaymentsProvider(settings)

    async def handle(request: web.Request) -> web.Response:
        try:
            provider.verify_webhook_headers(
                merchant_id=request.headers.get("X-MerchantId"),
                secret=request.headers.get("X-Secret"),
            )
            data = await request.json()
            if not isinstance(data, dict):
                raise AppError("Platega callback body must be a JSON object")
            async with session_factory() as session:
                result = await provider.handle_webhook(session=session, data=data)
            if result is not None and not result.already_processed:
                await _send_paid_order(bot, session_factory, result.order_id)
        except SecurityError as exc:
            log.warning("platega_callback_rejected", error=str(exc))
            return web.json_response({"ok": False, "error": "forbidden"}, status=403)
        except AppError as exc:
            log.warning("platega_callback_failed", error=str(exc))
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            log.exception("platega_callback_unexpected_error", error=str(exc))
            return web.json_response({"ok": False, "error": "internal error"}, status=500)
        return web.json_response({"ok": True})

    return handle


def register_platega_callback(
    app: web.Application,
    *,
    bot: Bot,
    settings: Settings,
    session_factory: async_sessionmaker,
) -> None:
    app.router.add_post(
        "/payments/platega/callback",
        create_platega_callback_handler(
            bot=bot,
            settings=settings,
            session_factory=session_factory,
        ),
    )
