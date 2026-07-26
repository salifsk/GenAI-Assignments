import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOCATORS_DIR = DATA_DIR / "locators"
GENERATED_TESTS_DIR = DATA_DIR / "generated_tests"
REPORTS_DIR = DATA_DIR / "reports"

# Default target under test. SauceDemo is a purpose-built QA practice site,
# safe to automate against (no ToS/anti-bot issues like production sites).
TARGET_URL = os.getenv("TARGET_URL") or "https://www.saucedemo.com/"

# Groq (LLM used by the generator agent)
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")

HEADLESS = os.getenv("HEADLESS", "true").lower() == "true"

for d in (LOCATORS_DIR, GENERATED_TESTS_DIR, REPORTS_DIR):
    d.mkdir(parents=True, exist_ok=True)
