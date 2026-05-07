# 🍞 Global Bread Knowledge Base

A self-building, LLM-powered encyclopedia of global bread culture. The system automatically ingests data from the web, compiles it into structured markdown, and keeps itself up-to-date.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    BREAD KNOWLEDGE BASE                         │
├─────────────────┬───────────────────┬───────────────────────────┤
│  INGESTION      │   LLM COMPILER    │   QUERY / UI              │
│                 │                   │                           │
│ ingest_data.py  │ build_knowledge   │ query.py (CLI + API)      │
│                 │ _base.py          │ web_ui.py (browser)       │
│ Sources:        │                   │                           │
│  • Wikipedia    │ Claude Opus 4.7   │ Commands:                 │
│  • Recipe sites │  → Synthesize     │  ask / compare / recipe   │
│  • Blogs        │  → Structure      │  browse / search          │
│  • PDFs         │  → Cross-link     │  interactive / export     │
│  • Images       │  → Deduplicate    │                           │
├─────────────────┴───────────────────┴───────────────────────────┤
│                    DATA LAYER                                   │
│                                                                 │
│  data/raw/<country>/<bread>/*.json   (raw scraped data)         │
│  data/images/<country>/<bread>/      (downloaded images)        │
│  knowledge_base/<Country>/<bread>.md (compiled entries)         │
├─────────────────────────────────────────────────────────────────┤
│  AUTO-UPDATE               │  QUALITY                          │
│  updater.py                │  linter.py                        │
│   → schedule.every(24h)    │   → Section checks                │
│   → re-ingest → re-merge   │   → Recipe completeness           │
│   → cross-link refresh     │   → LLM quality review            │
└────────────────────────────┴──────────────────────────────────-─┘
```

## File Structure

```
bread_knowledge_base/
├── src/
│   ├── config.py               # Central configuration
│   ├── ingest_data.py          # Data ingestion layer
│   ├── build_knowledge_base.py # LLM compiler
│   ├── query.py                # Query interface (CLI)
│   ├── updater.py              # Auto-update scheduler
│   └── linter.py               # Data quality checks
├── scripts/
│   ├── run_pipeline.sh         # Full pipeline runner
│   └── web_ui.py               # Browser-based viewer
├── knowledge_base/             # Compiled markdown entries
│   ├── USA/
│   │   ├── sourdough.md
│   │   └── bagel.md
│   ├── Italy/
│   │   ├── ciabatta.md
│   │   └── focaccia.md
│   └── France/
│       └── baguette.md
├── data/
│   ├── raw/                    # Raw scraped JSON files
│   └── images/                 # Downloaded images
├── templates/
│   └── bread_template.md       # Template for new entries
├── site/                       # Generated web UI (auto-built)
├── .env.example
├── requirements.txt
└── README.md
```

## Quick Start

### 1. Install

```bash
pip install -r requirements.txt
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
```

### 2. Ingest data for a specific bread

```bash
cd src
python ingest_data.py "Italy" "ciabatta"
```

### 3. Compile the knowledge base entry

```bash
python build_knowledge_base.py "Italy" "ciabatta"
# → Creates knowledge_base/Italy/ciabatta.md
```

### 4. Query the knowledge base

```bash
python query.py ask "What are the main differences between sourdough and ciabatta?"
python query.py compare sourdough ciabatta
python query.py recipe baguette
python query.py browse France
python query.py search "olive oil"
python query.py interactive   # REPL mode
```

### 5. Launch the web UI

```bash
python scripts/web_ui.py
# → http://localhost:8000
```

### 6. Run the full pipeline (all breads in catalog)

```bash
./scripts/run_pipeline.sh
```

### 7. Start the auto-updater

```bash
cd src && python updater.py         # runs every 24h
cd src && python updater.py --once  # run once and exit
```

---

## Example Query Output

```
$ python query.py compare sourdough ciabatta

| Feature         | Sourdough                    | Ciabatta                      |
|-----------------|------------------------------|-------------------------------|
| Origin          | USA (San Francisco)          | Italy (Veneto, 1982)          |
| Leavening       | Wild yeast + LAB bacteria    | Commercial yeast              |
| Hydration       | 75–80 %                      | 75–85 %                       |
| Flavor          | Tangy, complex, earthy       | Mild, wheaty, olive oil notes |
| Crumb           | Open, irregular              | Very open, large holes        |
| Crust           | Thick, chewy, blistered      | Thin, crispy                  |
| Age             | ~5,700 years                 | ~44 years (invented 1982)     |
| Key ingredient  | Active starter               | Extra-virgin olive oil        |
```

---

## Knowledge Base Entry Structure

Each `.md` file follows this schema:

```markdown
---
title: Ciabatta
country: Italy
tags: [italian, artisan, olive-oil, yeast]
last_updated: 2026-05-06
---

# Ciabatta
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
```

---

## LLM Design Choices

| Component | Model | Why |
|-----------|-------|-----|
| Initial compilation | `claude-opus-4-7` | Highest quality for first-pass synthesis |
| Incremental merging | `claude-sonnet-4-6` | Fast + cheap for frequent updates |
| Query answering | `claude-sonnet-4-6` | Good balance for interactive use |
| Linting | `claude-sonnet-4-6` | Structured output, cost-effective |

**Prompt caching** is enabled on all system prompts to minimize token costs on repeated calls.

---

## Future Improvements

| Feature | Description |
|---------|-------------|
| **RAG / Vector Search** | Embed all entries with `text-embedding-3-large`; use FAISS or Chroma for semantic search |
| **Fine-tuning** | Fine-tune a small model on the knowledge base for offline querying |
| **Image understanding** | Use Claude's vision to analyze bread images and extract visual characteristics |
| **Recommendation system** | "Users who like sourdough also enjoy…" based on ingredient/technique similarity |
| **API layer** | FastAPI REST endpoint for programmatic access |
| **Obsidian integration** | Knowledge base is already Obsidian-compatible (`[[wiki links]]`) |
| **Multi-language** | Generate entries in French, Italian, German alongside English |
| **Nutritional data** | Auto-fetch and structure nutritional info per bread |
| **Video links** | Ingest YouTube recipe videos via transcript API |
