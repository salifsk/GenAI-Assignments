import json


def test_generator_cleans_previous_test_files(tmp_path, monkeypatch):
    import agents.generator_agent as generator_agent

    monkeypatch.setattr(generator_agent, "GENERATED_TESTS_DIR", tmp_path)
    locators_dir = tmp_path / "locators"
    locators_dir.mkdir()
    monkeypatch.setattr(generator_agent, "LOCATORS_DIR", locators_dir)

    stale_file = tmp_path / "test_old_page.py"
    stale_file.write_text("print('stale')\n")

    (locators_dir / "page_1.json").write_text(json.dumps([{"locator": "#submit"}]))

    generator_agent.run()

    assert not stale_file.exists()
    assert (tmp_path / "test_page_1.py").exists()
