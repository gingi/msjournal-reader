from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests
from dotenv import load_dotenv

from .base import OcrEngine


@dataclass
class AzureVisionReadEngine(OcrEngine):
    """Azure AI Vision Read (v3.2) engine."""

    endpoint: str
    key: str
    language: str = "en"
    timeout_s: int = 180

    name: str = "azure"

    @classmethod
    def from_env(cls, *, language: str = "en", timeout_s: int = 180) -> "AzureVisionReadEngine":
        load_dotenv()
        endpoint = os.environ.get("AZURE_VISION_ENDPOINT", "").strip()
        key = os.environ.get("AZURE_VISION_KEY", "").strip()
        if not endpoint or not key:
            raise RuntimeError(
                "Missing AZURE_VISION_ENDPOINT/AZURE_VISION_KEY (set env vars or create .env; see .env.example)"
            )
        return cls(endpoint=endpoint, key=key, language=language, timeout_s=int(timeout_s))

    def ocr_png_bytes(self, png_bytes: bytes) -> str:
        analyze_url = self.endpoint.rstrip("/") + "/vision/v3.2/read/analyze"
        headers = {
            "Ocp-Apim-Subscription-Key": self.key,
            "Content-Type": "application/octet-stream",
        }
        params = {"language": self.language}

        r = requests.post(analyze_url, headers=headers, params=params, data=png_bytes, timeout=30)
        if r.status_code != 202:
            raise RuntimeError(f"Azure analyze failed ({r.status_code}): {r.text}")

        op_loc = r.headers.get("Operation-Location")
        if not op_loc:
            raise RuntimeError("Azure response missing Operation-Location header")

        deadline = time.time() + int(self.timeout_s)
        while time.time() < deadline:
            pr = requests.get(op_loc, headers={"Ocp-Apim-Subscription-Key": self.key}, timeout=30)
            if pr.status_code != 200:
                raise RuntimeError(f"Azure poll failed ({pr.status_code}): {pr.text}")
            j = pr.json()
            status = str(j.get("status", ""))
            if status.lower() == "succeeded":
                analyze = j.get("analyzeResult") or {}
                read_results = analyze.get("readResults") or []
                lines_out: list[str] = []
                for page in read_results:
                    for line in page.get("lines") or []:
                        t = str(line.get("text") or "").strip()
                        if t:
                            lines_out.append(t)
                out = "\n".join(lines_out).strip()
                return out + ("\n" if out and not out.endswith("\n") else "")
            if status.lower() == "failed":
                raise RuntimeError(f"Azure Read failed: {j}")
            time.sleep(0.7)

        raise RuntimeError("Azure Read timed out polling")
