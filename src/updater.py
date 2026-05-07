from __future__ import annotations
"""
updater.py — Tiered Auto-Update System

Schedule:
  - Yearly  : discover new countries / bread categories
  - Monthly : refresh every individual bread entry
  - On start: run everything immediately so you don't wait
"""

import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

import schedule
from rich.console import Console

from config import SEED_CATALOG, KNOWLEDGE_BASE_DIR, RAW_DIR
from ingest_data import ingest_bread
from build_knowledge_base import compile_bread, build_cross_links
from linter import lint_all

log = logging.getLogger(__name__)
console = Console()

UPDATE_LOG = Path(__file__).parent.parent / "data" / "update_log.jsonl"
STATE_FILE = Path(__file__).parent.parent / "data" / "update_state.json"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"last_category_update": None, "last_bread_updates": {}}


def _save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _log(entry: dict) -> None:
    UPDATE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with UPDATE_LOG.open("a") as f:
        f.write(json.dumps(entry) + "\n")


# ── Discover new categories (YEARLY) ──────────────────────────────────────────

# New countries / bread types to explore — expand this list anytime
EXPANDED_CATALOG: dict[str, list[str]] = {
    **SEED_CATALOG,
    "Japan":   ["shokupan", "melon pan", "curry bread"],
    "Mexico":  ["bolillo", "pan dulce", "telera"],
    "Ethiopia":["injera", "ambasha"],
    "Turkey":  ["simit", "pide", "lavash"],
    "China":   ["mantou", "bing", "baozi"],
    "Israel":  ["challah", "pita", "laffa"],
}


def run_category_discovery() -> None:
    """
    Yearly job: look for brand-new countries/bread types not yet in the KB.
    Only ingests + compiles entries that don't already exist.
    """
    console.rule("[bold yellow]YEARLY — Category Discovery[/bold yellow]")
    state = _load_state()
    new_count = 0

    for country, breads in EXPANDED_CATALOG.items():
        for bread in breads:
            kb_file = KNOWLEDGE_BASE_DIR / country / f"{bread.replace(' ', '_')}.md"
            if kb_file.exists():
                continue  # already have it
            console.print(f"  [cyan]New entry:[/cyan] {country} / {bread}")
            ingest_bread(bread, country)
            compile_bread(bread, country)
            new_count += 1
            time.sleep(1)

    build_cross_links(EXPANDED_CATALOG)
    state["last_category_update"] = _now()
    _save_state(state)
    _log({"ts": _now(), "job": "category_discovery", "new_entries": new_count})
    console.print(f"[green]Category discovery done — {new_count} new entries added[/green]")


# ── Refresh all bread entries (MONTHLY) ───────────────────────────────────────

def run_monthly_refresh() -> None:
    """
    Monthly job: re-ingest every known bread and merge any new info.
    Skips entries updated in the last 25 days to avoid redundant API calls.
    """
    console.rule("[bold blue]MONTHLY — Bread Refresh[/bold blue]")
    state = _load_state()
    refreshed = 0

    for country_dir in sorted(KNOWLEDGE_BASE_DIR.iterdir()):
        if not country_dir.is_dir():
            continue
        for md_file in sorted(country_dir.glob("*.md")):
            bread = md_file.stem.replace("_", " ")
            country = country_dir.name
            key = f"{country}/{bread}"

            last = state["last_bread_updates"].get(key)
            if last:
                days_ago = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).days
                if days_ago < 25:
                    console.print(f"  [dim]skip {key} (updated {days_ago}d ago)[/dim]")
                    continue

            console.print(f"  [cyan]Refreshing:[/cyan] {key}")
            ingest_bread(bread, country)
            compile_bread(bread, country, force=False)  # merge mode
            state["last_bread_updates"][key] = _now()
            _save_state(state)
            refreshed += 1
            time.sleep(1.5)

    # Quality check after refresh
    issues = lint_all(llm_check=False)
    _log({"ts": _now(), "job": "monthly_refresh", "refreshed": refreshed, "lint_issues": len(issues)})
    console.print(f"[green]Monthly refresh done — {refreshed} entries updated, {len(issues)} lint issues[/green]")


# ── Full first-run (runs immediately on startup) ───────────────────────────────

def run_full_pipeline() -> None:
    """
    Run everything from scratch: ingest → compile → cross-link → lint.
    Used on first launch or when you want a clean rebuild.
    """
    console.rule("[bold green]FULL PIPELINE — All Breads[/bold green]")
    catalog = SEED_CATALOG

    total = sum(len(v) for v in catalog.items())
    done = 0
    for country, breads in catalog.items():
        for bread in breads:
            done += 1
            console.print(f"  [{done}/{sum(len(v) for v in catalog.values())}] {country} / {bread}")
            ingest_bread(bread, country)
            compile_bread(bread, country)
            time.sleep(1)

    build_cross_links(catalog)
    lint_all(llm_check=False)
    console.print("[bold green]Full pipeline complete![/bold green]")


# ── Scheduler ──────────────────────────────────────────────────────────────────

def start_scheduler(first_run: bool = True) -> None:
    """
    Start the background scheduler:
      - Monthly refresh  (day 1 of every month at 03:00)
      - Yearly discovery (Jan 1 at 04:00)

    Pass first_run=False to skip the immediate startup run.
    """
    console.print("[bold]Scheduler started[/bold]")
    console.print("  • Monthly bread refresh  → 1st of every month")
    console.print("  • Yearly category update → Jan 1st")
    console.print("Press Ctrl+C to stop.\n")

    if first_run:
        console.print("[yellow]Running full pipeline now (first run)…[/yellow]")
        run_full_pipeline()

    # Monthly: run on the 1st at 3 AM
    schedule.every().month.at("03:00").do(run_monthly_refresh)

    # Yearly: run every Jan 1 at 4 AM  (approximated as every 365 days)
    schedule.every(365).days.at("04:00").do(run_category_discovery)

    while True:
        schedule.run_pending()
        time.sleep(60)


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if "--monthly" in sys.argv:
        run_monthly_refresh()
    elif "--yearly" in sys.argv:
        run_category_discovery()
    elif "--full" in sys.argv:
        run_full_pipeline()
    elif "--schedule" in sys.argv:
        # Run scheduler but skip the immediate first-run
        start_scheduler(first_run=False)
    else:
        # Default: run full pipeline now, then start scheduler
        start_scheduler(first_run=True)
