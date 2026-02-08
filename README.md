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

## Per-user neural post-corrector (optional)

This is the "no more hand-maintained table" option: train a small seq2seq model that rewrites OCR text into your preferred style.

Install optional deps:

```bash
pip install -r requirements-ml.txt
```

Train (uses your `gold/` pages + OCR output pages):

```bash
python3 scripts/train_postcorrector_byt5.py \
  --gold-dir gold \
  --hyp-dir out/<ink-stem> \
  --out-dir user_corrections/local/models/byt5
```

Apply during conversion:

```bash
python3 scripts/ink_to_text.py \
  "/path/to/Journal.ink" \
  --out-dir ./out \
  --engine azure \
  --postcorrector-model user_corrections/local/models/byt5
```

Guardrail: by default, `--postcorrector-model` must live under `user_corrections/local/` to reduce the chance of accidentally committing weights. Override with `--allow-nonlocal-postcorrector`.

## OpenClaw skill

The repo includes `SKILL.md` so it can be packaged/used as an OpenClaw skill.
