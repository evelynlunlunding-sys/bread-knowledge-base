from __future__ import annotations
"""Central configuration for the Bread Knowledge Base system."""

import os
from pathlib import Path
from dotenv import load_dotenv

# ── Paths ──────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent.parent

load_dotenv(ROOT / ".env", override=True)
KNOWLEDGE_BASE_DIR = ROOT / "knowledge_base"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
IMAGES_DIR = DATA_DIR / "images"
TEMPLATES_DIR = ROOT / "templates"

for d in (KNOWLEDGE_BASE_DIR, RAW_DIR, IMAGES_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ── Anthropic ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-6"          # fast + cheap for iteration
COMPILER_MODEL = "claude-opus-4-7"  # highest quality for final compilation

# ── Scheduler ─────────────────────────────────────────────────────────────────
UPDATE_INTERVAL_HOURS = int(os.getenv("UPDATE_INTERVAL_HOURS", "24"))

# ── Ingestion ──────────────────────────────────────────────────────────────────
MAX_SOURCES_PER_BREAD = int(os.getenv("MAX_SOURCES_PER_BREAD", "5"))
REQUEST_TIMEOUT = 15  # seconds
USER_AGENT = (
    "Mozilla/5.0 (compatible; BreadKnowledgeBot/1.0; "
    "+https://github.com/breadkb)"
)

# ── Seed catalog ──────────────────────────────────────────────────────────────
# country → list of bread names to bootstrap the knowledge base
SEED_CATALOG: dict[str, list[str]] = {
    "USA": ["sourdough", "bagel", "cornbread", "pretzel"],
    "Italy": ["ciabatta", "focaccia", "pane di casa", "grissini"],
    "France": ["baguette", "brioche", "pain de campagne", "croissant"],
    "Germany": ["pumpernickel", "rye bread", "pretzel", "vollkornbrot"],
    "India": ["naan", "chapati", "parotta", "pav"],
}

# ── Scrape sources ─────────────────────────────────────────────────────────────
# These are public, bread-related domains safe for educational scraping
SCRAPE_SOURCES = [
    "https://en.wikipedia.org/wiki/{query}",
    "https://www.thespruceeats.com/search?q={query}",
    "https://www.allrecipes.com/search?q={query}",
]
