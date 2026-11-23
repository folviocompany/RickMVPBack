import asyncio
import selectors
import sys

import uvicorn


async def serve() -> None:
    config = uvicorn.Config("app.main:app", host="0.0.0.0", port=8080)
    await uvicorn.Server(config).serve()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.run(
            serve(),
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    else:
        asyncio.run(serve())
