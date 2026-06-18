from __future__ import annotations

from aiogram import Router

from app.bot.handlers import admin, catalog, payments, purchases, start


def build_router() -> Router:
    router = Router()
    router.include_router(start.router)
    router.include_router(catalog.router)
    router.include_router(purchases.router)
    router.include_router(payments.router)
    router.include_router(admin.router)
    return router
