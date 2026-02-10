---
name: journal-reader
description: Convert journal handwriting exports (Microsoft Journal .ink today) into per-page Markdown via OCR (Azure AI Vision Read) + optional corrections.
metadata: {"openclaw":{"requires":{"bins":["python3"],"env":["AZURE_VISION_ENDPOINT","AZURE_VISION_KEY"]},"primaryEnv":"AZURE_VISION_KEY"}}
---

# journal-reader

## Quick start

1) Set Azure credentials (recommended: copy `.env.example` → `.env`):

- `AZURE_VISION_ENDPOINT` (e.g. `https://<resource>.cognitiveservices.azure.com/`)
- `AZURE_VISION_KEY`

2) Convert an `.ink` file:

```bash
python3 scripts/ink_to_text.py \
  "/path/to/Journal.ink" \
  --out-dir ./out \
  --engine azure \
  --corrections-map user_corrections/example_regex.json
```

Outputs:
- `./out/<ink-stem>/page_0000.md`
- `./out/<ink-stem>/combined.md`

## Corrections (post-OCR)

- Dict map: `{"wrong": "right"}` (word-boundary, case-insensitive)
- Regex list: `[["<regex>", "<replacement>"], ...]` applied in order

Keep personal corrections out of Git by putting them in `user_corrections/local/` (gitignored).

## Per-user neural post-corrector (optional)

Train a small seq2seq model that rewrites OCR text (hyp) into your preferred transcription style (gold). This is a learnable replacement for maintaining a large explicit correction table.

- Install optional deps:

```bash
pip install -r requirements-ml.txt
```

Note: OCR outputs are `page_XXXX.md`. Training utilities strip the `# Page N` wrapper automatically.

- Train:

```bash
python3 scripts/train_postcorrector_byt5.py \
  --gold-dir gold \
  --hyp-dir out/<ink-stem> \
  --out-dir user_corrections/local/models/byt5
```

- Apply during conversion:

```bash
python3 scripts/ink_to_text.py \
  "/path/to/Journal.ink" \
  --out-dir ./out \
  --engine azure \
  --postcorrector-model user_corrections/local/models/byt5
```

Guardrail: by default, `--postcorrector-model` must live under `user_corrections/local/` (gitignored). Override with `--allow-nonlocal-postcorrector`.

## Training helpers (not ML)

- Learn a word/phrase substitution dict from gold vs OCR:

```bash
python3 scripts/train_corrections.py \
  --gold-dir gold \
  --hyp-dir out/<ink-stem> \
  --out user_corrections/learned.json
```

- Greedy WER-optimizing regex corrections:

```bash
python3 scripts/learn_corrections_greedy.py \
  --gold-dir gold \
  --hyp-dir out/<ink-stem> \
  --out user_corrections/learned_greedy.json
```
