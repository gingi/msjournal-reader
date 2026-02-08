---
name: msjournal-reader
description: Convert Microsoft Journal .ink files into text using Azure AI Vision Read OCR. Use when extracting or exporting handwriting notes from Microsoft Journal (.ink) into .txt/.md (per-page + combined), optionally applying a user corrections map; also use when retraining/updating corrections from gold transcriptions.
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
- `./out/<ink-stem>/page_0000.txt` (+ `.md`)
- `./out/<ink-stem>/combined.txt` (+ `.md`)

## Corrections (post-OCR)

- Dict map: `{"wrong": "right"}` (word-boundary, case-insensitive)
- Regex list: `[["<regex>", "<replacement>"], ...]` applied in order

Keep personal corrections out of Git by putting them in `user_corrections/local/` (gitignored).

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
