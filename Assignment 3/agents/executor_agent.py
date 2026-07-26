"""
Test Executor Agent
--------------------
Runs the generated pytest/Playwright tests and produces a JUnit XML report
that the reporter agent (and the Azure Pipeline's test-results task) can
both consume.
"""
import subprocess
import sys
from pathlib import Path

from config import GENERATED_TESTS_DIR, REPORTS_DIR


def run():
    junit_path = Path(REPORTS_DIR) / "results.xml"
    cmd = [
        sys.executable, "-m", "pytest",
        str(GENERATED_TESTS_DIR),
        f"--junitxml={junit_path}",
        "-v",
    ]
    print(f"[executor] running: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    print(f"[executor] pytest exit code: {result.returncode}")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(run())
