import html
import re
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import cast
from xml.etree import ElementTree

import httpx
from pydantic import AnyHttpUrl, JsonValue

from app.domain import ArticleKind, SourceKind
from app.sources.base import (
    AdapterCursor,
    AuthorData,
    CollectedItem,
    FetchBatch,
    NormalizedItem,
    SourceAdapter,
    SourceDescriptor,
)

TAG_RE = re.compile(r"<[^>]+>")


class LobstersAdapter(SourceAdapter):
    descriptor = SourceDescriptor(
        slug="lobsters",
        name="Lobsters",
        kind=SourceKind.RSS,
        base_url=AnyHttpUrl("https://lobste.rs"),
    )

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            timeout=15,
            headers={"User-Agent": "AI-Tech-Radar/0.1"},
            follow_redirects=True,
        )
        self._owns_client = client is None

    async def fetch(self, cursor: AdapterCursor | None = None, *, limit: int = 100) -> FetchBatch:
        del cursor
        if limit < 1:
            raise ValueError("limit must be at least 1")
        response = await self._client.get("https://lobste.rs/rss")
        response.raise_for_status()
        payloads = self._parse_feed(response.content)[: min(limit, 50)]
        items = [
            CollectedItem(
                external_id=str(payload["guid"]),
                url=AnyHttpUrl(str(payload.get("comments") or payload["link"])),
                payload=payload,
            )
            for payload in payloads
        ]
        return FetchBatch(
            items=items,
            next_cursor=AdapterCursor(value={"snapshot": "front-page-rss"}),
            has_more=False,
        )

    def normalize(self, item: CollectedItem) -> NormalizedItem:
        payload = item.payload
        title = self._string(payload, "title")
        link = self._string(payload, "link")
        description = self._clean_html(self._optional_string(payload, "description") or "")
        author = self._optional_string(payload, "creator")
        categories = payload.get("categories", [])
        tags = (
            [value for value in categories if isinstance(value, str)]
            if isinstance(categories, list)
            else []
        )
        published = parsedate_to_datetime(self._string(payload, "pub_date"))
        if published.tzinfo is None:
            published = published.replace(tzinfo=UTC)
        return NormalizedItem(
            external_id=self._string(payload, "guid"),
            kind=ArticleKind.NEWS,
            canonical_url=AnyHttpUrl(link),
            title=title,
            content=f"{description}\n该条目进入 Lobsters 计算机社区前台热门流。".strip(),
            published_at=published,
            authors=[AuthorData(name=author)] if author else [],
            tags=[*tags, "Lobsters", "社区热点"],
            metadata={
                "provider": "lobsters",
                "rank": payload.get("rank"),
                "discussion_url": str(item.url),
            },
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    @staticmethod
    def _parse_feed(content: bytes) -> list[dict[str, JsonValue]]:
        root = ElementTree.fromstring(content)
        items: list[dict[str, JsonValue]] = []
        for rank, node in enumerate(root.findall("./channel/item"), start=1):
            categories = [
                value
                for category in node.findall("category")
                if (value := (category.text or "").strip())
            ]
            creator = node.find("{http://purl.org/dc/elements/1.1/}creator")
            payload: dict[str, JsonValue] = {
                "title": LobstersAdapter._node_text(node, "title"),
                "link": LobstersAdapter._node_text(node, "link"),
                "guid": LobstersAdapter._node_text(node, "guid"),
                "pub_date": LobstersAdapter._node_text(node, "pubDate"),
                "description": LobstersAdapter._node_text(node, "description", required=False),
                "comments": LobstersAdapter._node_text(node, "comments", required=False),
                "creator": (creator.text or "").strip() if creator is not None else "",
                "categories": cast(list[JsonValue], categories),
                "rank": rank,
            }
            items.append(payload)
        return items

    @staticmethod
    def _node_text(
        node: ElementTree.Element, name: str, *, required: bool = True
    ) -> str:
        child = node.find(name)
        value = (child.text or "").strip() if child is not None else ""
        if required and not value:
            raise ValueError(f"Lobsters RSS item is missing {name}")
        return value

    @staticmethod
    def _string(payload: dict[str, JsonValue], key: str) -> str:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"Lobsters item is missing {key}")
        return value.strip()

    @staticmethod
    def _optional_string(payload: dict[str, JsonValue], key: str) -> str | None:
        value = payload.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _clean_html(value: str) -> str:
        return html.unescape(TAG_RE.sub(" ", value)).replace("\n", " ").strip()
