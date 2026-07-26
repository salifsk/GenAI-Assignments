"""
Orchestrator
------------
Runs the four agents in sequence:
  scraper -> generator -> executor -> reporter

This is the single entry point used both locally and by the Azure Pipeline.
Each agent is independent and communicates only through the files in
data/ (locators -> generated_tests -> reports), so any agent can be
swapped out or re-run on its own.
"""
import argparse
import os
import sys

parser = argparse.ArgumentParser(description="Run the multi-agent web test framework")
parser.add_argument("--url", default=None, help="Override the target URL")
args = parser.parse_args()

if args.url:
    os.environ["TARGET_URL"] = args.url

from agents import scraper_agent, generator_agent, executor_agent, reporter_agent


def main():
    print("=== 1/4 Scraper agent: discovering locators ===")
    scraper_agent.run()

    print("\n=== 2/4 Generator agent: writing test cases (Groq) ===")
    generator_agent.run()

    print("\n=== 3/4 Executor agent: running tests ===")
    exit_code = executor_agent.run()

    print("\n=== 4/4 Reporter agent: summarizing results ===")
    reporter_agent.run()

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
