"""Public web search (DuckDuckGo HTML) and fetch. Payloads are untrusted."""

from __future__ import annotations

import html
import ipaddress
import json
import re
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

import httpx

SEARCH_URL = "https://html.duckduckgo.com/html/"
_HTML_RE = re.compile(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>")
_BR_RE = re.compile(r"(?is)<br\s*/?>")
_P_RE = re.compile(r"(?is)</p>")
_TAG_RE = re.compile(r"(?is)<[^>]+>")
_SPACE_RE = re.compile(r"[ \t]+")
_BLANK_RE = re.compile(r"\n\s*\n+")


def blocked_url(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except Exception:
        return "invalid url"
    if parsed.scheme not in ("http", "https"):
        return f"blocked scheme {parsed.scheme or '(none)'}"
    host = (parsed.hostname or "").lower()
    if not host:
        return "missing host"
    if host in ("localhost", "::1", "0.0.0.0") or host.endswith(".localhost"):
        return "blocked host"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
        return "blocked host"
    return None


def wrap_untrusted(body: str, *, url: str = "") -> str:
    attr = f' url="{html.escape(url, quote=True)}"' if url else ""
    return f'<untrusted source="web"{attr}>\n{body}\n</untrusted>'


def html_to_text(raw: str) -> str:
    raw = _HTML_RE.sub(" ", raw)
    raw = _BR_RE.sub("\n", raw)
    raw = _P_RE.sub("\n", raw)
    raw = _TAG_RE.sub(" ", raw)
    raw = html.unescape(raw)
    raw = _SPACE_RE.sub(" ", raw)
    raw = _BLANK_RE.sub("\n\n", raw)
    return raw.strip()


def _ddg_url(href: str) -> str:
    href = html.unescape(href or "")
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    qs = parse_qs(parsed.query)
    if "uddg" in qs:
        return unquote(qs["uddg"][0])
    return href


class _DDGResults(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_title = False
        self._in_snippet = False
        self._href = ""
        self._title: list[str] = []
        self._snippet: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        d = {k: (v or "") for k, v in attrs}
        cls = d.get("class", "")
        if tag == "a" and "result__a" in cls:
            self._in_title = True
            self._href = d.get("href", "")
            self._title = []
        elif "result__snippet" in cls:
            self._in_snippet = True
            self._snippet = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
            title = "".join(self._title).strip()
            url = _ddg_url(self._href)
            if title and url:
                self.results.append({"title": title, "url": url, "snippet": ""})
        if self._in_snippet and tag in ("a", "td", "div", "span"):
            self._in_snippet = False
            snippet = "".join(self._snippet).strip()
            if self.results and not self.results[-1]["snippet"]:
                self.results[-1]["snippet"] = snippet

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title.append(data)
        elif self._in_snippet:
            self._snippet.append(data)


def parse_ddg(raw: str) -> list[dict[str, str]]:
    parser = _DDGResults()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        return parser.results
    return parser.results


def _web_cfg(perm_cfg: dict) -> dict:
    return perm_cfg.get("web") or {}


def _headers(perm_cfg: dict) -> dict[str, str]:
    ua = str(_web_cfg(perm_cfg).get("user_agent") or "AgentOS/0.1")
    return {"User-Agent": ua}


def _timeout(perm_cfg: dict) -> float:
    return float(_web_cfg(perm_cfg).get("fetch_timeout_seconds") or 20)


def _clip(text: str, clip) -> str:
    return clip(text) if clip else text


async def _http(
    method: str,
    url: str,
    *,
    data: dict | None = None,
    headers: dict | None = None,
    timeout: float = 20.0,
) -> tuple[int, str, str]:
    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        resp = await client.request(method, url, data=data, headers=headers)
        ctype = resp.headers.get("content-type") or ""
        return resp.status_code, resp.text, ctype


async def search(query: str, perm_cfg: dict, clip=None) -> str:
    query = (query or "").strip()
    if not query:
        return wrap_untrusted("empty query")
    limit = int(_web_cfg(perm_cfg).get("search_max_results") or 5)
    try:
        status, raw, _ctype = await _http(
            "POST",
            SEARCH_URL,
            data={"q": query},
            headers=_headers(perm_cfg),
            timeout=_timeout(perm_cfg),
        )
    except Exception as exc:
        return wrap_untrusted(f"search error: {exc}")
    if status >= 400:
        return wrap_untrusted(f"search http {status}")
    hits = parse_ddg(raw)[: max(1, limit)]
    body = json.dumps(hits, ensure_ascii=False) if hits else "no results"
    return wrap_untrusted(_clip(body, clip))


async def fetch(url: str, perm_cfg: dict, clip=None) -> str:
    url = (url or "").strip()
    if not url:
        return wrap_untrusted("empty url")
    reason = blocked_url(url)
    if reason:
        return wrap_untrusted(reason, url=url)
    try:
        status, raw, ctype = await _http(
            "GET",
            url,
            headers=_headers(perm_cfg),
            timeout=_timeout(perm_cfg),
        )
    except Exception as exc:
        return wrap_untrusted(f"fetch error: {exc}", url=url)
    if status >= 400:
        return wrap_untrusted(f"fetch http {status}", url=url)
    if "html" in (ctype or "").lower() or (raw.lstrip()[:32].lower().startswith("<!doctype") or raw.lstrip()[:6].lower().startswith("<html")):
        text = html_to_text(raw)
    else:
        text = raw
    return wrap_untrusted(_clip(text, clip), url=url)
