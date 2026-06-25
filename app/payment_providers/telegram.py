from __future__ import annotations

from typing import Any

from aiogram import Bot
from aiogram.types import LabeledPrice
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.security import decimal_to_minor
from app.payment_providers.base import InvoiceRequest, PaymentProvider, PaymentResult
from app.services.orders import complete_successful_payment, validate_pre_checkout


class TelegramPaymentsProvider(PaymentProvider):
    name = "telegram"

    def __init__(self, bot: Bot, settings: Settings):
        self.bot = bot
        self.settings = settings

    async def create_invoice(self, request: InvoiceRequest) -> Any:
        minor_amount = decimal_to_minor(request.amount, request.currency)
        return await self.bot.send_invoice(
            chat_id=request.chat_id,
            title=request.title[:32],
            description=request.description[:255] or request.title,
            payload=request.payload,
            provider_token=self.settings.telegram_payment_provider_token,
            currency=request.currency,
            prices=[LabeledPrice(label=request.title[:32], amount=minor_amount)],
            start_parameter=f"order-{request.order_id}",
            need_email=False,
            need_phone_number=False,
            protect_content=True,
        )

    async def verify_payment(
        self,
        *,
        session: AsyncSession,
        payload: str,
        total_amount: int,
        currency: str,
    ) -> None:
        await validate_pre_checkout(
            session=session,
            settings=self.settings,
            payload=payload,
            total_amount=total_amount,
            currency=currency,
        )

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
        completed = await complete_successful_payment(
            session=session,
            settings=self.settings,
            payload=payload,
            total_amount=total_amount,
            currency=currency,
            telegram_payment_charge_id=telegram_payment_charge_id,
            provider_payment_charge_id=provider_payment_charge_id,
            raw_payload=raw_payload,
            provider_name=self.name,
        )
        return PaymentResult(
            order_id=completed.order.id,
            digital_item_values=[item.value for item in completed.digital_items],
            already_processed=completed.already_processed,
        )
