from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AccessDenied, NotFoundError
from app.core.security import validate_text
from app.db.models import Admin, User, UserBan
from app.services.audit import write_audit_log


async def get_or_create_user(
    session: AsyncSession,
    *,
    telegram_id: int,
    username: str | None,
    first_name: str | None,
    last_name: str | None,
) -> User:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    now = datetime.now(timezone.utc)
    if user is None:
        user = User(
            telegram_id=telegram_id,
            username=username,
            first_name=first_name,
            last_name=last_name,
            registered_at=now,
            last_activity_at=now,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user

    user.username = username
    user.first_name = first_name
    user.last_name = last_name
    user.last_activity_at = now
    await session.commit()
    return user


async def touch_user(session: AsyncSession, telegram_id: int) -> None:
    await session.execute(
        update(User)
        .where(User.telegram_id == telegram_id)
        .values(last_activity_at=datetime.now(timezone.utc))
    )
    await session.commit()


async def get_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User | None:
    return await session.scalar(select(User).where(User.telegram_id == telegram_id))


async def require_user_by_telegram_id(session: AsyncSession, telegram_id: int) -> User:
    user = await get_user_by_telegram_id(session, telegram_id)
    if user is None:
        raise NotFoundError("user not found")
    return user


async def is_admin(session: AsyncSession, settings: Settings, telegram_id: int) -> bool:
    if telegram_id in settings.admin_ids:
        return True
    admin = await session.scalar(
        select(Admin).where(Admin.telegram_id == telegram_id, Admin.is_active.is_(True))
    )
    return admin is not None


async def require_admin(session: AsyncSession, settings: Settings, telegram_id: int) -> Admin | None:
    if telegram_id in settings.admin_ids:
        admin = await session.scalar(select(Admin).where(Admin.telegram_id == telegram_id))
        return admin
    admin = await session.scalar(
        select(Admin).where(Admin.telegram_id == telegram_id, Admin.is_active.is_(True))
    )
    if admin is None:
        raise AccessDenied("admin access required")
    return admin


async def set_user_block(
    session: AsyncSession,
    *,
    user_id: int,
    blocked: bool,
    reason: str | None,
    actor_telegram_id: int,
    admin_id: int | None = None,
) -> None:
    user = await session.get(User, user_id, with_for_update=True)
    if user is None:
        raise NotFoundError("user not found")
    reason = validate_text(reason or "", field="reason", max_length=2048, required=False)
    old = {"is_blocked": user.is_blocked}
    user.is_blocked = blocked
    if blocked:
        session.add(UserBan(user_id=user.id, admin_id=admin_id, reason=reason, is_active=True))
    else:
        active_bans = await session.scalars(
            select(UserBan).where(UserBan.user_id == user.id, UserBan.is_active.is_(True))
        )
        now = datetime.now(timezone.utc)
        for ban in active_bans:
            ban.is_active = False
            ban.ended_at = now
    await write_audit_log(
        session,
        action="user.block" if blocked else "user.unblock",
        entity_type="user",
        entity_id=user.id,
        admin_id=admin_id,
        actor_telegram_id=actor_telegram_id,
        old_values=old,
        new_values={"is_blocked": blocked, "reason": reason},
    )
    await session.commit()
