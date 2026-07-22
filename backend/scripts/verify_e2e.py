"""Verify the public API and server-rendered Web routes used by the MVP."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, build_opener

BACKEND_URL = os.getenv("E2E_BACKEND_URL", "http://localhost:18000").rstrip("/")
FRONTEND_URL = os.getenv("E2E_FRONTEND_URL", "http://localhost:13000").rstrip("/")
EXPECTED_TITLE = "Radar E2E：可验证的高效推理信号"
OPENER = build_opener(ProxyHandler({}))


class E2EFailure(RuntimeError):
    """An actionable end-to-end assertion failure."""


def fetch(path: str, *, frontend: bool = False) -> tuple[int, bytes, Mapping[str, str]]:
    base_url = FRONTEND_URL if frontend else BACKEND_URL
    try:
        with OPENER.open(f"{base_url}{path}", timeout=20) as response:
            return response.status, response.read(), dict(response.headers.items())
    except HTTPError as exc:
        raise E2EFailure(f"GET {path} returned HTTP {exc.code}") from exc
    except URLError as exc:
        raise E2EFailure(f"GET {path} could not connect: {exc.reason}") from exc


def fetch_json(path: str) -> dict[str, Any]:
    status, body, _ = fetch(path)
    if status != 200:
        raise E2EFailure(f"GET {path} returned HTTP {status}")
    try:
        value = json.loads(body)
    except json.JSONDecodeError as exc:
        raise E2EFailure(f"GET {path} did not return JSON") from exc
    if not isinstance(value, dict):
        raise E2EFailure(f"GET {path} returned a non-object JSON value")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise E2EFailure(message)


def run() -> None:
    health = fetch_json("/health")
    require(health.get("status") == "ok", "backend health payload is not ok")
    print("[e2e] backend health: ok")

    articles = fetch_json("/articles?source=e2e-fixture&limit=10")
    items = articles.get("items")
    require(isinstance(items, list) and len(items) == 1, "fixture article was not returned")
    article = items[0]
    require(isinstance(article, dict), "fixture article has an invalid shape")
    require(article.get("title") == EXPECTED_TITLE, "fixture title does not match")
    article_id = article.get("id")
    require(isinstance(article_id, str) and article_id, "fixture article has no id")
    print("[e2e] sample data -> article API: ok")

    results = fetch_json("/search?q=radar-e2e&source=e2e-fixture")
    search_items = results.get("items")
    require(isinstance(search_items, list) and len(search_items) == 1, "search missed fixture")
    print("[e2e] search API: ok")

    home_status, home_body, _ = fetch("/", frontend=True)
    home_html = home_body.decode("utf-8")
    require(home_status == 200, "frontend home did not return HTTP 200")
    require(EXPECTED_TITLE in home_html, "frontend home did not render fixture article")
    print("[e2e] server-rendered home: ok")

    detail_status, detail_body, _ = fetch(f"/articles/{article_id}", frontend=True)
    detail_html = detail_body.decode("utf-8")
    require(detail_status == 200, "frontend detail did not return HTTP 200")
    require(EXPECTED_TITLE in detail_html, "frontend detail did not render fixture title")
    require("核心创新" in detail_html, "frontend detail did not render analysis")
    print("[e2e] server-rendered detail: ok")

    og_status, _, og_headers = fetch("/og.png", frontend=True)
    require(og_status == 200, "Open Graph image did not return HTTP 200")
    require(
        og_headers.get("Content-Type", "").startswith("image/png"),
        "Open Graph asset is not a PNG",
    )
    print("[e2e] social preview asset: ok")


if __name__ == "__main__":
    try:
        run()
    except E2EFailure as exc:
        print(f"[e2e] FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print("[e2e] PASS: sample data -> API -> Web")
