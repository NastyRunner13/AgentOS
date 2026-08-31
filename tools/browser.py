"""Playwright Chromium session: navigate, snapshot, click, type, close."""

from __future__ import annotations


class Browser:
    def __init__(self, perm_cfg: dict, clip=None) -> None:
        self.perm_cfg = perm_cfg
        self._clip = clip
        self._browser = None
        self._page = None

    async def run(self, args: dict) -> str:
        action = str(args.get("action", "snapshot"))
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return "playwright not installed"
        headless = bool(self.perm_cfg.get("browser", {}).get("headless", False))
        if action == "close":
            if self._browser:
                await self._browser.close()
                self._browser = None
                self._page = None
            return "closed"
        if self._browser is None:
            pw = await async_playwright().start()
            self._browser = await pw.chromium.launch(headless=headless)
            self._page = await self._browser.new_page()
        page = self._page
        if action == "navigate":
            url = str(args.get("url", ""))
            await page.goto(url)
            return f"navigated {page.url}"
        if action == "snapshot":
            text = await page.locator("body").inner_text()
            if self._clip:
                text = self._clip(text)
            return f'<untrusted source="web">\n{text}\n</untrusted>'
        if action == "click":
            await page.locator(str(args.get("ref", "body"))).first.click()
            return "clicked"
        if action == "type":
            await page.locator(str(args.get("ref", "body"))).first.fill(str(args.get("text", "")))
            return "typed"
        return f"unknown browser action {action}"
