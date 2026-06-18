from __future__ import annotations

from collections.abc import Iterable

from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.bot.callbacks import AdminCb, CatalogCb, MenuCb, ProductCb, PurchasesCb
from app.db.models import Category, Product, Subcategory
from app.services.catalog import Page


def main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Каталог", callback_data=MenuCb(action="cat"))
    builder.button(text="Мои покупки", callback_data=PurchasesCb(page=0))
    builder.button(text="Поддержка", callback_data=MenuCb(action="support"))
    builder.button(text="FAQ", callback_data=MenuCb(action="faq"))
    builder.button(text="Правила", callback_data=MenuCb(action="rules"))
    builder.adjust(1, 1, 2, 1)
    return builder.as_markup()


def _pager(builder: InlineKeyboardBuilder, *, cb_prev: object, cb_next: object, page: Page) -> None:
    row = []
    if page.page > 0:
        row.append(("Назад", cb_prev))
    if page.page + 1 < page.pages:
        row.append(("Далее", cb_next))
    for text, cb in row:
        builder.button(text=text, callback_data=cb)


def categories_keyboard(page: Page) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for category in page.items:
        assert isinstance(category, Category)
        builder.button(
            text=category.title,
            callback_data=CatalogCb(level="sub", parent_id=category.id, page=0),
        )
    _pager(
        builder,
        cb_prev=CatalogCb(level="cat", parent_id=0, page=page.page - 1),
        cb_next=CatalogCb(level="cat", parent_id=0, page=page.page + 1),
        page=page,
    )
    builder.button(text="В главное меню", callback_data=MenuCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def subcategories_keyboard(category_id: int, page: Page) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for subcategory in page.items:
        assert isinstance(subcategory, Subcategory)
        builder.button(
            text=subcategory.title,
            callback_data=CatalogCb(level="prod", parent_id=subcategory.id, page=0),
        )
    _pager(
        builder,
        cb_prev=CatalogCb(level="sub", parent_id=category_id, page=page.page - 1),
        cb_next=CatalogCb(level="sub", parent_id=category_id, page=page.page + 1),
        page=page,
    )
    builder.button(text="К категориям", callback_data=CatalogCb(level="cat", parent_id=0, page=0))
    builder.button(text="В главное меню", callback_data=MenuCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def products_keyboard(subcategory_id: int, page: Page) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for product in page.items:
        assert isinstance(product, Product)
        builder.button(
            text=f"{product.title} · {product.price} {product.currency}",
            callback_data=ProductCb(action="view", product_id=product.id, page=page.page),
        )
    _pager(
        builder,
        cb_prev=CatalogCb(level="prod", parent_id=subcategory_id, page=page.page - 1),
        cb_next=CatalogCb(level="prod", parent_id=subcategory_id, page=page.page + 1),
        page=page,
    )
    builder.button(text="К категориям", callback_data=CatalogCb(level="cat", parent_id=0, page=0))
    builder.button(text="В главное меню", callback_data=MenuCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def product_keyboard(product_id: int, *, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Купить", callback_data=ProductCb(action="buy", product_id=product_id, page=page))
    builder.button(text="Назад", callback_data=CatalogCb(level="cat", parent_id=0, page=0))
    builder.button(text="В главное меню", callback_data=MenuCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def purchases_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Обновить", callback_data=PurchasesCb(page=0))
    builder.button(text="В главное меню", callback_data=MenuCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def admin_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    buttons = [
        ("Статистика", AdminCb(action="stats")),
        ("Заказы", AdminCb(action="list", entity="orders")),
        ("Пользователи", AdminCb(action="list", entity="users")),
        ("Категории", AdminCb(action="list", entity="cats")),
        ("Подкатегории", AdminCb(action="list", entity="subs")),
        ("Товары", AdminCb(action="list", entity="products")),
        ("Цифровые товары", AdminCb(action="list", entity="items")),
        ("Рассылка", AdminCb(action="broadcast")),
        ("Настройки", AdminCb(action="settings")),
    ]
    for text, cb in buttons:
        builder.button(text=text, callback_data=cb)
    builder.adjust(2, 2, 2, 2, 1)
    return builder.as_markup()


def admin_back() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Админ-меню", callback_data=AdminCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def admin_orders_keyboard(order_ids: Iterable[int]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for order_id in order_ids:
        builder.button(
            text=f"Заказ #{order_id}",
            callback_data=AdminCb(action="view", entity="order", object_id=order_id),
        )
    builder.button(text="Админ-меню", callback_data=AdminCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def admin_order_keyboard(order_id: int, has_item: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if has_item:
        builder.button(
            text="Повторно отправить код",
            callback_data=AdminCb(action="resend", entity="order", object_id=order_id),
        )
    builder.button(text="Заказы", callback_data=AdminCb(action="list", entity="orders"))
    builder.button(text="Админ-меню", callback_data=AdminCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def admin_products_keyboard(page: Page) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Добавить товар", callback_data=AdminCb(action="pnew", entity="product"))
    for product in page.items:
        assert isinstance(product, Product)
        state = "вкл" if product.is_active else "выкл"
        builder.button(
            text=f"#{product.id} · {product.title} · {product.price} {product.currency} · {state}",
            callback_data=AdminCb(action="pview", entity="product", object_id=product.id, page=page.page),
        )
    _pager(
        builder,
        cb_prev=AdminCb(action="list", entity="products", page=page.page - 1),
        cb_next=AdminCb(action="list", entity="products", page=page.page + 1),
        page=page,
    )
    builder.button(text="Админ-меню", callback_data=AdminCb(action="home"))
    builder.adjust(1)
    return builder.as_markup()


def admin_product_keyboard(product: Product, *, page: int = 0) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(
        text="Название",
        callback_data=AdminCb(action="pedit", entity="title", object_id=product.id, page=page),
    )
    builder.button(
        text="Описание",
        callback_data=AdminCb(action="pedit", entity="desc", object_id=product.id, page=page),
    )
    builder.button(
        text="Цена",
        callback_data=AdminCb(action="pedit", entity="price", object_id=product.id, page=page),
    )
    builder.button(
        text="Валюта",
        callback_data=AdminCb(action="pedit", entity="curr", object_id=product.id, page=page),
    )
    builder.button(
        text="Сортировка",
        callback_data=AdminCb(action="pedit", entity="sort", object_id=product.id, page=page),
    )
    builder.button(
        text="Отключить" if product.is_active else "Включить",
        callback_data=AdminCb(action="ptog", entity="product", object_id=product.id, page=page),
    )
    builder.button(
        text="Удалить",
        callback_data=AdminCb(action="pdel", entity="product", object_id=product.id, page=page),
    )
    builder.button(text="К списку товаров", callback_data=AdminCb(action="list", entity="products", page=page))
    builder.button(text="Админ-меню", callback_data=AdminCb(action="home"))
    builder.adjust(2, 2, 1, 2, 1, 1)
    return builder.as_markup()


def admin_category_select_keyboard(page: Page, *, action: str, back_action: str = "list") -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for category in page.items:
        assert isinstance(category, Category)
        builder.button(
            text=category.title,
            callback_data=AdminCb(action=action, entity="cat", object_id=category.id, page=page.page),
        )
    _pager(
        builder,
        cb_prev=AdminCb(action=action, entity="catp", page=page.page - 1),
        cb_next=AdminCb(action=action, entity="catp", page=page.page + 1),
        page=page,
    )
    if back_action == "cancel":
        builder.button(text="Отмена", callback_data=AdminCb(action="pcancel", entity="product"))
    else:
        builder.button(text="К списку товаров", callback_data=AdminCb(action="list", entity="products"))
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
            text=subcategory.title,
            callback_data=AdminCb(action=action, entity="sub", object_id=subcategory.id, page=page.page),
        )
    _pager(
        builder,
        cb_prev=AdminCb(action=action, entity=f"sub{category_id}", page=page.page - 1),
        cb_next=AdminCb(action=action, entity=f"sub{category_id}", page=page.page + 1),
        page=page,
    )
    builder.button(text="К категориям", callback_data=AdminCb(action="pnew", entity="product"))
    builder.button(text="Отмена", callback_data=AdminCb(action="pcancel", entity="product"))
    builder.adjust(1)
    return builder.as_markup()


def admin_product_skip_keyboard(field: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Пропустить", callback_data=AdminCb(action="pskip", entity=field))
    builder.button(text="Отмена", callback_data=AdminCb(action="pcancel", entity="product"))
    builder.adjust(1)
    return builder.as_markup()


def admin_product_cancel_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Отмена", callback_data=AdminCb(action="pcancel", entity="product"))
    builder.adjust(1)
    return builder.as_markup()


def admin_product_confirm_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Создать товар", callback_data=AdminCb(action="pconfirm", entity="product"))
    builder.button(text="Отмена", callback_data=AdminCb(action="pcancel", entity="product"))
    builder.adjust(1)
    return builder.as_markup()
