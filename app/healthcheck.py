from __future__ import annotations

import asyncio

from sqlalchemy import text

from app.db.session import session_factory


async def main() -> None:
    async with session_factory() as session:
        await session.execute(text("SELECT 1"))


if __name__ == "__main__":
    asyncio.run(main())
