# msjournal-reader

Convert Microsoft Journal `.ink` files (SQLite DB) into text by extracting per-page rendered PNGs and running OCR.

This repo currently implements **Azure AI Vision Read**.
It’s structured to allow additional OCR providers later (see `msjournal_reader/ocr/`).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env with AZURE_VISION_ENDPOINT + AZURE_VISION_KEY
```

## Convert an .ink file

```bash
python3 scripts/ink_to_text.py \
  "/path/to/Journal.ink" \
  --out-dir ./out \
  --engine azure \
  --corrections-map user_corrections/example_regex.json
```

Outputs:
- `out/<ink-stem>/page_0000.txt` (+ `.md`)
- `out/<ink-stem>/combined.txt` (+ `.md`)

## Corrections

Provide either:
- a JSON dict map: `{ "wrong": "right" }`
- or a JSON regex list: `[["<regex>", "<replacement>"], ...]`

For personal corrections, use `user_corrections/local/` (gitignored).

## OpenClaw skill

The repo includes `SKILL.md` so it can be packaged/used as an OpenClaw skill.
