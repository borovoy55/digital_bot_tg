from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import secrets
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.core.exceptions import SecurityError, ValidationError

MAX_CALLBACK_DATA_LENGTH = 64
MAX_DIGITAL_ITEM_LENGTH = 4096
MAX_TITLE_LENGTH = 255
MAX_DESCRIPTION_LENGTH = 4096


@dataclass(frozen=True)
class ParsedOrderPayload:
    order_id: int
    nonce: str
    signature: str


def make_nonce() -> str:
    return secrets.token_urlsafe(8)


def _sign(secret: str, body: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), body.encode("utf-8"), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")[:24]


def make_order_payload(
    *,
    secret: str,
    order_id: int,
    user_id: int,
    product_id: int,
    nonce: str,
) -> str:
    body = f"{order_id}:{user_id}:{product_id}:{nonce}"
    payload = f"o:{order_id}:{nonce}:{_sign(secret, body)}"
    validate_callback_data(payload)
    return payload


def parse_order_payload(payload: str) -> ParsedOrderPayload:
    if not payload or len(payload) > 128:
        raise SecurityError("invalid payment payload")
    parts = payload.split(":")
    if len(parts) != 4 or parts[0] != "o":
        raise SecurityError("invalid payment payload")
    try:
        order_id = int(parts[1])
    except ValueError as exc:
        raise SecurityError("invalid payment payload") from exc
    nonce = parts[2]
    signature = parts[3]
    if len(nonce) < 8 or len(signature) < 16:
        raise SecurityError("invalid payment payload")
    return ParsedOrderPayload(order_id=order_id, nonce=nonce, signature=signature)


def verify_order_payload(
    *,
    secret: str,
    payload: str,
    order_id: int,
    user_id: int,
    product_id: int,
    stored_payload: str,
) -> None:
    parsed = parse_order_payload(payload)
    if parsed.order_id != order_id:
        raise SecurityError("payment payload order mismatch")
    body = f"{order_id}:{user_id}:{product_id}:{parsed.nonce}"
    expected_signature = _sign(secret, body)
    expected_payload = f"o:{order_id}:{parsed.nonce}:{expected_signature}"
    if not hmac.compare_digest(expected_signature, parsed.signature):
        raise SecurityError("payment payload signature mismatch")
    if not hmac.compare_digest(stored_payload, expected_payload):
        raise SecurityError("payment payload replay or substitution")


def validate_callback_data(value: str) -> None:
    if not value or len(value.encode("utf-8")) > MAX_CALLBACK_DATA_LENGTH:
        raise ValidationError("callback data is invalid")


def validate_text(value: str, *, field: str, max_length: int, required: bool = True) -> str:
    value = (value or "").strip()
    if required and not value:
        raise ValidationError(f"{field} is required")
    if len(value) > max_length:
        raise ValidationError(f"{field} is too long")
    return value


def normalize_digital_item(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise ValidationError("empty digital item")
    if len(value) > MAX_DIGITAL_ITEM_LENGTH:
        raise ValidationError("digital item is too long")
    return value


def parse_items_text(text: str) -> tuple[list[str], int]:
    items: list[str] = []
    errors = 0
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(normalize_digital_item(line))
        except ValidationError:
            errors += 1
    return items, errors


def parse_items_csv(content: str) -> tuple[list[str], int]:
    items: list[str] = []
    errors = 0
    reader = csv.reader(io.StringIO(content))
    for row in reader:
        if not row:
            continue
        try:
            items.append(normalize_digital_item(row[0]))
        except ValidationError:
            errors += 1
    return items, errors


def deduplicate_preserve_order(values: Iterable[str]) -> tuple[list[str], int]:
    seen = set()
    result: list[str] = []
    duplicates = 0
    for value in values:
        if value in seen:
            duplicates += 1
            continue
        seen.add(value)
        result.append(value)
    return result, duplicates


ZERO_DECIMAL_CURRENCIES = {"JPY", "KRW", "VND"}


def currency_exponent(currency: str) -> int:
    return 0 if currency.upper() in ZERO_DECIMAL_CURRENCIES else 2


def decimal_to_minor(amount: Decimal, currency: str) -> int:
    exponent = currency_exponent(currency)
    scale = Decimal(10) ** exponent
    return int((amount * scale).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def minor_to_decimal(amount: int, currency: str) -> Decimal:
    exponent = currency_exponent(currency)
    scale = Decimal(10) ** exponent
    return (Decimal(amount) / scale).quantize(Decimal("0.01") if exponent else Decimal("1"))


def csv_rows(rows: Sequence[Sequence[str]]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerows(rows)
    return output.getvalue()
