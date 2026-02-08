from __future__ import annotations

from .azure import AzureVisionReadEngine
from .base import OcrEngine


def build_engine(name: str, **kwargs) -> OcrEngine:
    """Engine factory.

    Keep flexible for future providers by adding new engines here.
    """
    n = (name or "azure").lower()
    if n in ("azure", "azure-read", "azure_read"):
        return AzureVisionReadEngine.from_env(
            language=str(kwargs.get("azure_language", "en")),
            timeout_s=int(kwargs.get("azure_timeout_s", 180)),
        )

    raise ValueError(f"Unsupported OCR engine: {name} (only 'azure' is implemented in this repo for now)")
