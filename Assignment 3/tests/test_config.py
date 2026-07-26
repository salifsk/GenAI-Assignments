import importlib

import dotenv


def test_default_target_url_is_saucedemo(monkeypatch):
    monkeypatch.delenv("TARGET_URL", raising=False)
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args, **kwargs: None)

    import config

    importlib.reload(config)
    assert config.TARGET_URL == "https://www.saucedemo.com/"
