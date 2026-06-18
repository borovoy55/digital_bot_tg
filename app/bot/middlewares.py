from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings


class DependenciesMiddleware(BaseMiddleware):
    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession], redis: Redis | None):
        self.session_factory = session_factory
        self.redis = redis
        self.settings = get_settings()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        async with self.session_factory() as session:
            data["session"] = session
            data["redis"] = self.redis
            data["settings"] = self.settings
            return await handler(event, data)
