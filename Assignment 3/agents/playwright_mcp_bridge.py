"""A small Playwright MCP-style adapter for browser automation.

This keeps the agent workflow generic while still providing an MCP-like tool
surface for the scraper and future agents: goto, list_interactive_elements,
click, fill, and select.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from playwright.sync_api import sync_playwright


class PlaywrightMcpBridge:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self._playwright = None
        self._browser = None
        self.page = None

    def start(self):
        if self.page is not None:
            return self.page

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self.page = self._browser.new_page()
        return self.page

    def stop(self):
        if self.page is not None:
            try:
                self.page.close()
            except Exception:
                pass
            self.page = None
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._playwright is not None:
            try:
                self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

    def goto(self, url: str) -> str:
        page = self.start()
        # increase timeouts for slower sites
        page.set_default_timeout(20000)
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        try:
            page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            # networkidle can fail on dynamic sites; give a short pause
            try:
                page.wait_for_timeout(1000)
            except Exception:
                pass
        return page.url

    def list_interactive_elements(self) -> List[Dict[str, Any]]:
        page = self.start()
        elements: List[Dict[str, Any]] = []
        # Common interactive tags
        for tag in ["button", "a", "input", "select", "textarea", "summary"]:
            for el in page.query_selector_all(tag):
                try:
                    if not el.is_visible():
                        continue
                    locator = self._best_locator(el)
                    if not locator:
                        continue
                    elements.append(
                        {
                            "tag": tag,
                            "locator": locator,
                            "text": (el.inner_text() or "").strip()[:80],
                            "type": el.get_attribute("type"),
                        }
                    )
                except Exception:
                    continue

        # role-based interactive elements
        for selector in ["[role='button']", "[role='link']"]:
            for el in page.query_selector_all(selector):
                try:
                    if not el.is_visible():
                        continue
                    locator = self._best_locator(el)
                    if not locator:
                        continue
                    elements.append(
                        {
                            "tag": selector,
                            "locator": locator,
                            "text": (el.inner_text() or "").strip()[:80],
                            "type": el.get_attribute("role"),
                        }
                    )
                except Exception:
                    continue

        return elements

    def click(self, locator: str) -> None:
        self.start().locator(locator).click()

    def fill(self, locator: str, value: str) -> None:
        self.start().locator(locator).fill(value)

    def select(self, locator: str, value: str) -> None:
        self.start().locator(locator).select_option(value)

    def discover_links(self, base_url: str, limit: int = 4) -> List[str]:
        page = self.start()
        found: List[str] = []
        seen = set()
        queue = [base_url]
        while queue and len(found) < limit:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)

            try:
                self.goto(current)
            except Exception:
                found.append(current)
                continue

            for anchor in page.query_selector_all("a"):
                try:
                    href = anchor.get_attribute("href")
                    if not href or href.startswith(("mailto:", "javascript:")):
                        continue
                    if href.strip().startswith("#"):
                        # skip same-page anchors
                        continue
                    absolute = urljoin(current, href)
                    parsed = urlparse(absolute)
                    if parsed.netloc and parsed.netloc != urlparse(base_url).netloc:
                        continue
                    if not absolute.startswith(("http://", "https://")):
                        continue
                    normalized = absolute.split("#", 1)[0]
                    if not normalized:
                        continue
                    if normalized not in seen:
                        queue.append(normalized)
                except Exception:
                    continue
            found.append(current)
        return found

    def _best_locator(self, element) -> Optional[str]:
        # Prefer stable attributes in this order: data-test, id, name, aria-label,
        # title, alt, href (for anchors), then class and finally visible text.
        try:
            data_test = element.get_attribute("data-test")
            if data_test:
                return f'[data-test="{data_test}"]'

            el_id = element.get_attribute("id")
            if el_id:
                return f"#{el_id}"

            name = element.get_attribute("name")
            if name:
                return f'[name="{name}"]'

            aria = element.get_attribute("aria-label")
            if aria:
                return f'[aria-label="{aria}"]'

            title = element.get_attribute("title")
            if title:
                return f'[title="{title}"]'

            alt = element.get_attribute("alt")
            if alt:
                return f'[alt="{alt}"]'

            href = element.get_attribute("href")
            tag_name = (element.evaluate("e => e.tagName") or "").lower()
            if href and tag_name == "a":
                href = href.strip()
                if href:
                    return f'a[href*="{href}"]'

            class_attr = element.get_attribute("class")
            if class_attr:
                first_class = class_attr.split()[0]
                if first_class:
                    # make a simple single-class selector
                    return f".{first_class}"

            text = (element.inner_text() or "").strip()
            if text:
                return f'text="{text[:40]}"'
        except Exception:
            return None
        return None
