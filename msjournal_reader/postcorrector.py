from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class PostCorrector:
    """Neural post-corrector: takes OCR text and rewrites it closer to user's gold style."""

    model_dir: Path
    device: str = "cpu"
    max_new_tokens: int = 1024

    def apply(self, text: str) -> str:
        """Apply the post-corrector to text.

        Lazy-imports transformers so the base skill can run without ML deps.
        """
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer  # type: ignore

        tok = AutoTokenizer.from_pretrained(str(self.model_dir))
        model = AutoModelForSeq2SeqLM.from_pretrained(str(self.model_dir))

        # device handling (cpu/cuda/mps). Keep simple.
        model.to(self.device)
        model.eval()

        inp = tok(text, return_tensors="pt", truncation=True)
        inp = {k: v.to(self.device) for k, v in inp.items()}

        out_ids = model.generate(
            **inp,
            max_new_tokens=int(self.max_new_tokens),
            do_sample=False,
        )
        out = tok.decode(out_ids[0], skip_special_tokens=True)
        out = out.strip()
        return out + ("\n" if out and not out.endswith("\n") else "")


def load_postcorrector(model_dir: Path, *, device: str = "cpu", max_new_tokens: int = 1024) -> PostCorrector:
    if not model_dir.exists():
        raise FileNotFoundError(f"Post-corrector model_dir not found: {model_dir}")
    return PostCorrector(model_dir=model_dir, device=device, max_new_tokens=max_new_tokens)
