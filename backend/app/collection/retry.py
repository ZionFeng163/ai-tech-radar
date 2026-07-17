import asyncio
from collections.abc import Awaitable, Callable

Sleep = Callable[[float], Awaitable[None]]
RetryCallback = Callable[[int, Exception, float], None]


async def retry_async[T](
    operation: Callable[[int], Awaitable[T]],
    *,
    max_attempts: int,
    backoff_seconds: float,
    sleep: Sleep = asyncio.sleep,
    on_retry: RetryCallback | None = None,
) -> tuple[T, int]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")
    if backoff_seconds < 0:
        raise ValueError("backoff_seconds cannot be negative")

    for attempt in range(1, max_attempts + 1):
        try:
            return await operation(attempt), attempt
        except Exception as error:
            if attempt == max_attempts:
                raise
            delay = backoff_seconds * (2 ** (attempt - 1))
            if on_retry is not None:
                on_retry(attempt, error, delay)
            await sleep(delay)

    raise RuntimeError("retry loop exhausted unexpectedly")
