from __future__ import annotations

import os
import unittest
from decimal import Decimal

try:
    import pytest
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
except ModuleNotFoundError as exc:  # pragma: no cover - local dependency-free smoke runs.
    raise unittest.SkipTest(f"PostgreSQL security tests require dev dependencies: {exc}") from exc

from app.core.config import Settings
from app.core.exceptions import AccessDenied, NoAvailableItems
from app.core.security import decimal_to_minor
from app.db.base import Base
from app.db.models import (
    Category,
    DigitalItem,
    DigitalItemStatus,
    Order,
    Product,
    Subcategory,
    User,
)
from app.services.orders import (
    complete_successful_payment,
    create_pending_order,
    get_order_for_user,
)

pytestmark = pytest.mark.postgres

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")


def test_database_url() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    return TEST_DATABASE_URL


async def make_session_factory():
    engine = create_async_engine(test_database_url(), pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


def make_settings() -> Settings:
    return Settings(
        BOT_TOKEN="1:test",
        DATABASE_URL=test_database_url(),
        CALLBACK_SECRET="x" * 32,
        TELEGRAM_PAYMENT_PROVIDER_TOKEN="provider",
    )


async def seed_product(session_factory, *, codes: list[str]) -> tuple[int, int, int]:
    async with session_factory() as session:
        user1 = User(telegram_id=1001, username="u1")
        user2 = User(telegram_id=1002, username="u2")
        category = Category(title="Cat")
        session.add_all([user1, user2, category])
        await session.flush()
        subcategory = Subcategory(category_id=category.id, title="Sub")
        session.add(subcategory)
        await session.flush()
        product = Product(
            category_id=category.id,
            subcategory_id=subcategory.id,
            title="Product",
            description="Test",
            price=Decimal("10.00"),
            currency="RUB",
        )
        session.add(product)
        await session.flush()
        for code in codes:
            session.add(
                DigitalItem(
                    product_id=product.id,
                    value=code,
                    status=DigitalItemStatus.AVAILABLE.value,
                )
            )
        await session.commit()
        return user1.telegram_id, user2.telegram_id, product.id


async def test_double_sale_only_one_order_gets_single_code() -> None:
    engine, session_factory = await make_session_factory()
    settings = make_settings()
    user1, user2, product_id = await seed_product(session_factory, codes=["ONLY-CODE"])
    async with session_factory() as session:
        order1 = await create_pending_order(session, settings=settings, telegram_id=user1, product_id=product_id)
    async with session_factory() as session:
        order2 = await create_pending_order(session, settings=settings, telegram_id=user2, product_id=product_id)

    async def pay(order: Order, charge: str) -> str:
        async with session_factory() as session:
            try:
                result = await complete_successful_payment(
                    session=session,
                    settings=settings,
                    payload=order.payment_payload,
                    total_amount=decimal_to_minor(order.amount, order.currency),
                    currency=order.currency,
                    telegram_payment_charge_id=charge,
                    provider_payment_charge_id=charge,
                    raw_payload={"charge": charge},
                )
                return result.digital_item.value
            except NoAvailableItems:
                return "NO-STOCK"

    values = sorted([await pay(order1, "charge-1"), await pay(order2, "charge-2")])
    assert values == ["NO-STOCK", "ONLY-CODE"]
    async with session_factory() as session:
        sold = list(
            await session.scalars(
                select(DigitalItem).where(DigitalItem.status == DigitalItemStatus.SOLD.value)
            )
        )
        assert len(sold) == 1
    await engine.dispose()


async def test_repeated_successful_payment_is_idempotent() -> None:
    engine, session_factory = await make_session_factory()
    settings = make_settings()
    user1, _, product_id = await seed_product(session_factory, codes=["A", "B"])
    async with session_factory() as session:
        order = await create_pending_order(session, settings=settings, telegram_id=user1, product_id=product_id)

    async with session_factory() as session:
        first = await complete_successful_payment(
            session=session,
            settings=settings,
            payload=order.payment_payload,
            total_amount=decimal_to_minor(order.amount, order.currency),
            currency=order.currency,
            telegram_payment_charge_id="charge-repeat",
            provider_payment_charge_id="provider-repeat",
            raw_payload={},
        )
    async with session_factory() as session:
        second = await complete_successful_payment(
            session=session,
            settings=settings,
            payload=order.payment_payload,
            total_amount=decimal_to_minor(order.amount, order.currency),
            currency=order.currency,
            telegram_payment_charge_id="charge-repeat",
            provider_payment_charge_id="provider-repeat",
            raw_payload={},
        )
    assert first.digital_item.value == second.digital_item.value
    assert second.already_processed is True
    await engine.dispose()


async def test_foreign_order_access_denied() -> None:
    engine, session_factory = await make_session_factory()
    settings = make_settings()
    user1, user2, product_id = await seed_product(session_factory, codes=["CODE"])
    async with session_factory() as session:
        order = await create_pending_order(session, settings=settings, telegram_id=user1, product_id=product_id)
    async with session_factory() as session:
        with pytest.raises(AccessDenied):
            await get_order_for_user(session, telegram_id=user2, order_id=order.id)
    await engine.dispose()
