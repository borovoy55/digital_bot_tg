from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import Settings
from app.core.exceptions import (
    AccessDenied,
    NoAvailableItems,
    NotFoundError,
    PaymentError,
    SecurityError,
)
from app.core.security import (
    decimal_to_minor,
    make_nonce,
    make_order_payload,
    minor_to_decimal,
    parse_order_payload,
    verify_order_payload,
)
from app.db.models import (
    DigitalItem,
    DigitalItemStatus,
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
    User,
)
from app.services.catalog import ensure_product_can_be_bought


@dataclass(frozen=True)
class CompletedOrder:
    order: Order
    digital_items: list[DigitalItem]
    already_processed: bool = False

    @property
    def digital_item(self) -> DigitalItem:
        return self.digital_items[0]


async def create_pending_order(
    session: AsyncSession,
    *,
    settings: Settings,
    telegram_id: int,
    product_id: int,
    quantity: int = 1,
    payment_provider: str = "telegram",
) -> Order:
    if quantity < 1:
        raise PaymentError("quantity must be positive")
    async with session.begin():
        user = await session.scalar(
            select(User).where(User.telegram_id == telegram_id).with_for_update()
        )
        if user is None:
            raise NotFoundError("user not found")
        if user.is_blocked:
            raise AccessDenied("user is blocked")

        product = await ensure_product_can_be_bought(session, product_id, quantity=quantity)
        order = Order(
            user_id=user.id,
            product_id=product.id,
            category_id=product.category_id,
            subcategory_id=product.subcategory_id,
            amount=product.price * quantity,
            quantity=quantity,
            currency=product.currency,
            status=OrderStatus.PENDING.value,
            payment_provider=payment_provider,
        )
        session.add(order)
        await session.flush()
        nonce = make_nonce()
        order.payment_payload = make_order_payload(
            secret=settings.callback_secret,
            order_id=order.id,
            user_id=user.id,
            product_id=product.id,
            nonce=nonce,
        )
    await session.refresh(order)
    return order


async def _load_order_for_payment(session: AsyncSession, order_id: int, *, lock: bool) -> Order:
    stmt = (
        select(Order)
        .where(Order.id == order_id)
        .options(selectinload(Order.issued_items), selectinload(Order.user), selectinload(Order.product))
    )
    if lock:
        stmt = stmt.with_for_update()
    order = await session.scalar(stmt)
    if order is None:
        raise SecurityError("order not found for payment payload")
    return order


async def validate_pre_checkout(
    *,
    session: AsyncSession,
    settings: Settings,
    payload: str,
    total_amount: int,
    currency: str,
) -> None:
    parsed = parse_order_payload(payload)
    order = await _load_order_for_payment(session, parsed.order_id, lock=False)
    if order.payment_payload is None:
        raise SecurityError("order has no payment payload")
    verify_order_payload(
        secret=settings.callback_secret,
        payload=payload,
        order_id=order.id,
        user_id=order.user_id,
        product_id=order.product_id,
        stored_payload=order.payment_payload,
    )
    if order.status != OrderStatus.PENDING.value:
        raise PaymentError("order is not pending")
    if order.user.is_blocked:
        raise AccessDenied("user is blocked")
    if order.currency != currency:
        raise PaymentError("currency mismatch")
    if decimal_to_minor(order.amount, order.currency) != total_amount:
        raise PaymentError("amount mismatch")
    await ensure_product_can_be_bought(session, order.product_id, quantity=order.quantity)


async def _reserve_items(
    session: AsyncSession,
    *,
    product_id: int,
    order_id: int,
    user_id: int,
) -> list[DigitalItem]:
    order = await session.get(Order, order_id)
    quantity = order.quantity if order else 1
    stmt = (
        select(DigitalItem)
        .where(
            DigitalItem.product_id == product_id,
            DigitalItem.status == DigitalItemStatus.AVAILABLE.value,
        )
        .order_by(DigitalItem.id.asc())
        .limit(quantity)
        .with_for_update(skip_locked=True)
    )
    items = list(await session.scalars(stmt))
    if len(items) < quantity:
        raise NoAvailableItems("no available digital items")
    now = datetime.now(timezone.utc)
    for item in items:
        item.status = DigitalItemStatus.RESERVED.value
        item.order_id = order_id
        item.sold_to_user_id = user_id
        item.sold_at = now
    await session.flush()
    for item in items:
        item.status = DigitalItemStatus.SOLD.value
    return items


