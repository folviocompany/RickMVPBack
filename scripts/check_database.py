import asyncio
import selectors
import sys

from sqlalchemy import text

from app.db.session import session_factory


async def check() -> None:
    async with session_factory() as session:
        result = await session.execute(text("select 1"))
        if result.scalar_one() != 1:
            raise RuntimeError("O banco não retornou o resultado esperado")
    print("Conexão assíncrona com PostgreSQL: OK")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.run(
            check(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    else:
        asyncio.run(check())
