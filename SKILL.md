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

## Slack DM review protocol (remote Q/A, deterministic commands)

In Slack DM, treat messages containing a `jr:` command as review commands (often preceded by an @mention).
Anything else is normal chat.

Command handler entrypoint:
- `PYTHONPATH=. python3 scripts/jr_cmd.py "<raw message>"`

Supported commands:
- `jr: review` / `jr: next`
- `jr: accept 1|2|3`
- `jr: accept <replacement text>`
- `jr: skip`
- `jr: image`
- `jr: stop`

Rules:
- Always paste the script output verbatim (no emoji-only reactions, no freelancing).
- Do **not** show items in batch mode.
- After `accept`/`skip`, do **not** auto-post the next item; tell the user to send `jr: next`.
- After the first accepted correction, start a 1-hour integration timer.
- If the queue completes, integrate immediately.

If the user replies `!jr image`:

- Do **not** ask which item. Use the currently pending item.
- Do **not** try to fetch/read Slack attachments or ask the user to re-upload anything.
- Always generate the image locally from the `.ink` source and send it.

Steps:
1) `cd /home/shiran/src/msjournal-reader`
2) Run:
   - `PYTHONPATH=. python3 scripts/chat_review.py image`
     - This prints JSON with `png`, `doc`, `page`, and the exact `example.path` + `example.line` used.
3) Send the PNG at `png` to Slack as an attachment (prefer replying in the same DM thread).
4) In the same message, paste:
   - `doc` + `page`
   - `example.line`

Cropping:
- Leave cropping best-effort.
- Do **not** `pip install` anything at runtime.
- Our Python env workflows use `uv` (not venv).
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
