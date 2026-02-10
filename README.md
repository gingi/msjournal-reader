# msjournal-reader

Convert Microsoft Journal `.ink` files (SQLite DB) into text by extracting per-page rendered PNGs and running OCR.

This repo currently implements **Azure AI Vision Read**.
It’s structured to allow additional OCR providers later (see `msjournal_reader/ocr/`).

## Setup

### 1) Install dependencies

Recommended (uv):

```bash
uv venv --clear .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

Or using the standard library venv:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) Configure Azure

Copy `.env.example` → `.env` and set:
- `AZURE_VISION_ENDPOINT`
- `AZURE_VISION_KEY`

## Convert an .ink file

Run from the repo root (either `pip install -e .` or use `PYTHONPATH=.`):

```bash
PYTHONPATH=. python3 scripts/ink_to_text.py \
  "/path/to/Journal.ink" \
  --out-dir ./out \
  --engine azure \
  --corrections-map user_corrections/example_regex.json
```

Outputs:
- `out/<ink-stem>/page_0000.md`
- `out/<ink-stem>/combined.md`

## Corrections (post-OCR)

Provide either:
- a JSON dict map: `{ "wrong": "right" }`
- or a JSON regex list: `[["<regex>", "<replacement>"], ...]`

For personal corrections, store them in **`user_corrections/local/`** (gitignored). This directory is a good candidate to keep on a synced drive (e.g., OneDrive) and symlink back into the repo.

## Per-user neural post-corrector (optional)

Train a small seq2seq model that rewrites OCR text into your preferred style.

Note: OCR outputs are page markdown (`page_XXXX.md`). Training utilities strip the `# Page N` wrapper automatically.

Install optional deps:

```bash
pip install -r requirements-ml.txt
```

Train (uses your `gold/` pages + OCR output pages):

```bash
PYTHONPATH=. python3 scripts/train_postcorrector_byt5.py \
  --gold-dir gold \
  --hyp-dir out/<ink-stem> \
  --out-dir user_corrections/local/models/byt5
```

Apply during conversion:

```bash
PYTHONPATH=. python3 scripts/ink_to_text.py \
  "/path/to/Journal.ink" \
  --out-dir ./out \
  --engine azure \
  --postcorrector-model user_corrections/local/models/byt5
```

Guardrail: by default, `--postcorrector-model` must live under `user_corrections/local/` to reduce the chance of accidentally committing weights. Override with `--allow-nonlocal-postcorrector`.

## Grouped markdown exports

Build grouped markdown files from exported page markdown under `exports-base`.

By default, the exporter groups by date when dates are detectable, and falls back to page-based grouping.

```bash
PYTHONPATH=. python3 scripts/build_year_exports.py \
  --exports-base /path/to/exports/msjournal-reader \
  --out-dir /path/to/exports/msjournal-reader/yearly
```

Common options:
- `--group-by auto|date|page` (default: `auto`)
- `--min-year 2024` / `--max-year 2026`
- `--fill-missing-days` (optional)

Outputs:
- Date-grouped: `yearly/journal-YYYY.md`
- Page-grouped: `yearly/journal-pages-<doc>.md`

## Lightweight search index (SQLite FTS)

Build/update an index for fast keyword search (date filtering available when dates are parseable):

```bash
PYTHONPATH=. python3 scripts/build_index.py \
  --exports-base /path/to/exports/msjournal-reader \
  --db /path/to/exports/msjournal-reader/index/journal_index.sqlite

PYTHONPATH=. python3 scripts/query_index.py \
  --db /path/to/exports/msjournal-reader/index/journal_index.sqlite \
  --q "taxes" --limit 10
```

## Incremental nightly sync (export + year files + index)

For per-user automation, use:

- `scripts/update_exports.py` (skips pages already exported and refreshes derived artifacts)
- A per-user config JSON under `user_corrections/local/` (example: `user_corrections/example_journals.json`)

Example:

```bash
PYTHONPATH=. python3 scripts/update_exports.py \
  --config user_corrections/local/journals.json \
  --exports-base /path/to/exports/msjournal-reader \
  --yearly-out /path/to/exports/msjournal-reader/yearly \
  --index-db /path/to/exports/msjournal-reader/index/journal_index.sqlite
```

## OpenClaw skill

The repo includes `SKILL.md` so it can be packaged/used as an OpenClaw skill.