async def complete_successful_payment(
    *,
    session: AsyncSession,
    settings: Settings,
    payload: str,
    total_amount: int,
    currency: str,
    telegram_payment_charge_id: str | None,
    provider_payment_charge_id: str | None,
    raw_payload: dict[str, Any],
    provider_name: str = "telegram",
) -> CompletedOrder:
    parsed = parse_order_payload(payload)
    raise_after_commit: Exception | None = None
    items: list[DigitalItem] = []
    async with session.begin():
        order = await _load_order_for_payment(session, parsed.order_id, lock=True)
        if order.payment_payload is None:
            raise SecurityError("order has no payment payload")
        verify_order_payload(
            secret=settings.callback_secret,
            payload=payload,
            order_id=order.id,
            user_id=order.user_id,
            product_id=order.product_id,
            stored_payload=order.payment_payload,
        )

        if order.status == OrderStatus.PAID.value:
            if not order.issued_items:
                raise PaymentError("paid order has no issued item")
            return CompletedOrder(order=order, digital_items=list(order.issued_items), already_processed=True)
        if order.status != OrderStatus.PENDING.value:
            raise PaymentError("order is not pending")
        if order.currency != currency:
            order.status = OrderStatus.ERROR.value
            await session.flush()
            raise_after_commit = PaymentError("currency mismatch")

        expected_amount = decimal_to_minor(order.amount, order.currency)
        if raise_after_commit is None and expected_amount != total_amount:
            order.status = OrderStatus.ERROR.value
            await session.flush()
            raise_after_commit = PaymentError("amount mismatch")

        existing_payment = None
        if raise_after_commit is None and (telegram_payment_charge_id or provider_payment_charge_id):
            charge_conditions = []
            if telegram_payment_charge_id:
                charge_conditions.append(Payment.telegram_payment_charge_id == telegram_payment_charge_id)
            if provider_payment_charge_id:
                charge_conditions.append(Payment.provider_payment_charge_id == provider_payment_charge_id)
            existing_payment = await session.scalar(
                select(Payment).where(or_(*charge_conditions))
            )
        if raise_after_commit is None and existing_payment is not None and existing_payment.order_id != order.id:
            order.status = OrderStatus.ERROR.value
            await session.flush()
            raise_after_commit = SecurityError("payment charge id was already used by another order")

        if raise_after_commit is None:
            try:
                items = await _reserve_items(
                    session,
                    product_id=order.product_id,
                    order_id=order.id,
                    user_id=order.user_id,
                )
            except NoAvailableItems as exc:
                order.status = OrderStatus.ERROR.value
                await session.flush()
                raise_after_commit = exc

        if raise_after_commit is None:
            assert items
            paid_at = datetime.now(timezone.utc)
            order.status = OrderStatus.PAID.value
            order.paid_at = paid_at
            order.telegram_payment_charge_id = telegram_payment_charge_id
            order.provider_payment_charge_id = provider_payment_charge_id

            if existing_payment is None:
                session.add(
                    Payment(
                        order_id=order.id,
                        provider=provider_name,
                        status=PaymentStatus.SUCCEEDED.value,
                        amount=minor_to_decimal(total_amount, currency),
                        currency=currency,
                        telegram_payment_charge_id=telegram_payment_charge_id,
                        provider_payment_charge_id=provider_payment_charge_id,
                        raw_payload=raw_payload,
                    )
                )
    if raise_after_commit is not None:
        raise raise_after_commit
    assert items
    await session.refresh(order)
    for item in items:
        await session.refresh(item)
    return CompletedOrder(order=order, digital_items=items)


async def complete_external_successful_payment(
    *,
    session: AsyncSession,
    settings: Settings,
    payload: str,
    provider_name: str,
    provider_payment_charge_id: str | None,
    raw_payload: dict[str, Any],
    amount: int | None = None,
    currency: str | None = None,
) -> CompletedOrder:
    parsed = parse_order_payload(payload)
    order = await _load_order_for_payment(session, parsed.order_id, lock=False)
    total_amount = amount if amount is not None else decimal_to_minor(order.amount, order.currency)
    payment_currency = currency or order.currency
    return await complete_successful_payment(
        session=session,
        settings=settings,
        payload=payload,
        total_amount=total_amount,
        currency=payment_currency,
        telegram_payment_charge_id=None,
        provider_payment_charge_id=provider_payment_charge_id,
        raw_payload=raw_payload,
        provider_name=provider_name,
    )


async def mark_external_payment_not_confirmed(
    *,
    session: AsyncSession,
    settings: Settings,
    payload: str,
    status: str,
) -> Order:
    parsed = parse_order_payload(payload)
    async with session.begin():
        order = await _load_order_for_payment(session, parsed.order_id, lock=True)
        if order.payment_payload is None:
            raise SecurityError("order has no payment payload")
        verify_order_payload(
            secret=settings.callback_secret,
            payload=payload,
            order_id=order.id,
            user_id=order.user_id,
            product_id=order.product_id,
            stored_payload=order.payment_payload,
        )
        if status == "CANCELED" and order.status == OrderStatus.PENDING.value:
            order.status = OrderStatus.CANCELLED.value
        elif status == "CHARGEBACK" and order.status == OrderStatus.PAID.value:
            order.status = OrderStatus.REFUNDED.value
        await session.flush()
    await session.refresh(order)
    return order


async def get_order_for_user(
    session: AsyncSession,
    *,
    telegram_id: int,
    order_id: int,
) -> Order:
    order = await session.scalar(
        select(Order)
        .join(User, User.id == Order.user_id)
        .where(Order.id == order_id, User.telegram_id == telegram_id)
        .options(selectinload(Order.product), selectinload(Order.issued_items))
    )
    if order is None:
        raise AccessDenied("order not found")
    return order


async def list_user_orders(session: AsyncSession, *, telegram_id: int, limit: int = 20) -> list[Order]:
    rows = await session.scalars(
        select(Order)
        .join(User, User.id == Order.user_id)
        .where(User.telegram_id == telegram_id)
        .options(selectinload(Order.product), selectinload(Order.issued_items))
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    return list(rows)
