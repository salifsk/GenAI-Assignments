"""
Scraper Agent
-------------
Uses a lightweight Playwright MCP-style adapter to discover interactive
controls on a target web page and save a machine-readable locator map.
The workflow is now generic and can work for many websites, not only
SauceDemo.
"""
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from agents.playwright_mcp_bridge import PlaywrightMcpBridge
from config import TARGET_URL, LOCATORS_DIR, HEADLESS


def _slugify(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/").replace("/", "_").replace("-", "_")
    path = re.sub(r"[^0-9a-zA-Z_]+", "_", path).strip("_")
    return path or "home"


def scrape_page(bridge: PlaywrightMcpBridge, page_name: str, url: str):
    bridge.goto(url)
    elements = bridge.list_interactive_elements()

    seen = set()
    unique = []
    for element in elements:
        if element["locator"] in seen:
            continue
        seen.add(element["locator"])
        unique.append(element)

    if not unique:
        unique.append(
            {
                "tag": "body",
                "locator": "body",
                "text": "fallback",
                "type": None,
            }
        )

    out_path = Path(LOCATORS_DIR) / f"{page_name}.json"
    out_path.write_text(json.dumps(unique, indent=2))
    print(f"[scraper] saved {len(unique)} locators -> {out_path}")
    return unique


def run():
    bridge = PlaywrightMcpBridge(headless=HEADLESS)
    try:
        discovered_urls = [TARGET_URL]
        discovered_urls.extend(bridge.discover_links(TARGET_URL, limit=3))

        seen_urls = set()
        for index, url in enumerate(discovered_urls, start=1):
            if url in seen_urls:
                continue
            seen_urls.add(url)
            page_name = f"page_{index}_{_slugify(url)}"
            scrape_page(bridge, page_name, url)
    finally:
        bridge.stop()


if __name__ == "__main__":
    run()
