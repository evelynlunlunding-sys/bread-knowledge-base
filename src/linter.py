from __future__ import annotations
"""
linter.py — Data Quality / LLM-based Linter

Checks every knowledge base entry for:
  - Missing required sections
  - Incomplete recipes (missing ingredients or method)
  - Missing images
  - Inconsistent or suspicious content
  - Suggests related breads not yet cross-linked
  - Recommends new sources to ingest

Writes a lint_report.md to the project root.
"""

import re
import logging
from pathlib import Path
from dataclasses import dataclass, field

import anthropic

from config import ANTHROPIC_API_KEY, MODEL, KNOWLEDGE_BASE_DIR

log = logging.getLogger(__name__)
client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

REQUIRED_SECTIONS = [
    "## Overview",
    "## Origin",
    "## History",
    "## Recipe",
    "### Ingredients",
    "### Method",
    "## Variations",
    "## Cultural Context",
    "## Related Breads",
    "## References",
]

LINT_REPORT = Path(__file__).parent.parent / "lint_report.md"


# ── Issue model ────────────────────────────────────────────────────────────────

@dataclass
class LintIssue:
    file: str
    severity: str  # error | warning | suggestion
    message: str


# ── Rule-based checks (fast, no LLM) ──────────────────────────────────────────

def _check_sections(content: str, filepath: str) -> list[LintIssue]:
    issues = []
    for section in REQUIRED_SECTIONS:
        # Allow partial heading match (e.g. "## Origin & Country")
        pattern = re.escape(section).replace(r"\ ", r"[\s\S]{0,20}")
        if not re.search(pattern, content, re.IGNORECASE):
            issues.append(LintIssue(
                file=filepath,
                severity="error",
                message=f"Missing required section: `{section}`",
            ))
    return issues


def _check_images(content: str, filepath: str) -> list[LintIssue]:
    issues = []
    if "## Images" not in content and "![" not in content:
        issues.append(LintIssue(
            file=filepath,
            severity="warning",
            message="No images referenced. Consider adding at least one image.",
        ))
    # Check for broken local paths
    for match in re.finditer(r"!\[.*?\]\((data/images/[^\)]+)\)", content):
        img_path = Path(match.group(1))
        if not img_path.exists():
            issues.append(LintIssue(
                file=filepath,
                severity="warning",
                message=f"Image file not found: `{img_path}`",
            ))
    return issues


def _check_recipe_completeness(content: str, filepath: str) -> list[LintIssue]:
    issues = []
    if "### Ingredients" in content:
        ingr_block = content.split("### Ingredients")[1].split("###")[0]
        if len(ingr_block.strip()) < 50:
            issues.append(LintIssue(
                file=filepath,
                severity="warning",
                message="Ingredients section seems too short.",
            ))
    if "### Method" in content:
        method_block = content.split("### Method")[1].split("##")[0]
        if len(method_block.strip()) < 100:
            issues.append(LintIssue(
                file=filepath,
                severity="warning",
                message="Method section seems too short.",
            ))
    return issues


def _check_references(content: str, filepath: str) -> list[LintIssue]:
    issues = []
    if "## References" not in content:
        issues.append(LintIssue(
            file=filepath,
            severity="error",
            message="Missing References section.",
        ))
    else:
        refs = content.split("## References")[-1]
        urls = re.findall(r"https?://\S+", refs)
        if len(urls) < 1:
            issues.append(LintIssue(
                file=filepath,
                severity="warning",
                message="References section has no URLs.",
            ))
    return issues


# ── LLM-based checks ──────────────────────────────────────────────────────────

LLM_LINT_PROMPT = """\
Review this bread knowledge base entry for quality issues.
Check for:
1. Factual inconsistencies or suspicious claims
2. Missing cultural context that should be added
3. Breads that should be cross-linked but aren't
4. New source types that would improve this entry (academic papers, books, videos)

Respond as a JSON array of objects: {{"severity": "warning|suggestion", "message": "..."}}
Only flag real issues. Be concise. Max 5 items.

<entry>
{content}
</entry>
"""


def _llm_check(content: str, filepath: str) -> list[LintIssue]:
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=512,
            system=[
                {
                    "type": "text",
                    "text": "You are a food encyclopedia editor reviewing bread knowledge base entries.",
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{
                "role": "user",
                "content": LLM_LINT_PROMPT.format(content=content[:4000]),
            }],
        )
        raw = response.content[0].text.strip()
        # Extract JSON array from response
        json_match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not json_match:
            return []
        import json
        items = json.loads(json_match.group())
        return [
            LintIssue(file=filepath, severity=i.get("severity", "suggestion"), message=i.get("message", ""))
            for i in items
            if i.get("message")
        ]
    except Exception as e:
        log.warning(f"LLM lint failed for {filepath}: {e}")
        return []


# ── Entry point ────────────────────────────────────────────────────────────────

def lint_entry(md_path: Path, llm_check: bool = True) -> list[LintIssue]:
    content = md_path.read_text(encoding="utf-8")
    filepath = str(md_path.relative_to(KNOWLEDGE_BASE_DIR))
    issues: list[LintIssue] = []
    issues += _check_sections(content, filepath)
    issues += _check_images(content, filepath)
    issues += _check_recipe_completeness(content, filepath)
    issues += _check_references(content, filepath)
    if llm_check and len(content) > 200:
        issues += _llm_check(content, filepath)
    return issues


def lint_all(llm_check: bool = True) -> list[LintIssue]:
    all_issues: list[LintIssue] = []
    md_files = list(KNOWLEDGE_BASE_DIR.rglob("*.md"))
    if not md_files:
        log.warning("No markdown files found in knowledge base.")
        return []

    for md in sorted(md_files):
        issues = lint_entry(md, llm_check=llm_check)
        all_issues.extend(issues)
        if issues:
            log.info(f"{md.name}: {len(issues)} issue(s)")

    _write_report(all_issues)
    return all_issues


def _write_report(issues: list[LintIssue]) -> None:
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    suggestions = [i for i in issues if i.severity == "suggestion"]

    lines = [
        "# Knowledge Base Lint Report\n",
        f"> Generated by `linter.py`\n",
        f"\n**{len(errors)} errors | {len(warnings)} warnings | {len(suggestions)} suggestions**\n",
    ]

    for label, group in [("Errors", errors), ("Warnings", warnings), ("Suggestions", suggestions)]:
        if not group:
            continue
        lines.append(f"\n## {label}\n")
        for issue in group:
            lines.append(f"- `{issue.file}`: {issue.message}")

    LINT_REPORT.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"Lint report written to {LINT_REPORT.name}")


# ── CLI ────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    llm = "--no-llm" not in sys.argv
    issues = lint_all(llm_check=llm)
    print(f"\nTotal issues: {len(issues)}")
    for i in issues:
        print(f"  [{i.severity.upper()}] {i.file}: {i.message}")
