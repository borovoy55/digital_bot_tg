from __future__ import annotations

import structlog
from aiogram import Router
from aiogram.types import Message, PreCheckoutQuery
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AppError, NoAvailableItems
from app.payment_providers.telegram import TelegramPaymentsProvider

router = Router()
log = structlog.get_logger(__name__)


@router.pre_checkout_query()
async def pre_checkout(
    query: PreCheckoutQuery,
    session: AsyncSession,
    settings: Settings,
) -> None:
    provider = TelegramPaymentsProvider(query.bot, settings)
    try:
        await provider.verify_payment(
            session=session,
            payload=query.invoice_payload,
            total_amount=query.total_amount,
            currency=query.currency,
        )
    except AppError as exc:
        await query.answer(ok=False, error_message=str(exc))
        return
    await query.answer(ok=True)


@router.message(lambda message: message.successful_payment is not None)
async def successful_payment(
    message: Message,
    session: AsyncSession,
    settings: Settings,
) -> None:
    payment = message.successful_payment
    if payment is None:
        return
    provider = TelegramPaymentsProvider(message.bot, settings)
    try:
        result = await provider.handle_successful_payment(
            session=session,
            payload=payment.invoice_payload,
            total_amount=payment.total_amount,
            currency=payment.currency,
            telegram_payment_charge_id=payment.telegram_payment_charge_id,
            provider_payment_charge_id=payment.provider_payment_charge_id,
            raw_payload=payment.model_dump(mode="json"),
        )
    except NoAvailableItems:
        log.error("paid_order_without_inventory", payload=payment.invoice_payload)
        await message.answer(
            "Оплата получена, но товар временно закончился. Администратор уже получил ошибку."
        )
        return
    except AppError as exc:
        log.warning("payment_processing_failed", error=str(exc), payload=payment.invoice_payload)
        await message.answer("Платеж не удалось обработать автоматически. Обратитесь в поддержку.")
        return

    prefix = "Код уже был выдан ранее" if result.already_processed else "Покупка оплачена"
    await message.answer(f"{prefix}.\n\nВаш цифровой товар:\n`{result.digital_item_value}`", parse_mode="Markdown")
