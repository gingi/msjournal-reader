---
name: msjournal-reader
description: Convert Microsoft Journal .ink files into text using Azure AI Vision Read OCR. Use when extracting or exporting handwriting notes from Microsoft Journal (.ink) into per-page Markdown, optionally applying a user corrections map; also use when rebuilding grouped exports/search index or retraining/updating corrections from gold transcriptions.
---

# msjournal-reader

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
