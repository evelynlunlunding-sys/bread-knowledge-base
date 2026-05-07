from __future__ import annotations
"""
build_knowledge_base.py — LLM Compiler Layer

Reads raw JSON sources from data/raw/ and uses Claude to:
  1. Synthesize multiple sources into one coherent markdown file
  2. Enforce the required section structure
  3. Deduplicate and cross-link related breads
  4. Save to knowledge_base/<Country>/<bread>.md
"""

import json
import time
import logging
from pathlib import Path

import anthropic
import frontmatter

from config import (
    ANTHROPIC_API_KEY, MODEL, COMPILER_MODEL,
    RAW_DIR, KNOWLEDGE_BASE_DIR, SEED_CATALOG, IMAGES_DIR,
)

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ── Prompt templates ───────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are a world-class food historian and technical writer specializing in global bread culture.
Your task: synthesize raw research data into a beautifully structured markdown knowledge base entry.

Rules:
- Write in clear, engaging English suitable for an educated general audience
- Be factually accurate; if uncertain, say so
- Include ALL required sections (see structure below)
- Keep recipes practical and complete
- Use markdown headings, tables, and lists appropriately
- Cross-link related breads using [[bread name]] wiki-style links
- Reference all sources at the end

Required markdown structure:
# {Bread Name}

## Overview
## Origin & Country
## History & Evolution
## Recipe
### Ingredients
### Method
## Variations
## Cultural Context
## Images
## Related Breads
## References
"""

COMPILE_PROMPT = """\
Below are {n} raw research sources about **{bread}** bread from **{country}**.
Synthesize them into a single, comprehensive knowledge base entry following the required structure.
Include a YAML frontmatter block at the top with: title, country, tags, last_updated.

<sources>
{sources_block}
</sources>

Write the complete markdown document now.
"""

MERGE_PROMPT = """\
The existing knowledge base entry for **{bread}** ({country}) needs to be updated
with new information from the source below.

<existing>
{existing}
</existing>

<new_source>
{new_source}
</new_source>

Instructions:
- Keep all existing correct information
- Add genuinely new facts, recipe details, or cultural notes
- Update the References section to include the new source
- Update last_updated in frontmatter to today
- Return the complete updated markdown document (including frontmatter)
"""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _slug(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _load_raw_sources(country: str, bread: str) -> list[dict]:
    raw_dir = RAW_DIR / _slug(country) / _slug(bread)
    if not raw_dir.exists():
        return []
    sources = []
    for f in sorted(raw_dir.glob("*.json")):
        try:
            sources.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return sources


def _sources_block(sources: list[dict]) -> str:
    blocks = []
    for i, s in enumerate(sources, 1):
        blocks.append(
            f"--- SOURCE {i}: {s.get('title', 'Untitled')} ---\n"
            f"URL: {s.get('url', '')}\n\n"
            f"{s.get('body_text', '')[:3000]}\n"
        )
    return "\n\n".join(blocks)


def _kb_path(country: str, bread: str) -> Path:
    country_dir = KNOWLEDGE_BASE_DIR / country
    country_dir.mkdir(parents=True, exist_ok=True)
    return country_dir / f"{_slug(bread)}.md"


def _call_llm(system: str, user: str, model: str = MODEL) -> str:
    """Single LLM call with prompt caching on the system prompt."""
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},  # prompt caching
            }
        ],
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text


# ── Core compilation ───────────────────────────────────────────────────────────

def compile_bread(bread: str, country: str, force: bool = False) -> Path | None:
    """
    Compile raw sources for a bread into a structured markdown file.
    If the file already exists, merges new sources instead of rewriting.
    """
    kb_path = _kb_path(country, bread)
    sources = _load_raw_sources(country, bread)

    if not sources:
        log.warning(f"No raw sources found for {country}/{bread} — run ingest first")
        return None

    if kb_path.exists() and not force:
        log.info(f"Updating existing entry: {kb_path.name}")
        return _merge_new_sources(bread, country, kb_path, sources)

    log.info(f"Compiling new entry: {country}/{bread} ({len(sources)} sources)")
    prompt = COMPILE_PROMPT.format(
        n=len(sources),
        bread=bread,
        country=country,
        sources_block=_sources_block(sources),
    )

    try:
        md_text = _call_llm(SYSTEM_PROMPT, prompt, model=COMPILER_MODEL)
        kb_path.write_text(md_text, encoding="utf-8")
        log.info(f"  ✓ written → {kb_path.relative_to(KNOWLEDGE_BASE_DIR.parent)}")
        return kb_path
    except Exception as e:
        log.error(f"  LLM compilation failed for {bread}: {e}")
        return None


def _merge_new_sources(
    bread: str, country: str, kb_path: Path, sources: list[dict]
) -> Path:
    """Add any new sources to an existing markdown entry."""
    existing = kb_path.read_text(encoding="utf-8")
    # Only pass sources that aren't already referenced
    refs_in_existing = existing.lower()
    new_sources = [
        s for s in sources
        if s.get("url", "").split("/")[-1] not in refs_in_existing
    ]
    if not new_sources:
        log.info(f"  No new sources for {bread} — skipping merge")
        return kb_path

    log.info(f"  Merging {len(new_sources)} new source(s) into {bread}")
    prompt = MERGE_PROMPT.format(
        bread=bread,
        country=country,
        existing=existing[:6000],
        new_source=_sources_block(new_sources[:2]),
    )
    try:
        updated = _call_llm(SYSTEM_PROMPT, prompt, model=MODEL)
        kb_path.write_text(updated, encoding="utf-8")
        log.info(f"  ✓ updated → {kb_path.name}")
    except Exception as e:
        log.error(f"  Merge failed for {bread}: {e}")
    return kb_path


# ── Cross-linking pass ─────────────────────────────────────────────────────────

def build_cross_links(catalog: dict[str, list[str]]) -> None:
    """
    After all entries are compiled, run a second pass to inject
    cross-links into the Related Breads section.
    """
    all_breads = [b for breads in catalog.values() for b in breads]
    all_breads_lower = {b.lower(): b for b in all_breads}

    for country, breads in catalog.items():
        for bread in breads:
            kb_path = _kb_path(country, bread)
            if not kb_path.exists():
                continue
            text = kb_path.read_text(encoding="utf-8")
            # Find mentions of other breads and linkify them
            for other_lower, other_name in all_breads_lower.items():
                if other_lower == bread.lower():
                    continue
                if other_lower in text.lower() and f"[[{other_name}]]" not in text:
                    # Simple replacement: first plain mention → wiki link
                    text = text.replace(
                        other_name, f"[[{other_name}]]", 1
                    )
            kb_path.write_text(text, encoding="utf-8")

    log.info("Cross-linking pass complete.")


# ── Full build ─────────────────────────────────────────────────────────────────

def build_all(catalog: dict[str, list[str]], force: bool = False) -> None:
    """Compile every bread in the catalog."""
    for country, breads in catalog.items():
        for bread in breads:
            compile_bread(bread, country, force=force)
            time.sleep(0.5)  # avoid rate limits

    build_cross_links(catalog)
    log.info("Knowledge base build complete.")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) == 3:
        compile_bread(sys.argv[2], sys.argv[1])
    elif "--force" in sys.argv:
        build_all(SEED_CATALOG, force=True)
    else:
        build_all(SEED_CATALOG)
