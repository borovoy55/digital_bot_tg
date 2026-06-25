from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from aiohttp import ClientSession, ClientTimeout
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import PaymentError, SecurityError
from app.core.security import decimal_to_minor
from app.payment_providers.base import InvoiceRequest, PaymentResult
from app.services.orders import (
    complete_external_successful_payment,
    mark_external_payment_not_confirmed,
)


@dataclass(frozen=True)
class PlategaInvoice:
    order_id: int
    transaction_id: str
    redirect_url: str
    status: str
    raw_payload: dict[str, Any]


class PlategaPaymentsProvider:
    name = "platega"

    def __init__(self, settings: Settings):
        self.settings = settings

    def _headers(self) -> dict[str, str]:
        if not self.settings.platega_merchant_id or not self.settings.platega_api_key:
            raise PaymentError("Platega credentials are not configured")
        return {
            "Content-Type": "application/json",
            "X-MerchantId": self.settings.platega_merchant_id,
            "X-Secret": self.settings.platega_api_key,
        }

    def _endpoint(self) -> str:
        base_url = self.settings.platega_base_url.rstrip("/")
        if self.settings.platega_payment_method is None:
            return f"{base_url}/v2/transaction/process"
        return f"{base_url}/transaction/process"

    async def create_invoice(self, request: InvoiceRequest) -> PlategaInvoice:
        body: dict[str, Any] = {
            "paymentDetails": {
                "amount": float(request.amount),
                "currency": request.currency,
            },
            "description": request.description or request.title,
            "payload": request.payload,
        }
        if self.settings.platega_payment_method is not None:
            body["paymentMethod"] = self.settings.platega_payment_method
        if self.settings.platega_return_url:
            body["return"] = self.settings.platega_return_url
        if self.settings.platega_failed_url:
            body["failedUrl"] = self.settings.platega_failed_url

        timeout = ClientTimeout(total=30)
        async with ClientSession(timeout=timeout) as client:
            async with client.post(self._endpoint(), headers=self._headers(), json=body) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    raise PaymentError(f"Platega payment creation failed: {response.status}")

        transaction_id = str(data.get("transactionId") or "")
        redirect_url = str(data.get("redirect") or "")
        if not transaction_id or not redirect_url:
            raise PaymentError("Platega response has no transaction redirect")
        return PlategaInvoice(
            order_id=request.order_id,
            transaction_id=transaction_id,
            redirect_url=redirect_url,
            status=str(data.get("status") or "PENDING"),
            raw_payload=data,
        )

    def verify_webhook_headers(self, *, merchant_id: str | None, secret: str | None) -> None:
        if not self.settings.platega_merchant_id or not self.settings.platega_api_key:
            raise SecurityError("Platega credentials are not configured")
        if merchant_id != self.settings.platega_merchant_id or secret != self.settings.platega_api_key:
            raise SecurityError("invalid Platega webhook headers")

    @staticmethod
    def _payload(data: dict[str, Any]) -> str:
        payload = data.get("payload")
        if not isinstance(payload, str) or not payload:
            raise PaymentError("Platega webhook has no payload")
        return payload

    @staticmethod
    def _transaction_id(data: dict[str, Any]) -> str | None:
        value = data.get("transactionId") or data.get("id")
        return str(value) if value else None

    @staticmethod
    def _amount_and_currency(data: dict[str, Any]) -> tuple[int | None, str | None]:
        details = data.get("paymentDetails")
        amount: Decimal | None = None
        currency: str | None = None
        if isinstance(details, dict):
            raw_amount = details.get("amount")
            raw_currency = details.get("currency")
            if raw_amount is not None:
                try:
                    amount = Decimal(str(raw_amount).replace(",", "."))
                except InvalidOperation:
                    amount = None
            if isinstance(raw_currency, str):
                currency = raw_currency.upper()
        elif isinstance(details, str):
            parts = details.split()
            if len(parts) >= 2:
                try:
                    amount = Decimal(parts[0].replace(",", "."))
                    currency = parts[1].upper()
                except InvalidOperation:
                    amount = None

        if amount is None or currency is None:
            return None, currency
        return decimal_to_minor(amount, currency), currency

    async def handle_webhook(self, *, session: AsyncSession, data: dict[str, Any]) -> PaymentResult | None:
        status = str(data.get("status") or "").upper()
        payload = self._payload(data)
        transaction_id = self._transaction_id(data)
        if status == "CONFIRMED":
            amount, currency = self._amount_and_currency(data)
            completed = await complete_external_successful_payment(
                session=session,
                settings=self.settings,
                payload=payload,
                provider_name=self.name,
                provider_payment_charge_id=transaction_id,
                raw_payload=data,
                amount=amount,
                currency=currency,
            )
            return PaymentResult(
                order_id=completed.order.id,
                digital_item_values=[item.value for item in completed.digital_items],
                already_processed=completed.already_processed,
            )
        if status in {"CANCELED", "CHARGEBACK"}:
            await mark_external_payment_not_confirmed(
                session=session,
                settings=self.settings,
                payload=payload,
                status=status,
            )
            return None
        raise PaymentError(f"unsupported Platega status: {status}")
