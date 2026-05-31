from __future__ import annotations

import asyncio
from threading import Thread
from typing import Awaitable, TypeVar, cast

T = TypeVar("T")


def run_async(coro: Awaitable[T]) -> T:
    """Run an async coroutine safely from sync contexts (Celery-friendly)."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result_container: dict[str, object] = {}

    def runner() -> None:
        try:
            result_container["result"] = asyncio.run(coro)
        except Exception as error:
            result_container["error"] = error

    thread = Thread(target=runner, daemon=True)
    thread.start()
    thread.join()

    if "error" in result_container:
        raise cast(Exception, result_container["error"])

    return cast(T, result_container.get("result"))
