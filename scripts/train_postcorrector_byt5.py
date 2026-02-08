#!/usr/bin/env python3
"""Train a per-user neural post-corrector (OCR hyp -> gold) using ByT5.

This does NOT change the OCR engine. It learns your idiosyncrasies as a rewrite layer.

Data convention:
- gold pages: gold/*page-0001*.txt (or page_0001, page-0001, page_0001)
- hyp pages : <hyp-dir>/page_0001.txt

Example:
  python3 scripts/train_postcorrector_byt5.py \
    --gold-dir gold \
    --hyp-dir out/journal-feb-2026 \
    --out-dir user_corrections/local/models/byt5 \
    --model google/byt5-small \
    --epochs 10

Requires optional deps:
  pip install -r requirements-ml.txt
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def _page_id(name: str) -> str | None:
    m = re.search(r"page[-_](\d{4})", name)
    return m.group(1) if m else None


def load_pairs(gold_dir: Path, hyp_dir: Path) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    for gp in sorted(gold_dir.glob("*.txt")):
        pid = _page_id(gp.name)
        if not pid:
            continue
        hp = hyp_dir / f"page_{pid}.txt"
        if not hp.exists():
            continue
        gold = gp.read_text(encoding="utf-8", errors="replace").strip()
        hyp = hp.read_text(encoding="utf-8", errors="replace").strip()
        if not gold or not hyp:
            continue
        pairs.append({"page": pid, "input": hyp, "target": gold})
    return pairs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold-dir", required=True)
    ap.add_argument("--hyp-dir", required=True)
    ap.add_argument("--out-dir", required=True, help="Where to save the fine-tuned model")
    ap.add_argument("--model", default="google/byt5-small")
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--lr", type=float, default=5e-4)
    ap.add_argument("--batch-size", type=int, default=1)
    ap.add_argument("--max-source-length", type=int, default=1024)
    ap.add_argument("--max-target-length", type=int, default=1024)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    gold_dir = Path(args.gold_dir)
    hyp_dir = Path(args.hyp_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    pairs = load_pairs(gold_dir, hyp_dir)
    if not pairs:
        raise SystemExit("No training pairs found. Check gold filenames + hyp-dir/page_XXXX.txt")

    # Write dataset snapshot for reproducibility (local path recommended)
    (out_dir / "train_pairs.json").write_text(json.dumps(pairs, indent=2) + "\n", encoding="utf-8")

    # Lazy imports so base install works
    import numpy as np  # type: ignore
    import torch  # type: ignore
    from datasets import Dataset  # type: ignore
    from transformers import (  # type: ignore
        AutoModelForSeq2SeqLM,
        AutoTokenizer,
        DataCollatorForSeq2Seq,
        Seq2SeqTrainer,
        Seq2SeqTrainingArguments,
        set_seed,
    )

    set_seed(int(args.seed))

    ds = Dataset.from_list(pairs)

    tok = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSeq2SeqLM.from_pretrained(args.model)

    def preprocess(ex):
        x = tok(ex["input"], max_length=int(args.max_source_length), truncation=True)
        y = tok(ex["target"], max_length=int(args.max_target_length), truncation=True)
        x["labels"] = y["input_ids"]
        return x

    tds = ds.map(preprocess, remove_columns=list(ds.features))

    collator = DataCollatorForSeq2Seq(tokenizer=tok, model=model)

    training_args = Seq2SeqTrainingArguments(
        output_dir=str(out_dir / "_runs"),
        num_train_epochs=float(args.epochs),
        learning_rate=float(args.lr),
        per_device_train_batch_size=int(args.batch_size),
        gradient_accumulation_steps=4,
        logging_steps=5,
        save_strategy="no",
        evaluation_strategy="no",
        report_to=[],
        fp16=False,
    )

    trainer = Seq2SeqTrainer(
        model=model,
        args=training_args,
        train_dataset=tds,
        data_collator=collator,
        tokenizer=tok,
    )

    trainer.train()

    # Save model + tokenizer where the runtime loader expects it
    model.save_pretrained(str(out_dir))
    tok.save_pretrained(str(out_dir))

    # Tiny sanity check: run the first example
    ex0 = pairs[0]
    inp = tok(ex0["input"], return_tensors="pt", truncation=True)
    with torch.no_grad():
        out_ids = model.generate(**inp, max_new_tokens=256, do_sample=False)
    out = tok.decode(out_ids[0], skip_special_tokens=True)

    (out_dir / "sanity.txt").write_text(
        "INPUT:\n" + ex0["input"] + "\n\nPRED:\n" + out + "\n\nGOLD:\n" + ex0["target"] + "\n",
        encoding="utf-8",
    )

    print(f"OK: trained post-corrector on {len(pairs)} pages -> {out_dir}")


if __name__ == "__main__":
    main()
