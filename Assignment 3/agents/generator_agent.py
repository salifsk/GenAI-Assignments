"""
Test Generator Agent
---------------------
Reads scraped locator maps and generates pytest + Playwright tests for each
page.

Primary path: send the locators to Groq (LLM) and let it write the test
functions. If GROQ_API_KEY is missing, or the API call fails for any
reason (network issue, rate limit, bad response), we fall back to a
built-in generic template so the pipeline never hard-fails just because
the LLM step had a problem.
"""
import json
import ast
import re
from pathlib import Path

from groq import Groq

from config import LOCATORS_DIR, GENERATED_TESTS_DIR, GROQ_API_KEY, GROQ_MODEL, TARGET_URL

SYSTEM_PROMPT = """You are a senior QA automation engineer. Given a JSON list of
locators found on a web page, write pytest test functions using Playwright's
sync API.

Rules:
- A fixture named `page` is already available to every test function.
- Do not define or override any fixture named `page`.
- Import `from playwright.sync_api import expect` at the top of the file.
- Write standalone test code that does not read files or depend on page-specific
  assumptions.
- Hardcode the given target URL directly as a string literal in every test's
  page.goto(...) call.
- Many modern pages (e.g. Amazon-style sites) never reach a true "network idle"
  state because of background ads/tracking/analytics traffic. Therefore:
    - Always call page.goto(url, wait_until="domcontentloaded", timeout=20000).
    - Never call page.wait_for_load_state("networkidle") without wrapping it in
      a try/except with a short timeout (<= 5000ms), since it may never resolve.
- When asserting a locator is visible, use `.first` on the locator (e.g.
  expect(page.locator(selector).first).to_be_visible()) since many selectors
  match more than one element on real-world pages.
- Wrap individual locator-visibility checks in try/except so one missing or
  stale locator does not fail the whole test; keep at least one hard assertion
  (e.g. that the page has at least one interactive element) unwrapped so the
  test can still meaningfully fail.
- Output ONLY valid, runnable Python code. No markdown fences, no prose.
- Every test function name must start with test_
"""


def _client():
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set. Add it to your .env file.")
    return Groq(api_key=GROQ_API_KEY)


def _clean_generated_code(code: str) -> str:
    """Trim trailing non-Python text from the LLM response."""
    code = code.replace("```python", "").replace("```", "").strip()
    lines = code.splitlines()
    for end in range(len(lines), 0, -1):
        candidate = "\n".join(lines[:end])
        try:
            ast.parse(candidate)
            return candidate.strip()
        except SyntaxError:
            continue
    raise ValueError("Unable to extract valid Python code from the LLM response.")


def _sanitize_page_name(page_name: str) -> str:
    return re.sub(r"[^0-9a-zA-Z_]+", "_", page_name).strip("_") or "page"


def _generate_with_groq(page_name: str, locators: list[dict], target_url: str) -> str:
    client = _client()
    user_prompt = (
        f"Page name: {page_name}\n"
        f"Target URL: {target_url}\n"
        f"Locators discovered on this page (JSON):\n{json.dumps(locators, indent=2)}\n\n"
        "Write pytest test functions (Playwright sync API) that verify this "
        "page loads correctly and that a few of its key interactive elements "
        "are present and usable. Prefer 2-4 focused test functions over one "
        "giant test."
    )
    response = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.2,
        max_tokens=1500,
    )
    raw_code = response.choices[0].message.content or ""
    return _clean_generated_code(raw_code)


def _build_generic_tests(page_name: str, locators: list[dict], target_url: str) -> str:
    """Deterministic fallback used when Groq is unavailable or fails."""
    selectors = [item.get("locator") for item in locators if item.get("locator")][:4]
    if not selectors:
        selectors = ["body"]

    goto_lines = [
        f'    page.goto({target_url!r}, wait_until="domcontentloaded", timeout=20000)',
        "    try:",
        '        page.wait_for_load_state("networkidle", timeout=5000)',
        "    except Exception:",
        "        pass",
    ]

    checks = [
        '    expect(page.locator("body")).to_be_visible()',
        '    interactive_count = page.locator("button, a, input, select, textarea").count()',
        "    assert interactive_count >= 1",
    ]
    for selector in selectors[:3]:
        checks.append("    try:")
        checks.append(f"        expect(page.locator({selector!r}).first).to_be_visible()")
        checks.append("    except Exception:")
        checks.append("        pass")

    safe_name = _sanitize_page_name(page_name)
    lines = [
        "from playwright.sync_api import expect",
        "",
        f"def test_{safe_name}_loads(page):",
        *goto_lines,
        *checks,
        "",
        f"def test_{safe_name}_has_interactive_controls(page):",
        *goto_lines,
        '    interactive_count = page.locator("button, a, input, select, textarea").count()',
        "    assert interactive_count >= 1",
    ]
    return "\n".join(lines) + "\n"


def _clear_generated_tests():
    Path(GENERATED_TESTS_DIR).mkdir(parents=True, exist_ok=True)
    for old_file in Path(GENERATED_TESTS_DIR).glob("*.py"):
        if old_file.name == ".gitkeep":
            continue
        old_file.unlink()


def generate_tests_for_page(page_name, locators):
    safe_page_name = _sanitize_page_name(page_name)
    code = None

    if GROQ_API_KEY:
        try:
            code = _generate_with_groq(page_name, locators, TARGET_URL)
            print(f"[generator] {page_name}: generated tests with Groq ({GROQ_MODEL})")
        except Exception as exc:
            print(f"[generator] {page_name}: Groq generation failed ({exc!r}); "
                  f"falling back to built-in template")
            code = None

    if code is None:
        code = _build_generic_tests(page_name, locators, TARGET_URL)
        print(f"[generator] {page_name}: generated tests with built-in template")

    out_path = Path(GENERATED_TESTS_DIR) / f"test_{safe_page_name}.py"
    out_path.write_text(code + "\n")
    print(f"[generator] wrote {out_path}")
    return out_path


def run():
    locator_files = sorted(Path(LOCATORS_DIR).glob("*.json"))
    if not locator_files:
        raise RuntimeError("No locator files found. Run the scraper agent first.")

    _clear_generated_tests()

    for f in locator_files:
        page_name = f.stem
        locators = json.loads(f.read_text())
        if not locators:
            print(f"[generator] skipping {page_name}, no locators found")
            continue
        generate_tests_for_page(page_name, locators)


if __name__ == "__main__":
    run()
