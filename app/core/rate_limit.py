from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from redis.asyncio import Redis


class RedisRateLimitMiddleware(BaseMiddleware):
    def __init__(self, redis: Redis | None, *, limit: int, window_seconds: int, key_prefix: str):
        self.redis = redis
        self.limit = limit
        self.window_seconds = window_seconds
        self.key_prefix = key_prefix

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if self.redis is None:
            return await handler(event, data)

        telegram_id = None
        if isinstance(event, Message) and event.from_user:
            telegram_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            telegram_id = event.from_user.id
        if telegram_id is None:
            return await handler(event, data)

        key = f"{self.key_prefix}:{telegram_id}"
        count = await self.redis.incr(key)
        if count == 1:
            await self.redis.expire(key, self.window_seconds)
        if count > self.limit:
            if isinstance(event, CallbackQuery):
                await event.answer("Слишком много действий. Попробуйте чуть позже.", show_alert=True)
            elif isinstance(event, Message):
                await event.answer("Слишком много сообщений. Попробуйте чуть позже.")
            return None
        return await handler(event, data)


async def check_order_rate_limit(
    redis: Redis | None,
    *,
    telegram_id: int,
    limit: int,
    window_seconds: int = 3600,
) -> bool:
    if redis is None:
        return True
    key = f"orders:{telegram_id}"
    count = await redis.incr(key)
    if count == 1:
        await redis.expire(key, window_seconds)
    return count <= limit
