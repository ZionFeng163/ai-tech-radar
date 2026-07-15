import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse
from xml.etree import ElementTree

from pydantic import JsonValue

ATOM = "http://www.w3.org/2005/Atom"
ARXIV = "http://arxiv.org/schemas/atom"
OPENSEARCH = "http://a9.com/-/spec/opensearch/1.1/"
VERSION_PATTERN = re.compile(r"v(?P<version>\d+)$")


@dataclass(frozen=True, slots=True)
class ParsedFeed:
    total_results: int
    start_index: int
    items_per_page: int
    entries: list[dict[str, JsonValue]]


def _text(element: ElementTree.Element, path: str) -> str | None:
    value = element.findtext(path)
    return value.strip() if value and value.strip() else None


def _compact(value: str | None) -> str | None:
    return " ".join(value.split()) if value else None


def _integer(root: ElementTree.Element, path: str, default: int) -> int:
    value = _text(root, path)
    return int(value) if value is not None else default


def _identifier(versioned_id: str) -> tuple[str, int | None]:
    path = urlparse(versioned_id).path.rstrip("/")
    value = path.split("/abs/", 1)[-1].lstrip("/")
    match = VERSION_PATTERN.search(value)
    if match is None:
        return value, None
    return value[: match.start()], int(match.group("version"))


def parse_datetime(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_feed(xml: bytes | str) -> ParsedFeed:
    root = ElementTree.fromstring(xml)
    entries: list[dict[str, JsonValue]] = []

    for entry in root.findall(f"{{{ATOM}}}entry"):
        versioned_id = _text(entry, f"{{{ATOM}}}id")
        if versioned_id is None:
            continue
        external_id, version = _identifier(versioned_id)

        links: dict[str, str] = {}
        for link in entry.findall(f"{{{ATOM}}}link"):
            href = link.get("href")
            relation = link.get("rel", "alternate")
            title = link.get("title")
            media_type = link.get("type")
            if href is None:
                continue
            if title == "pdf" or media_type == "application/pdf":
                links["pdf"] = href
            elif relation == "license":
                links["license"] = href
            elif relation == "alternate":
                links["detail"] = href

        authors: list[JsonValue] = [
            {"name": name}
            for author in entry.findall(f"{{{ATOM}}}author")
            if (name := _compact(_text(author, f"{{{ATOM}}}name"))) is not None
        ]
        categories: list[JsonValue] = [
            term
            for category in entry.findall(f"{{{ATOM}}}category")
            if (term := category.get("term")) is not None
        ]
        primary_category = entry.find(f"{{{ARXIV}}}primary_category")
        detail_url = links.get("detail", versioned_id)

        payload: dict[str, JsonValue] = {
            "external_id": external_id,
            "versioned_id": f"{external_id}v{version}" if version is not None else external_id,
            "version": version,
            "detail_url": detail_url,
            "pdf_url": links.get("pdf"),
            "title": _compact(_text(entry, f"{{{ATOM}}}title")),
            "summary": _compact(_text(entry, f"{{{ATOM}}}summary")),
            "authors": authors,
            "categories": categories,
            "primary_category": (
                primary_category.get("term") if primary_category is not None else None
            ),
            "published": _text(entry, f"{{{ATOM}}}published"),
            "updated": _text(entry, f"{{{ATOM}}}updated"),
            "license": links.get("license"),
            "doi": _text(entry, f"{{{ARXIV}}}doi"),
            "journal_ref": _compact(_text(entry, f"{{{ARXIV}}}journal_ref")),
            "comment": _compact(_text(entry, f"{{{ARXIV}}}comment")),
        }
        entries.append(payload)

    return ParsedFeed(
        total_results=_integer(root, f"{{{OPENSEARCH}}}totalResults", len(entries)),
        start_index=_integer(root, f"{{{OPENSEARCH}}}startIndex", 0),
        items_per_page=_integer(root, f"{{{OPENSEARCH}}}itemsPerPage", len(entries)),
        entries=entries,
    )
