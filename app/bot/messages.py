from __future__ import annotations

from html import escape

from app.db.models import Order


def format_paid_order_message(order: Order, *, repeated: bool = False) -> str:
    product_title = order.product.title if order.product else f"товар #{order.product_id}"
    codes = "\n".join(f"<code>{escape(item.value)}</code>" for item in order.issued_items)
    code_title = "Ваш код" if len(order.issued_items) == 1 else "Ваши коды"
    title = "🔁 <b>Повторная отправка заказа</b>" if repeated else "✅ <b>Спасибо за покупку!</b>"

    return "\n".join(
        [
            title,
            "",
            f"🧾 <b>Заказ №{order.id}</b>",
            f"🛒 <b>Вы купили:</b> {escape(product_title)}",
            f"🔢 <b>Количество:</b> {order.quantity} шт.",
            f"💰 <b>Сумма:</b> {escape(str(order.amount))} {escape(order.currency)}",
            "",
            f"🔑 <b>{code_title} для товара «{escape(product_title)}»:</b>",
            codes,
        ]
    )
