from __future__ import annotations

from pathlib import Path


def is_under(path: Path, root: Path) -> bool:
    """Return True if path is under root (after resolving)."""
    p = path.expanduser().resolve()
    r = root.expanduser().resolve()
    try:
        return p.is_relative_to(r)  # py3.9+
    except Exception:
        return str(p).startswith(str(r) + "/")


def require_under(path: Path, root: Path, *, hint: str | None = None) -> Path:
    """Resolve and require that path is under root."""
    p = path.expanduser().resolve()
    r = root.expanduser().resolve()
    if not is_under(p, r):
        msg = f"Path must be under {r}: {p}"
        if hint:
            msg += "\n" + str(hint)
        raise ValueError(msg)
    return p
