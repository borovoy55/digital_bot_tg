from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class MenuCb(CallbackData, prefix="m"):
    action: str


class CatalogCb(CallbackData, prefix="c"):
    level: str
    parent_id: int = 0
    page: int = 0


class ProductCb(CallbackData, prefix="p"):
    action: str
    product_id: int
    page: int = 0


class PurchasesCb(CallbackData, prefix="u"):
    page: int = 0


class AdminCb(CallbackData, prefix="a"):
    action: str
    entity: str = "-"
    object_id: int = 0
    page: int = 0
