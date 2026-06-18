from __future__ import annotations

import asyncio

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web
from redis.asyncio import Redis

from app.bot.middlewares import DependenciesMiddleware
from app.bot.router import build_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.rate_limit import RedisRateLimitMiddleware
from app.db.base import Base
from app.db.session import engine, session_factory


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)

    if settings.create_tables_on_startup:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    bot = Bot(token=settings.bot_token)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    dispatcher = Dispatcher()
    dispatcher.update.middleware(DependenciesMiddleware(session_factory=session_factory, redis=redis))
    dispatcher.message.middleware(
        RedisRateLimitMiddleware(
            redis,
            limit=settings.rate_limit_messages_per_minute,
            window_seconds=60,
            key_prefix="rl:msg",
        )
    )
    dispatcher.callback_query.middleware(
        RedisRateLimitMiddleware(
            redis,
            limit=settings.rate_limit_callbacks_per_minute,
            window_seconds=60,
            key_prefix="rl:cb",
        )
    )
    dispatcher.include_router(build_router())

    if settings.webhook_mode:
        if not settings.webhook_url:
            raise RuntimeError("WEBHOOK_URL is required when WEBHOOK_MODE=true")
        app = web.Application()
        SimpleRequestHandler(dispatcher=dispatcher, bot=bot).register(app, path="/telegram/webhook")
        setup_application(app, dispatcher, bot=bot)
        await bot.set_webhook(settings.webhook_url)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host=settings.webhook_host, port=settings.webhook_port)
        await site.start()
        await asyncio.Event().wait()
        return

    await bot.delete_webhook(drop_pending_updates=True)
    await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())


if __name__ == "__main__":
    asyncio.run(main())
