from __future__ import annotations

from datetime import datetime, timezone

from aiogram import Bot
from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Broadcast, BroadcastStatus, Order, OrderStatus, User


async def create_broadcast(
    session: AsyncSession,
    *,
    target_type: str,
    text: str,
    admin_id: int | None,
    product_id: int | None = None,
) -> Broadcast:
    broadcast = Broadcast(
        admin_id=admin_id,
        target_type=target_type,
        product_id=product_id,
        text=text,
        status=BroadcastStatus.DRAFT.value,
    )
    session.add(broadcast)
    await session.commit()
    await session.refresh(broadcast)
    return broadcast


async def _target_users(session: AsyncSession, broadcast: Broadcast) -> list[int]:
    if broadcast.target_type == "all":
        rows = await session.scalars(select(User.telegram_id).where(User.is_blocked.is_(False)))
        return list(rows)
    if broadcast.target_type == "buyers":
        rows = await session.scalars(
            select(distinct(User.telegram_id))
            .join(Order, Order.user_id == User.id)
            .where(Order.status == OrderStatus.PAID.value, User.is_blocked.is_(False))
        )
        return list(rows)
    if broadcast.target_type == "product" and broadcast.product_id is not None:
        rows = await session.scalars(
            select(distinct(User.telegram_id))
            .join(Order, Order.user_id == User.id)
            .where(
                Order.status == OrderStatus.PAID.value,
                Order.product_id == broadcast.product_id,
                User.is_blocked.is_(False),
            )
        )
        return list(rows)
    return []


async def run_broadcast(session: AsyncSession, bot: Bot, broadcast_id: int) -> Broadcast:
    broadcast = await session.get(Broadcast, broadcast_id, with_for_update=True)
    if broadcast is None:
        raise ValueError("broadcast not found")
    broadcast.status = BroadcastStatus.RUNNING.value
    await session.commit()

    sent = 0
    errors = 0
    for telegram_id in await _target_users(session, broadcast):
        try:
            await bot.send_message(telegram_id, broadcast.text)
            sent += 1
        except Exception:
            errors += 1
    broadcast.sent_count = sent
    broadcast.error_count = errors
    broadcast.status = BroadcastStatus.FINISHED.value
    broadcast.completed_at = datetime.now(timezone.utc)
    await session.commit()
    return broadcast
