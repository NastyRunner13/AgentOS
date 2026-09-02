"""Playwright Chromium session: navigate, snapshot, click, type, upload, wait, screenshot, close."""

from __future__ import annotations

import asyncio
from pathlib import Path


class Browser:
    def __init__(self, perm_cfg: dict, clip=None) -> None:
        self.perm_cfg = perm_cfg
        self._clip = clip
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    async def _close_session(self) -> None:
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw:
            try:
                await self._pw.stop()
            except Exception:
                pass
            self._pw = None
        self._page = None

    def _is_alive(self) -> bool:
        if self._page is None:
            return False
        try:
            if hasattr(self._page, "is_closed") and self._page.is_closed():
                if self._context and hasattr(self._context, "pages") and self._context.pages:
                    self._page = self._context.pages[0]
                    return not (hasattr(self._page, "is_closed") and self._page.is_closed())
                return False
        except Exception:
            return False
        return True

    async def _init_session(self) -> str | None:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return "playwright not installed"

        b_cfg = self.perm_cfg.get("browser") or {}
        headless = bool(b_cfg.get("headless", False))
        cdp_url = b_cfg.get("cdp_url")
        user_data_dir = b_cfg.get("user_data_dir")

        if self._pw is None:
            self._pw = await async_playwright().start()

        if cdp_url:
            self._browser = await self._pw.chromium.connect_over_cdp(str(cdp_url))
            contexts = self._browser.contexts
            self._context = contexts[0] if contexts else await self._browser.new_context()
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        elif user_data_dir:
            profile_path = Path(user_data_dir).resolve()
            profile_path.mkdir(parents=True, exist_ok=True)
            self._context = await self._pw.chromium.launch_persistent_context(
                user_data_dir=str(profile_path),
                headless=headless,
            )
            self._browser = None
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
        else:
            self._browser = await self._pw.chromium.launch(headless=headless)
            self._context = await self._browser.new_context()
            self._page = await self._context.new_page()

        # Handle alert / confirm dialogs without blocking
        self._page.on("dialog", lambda dialog: asyncio.create_task(dialog.accept()))
        return None

    async def run(self, args: dict) -> str:
        action = str(args.get("action", "snapshot"))
        if action == "close":
            await self._close_session()
            return "closed"

        if not self._is_alive():
            await self._close_session()
            err = await self._init_session()
            if err:
                return err

        try:
            return await self._dispatch(action, args)
        except Exception as e:
            if "closed" in str(e).lower():
                await self._close_session()
            raise

    async def _dispatch(self, action: str, args: dict) -> str:
        page = self._page
        if action == "navigate":
            url = str(args.get("url", "")).strip()
            if not url:
                return "empty url"
            if url != "about:blank":
                from tools.web import blocked_url
                reason = blocked_url(url)
                if reason:
                    return f"blocked url: {reason}"
            try:
                await page.goto(url)
            except Exception as e:
                if "closed" in str(e).lower():
                    await self._close_session()
                    err = await self._init_session()
                    if err:
                        return f"failed to reopen browser: {err}"
                    await self._page.goto(url)
                    return f"navigated {self._page.url}"
                raise
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
        if action == "upload":
            ref = str(args.get("ref") or 'input[type="file"]')
            path = str(args.get("path") or "").strip()
            if not path:
                return "missing path for upload"
            target_path = Path(path).resolve()
            if not target_path.exists():
                return f"upload file not found: {path}"
            await page.locator(ref).first.set_input_files(str(target_path))
            return f"uploaded {target_path.name}"
        if action == "wait":
            ref = args.get("ref")
            timeout = float(args.get("timeout") or 10.0) * 1000
            if ref:
                await page.locator(str(ref)).first.wait_for(timeout=timeout)
                return f"waited for {ref}"
            await page.wait_for_load_state("networkidle", timeout=timeout)
            return "waited for networkidle"
        if action == "screenshot":
            save_path = args.get("path")
            if save_path:
                p = Path(str(save_path)).resolve()
                p.parent.mkdir(parents=True, exist_ok=True)
                await page.screenshot(path=str(p))
                return f"screenshot saved to {p}"
            shot_bytes = await page.screenshot()
            return f'<untrusted source="web_screenshot">\n[screenshot captured: {len(shot_bytes)} bytes]\n</untrusted>'
        return f"unknown browser action {action}"

