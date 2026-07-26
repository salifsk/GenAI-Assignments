"""
Reporter Agent
--------------
Parses the JUnit XML produced by the executor agent and writes a short
human-readable summary, used both in CI logs and as a build artifact.
"""
import xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime

from config import REPORTS_DIR


def run():
    junit_path = Path(REPORTS_DIR) / "results.xml"
    if not junit_path.exists():
        print("[reporter] no results.xml found, skipping")
        return

    tree = ET.parse(junit_path)
    root = tree.getroot()
    suite = root.find("testsuite") if root.tag != "testsuite" else root

    total = int(suite.get("tests", 0))
    failures = int(suite.get("failures", 0))
    errors = int(suite.get("errors", 0))
    skipped = int(suite.get("skipped", 0))
    time_taken = suite.get("time", "0")
    passed = total - failures - errors - skipped

    lines = [
        "# Test run summary",
        "",
        f"Run at: {datetime.utcnow().isoformat()}Z",
        "",
        "| Metric | Count |",
        "|---|---|",
        f"| Total | {total} |",
        f"| Passed | {passed} |",
        f"| Failed | {failures} |",
        f"| Errors | {errors} |",
        f"| Skipped | {skipped} |",
        f"| Duration (s) | {time_taken} |",
        "",
    ]

    if failures or errors:
        lines.append("## Failed tests")
        for tc in suite.findall("testcase"):
            if tc.find("failure") is not None or tc.find("error") is not None:
                lines.append(f"- {tc.get('classname')}.{tc.get('name')}")

    summary_path = Path(REPORTS_DIR) / "summary.md"
    summary_path.write_text("\n".join(lines))
    print(f"[reporter] wrote {summary_path}")
    print("\n".join(lines))


if __name__ == "__main__":
    run()
