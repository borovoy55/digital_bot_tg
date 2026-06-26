from __future__ import annotations

from collections.abc import Iterable
from decimal import Decimal
import re

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import AdminCb, CatalogCb, MenuCb, ProductCb, PurchasesCb
from app.db.models import Category, Product, Subcategory, User
from app.services.catalog import Page, PublicProduct
from app.services.menu import MenuButton


def _status_icon(is_active: bool) -> str:
    return "✅" if is_active else "⏸"


COUNTRY_FLAGS = {
    "казахстан": "🇰🇿",
    "kz": "🇰🇿",
    "kzt": "🇰🇿",
    "сша": "🇺🇸",
    "usa": "🇺🇸",
    "us": "🇺🇸",
    "usd": "🇺🇸",
    "турция": "🇹🇷",
    "turkey": "🇹🇷",
    "try": "🇹🇷",
    "индия": "🇮🇳",
    "india": "🇮🇳",
    "inr": "🇮🇳",
    "россия": "🇷🇺",
    "russia": "🇷🇺",
    "rub": "🇷🇺",
}


def _compact_money(value: object) -> str:
    if isinstance(value, Decimal):
        text = format(value.normalize(), "f")
    else:
        text = str(value)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _country_flag(product: Product) -> str:
    parts = [
        product.subcategory.title if product.subcategory else "",
        product.category.title if product.category else "",
        product.title,
        product.currency,
    ]
    haystack = " ".join(parts).lower()
    for needle, flag in COUNTRY_FLAGS.items():
        if needle in haystack:
            return flag
    return "🌐"


def _product_nominal(product: Product) -> str:
    match = re.search(r"(\d+(?:[.,]\d+)?)\s*(KZT|RUB|USD|EUR|INR|TRY|USDT)", product.title, re.IGNORECASE)
    if match:
        amount = match.group(1).replace(",", ".")
        currency = match.group(2).upper()
        if "." in amount:
            amount = amount.rstrip("0").rstrip(".")
        return f"{amount} {currency}"
    return f"{_compact_money(product.price)} {product.currency}"


def _admin_product_button_text(product: Product) -> str:
    flag = _country_flag(product)
    nominal = _product_nominal(product)
    price = f"{_compact_money(product.price)} {product.currency}"
    return f"{_status_icon(product.is_active)} {flag} #{product.id} · {nominal} · {price}"


