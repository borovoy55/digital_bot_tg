from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError, ValidationError
from app.core.security import csv_rows, deduplicate_preserve_order, normalize_digital_item
from app.db.models import DigitalItem, DigitalItemStatus
from app.services.audit import write_audit_log


@dataclass(frozen=True)
class ImportResult:
    processed: int
    added: int
    skipped: int
    duplicates: int
    errors: int


async def import_digital_items(
    session: AsyncSession,
    *,
    product_id: int,
    raw_values: Iterable[str],
    actor_telegram_id: int,
    admin_id: int | None = None,
) -> ImportResult:
    normalized: list[str] = []
    errors = 0
    processed = 0
    for raw in raw_values:
        processed += 1
        try:
            normalized.append(normalize_digital_item(raw))
        except Exception:
            errors += 1

    unique_values, file_duplicates = deduplicate_preserve_order(normalized)
    existing_values = set()
    if unique_values:
        existing = await session.scalars(
            select(DigitalItem.value).where(
                DigitalItem.product_id == product_id,
                DigitalItem.value.in_(unique_values),
            )
        )
        existing_values = set(existing)

    added = 0
    for value in unique_values:
        if value in existing_values:
            continue
        session.add(
            DigitalItem(
                product_id=product_id,
                value=value,
                status=DigitalItemStatus.AVAILABLE.value,
                uploaded_by_admin_id=admin_id,
            )
        )
        added += 1

    skipped = processed - added - errors
    await write_audit_log(
        session,
        action="digital_items.import",
        entity_type="product",
        entity_id=product_id,
        admin_id=admin_id,
        actor_telegram_id=actor_telegram_id,
        new_values={
            "processed": processed,
            "added": added,
            "skipped": skipped,
            "duplicates": file_duplicates + len(existing_values),
            "errors": errors,
        },
    )
    await session.commit()
    return ImportResult(
        processed=processed,
        added=added,
        skipped=skipped,
        duplicates=file_duplicates + len(existing_values),
        errors=errors,
    )


async def search_digital_items(
    session: AsyncSession,
    *,
    query: str,
    product_id: int | None = None,
    limit: int = 20,
) -> list[DigitalItem]:
    stmt = select(DigitalItem).where(DigitalItem.value.ilike(f"%{query[:128]}%"))
    if product_id is not None:
        stmt = stmt.where(DigitalItem.product_id == product_id)
    rows = await session.scalars(stmt.order_by(DigitalItem.id.desc()).limit(limit))
    return list(rows)


async def update_digital_item_value(
    session: AsyncSession,
    *,
    item_id: int,
    value: str,
    actor_telegram_id: int,
    admin_id: int | None = None,
) -> DigitalItem:
    item = await session.get(DigitalItem, item_id, with_for_update=True)
    if item is None:
        raise NotFoundError("digital item not found")
    new_value = normalize_digital_item(value)
    duplicate = await session.scalar(
        select(DigitalItem).where(
            DigitalItem.product_id == item.product_id,
            DigitalItem.value == new_value,
            DigitalItem.id != item.id,
        )
    )
    if duplicate is not None:
        raise ValidationError("duplicate digital item")
    old_value = item.value
    item.value = new_value
    await write_audit_log(
        session,
        action="digital_items.update",
        entity_type="digital_item",
        entity_id=item.id,
        admin_id=admin_id,
        actor_telegram_id=actor_telegram_id,
        old_values={"value": old_value},
        new_values={"value": new_value},
    )
    await session.commit()
    return item


async def delete_digital_item(
    session: AsyncSession,
    *,
    item_id: int,
    actor_telegram_id: int,
    admin_id: int | None = None,
) -> DigitalItem:
    item = await session.get(DigitalItem, item_id, with_for_update=True)
    if item is None:
        raise NotFoundError("digital item not found")
    old = {"status": item.status}
    item.status = DigitalItemStatus.DELETED.value
    await write_audit_log(
        session,
        action="digital_items.delete",
        entity_type="digital_item",
        entity_id=item.id,
        admin_id=admin_id,
        actor_telegram_id=actor_telegram_id,
        old_values=old,
        new_values={"status": item.status},
    )
    await session.commit()
    return item


async def export_digital_items_csv(
    session: AsyncSession,
    *,
    product_id: int,
) -> str:
    rows = await session.scalars(
        select(DigitalItem)
        .where(DigitalItem.product_id == product_id)
        .order_by(DigitalItem.id.asc())
    )
    data = [["id", "product_id", "value", "status", "order_id", "sold_to_user_id", "sold_at"]]
    for item in rows:
        data.append(
            [
                str(item.id),
                str(item.product_id),
                item.value,
                item.status,
                str(item.order_id or ""),
                str(item.sold_to_user_id or ""),
                item.sold_at.isoformat() if item.sold_at else "",
            ]
        )
    return csv_rows(data)
