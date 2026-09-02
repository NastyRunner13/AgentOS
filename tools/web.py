"""Public web search and fetch. Payloads are untrusted."""

from __future__ import annotations

import html
import ipaddress
import json
import os
import re
import socket
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlencode, urljoin, urlparse

import httpx

SEARCH_URL = "https://html.duckduckgo.com/html/"
BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
_BLOCK_MARKERS = (
    "anomaly-modal",
    "anomaly.js",
    "not a robot",
    "/wr.do?",
    "detected unusual traffic",
)
_SKIP_TAGS = frozenset({"script", "style", "noscript", "svg", "nav", "footer"})
_SPACE_RE = re.compile(r"[ \t]+")
_BLANK_RE = re.compile(r"\n\s*\n+")


def _is_ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast)


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
        if _is_ip_blocked(ip):
            return "blocked host"
        return None
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:
        return None
    for info in infos:
        sockaddr = info[4]
        try:
            ip = ipaddress.ip_address(sockaddr[0])
            if _is_ip_blocked(ip):
                return "blocked host"
        except ValueError:
            continue
    return None


def wrap_untrusted(body: str, *, url: str = "") -> str:
    attr = f' url="{html.escape(url, quote=True)}"' if url else ""
    return f'<untrusted source="web"{attr}>\n{body}\n</untrusted>'


