from agents.playwright_mcp_bridge import PlaywrightMcpBridge


class FakeAnchor:
    def __init__(self, href):
        self._href = href

    def get_attribute(self, attr):
        if attr == "href":
            return self._href
        return None


class FakePage:
    def __init__(self, hrefs):
        self._hrefs = hrefs

    def query_selector_all(self, selector):
        if selector != "a":
            return []
        return [FakeAnchor(href) for href in self._hrefs]

    def goto(self, *args, **kwargs):
        return None

    def wait_for_load_state(self, *args, **kwargs):
        return None

    def wait_for_timeout(self, *args, **kwargs):
        return None

    def set_default_timeout(self, *args, **kwargs):
        return None


def test_discover_links_ignores_hash_links(monkeypatch):
    bridge = PlaywrightMcpBridge(headless=True)
    fake_page = FakePage(["#", "/about"])

    monkeypatch.setattr(bridge, "start", lambda: fake_page)
    monkeypatch.setattr(bridge, "goto", lambda url: None)

    links = bridge.discover_links("https://example.com", limit=2)

    assert "https://example.com" in links
    assert "https://example.com/about" in links
    assert "#" not in links