def main_menu(buttons: Iterable[MenuButton] | None = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    source = list(buttons or [])
    if not source:
        builder.button(text="🛒 Товары", callback_data=MenuCb(action="cat"))
        builder.button(text="💲 Купить", callback_data=MenuCb(action="buy"))
        builder.button(text="ℹ️ Личный кабинет", callback_data=PurchasesCb(page=0))
        builder.button(text="💬 Помощь", callback_data=MenuCb(action="b_support"))
        builder.button(text="📔 Инструкции по активации", callback_data=MenuCb(action="b_instructions"))
        builder.button(text="🤷‍♂️ Не получил товар", callback_data=MenuCb(action="b_not_received"))
    for button in source:
        if button.kind == "catalog":
            builder.button(text=button.label, callback_data=MenuCb(action="cat"))
        elif button.kind == "buy":
            builder.button(text=button.label, callback_data=MenuCb(action="buy"))
        elif button.kind == "purchases":
            builder.button(text=button.label, callback_data=PurchasesCb(page=0))
        elif button.kind == "text":
            builder.button(text=button.label, callback_data=MenuCb(action=f"b_{button.id}"))
    builder.adjust(2, 1, 2, 1, 2, 2)
    return builder.as_markup()


def _pager(builder: InlineKeyboardBuilder, *, cb_prev: object, cb_next: object, page: Page) -> None:
    row = []
    if page.page > 0:
        row.append(("◀️ Назад", cb_prev))
    if page.page + 1 < page.pages:
        row.append(("Вперед ▶️", cb_next))
    for text, cb in row:
        builder.button(text=text, callback_data=cb)


def categories_keyboard(page: Page) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for category in page.items:
        assert isinstance(category, Category)
        builder.button(
            text=f"📁 {category.title}",
            callback_data=CatalogCb(level="sub", parent_id=category.id, page=0),
        )
    _pager(
        builder,
        cb_prev=CatalogCb(level="cat", parent_id=0, page=page.page - 1),
        cb_next=CatalogCb(level="cat", parent_id=0, page=page.page + 1),
        page=page,
    )
    builder.button(text="◀️ Назад", callback_data=MenuCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def subcategories_keyboard(category_id: int, page: Page) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for subcategory in page.items:
        assert isinstance(subcategory, Subcategory)
        builder.button(
            text=f"🗂 {subcategory.title}",
            callback_data=CatalogCb(level="prod", parent_id=subcategory.id, page=0),
        )
    _pager(
        builder,
        cb_prev=CatalogCb(level="sub", parent_id=category_id, page=page.page - 1),
        cb_next=CatalogCb(level="sub", parent_id=category_id, page=page.page + 1),
        page=page,
    )
    builder.button(text="◀️ Назад", callback_data=CatalogCb(level="cat", parent_id=0, page=0))
    builder.button(text="🏠 В главное меню", callback_data=MenuCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def products_keyboard(subcategory_id: int, *, category_id: int, page: Page) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for product in page.items:
        assert isinstance(product, Product)
        builder.button(
            text=f"📦 {product.title} · {product.price} {product.currency}",
            callback_data=ProductCb(action="view", product_id=product.id, page=page.page),
        )
    _pager(
        builder,
        cb_prev=CatalogCb(level="prod", parent_id=subcategory_id, page=page.page - 1),
        cb_next=CatalogCb(level="prod", parent_id=subcategory_id, page=page.page + 1),
        page=page,
    )
    builder.button(text="◀️ Назад", callback_data=CatalogCb(level="sub", parent_id=category_id, page=0))
    builder.button(text="🏠 В главное меню", callback_data=MenuCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def buy_products_keyboard(page: Page) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in page.items:
        assert isinstance(item, PublicProduct)
        product = item.product
        builder.button(
            text=f"{_country_flag(product)} {_product_nominal(product)}",
            callback_data=ProductCb(action="view", product_id=product.id, page=page.page),
        )
    _pager(
        builder,
        cb_prev=CatalogCb(level="all", parent_id=0, page=page.page - 1),
        cb_next=CatalogCb(level="all", parent_id=0, page=page.page + 1),
        page=page,
    )
    builder.button(text="🏠 В главное меню", callback_data=MenuCb(action="home"))
    builder.adjust(2, 2, 2, 2, 2, 1)
    return builder.as_markup()


def product_keyboard(product_id: int, *, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🛒 Купить", callback_data=ProductCb(action="buy", product_id=product_id, page=page))
    builder.button(text="◀️ Назад", callback_data=CatalogCb(level="all", parent_id=0, page=page))
    builder.button(text="🏠 В главное меню", callback_data=MenuCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def quantity_keyboard(product_id: int, *, quantity: int, available: int, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if quantity > 1:
        builder.button(
            text="➖",
            callback_data=ProductCb(action=f"q{quantity - 1}", product_id=product_id, page=page),
        )
    builder.button(text=f"{quantity} шт.", callback_data=ProductCb(action="noop", product_id=product_id, page=page))
    if quantity < available:
        builder.button(
            text="➕",
            callback_data=ProductCb(action=f"q{quantity + 1}", product_id=product_id, page=page),
        )
    builder.button(text="🔢 Ввести количество", callback_data=ProductCb(action="qinput", product_id=product_id, page=page))
    builder.button(text="💳 Оплатить", callback_data=ProductCb(action=f"pay{quantity}", product_id=product_id, page=page))
    builder.button(text="◀️ Назад", callback_data=ProductCb(action="view", product_id=product_id, page=page))
    builder.button(text="🏠 В главное меню", callback_data=MenuCb(action="home"))
    builder.adjust(3, 1, 1, 1, 1)
    return builder.as_markup()


def quantity_input_keyboard(product_id: int, *, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data=ProductCb(action="view", product_id=product_id, page=page))
    builder.button(text="🏠 В главное меню", callback_data=MenuCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def payment_url_keyboard(payment_url: str, *, product_id: int, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💳 Перейти к оплате", url=payment_url)
    builder.button(text="◀️ Назад", callback_data=ProductCb(action="view", product_id=product_id, page=page))
    builder.button(text="🏠 В главное меню", callback_data=MenuCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def purchases_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Обновить", callback_data=PurchasesCb(page=0))
    builder.button(text="🏠 В главное меню", callback_data=MenuCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def admin_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    buttons = [
        ("📊 Статистика", AdminCb(action="stats")),
        ("🧾 Заказы", AdminCb(action="list", entity="orders")),
        ("👥 Пользователи", AdminCb(action="list", entity="users")),
        ("📁 Категории", AdminCb(action="list", entity="cats")),
        ("🗂 Подкатегории", AdminCb(action="list", entity="subs")),
        ("📦 Товары", AdminCb(action="list", entity="products")),
        ("🔑 Цифровые товары", AdminCb(action="list", entity="items")),
        ("🧩 Кнопки меню", AdminCb(action="menu")),
        ("📣 Рассылка", AdminCb(action="broadcast")),
        ("⚙️ Настройки", AdminCb(action="settings")),
    ]
    for text, cb in buttons:
        builder.button(text=text, callback_data=cb)
    builder.adjust(2, 2, 2, 2, 2)
    return builder.as_markup()


def admin_back() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🛠 Админ-меню", callback_data=AdminCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def admin_orders_keyboard(order_ids: Iterable[int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order_id in order_ids:
        builder.button(
            text=f"Заказ #{order_id}",
            callback_data=AdminCb(action="view", entity="order", object_id=order_id),
        )
    builder.button(text="🛠 Админ-меню", callback_data=AdminCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def admin_categories_keyboard(page: Page) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕📁 Создать категорию", callback_data=AdminCb(action="cnew", entity="category"))
    for category in page.items:
        assert isinstance(category, Category)
        state = "вкл" if category.is_active else "выкл"
        builder.button(
            text=f"{_status_icon(category.is_active)} 📁 #{category.id} · {category.title} · {state}",
            callback_data=AdminCb(action="cview", entity="category", object_id=category.id, page=page.page),
        )
    _pager(
        builder,
        cb_prev=AdminCb(action="list", entity="cats", page=page.page - 1),
        cb_next=AdminCb(action="list", entity="cats", page=page.page + 1),
        page=page,
    )
    builder.button(text="🛠 Админ-меню", callback_data=AdminCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def admin_category_keyboard(category: Category, *, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✏️ Название",
        callback_data=AdminCb(action="cedit", entity="title", object_id=category.id, page=page),
    )
    builder.button(
        text="🔢 Сортировка",
        callback_data=AdminCb(action="cedit", entity="sort", object_id=category.id, page=page),
    )
    builder.button(
        text="⏸ Отключить" if category.is_active else "✅ Включить",
        callback_data=AdminCb(action="ctog", entity="category", object_id=category.id, page=page),
    )
    builder.button(
        text="➕🗂 Создать подкатегорию",
        callback_data=AdminCb(action="snew", entity="cat", object_id=category.id, page=page),
    )
    builder.button(
        text="🗂 Подкатегории",
        callback_data=AdminCb(action="list", entity="subs", object_id=category.id),
    )
    builder.button(
        text="🗑 Удалить",
        callback_data=AdminCb(action="cdel", entity="category", object_id=category.id, page=page),
    )
    builder.button(text="📁 К списку категорий", callback_data=AdminCb(action="list", entity="cats", page=page))
    builder.button(text="🛠 Админ-меню", callback_data=AdminCb(action="home"))
    builder.adjust(2, 2, 2, 1, 1)
    return builder.as_markup()


def admin_subcategories_keyboard(page: Page, *, category_id: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="➕🗂 Создать подкатегорию",
        callback_data=AdminCb(action="snew", entity="cat", object_id=category_id),
    )
    for subcategory in page.items:
        assert isinstance(subcategory, Subcategory)
        state = "вкл" if subcategory.is_active else "выкл"
        builder.button(
            text=f"{_status_icon(subcategory.is_active)} 🗂 #{subcategory.id} · cat={subcategory.category_id} · {subcategory.title} · {state}",
            callback_data=AdminCb(
                action="sview",
                entity="subcategory",
                object_id=subcategory.id,
                page=page.page,
            ),
        )
    _pager(
        builder,
        cb_prev=AdminCb(action="list", entity="subs", object_id=category_id, page=page.page - 1),
        cb_next=AdminCb(action="list", entity="subs", object_id=category_id, page=page.page + 1),
        page=page,
    )
    builder.button(text="📁 Категории", callback_data=AdminCb(action="list", entity="cats"))
    builder.button(text="🛠 Админ-меню", callback_data=AdminCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def admin_subcategory_keyboard(subcategory: Subcategory, *, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✏️ Название",
        callback_data=AdminCb(action="sedit", entity="title", object_id=subcategory.id, page=page),
    )
    builder.button(
        text="🔢 Сортировка",
        callback_data=AdminCb(action="sedit", entity="sort", object_id=subcategory.id, page=page),
    )
    builder.button(
        text="⏸ Отключить" if subcategory.is_active else "✅ Включить",
        callback_data=AdminCb(action="stog", entity="subcategory", object_id=subcategory.id, page=page),
    )
    builder.button(
        text="🗑 Удалить",
        callback_data=AdminCb(action="sdel", entity="subcategory", object_id=subcategory.id, page=page),
    )
    builder.button(
        text="🗂 К подкатегориям",
        callback_data=AdminCb(action="list", entity="subs", object_id=subcategory.category_id, page=page),
    )
    builder.button(text="🛠 Админ-меню", callback_data=AdminCb(action="home"))
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()


def admin_order_keyboard(order_id: int, has_item: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_item:
        builder.button(
            text="🔁 Повторно отправить код",
            callback_data=AdminCb(action="resend", entity="order", object_id=order_id),
        )
    builder.button(text="🧾 Заказы", callback_data=AdminCb(action="list", entity="orders"))
    builder.button(text="🛠 Админ-меню", callback_data=AdminCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def admin_users_keyboard(page: Page) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for user in page.items:
        assert isinstance(user, User)
        blocked = "🚫" if user.is_blocked else "👤"
        label = f"{blocked} #{user.id} · {user.telegram_id}"
        if user.username:
            label += f" · @{user.username}"
        builder.button(
            text=label,
            callback_data=AdminCb(action="uview", entity="user", object_id=user.id, page=page.page),
        )
    _pager(
        builder,
        cb_prev=AdminCb(action="list", entity="users", page=page.page - 1),
        cb_next=AdminCb(action="list", entity="users", page=page.page + 1),
        page=page,
    )
    builder.button(text="🛠 Админ-меню", callback_data=AdminCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def admin_user_keyboard(user_id: int, *, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👥 К пользователям", callback_data=AdminCb(action="list", entity="users", page=page))
    builder.button(text="🛠 Админ-меню", callback_data=AdminCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def admin_products_keyboard(page: Page) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕📦 Создать товар", callback_data=AdminCb(action="pnew", entity="product"))
    for product in page.items:
        assert isinstance(product, Product)
        builder.button(
            text=_admin_product_button_text(product),
            callback_data=AdminCb(action="pview", entity="product", object_id=product.id, page=page.page),
        )
    _pager(
        builder,
        cb_prev=AdminCb(action="list", entity="products", page=page.page - 1),
        cb_next=AdminCb(action="list", entity="products", page=page.page + 1),
        page=page,
    )
    builder.button(text="🛠 Админ-меню", callback_data=AdminCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def admin_empty_product_tree_keyboard(*, reason: str, category_id: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if reason == "category":
        builder.button(text="➕📁 Создать категорию", callback_data=AdminCb(action="cnew", entity="category"))
    elif reason == "subcategory":
        builder.button(
            text="➕🗂 Создать подкатегорию",
            callback_data=AdminCb(action="snew", entity="cat", object_id=category_id),
        )
        builder.button(text="📁 Выбрать другую категорию", callback_data=AdminCb(action="pnew", entity="product"))
    builder.button(text="📦 К товарам", callback_data=AdminCb(action="list", entity="products"))
    builder.button(text="🛠 Админ-меню", callback_data=AdminCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def admin_product_keyboard(product: Product, *, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="✏️ Название",
        callback_data=AdminCb(action="pedit", entity="title", object_id=product.id, page=page),
    )
    builder.button(
        text="📝 Описание",
        callback_data=AdminCb(action="pedit", entity="desc", object_id=product.id, page=page),
    )
    builder.button(
        text="💰 Цена",
        callback_data=AdminCb(action="pedit", entity="price", object_id=product.id, page=page),
    )
    builder.button(
        text="💱 Валюта",
        callback_data=AdminCb(action="pedit", entity="curr", object_id=product.id, page=page),
    )
    builder.button(
        text="🔢 Сортировка",
        callback_data=AdminCb(action="pedit", entity="sort", object_id=product.id, page=page),
    )
    builder.button(
        text="⏸ Отключить" if product.is_active else "✅ Включить",
        callback_data=AdminCb(action="ptog", entity="product", object_id=product.id, page=page),
    )
    builder.button(
        text="🔑 Коды товара",
        callback_data=AdminCb(action="items", entity="product", object_id=product.id, page=page),
    )
    builder.button(
        text="🗑 Удалить",
        callback_data=AdminCb(action="pdel", entity="product", object_id=product.id, page=page),
    )
    builder.button(text="📦 К списку товаров", callback_data=AdminCb(action="list", entity="products", page=page))
    builder.button(text="🛠 Админ-меню", callback_data=AdminCb(action="home"))
    builder.adjust(2, 2, 2, 2, 1, 1)
    return builder.as_markup()


def admin_digital_product_keyboard(product_id: int, *, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Смотреть все коды", callback_data=AdminCb(action="ilist", entity="product", object_id=product_id, page=0))
    builder.button(text="➕ Загрузить коды", callback_data=AdminCb(action="iupload", entity="product", object_id=product_id, page=page))
    builder.button(text="🔎 Найти код", callback_data=AdminCb(action="isearch", entity="product", object_id=product_id, page=page))
    builder.button(text="📤 Экспорт CSV", callback_data=AdminCb(action="iexport", entity="product", object_id=product_id, page=page))
    builder.button(text="📦 К товару", callback_data=AdminCb(action="pview", entity="product", object_id=product_id, page=page))
    builder.button(text="🛠 Админ-меню", callback_data=AdminCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def admin_digital_items_keyboard(page: Page, *, product_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in page.items:
        item_id = getattr(item, "id")
        status = getattr(item, "status")
        builder.button(
            text=f"🔑 #{item_id} · {status}",
            callback_data=AdminCb(action="iview", entity="item", object_id=item_id, page=page.page),
        )
    _pager(
        builder,
        cb_prev=AdminCb(action="ilist", entity="product", object_id=product_id, page=page.page - 1),
        cb_next=AdminCb(action="ilist", entity="product", object_id=product_id, page=page.page + 1),
        page=page,
    )
    builder.button(text="🔑 Коды товара", callback_data=AdminCb(action="items", entity="product", object_id=product_id))
    builder.adjust(1)
    return builder.as_markup()


def admin_digital_search_keyboard(items: Iterable[object], *, product_id: int, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for item in items:
        item_id = getattr(item, "id")
        status = getattr(item, "status")
        builder.button(
            text=f"🔑 #{item_id} · {status}",
            callback_data=AdminCb(action="iview", entity="item", object_id=item_id, page=page),
        )
    builder.button(text="🔑 Коды товара", callback_data=AdminCb(action="items", entity="product", object_id=product_id, page=page))
    builder.adjust(1)
    return builder.as_markup()


def admin_digital_item_keyboard(
    item_id: int,
    *,
    product_id: int,
    page: int = 0,
    can_modify: bool = True,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if can_modify:
        builder.button(text="✏️ Изменить код", callback_data=AdminCb(action="iedit", entity="item", object_id=item_id, page=page))
        builder.button(text="🗑 Удалить", callback_data=AdminCb(action="idel", entity="item", object_id=item_id, page=page))
    builder.button(text="📋 Все коды", callback_data=AdminCb(action="ilist", entity="product", object_id=product_id, page=page))
    builder.button(text="🔑 Коды товара", callback_data=AdminCb(action="items", entity="product", object_id=product_id))
    builder.adjust(1)
    return builder.as_markup()


def admin_menu_buttons_keyboard(buttons: Iterable[MenuButton]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="➕ Создать кнопку", callback_data=AdminCb(action="mbnew"))
    for button in buttons:
        icon = "✅" if button.visible else "⏸"
        builder.button(text=f"{icon} {button.label}", callback_data=AdminCb(action="mbview", entity=button.id))
    builder.button(text="🛠 Админ-меню", callback_data=AdminCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def admin_menu_button_keyboard(button: MenuButton) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✏️ Название", callback_data=AdminCb(action="mbedit", entity=button.id))
    if button.kind == "text":
        builder.button(text="📝 Содержимое", callback_data=AdminCb(action="mbtext", entity=button.id))
    builder.button(
        text="⏸ Скрыть" if button.visible else "✅ Показать",
        callback_data=AdminCb(action="mbtog", entity=button.id),
    )
    builder.button(text="🔢 Сортировка", callback_data=AdminCb(action="mbsort", entity=button.id))
    if not button.builtin:
        builder.button(text="🗑 Удалить", callback_data=AdminCb(action="mbdel", entity=button.id))
    builder.button(text="🧩 К кнопкам", callback_data=AdminCb(action="menu"))
    builder.adjust(1)
    return builder.as_markup()


def admin_settings_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="👋 Приветствие", callback_data=AdminCb(action="stext", entity="welcome_text"))
    builder.button(text="💬 Поддержка", callback_data=AdminCb(action="stext", entity="support_text"))
    builder.button(text="❓ FAQ", callback_data=AdminCb(action="stext", entity="faq_text"))
    builder.button(text="📜 Правила", callback_data=AdminCb(action="stext", entity="rules_text"))
    builder.button(text="🔐 Конфиденциальность", callback_data=AdminCb(action="stext", entity="privacy_text"))
    builder.button(text="📄 Соглашение", callback_data=AdminCb(action="stext", entity="terms_text"))
    builder.button(text="🧩 Кнопки меню", callback_data=AdminCb(action="menu"))
    builder.button(text="🛠 Админ-меню", callback_data=AdminCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def admin_category_select_keyboard(
    page: Page,
    *,
    action: str,
    back_action: str = "list",
    back_entity: str = "products",
    back_text: str = "К списку товаров",
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for category in page.items:
        assert isinstance(category, Category)
        builder.button(
            text=f"📁 {category.title}",
            callback_data=AdminCb(action=action, entity="cat", object_id=category.id, page=page.page),
        )
    _pager(
        builder,
        cb_prev=AdminCb(action=action, entity="catp", page=page.page - 1),
        cb_next=AdminCb(action=action, entity="catp", page=page.page + 1),
        page=page,
    )
    if back_action == "cancel":
        builder.button(text="❌ Отмена", callback_data=AdminCb(action="pcancel", entity="product"))
    else:
        builder.button(text=back_text, callback_data=AdminCb(action="list", entity=back_entity))
    builder.adjust(1)
    return builder.as_markup()


def admin_subcategory_select_keyboard(
    category_id: int,
    page: Page,
    *,
    action: str,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for subcategory in page.items:
        assert isinstance(subcategory, Subcategory)
        builder.button(
            text=f"🗂 {subcategory.title}",
            callback_data=AdminCb(action=action, entity="sub", object_id=subcategory.id, page=page.page),
        )
    _pager(
        builder,
        cb_prev=AdminCb(action=action, entity=f"sub{category_id}", page=page.page - 1),
        cb_next=AdminCb(action=action, entity=f"sub{category_id}", page=page.page + 1),
        page=page,
    )
    builder.button(text="📁 К категориям", callback_data=AdminCb(action="pnew", entity="product"))
    builder.button(text="❌ Отмена", callback_data=AdminCb(action="pcancel", entity="product"))
    builder.adjust(1)
    return builder.as_markup()


def admin_product_skip_keyboard(field: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="⏭ Пропустить", callback_data=AdminCb(action="pskip", entity=field))
    builder.button(text="❌ Отмена", callback_data=AdminCb(action="pcancel", entity="product"))
    builder.adjust(1)
    return builder.as_markup()


def admin_product_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data=AdminCb(action="pcancel", entity="product"))
    builder.adjust(1)
    return builder.as_markup()


def admin_product_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Создать товар", callback_data=AdminCb(action="pconfirm", entity="product"))
    builder.button(text="❌ Отмена", callback_data=AdminCb(action="pcancel", entity="product"))
    builder.adjust(1)
    return builder.as_markup()
