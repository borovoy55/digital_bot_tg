from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog


async def write_audit_log(
    session: AsyncSession,
    *,
    action: str,
    entity_type: str,
    entity_id: Any | None = None,
    admin_id: int | None = None,
    actor_telegram_id: int | None = None,
    old_values: dict[str, Any] | None = None,
    new_values: dict[str, Any] | None = None,
) -> AuditLog:
    log = AuditLog(
        admin_id=admin_id,
        actor_telegram_id=actor_telegram_id,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        old_values=old_values,
        new_values=new_values,
    )
    session.add(log)
    return log
