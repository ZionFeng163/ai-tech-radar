import hashlib
import html
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "source",
}
ARXIV_PATH = re.compile(r"^/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?(?:\.pdf)?$")


def normalize_title(value: str) -> str:
    decoded = html.unescape(value)
    normalized = unicodedata.normalize("NFKC", decoded).casefold().replace("_", " ")
    return " ".join(re.findall(r"[^\W_]+", normalized, flags=re.UNICODE))


def title_fingerprint(value: str) -> str:
    return hashlib.sha256(normalize_title(value).encode()).hexdigest()


def canonicalize_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    scheme = parsed.scheme.casefold() or "https"
    hostname = (parsed.hostname or "").casefold()
    if hostname == "export.arxiv.org":
        hostname = "arxiv.org"
    port = parsed.port
    if port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        hostname = f"{hostname}:{port}"

    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    arxiv_match = ARXIV_PATH.fullmatch(path) if hostname == "arxiv.org" else None
    if arxiv_match:
        path = f"/abs/{arxiv_match.group(1)}"
    elif path != "/":
        path = path.rstrip("/")

    query = urlencode(
        sorted(
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if key.casefold() not in TRACKING_PARAMETERS and not key.casefold().startswith("utm_")
        ),
        doseq=True,
    )
    return urlunsplit((scheme, hostname, path, query, ""))


def normalized_author_name(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def slugify_tag(value: str) -> str:
    normalized = normalize_title(value).replace(" ", "-")
    if normalized:
        return normalized[:100]
    return hashlib.sha256(value.encode()).hexdigest()[:16]
