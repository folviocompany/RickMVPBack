import asyncio
import selectors
import sys
from collections.abc import Coroutine
from typing import Any


def run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    if sys.platform == "win32":
        return asyncio.run(
            coroutine,
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    return asyncio.run(coroutine)
