from __future__ import annotations

from abc import ABC, abstractmethod


class OcrEngine(ABC):
    name: str

    @abstractmethod
    def ocr_png_bytes(self, png_bytes: bytes) -> str:
        """Return OCR text for a PNG (as bytes). Should return a trailing newline when non-empty."""
        raise NotImplementedError
