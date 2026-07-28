import asyncio
import hashlib
import ipaddress
import json
import socket
from abc import ABC, abstractmethod
from html.parser import HTMLParser
from io import BytesIO
from typing import Protocol
from urllib.parse import quote, urljoin, urlparse

import httpx
from pypdf import PdfReader

from app.research.models import EvidenceCandidate, EvidenceDocument

MAX_DOCUMENT_BYTES = 30 * 1024 * 1024


class EvidenceResolutionError(RuntimeError):
    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage


class EvidenceResolver(Protocol):
    async def resolve(
        self,
        candidate: EvidenceCandidate,
        *,
        max_characters: int,
        timeout_seconds: float,
    ) -> EvidenceDocument: ...


class ContentExtractor(ABC):
    name: str

    @abstractmethod
    def supports(self, media_type: str, url: str) -> bool:
        """Return whether this extractor can process the response."""

    @abstractmethod
    def extract(self, payload: bytes, *, max_characters: int) -> str:
        """Return normalized text from the response bytes."""


class PdfExtractor(ContentExtractor):
    name = "pypdf"

    def supports(self, media_type: str, url: str) -> bool:
        return "pdf" in media_type or url.casefold().endswith(".pdf")

    def extract(self, payload: bytes, *, max_characters: int) -> str:
        if not payload.startswith(b"%PDF"):
            raise EvidenceResolutionError("extract", "document has no PDF header")
        try:
            reader = PdfReader(BytesIO(payload), strict=False)
        except Exception as error:
            raise EvidenceResolutionError("extract", f"PDF parse failed: {error}") from error
        page_count = len(reader.pages)
        priority_pages = _representative_page_indexes(page_count)
        paragraphs: list[str] = []
        total = 0
        per_page_limit = max(800, min(3_000, max_characters // max(1, len(priority_pages))))
        for page_index in priority_pages:
            try:
                text = reader.pages[page_index].extract_text() or ""
            except Exception:
                continue
            text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
            if not text:
                continue
            excerpt = text[:per_page_limit]
            paragraphs.append(f"[PDF page {page_index + 1}]\n{excerpt}")
            total += len(excerpt)
            if total >= max_characters:
                break
        return "\n\n".join(paragraphs)[:max_characters]


def _representative_page_indexes(page_count: int) -> list[int]:
    """Keep the opening argument while sampling results and conclusions."""

    if page_count <= 8:
        return list(range(page_count))
    candidates = [
        0,
        1,
        2,
        3,
        page_count // 3,
        (page_count * 2) // 3,
        page_count - 2,
        page_count - 1,
    ]
    return list(dict.fromkeys(index for index in candidates if 0 <= index < page_count))


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(
        self, tag: str, _attrs: list[tuple[str, str | None]]
    ) -> None:
        if tag in {"script", "style", "noscript", "svg", "sup"}:
            self._ignored_depth += 1
        elif tag in {"p", "br", "li", "h1", "h2", "h3", "article", "section"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg", "sup"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif tag in {"p", "li", "article", "section"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth and data.strip():
            self.parts.append(data)


class HtmlExtractor(ContentExtractor):
    name = "html-visible-text"

    def supports(self, media_type: str, url: str) -> bool:
        del url
        return "html" in media_type

    def extract(self, payload: bytes, *, max_characters: int) -> str:
        parser = _VisibleTextParser()
        parser.feed(payload.decode("utf-8", errors="replace"))
        lines = [" ".join(line.split()) for line in "".join(parser.parts).splitlines()]
        return "\n".join(line for line in lines if line)[:max_characters]


class JsonExtractor(ContentExtractor):
    name = "json"

    def supports(self, media_type: str, url: str) -> bool:
        del url
        return "json" in media_type

    def extract(self, payload: bytes, *, max_characters: int) -> str:
        try:
            value = json.loads(payload)
        except ValueError as error:
            raise EvidenceResolutionError("extract", f"JSON parse failed: {error}") from error
        return json.dumps(value, ensure_ascii=False, indent=2)[:max_characters]


class PlainTextExtractor(ContentExtractor):
    name = "plain-text"

    def supports(self, media_type: str, url: str) -> bool:
        return media_type.startswith("text/") or url.casefold().endswith(
            (".md", ".txt")
        )

    def extract(self, payload: bytes, *, max_characters: int) -> str:
        return payload.decode("utf-8", errors="replace").strip()[:max_characters]


class HttpEvidenceResolver:
    def __init__(
        self,
        extractors: tuple[ContentExtractor, ...] | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        validate_network: bool = True,
    ) -> None:
        self.extractors = extractors or (
            PdfExtractor(),
            HtmlExtractor(),
            JsonExtractor(),
            PlainTextExtractor(),
        )
        self._client = client
        self._validate_network = validate_network

    async def resolve(
        self,
        candidate: EvidenceCandidate,
        *,
        max_characters: int,
        timeout_seconds: float,
    ) -> EvidenceDocument:
        url = canonical_document_url(candidate.url)
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=False,
            headers={"User-Agent": "AI-Tech-Radar/0.1"},
        )
        try:
            payload, media_type = await self._download(client, url)
        finally:
            if owns_client:
                await client.aclose()
        extractor = next(
            (
                extractor
                for extractor in self.extractors
                if extractor.supports(media_type, url)
            ),
            None,
        )
        if extractor is None:
            raise EvidenceResolutionError(
                "extract", f"unsupported content type {media_type or 'unknown'}"
            )
        text = await asyncio.to_thread(
            extractor.extract,
            payload,
            max_characters=max_characters,
        )
        if not text.strip():
            raise EvidenceResolutionError("extract", "document contains no readable text")
        return EvidenceDocument(
            url=candidate.url,
            media_type=media_type,
            extractor=extractor.name,
            text=text.strip(),
            content_hash=hashlib.sha256(payload).hexdigest(),
        )

    async def _download(
        self, client: httpx.AsyncClient, url: str
    ) -> tuple[bytes, str]:
        current_url = url
        for _redirect_count in range(4):
            if self._validate_network:
                await _require_public_https_url(current_url)
            chunks: list[bytes] = []
            size = 0
            try:
                async with client.stream("GET", current_url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            raise EvidenceResolutionError(
                                "redirect", "redirect response has no location"
                            )
                        current_url = urljoin(current_url, location)
                        continue
                    response.raise_for_status()
                    media_type = response.headers.get("content-type", "").split(
                        ";", 1
                    )[0]
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_DOCUMENT_BYTES:
                            raise EvidenceResolutionError(
                                "download", "document exceeds 30 MB"
                            )
                        chunks.append(chunk)
            except httpx.HTTPError as error:
                raise EvidenceResolutionError("download", str(error)) from error
            return b"".join(chunks), media_type.casefold()
        raise EvidenceResolutionError("redirect", "too many redirects")


def canonical_document_url(value: str) -> str:
    parsed = urlparse(value)
    if (parsed.hostname or "").casefold() != "github.com":
        return value
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) < 5 or parts[2] != "blob":
        return value
    owner, repository, _, reference, *document_path = parts
    encoded_path = "/".join(quote(part, safe="") for part in document_path)
    return (
        "https://raw.githubusercontent.com/"
        f"{quote(owner, safe='')}/{quote(repository, safe='')}/"
        f"{quote(reference, safe='')}/{encoded_path}"
    )


async def _require_public_https_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise EvidenceResolutionError("policy", "only public HTTPS documents are allowed")
    hostname = parsed.hostname.casefold()
    if hostname in {"localhost", "localhost.localdomain"}:
        raise EvidenceResolutionError("policy", "local document hosts are not allowed")
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        try:
            addresses = await asyncio.to_thread(
                socket.getaddrinfo,
                hostname,
                443,
                type=socket.SOCK_STREAM,
            )
        except OSError as error:
            raise EvidenceResolutionError("resolve", str(error)) from error
        resolved = {ipaddress.ip_address(item[4][0]) for item in addresses}
    else:
        resolved = {literal}
    if not resolved or any(not address.is_global for address in resolved):
        raise EvidenceResolutionError("policy", "document host resolved to a private address")
