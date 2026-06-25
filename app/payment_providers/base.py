from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class InvoiceRequest:
    chat_id: int
    title: str
    description: str
    payload: str
    currency: str
    amount: Decimal
    order_id: int


@dataclass(frozen=True)
class PaymentResult:
    order_id: int
    digital_item_values: list[str]
    already_processed: bool = False

    @property
    def digital_item_value(self) -> str:
        return self.digital_item_values[0]


class PaymentProvider(ABC):
    name: str

    @abstractmethod
    async def create_invoice(self, request: InvoiceRequest) -> Any:
        raise NotImplementedError

    @abstractmethod
    async def verify_payment(self, *, session: AsyncSession, payload: str, total_amount: int, currency: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def handle_successful_payment(
        self,
        *,
        session: AsyncSession,
        payload: str,
        total_amount: int,
        currency: str,
        telegram_payment_charge_id: str | None,
        provider_payment_charge_id: str | None,
        raw_payload: dict[str, Any],
    ) -> PaymentResult:
        raise NotImplementedError
