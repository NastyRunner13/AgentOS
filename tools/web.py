"""Public web search and fetch. Payloads are untrusted."""

from __future__ import annotations

import json
import os
from urllib.parse import urlencode, urljoin, urlparse

import httpx

from tools.web_html import blocked_url, html_to_text, parse_ddg, slice_pattern, wrap_untrusted

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
