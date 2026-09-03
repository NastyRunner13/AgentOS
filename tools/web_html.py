"""HTML extraction, URL blocks, and DuckDuckGo result parsing."""

from __future__ import annotations

import html
import ipaddress
import re
import socket
from html.parser import HTMLParser
from urllib.parse import parse_qs, unquote, urlparse

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