class _ToText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self._pre = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
            return
        if self._skip:
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.parts.append(f"\n\n{'#' * int(tag[1])} ")
        elif tag == "br":
            self.parts.append("\n")
        elif tag in ("p", "div", "tr", "section", "article", "blockquote"):
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag == "pre":
            self._pre += 1
            self.parts.append("\n```\n")
        elif tag == "code" and not self._pre:
            self.parts.append("`")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
            return
        if self._skip:
            return
        if tag == "pre":
            self._pre = max(0, self._pre - 1)
            self.parts.append("\n```\n")
        elif tag == "code" and not self._pre:
            self.parts.append("`")
        elif tag in ("p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "table"):
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip or not data:
            return
        if self._pre:
            self.parts.append(data)
        else:
            self.parts.append(_SPACE_RE.sub(" ", data))


def html_to_text(raw: str) -> str:
    parser = _ToText()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        pass
    text = "".join(parser.parts)
    text = html.unescape(text)
    return _BLANK_RE.sub("\n\n", text).strip()


def slice_pattern(text: str, pattern: str, *, context: int = 10, max_hits: int = 20) -> str:
    try:
        rx = re.compile(pattern, re.I)
    except re.error as exc:
        return f"invalid pattern: {exc}"
    lines = text.splitlines()
    if not lines:
        return "no matches"
    used = [False] * len(lines)
    chunks: list[str] = []
    for i, line in enumerate(lines):
        if used[i] or not rx.search(line):
            continue
        start = max(0, i - context)
        end = min(len(lines), i + context + 1)
        for j in range(start, end):
            used[j] = True
        chunks.append("\n".join(lines[start:end]))
        if len(chunks) >= max_hits:
            break
    if not chunks:
        return "no matches"
    return f"{len(chunks)} match(es)\n\n" + "\n\n---\n\n".join(chunks)


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
    ua = str(_web_cfg(perm_cfg).get("user_agent") or _DEFAULT_UA)
    return {"User-Agent": ua}


def _timeout(perm_cfg: dict) -> float:
    return float(_web_cfg(perm_cfg).get("fetch_timeout_seconds") or 20)


def _clip(text: str, clip) -> str:
    return clip(text) if clip else text


def _compose_query(query: str, site: str) -> str:
    query = (query or "").strip()
    host = (site or "").strip().lower().removeprefix("site:").strip().strip("/")
    if host and f"site:{host}" not in query.lower():
        query = f"{query} site:{host}".strip()
    return query


def _pack(hits: list[dict[str, str]], limit: int) -> list[dict]:
    out: list[dict] = []
    for i, hit in enumerate(hits[: max(1, limit)], 1):
        url = hit.get("url") or ""
        out.append(
            {
                "n": i,
                "title": hit.get("title") or "",
                "url": url,
                "domain": urlparse(url).hostname or "",
                "snippet": hit.get("snippet") or "",
            }
        )
    return out


def _ddg_blocked(status: int, raw: str) -> bool:
    if status in (202, 403, 429) or status >= 500:
        return True
    body = (raw or "").lower()
    return any(marker in body for marker in _BLOCK_MARKERS)


async def _http(
    method: str,
    url: str,
    *,
    data: dict | None = None,
    headers: dict | None = None,
    timeout: float = 20.0,
    max_redirects: int = 5,
) -> tuple[int, str, str]:
    curr_url = url
    curr_method = method
    curr_data = data
    async with httpx.AsyncClient(follow_redirects=False, timeout=timeout) as client:
        for _ in range(max_redirects + 1):
            resp = await client.request(curr_method, curr_url, data=curr_data, headers=headers)
            if resp.is_redirect and "location" in resp.headers:
                curr_url = urljoin(curr_url, str(resp.headers["location"]))
                blocked = blocked_url(curr_url)
                if blocked:
                    raise RuntimeError(f"blocked redirect: {blocked}")
                curr_method = "GET"
                curr_data = None
                continue
            ctype = resp.headers.get("content-type") or ""
            return resp.status_code, resp.text, ctype
        raise RuntimeError("too many redirects")


async def _search_ddg(query: str, perm_cfg: dict, limit: int) -> tuple[list[dict[str, str]], str]:
    try:
        status, raw, _ctype = await _http(
            "POST",
            SEARCH_URL,
            data={"q": query},
            headers=_headers(perm_cfg),
            timeout=_timeout(perm_cfg),
        )
    except Exception as exc:
        return [], f"search error: {exc}"
    if _ddg_blocked(status, raw):
        return [], "search blocked: duckduckgo interstitial"
    if status >= 400:
        return [], f"search http {status}"
    return parse_ddg(raw)[: max(1, limit)], ""


async def _search_brave(query: str, perm_cfg: dict, limit: int) -> tuple[list[dict[str, str]], str]:
    env_name = str(_web_cfg(perm_cfg).get("brave_api_key_env") or "BRAVE_API_KEY")
    key = os.environ.get(env_name) or ""
    if not key:
        return [], "brave search needs BRAVE_API_KEY"
    url = BRAVE_URL + "?" + urlencode({"q": query, "count": max(1, min(int(limit), 20))})
    headers = {
        **_headers(perm_cfg),
        "Accept": "application/json",
        "X-Subscription-Token": key,
    }
    try:
        status, raw, _ctype = await _http(
            "GET",
            url,
            headers=headers,
            timeout=_timeout(perm_cfg),
        )
    except Exception as exc:
        return [], f"search error: {exc}"
    if status >= 400:
        return [], f"search http {status}"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return [], "search error: invalid brave json"
    results = ((data.get("web") or {}).get("results")) or []
    hits: list[dict[str, str]] = []
    for item in results:
        title = str(item.get("title") or "").strip()
        href = str(item.get("url") or "").strip()
        if title and href:
            hits.append(
                {
                    "title": title,
                    "url": href,
                    "snippet": str(item.get("description") or "").strip(),
                }
            )
    return hits[: max(1, limit)], ""


async def _search_provider(
    name: str, query: str, perm_cfg: dict, limit: int
) -> tuple[list[dict[str, str]], str]:
    name = (name or "duckduckgo").strip().lower() or "duckduckgo"
    if name in ("duckduckgo", "ddg"):
        return await _search_ddg(query, perm_cfg, limit)
    if name == "brave":
        return await _search_brave(query, perm_cfg, limit)
    return [], f"unknown search provider {name}"


def _limit(perm_cfg: dict, raw) -> int:
    if raw is None or raw == "":
        raw = _web_cfg(perm_cfg).get("search_max_results") or 5
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 5
    return max(1, min(n, 20))


async def search(query: str, perm_cfg: dict, clip=None, **opts) -> str:
    query = _compose_query(query, str(opts.get("site") or ""))
    if not query:
        return wrap_untrusted("empty query")
    limit = _limit(perm_cfg, opts.get("max_results"))
    cfg = _web_cfg(perm_cfg)
    provider = str(cfg.get("provider") or "duckduckgo").strip().lower() or "duckduckgo"
    fallback = str(cfg.get("fallback") or "").strip().lower()
    hits, err = await _search_provider(provider, query, perm_cfg, limit)
    if not hits and err and fallback and fallback != provider:
        hits2, err2 = await _search_provider(fallback, query, perm_cfg, limit)
        if hits2:
            hits, err = hits2, ""
        elif err2:
            if "needs BRAVE_API_KEY" in err2:
                err = f"{err}; {fallback} fallback needs BRAVE_API_KEY" if err else err2
            else:
                err = f"{err}; fallback {fallback}: {err2}" if err else err2
    if err and not hits:
        return wrap_untrusted(_clip(err, clip))
    packed = _pack(hits, limit)
    body = json.dumps(packed, ensure_ascii=False) if packed else "no results"
    return wrap_untrusted(_clip(body, clip))


async def fetch(url: str, perm_cfg: dict, clip=None, **opts) -> str:
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
    lead = raw.lstrip()[:32].lower()
    if "html" in (ctype or "").lower() or lead.startswith("<!doctype") or lead.startswith("<html"):
        text = html_to_text(raw)
    else:
        text = raw
    pattern = str(opts.get("pattern") or "").strip()
    if pattern:
        text = slice_pattern(text, pattern)
    return wrap_untrusted(_clip(text, clip), url=url)
