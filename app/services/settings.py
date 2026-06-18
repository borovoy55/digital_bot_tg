from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Setting
from app.services.audit import write_audit_log


async def get_setting_text(session: AsyncSession, key: str, default: str = "") -> str:
    setting = await session.get(Setting, key)
    if setting is None:
        return default
    return setting.value_text or default


async def set_setting_text(
    session: AsyncSession,
    *,
    key: str,
    value: str,
    actor_telegram_id: int,
    admin_id: int | None = None,
) -> None:
    setting = await session.get(Setting, key)
    old_value = setting.value_text if setting else None
    if setting is None:
        setting = Setting(key=key, value_text=value)
        session.add(setting)
    else:
        setting.value_text = value
    await write_audit_log(
        session,
        action="setting.update",
        entity_type="setting",
        entity_id=key,
        admin_id=admin_id,
        actor_telegram_id=actor_telegram_id,
        old_values={"value_text": old_value},
        new_values={"value_text": value},
    )
    await session.commit()


async def maintenance_enabled(session: AsyncSession, env_default: bool) -> bool:
    setting = await session.scalar(select(Setting).where(Setting.key == "maintenance_mode"))
    if setting is None or not setting.value:
        return env_default
    return bool(setting.value.get("enabled", env_default))
