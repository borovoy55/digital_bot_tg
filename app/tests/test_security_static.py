from __future__ import annotations

import ast
import unittest
from pathlib import Path

from app.core.exceptions import SecurityError
from app.core.security import (
    make_order_payload,
    parse_order_payload,
    verify_order_payload,
)

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class SecurityStaticTests(unittest.TestCase):
    def test_payment_payload_is_hmac_signed_and_tamper_resistant(self) -> None:
        payload = make_order_payload(
            secret="x" * 32,
            order_id=10,
            user_id=20,
            product_id=30,
            nonce="abcdefghi",
        )
        parsed = parse_order_payload(payload)
        self.assertEqual(parsed.order_id, 10)
        verify_order_payload(
            secret="x" * 32,
            payload=payload,
            order_id=10,
            user_id=20,
            product_id=30,
            stored_payload=payload,
        )
        with self.assertRaises(SecurityError):
            verify_order_payload(
                secret="x" * 32,
                payload=payload,
                order_id=10,
                user_id=21,
                product_id=30,
                stored_payload=payload,
            )

    def test_double_sale_uses_postgres_skip_locked(self) -> None:
        source = read("app/services/orders.py")
        self.assertIn("with_for_update(skip_locked=True)", source)
        self.assertIn("DigitalItemStatus.AVAILABLE.value", source)
        self.assertIn("DigitalItemStatus.SOLD.value", source)

    def test_double_spend_has_unique_payment_constraints_and_charge_check(self) -> None:
        models = read("app/db/models.py")
        orders = read("app/services/orders.py")
        self.assertIn("uq_payments_telegram_charge", models)
        self.assertIn("uq_payments_provider_charge", models)
        self.assertIn("payment charge id was already used by another order", orders)

    def test_repeated_successful_payment_is_idempotent(self) -> None:
        source = read("app/services/orders.py")
        self.assertIn("already_processed=True", source)
        self.assertIn("order.status == OrderStatus.PAID.value", source)

    def test_user_cannot_view_foreign_order_or_code(self) -> None:
        source = read("app/services/orders.py")
        self.assertIn("User.telegram_id == telegram_id", source)
        self.assertIn("Order.id == order_id", source)
        purchases = read("app/bot/handlers/purchases.py")
        self.assertIn("list_user_orders", purchases)
        self.assertNotIn("select(DigitalItem)", purchases)

    def test_sql_injection_avoids_raw_f_string_sql(self) -> None:
        for rel in ["app/services", "app/bot/handlers"]:
            for path in (ROOT / rel).rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "text":
                        self.fail(f"raw SQL text() is not allowed in {path}")
        source = read("app/services/digital_items.py")
        self.assertIn(".ilike(", source)

    def test_race_condition_locks_order_and_item_inside_transaction(self) -> None:
        source = read("app/services/orders.py")
        self.assertIn("async with session.begin()", source)
        self.assertIn("lock=True", source)
        self.assertIn("with_for_update()", source)
        self.assertIn("with_for_update(skip_locked=True)", source)

    def test_user_has_no_admin_handler_access(self) -> None:
        admin = read("app/bot/handlers/admin.py")
        users = read("app/services/users.py")
        self.assertIn("require_admin", admin)
        self.assertIn("AccessDenied", admin)
        self.assertIn("telegram_id in settings.admin_ids", users)
        self.assertIn("Admin.is_active.is_(True)", users)

    def test_products_can_be_managed_with_admin_buttons(self) -> None:
        admin = read("app/bot/handlers/admin.py")
        keyboards = read("app/bot/keyboards.py")
        service = read("app/services/admin.py")
        self.assertIn("ProductCreateState", admin)
        self.assertIn("ProductEditState", admin)
        self.assertIn('AdminCb.filter(F.action == "pnew")', admin)
        self.assertIn('AdminCb.filter(F.action == "pedit")', admin)
        self.assertIn("admin_products_keyboard", keyboards)
        self.assertIn("admin_product_keyboard", keyboards)
        self.assertIn("update_product_description", service)
        self.assertIn("update_product_currency", service)


if __name__ == "__main__":
    unittest.main()
