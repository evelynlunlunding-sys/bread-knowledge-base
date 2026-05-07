#!/usr/bin/env bash
# run_pipeline.sh — Full pipeline runner
# Usage: ./scripts/run_pipeline.sh [--country Italy] [--bread ciabatta]

set -e
cd "$(dirname "$0")/.."

source .env 2>/dev/null || true

if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo "ERROR: ANTHROPIC_API_KEY not set. Copy .env.example to .env and add your key."
  exit 1
fi

COUNTRY=${COUNTRY:-""}
BREAD=${BREAD:-""}

cd src

if [ -n "$COUNTRY" ] && [ -n "$BREAD" ]; then
  echo "==> Ingesting: $COUNTRY / $BREAD"
  python ingest_data.py "$COUNTRY" "$BREAD"
  echo "==> Compiling knowledge base entry …"
  python build_knowledge_base.py "$COUNTRY" "$BREAD"
  echo "==> Running linter …"
  python linter.py --no-llm
else
  echo "==> Full pipeline: ingest → compile → lint"
  python ingest_data.py
  python build_knowledge_base.py
  python linter.py
fi

echo ""
echo "Done. Browse knowledge_base/ or run:"
echo "  python src/query.py ask 'What is the difference between sourdough and ciabatta?'"
