from collections.abc import Awaitable, Callable
from time import perf_counter

from fastapi import FastAPI, Request, Response

from app.api import router
from app.config import get_settings

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
app.include_router(router)


@app.middleware("http")
async def response_timing(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    started = perf_counter()
    response = await call_next(request)
    duration_ms = (perf_counter() - started) * 1_000
    response.headers["Server-Timing"] = f"app;dur={duration_ms:.3f}"
    response.headers["X-Response-Time-Ms"] = f"{duration_ms:.3f}"
    return response


@app.get("/health", tags=["system"])
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ai-tech-radar-api"}
