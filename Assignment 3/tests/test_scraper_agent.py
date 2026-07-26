import agents.scraper_agent as scraper_agent


class FakeBridge:
    def __init__(self):
        self.visited = []

    def goto(self, url):
        self.visited.append(url)

    def list_interactive_elements(self):
        return []

    def discover_links(self, base_url, limit=3):
        return []

    def stop(self):
        return None


def test_scraper_falls_back_to_target_url_when_discovery_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper_agent, "LOCATORS_DIR", tmp_path)
    monkeypatch.setattr(scraper_agent, "TARGET_URL", "https://example.com")
    monkeypatch.setattr(scraper_agent, "PlaywrightMcpBridge", lambda *args, **kwargs: FakeBridge())

    scraper_agent.run()

    saved = tmp_path / "page_1_home.json"
    assert saved.exists()
    payload = saved.read_text()
    assert '"locator": "body"' in payload
