from __future__ import annotations
"""
query.py — LLM-powered Query Interface

Allows users to ask questions against the knowledge base.
Supports:
  - Free-form Q&A
  - Bread comparisons
  - Recipe retrieval
  - Country browsing
  - Generating markdown summaries and comparison tables
"""

import re
import logging
from pathlib import Path

import anthropic
import click
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from config import ANTHROPIC_API_KEY, MODEL, KNOWLEDGE_BASE_DIR

log = logging.getLogger(__name__)
console = Console()
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ── Knowledge base loader ──────────────────────────────────────────────────────

def _load_all_entries() -> dict[str, str]:
    """Load all markdown files as {path_str: content}."""
    entries = {}
    for md in sorted(KNOWLEDGE_BASE_DIR.rglob("*.md")):
        key = str(md.relative_to(KNOWLEDGE_BASE_DIR))
        entries[key] = md.read_text(encoding="utf-8")
    return entries


def _load_country(country: str) -> dict[str, str]:
    country_dir = KNOWLEDGE_BASE_DIR / country
    if not country_dir.exists():
        return {}
    return {
        md.stem: md.read_text(encoding="utf-8")
        for md in sorted(country_dir.glob("*.md"))
    }


def _find_bread(name: str) -> str | None:
    """Find a bread file by name (fuzzy)."""
    name_slug = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    for md in KNOWLEDGE_BASE_DIR.rglob("*.md"):
        if name_slug in md.stem:
            return md.read_text(encoding="utf-8")
    return None


def _context_block(entries: dict[str, str], max_chars: int = 20_000) -> str:
    """Pack knowledge base entries into a context string, capped at max_chars."""
    blocks = []
    total = 0
    for path, content in entries.items():
        chunk = f"=== {path} ===\n{content[:3000]}\n"
        if total + len(chunk) > max_chars:
            break
        blocks.append(chunk)
        total += len(chunk)
    return "\n".join(blocks)


# ── LLM call with prompt caching ──────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are an expert on global bread culture with access to a structured knowledge base.
Answer questions concisely and accurately based on the provided knowledge base content.
When generating comparisons, use markdown tables.
When generating recipes, use numbered steps.
Always cite which bread entry your information comes from.
If the knowledge base doesn't contain the answer, say so clearly.
"""


def _query_llm(question: str, context: str) -> str:
    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f"<knowledge_base>\n{context}\n</knowledge_base>\n\n"
                    f"Question: {question}"
                ),
            }
        ],
    )
    return response.content[0].text


# ── Query types ────────────────────────────────────────────────────────────────

def answer(question: str) -> str:
    """General Q&A against the full knowledge base."""
    entries = _load_all_entries()
    if not entries:
        return "Knowledge base is empty. Run `build_knowledge_base.py` first."
    context = _context_block(entries)
    return _query_llm(question, context)


def compare_breads(bread_a: str, bread_b: str) -> str:
    """Generate a comparison table between two breads."""
    content_a = _find_bread(bread_a)
    content_b = _find_bread(bread_b)
    if not content_a:
        return f"Bread '{bread_a}' not found in knowledge base."
    if not content_b:
        return f"Bread '{bread_b}' not found in knowledge base."
    context = f"=== {bread_a} ===\n{content_a[:4000]}\n\n=== {bread_b} ===\n{content_b[:4000]}"
    question = (
        f"Create a detailed comparison table between {bread_a} and {bread_b}. "
        "Include: origin, texture, flavor profile, key ingredients, "
        "leavening method, baking time, and cultural significance."
    )
    return _query_llm(question, context)


def get_recipe(bread: str) -> str:
    """Retrieve and format a recipe for a specific bread."""
    content = _find_bread(bread)
    if not content:
        return f"Recipe for '{bread}' not found. Run ingestion first."
    return _query_llm(
        f"Extract and format the complete recipe for {bread} with "
        "precise measurements, step-by-step method, tips, and serving suggestions.",
        content,
    )


def browse_country(country: str) -> str:
    """List all breads from a country with summaries."""
    entries = _load_country(country)
    if not entries:
        return f"No breads found for country '{country}'."
    context = _context_block(entries, max_chars=15_000)
    return _query_llm(
        f"List all breads from {country} in the knowledge base. "
        "For each, give a 1-sentence description and its key characteristics.",
        context,
    )


def search_by_ingredient(ingredient: str) -> str:
    """Find all breads that prominently feature a specific ingredient."""
    entries = _load_all_entries()
    # Pre-filter: only entries that mention the ingredient
    filtered = {
        k: v for k, v in entries.items()
        if ingredient.lower() in v.lower()
    }
    if not filtered:
        return f"No breads found featuring '{ingredient}'."
    context = _context_block(filtered)
    return _query_llm(
        f"List all breads that feature {ingredient} as a key ingredient. "
        "Explain how {ingredient} is used in each.",
        context,
    )


# ── Markdown export helpers ────────────────────────────────────────────────────

def export_summary(output_path: str = "summary.md") -> None:
    """Generate a full knowledge base summary document."""
    entries = _load_all_entries()
    context = _context_block(entries)
    summary = _query_llm(
        "Generate a comprehensive summary of the entire bread knowledge base. "
        "Organize by continent, then country. Include a table of all breads with "
        "country, type (leavened/unleavened/sourdough), and one key fact.",
        context,
    )
    Path(output_path).write_text(summary, encoding="utf-8")
    console.print(f"[green]Summary exported to {output_path}[/green]")


# ── CLI ────────────────────────────────────────────────────────────────────────

@click.group()
def cli():
    """Bread Knowledge Base — LLM Query Interface"""


@cli.command()
@click.argument("question")
def ask(question: str):
    """Ask a free-form question about bread."""
    console.print(f"\n[bold cyan]Q:[/bold cyan] {question}\n")
    result = answer(question)
    console.print(Markdown(result))


@cli.command()
@click.argument("bread_a")
@click.argument("bread_b")
def compare(bread_a: str, bread_b: str):
    """Compare two breads side by side."""
    console.print(f"\n[bold]Comparing:[/bold] {bread_a} vs {bread_b}\n")
    result = compare_breads(bread_a, bread_b)
    console.print(Markdown(result))


@cli.command()
@click.argument("bread")
def recipe(bread: str):
    """Get the full recipe for a bread."""
    result = get_recipe(bread)
    console.print(Markdown(result))


@cli.command()
@click.argument("country")
def browse(country: str):
    """Browse all breads from a country."""
    result = browse_country(country)
    console.print(Markdown(result))


@cli.command()
@click.argument("ingredient")
def search(ingredient: str):
    """Find breads by ingredient."""
    result = search_by_ingredient(ingredient)
    console.print(Markdown(result))


@cli.command()
@click.option("--output", default="summary.md")
def export(output: str):
    """Export a full knowledge base summary."""
    export_summary(output)


@cli.command()
def interactive():
    """Start an interactive Q&A session."""
    console.print("[bold green]Bread KB Interactive Mode[/bold green] (type 'exit' to quit)\n")
    entries = _load_all_entries()
    context = _context_block(entries)

    while True:
        try:
            q = console.input("[bold cyan]> [/bold cyan]").strip()
        except (KeyboardInterrupt, EOFError):
            break
        if q.lower() in ("exit", "quit", "q"):
            break
        if not q:
            continue
        answer_text = _query_llm(q, context)
        console.print(Markdown(answer_text))
        console.print()


if __name__ == "__main__":
    cli()
