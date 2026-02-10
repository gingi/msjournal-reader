#!/usr/bin/env bash
set -euo pipefail

# Build a trimmed, publishable ClawHub bundle from this dev checkout.
# Output: ./publish/journal-reader/

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="$ROOT_DIR/publish/journal-reader"

rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR"

rsync -a --delete \
  --exclude '.git' \
  --exclude '.github' \
  --exclude '.venv' \
  --exclude '.venv-pdf' \
  --exclude '.pytest_cache' \
  --exclude 'tmp' \
  --exclude 'tests' \
  --exclude '.env' \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'out*' \
  --exclude 'exports*' \
  --exclude 'index*' \
  --exclude '*.sqlite' \
  --exclude 'publish' \
  "$ROOT_DIR/" \
  "$OUT_DIR/"

echo "Wrote publish bundle: $OUT_DIR"