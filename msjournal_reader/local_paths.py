from __future__ import annotations

from pathlib import Path


def is_under(path: Path, root: Path, *, resolve_symlinks: bool = True) -> bool:
    """Return True if path is under root.

    If resolve_symlinks=True (default), compares fully-resolved paths.
    If resolve_symlinks=False, compares lexical/absolute paths so symlinks under
    root are allowed even if they point elsewhere.
    """
    p = path.expanduser()
    r = root.expanduser()

    p2 = p.resolve() if resolve_symlinks else p.absolute()
    r2 = r.resolve() if resolve_symlinks else r.absolute()

    try:
        return p2.is_relative_to(r2)  # py3.9+
    except AttributeError:
        # Defensive fallback: is_relative_to requires Python 3.9+, which matches
        # our requires-python constraint, so this branch should never execute.
        # However, relative_to() provides platform-independent path comparison.
        try:
            p2.relative_to(r2)
            return True
        except ValueError:
            return False


def require_under(
    path: Path,
    root: Path,
    *,
    hint: str | None = None,
    resolve_symlinks: bool = True,
) -> Path:
    """Return the chosen normalized path and require that it is under root."""
    p = path.expanduser()
    r = root.expanduser()

    p2 = p.resolve() if resolve_symlinks else p.absolute()
    r2 = r.resolve() if resolve_symlinks else r.absolute()

    if not is_under(p2, r2, resolve_symlinks=False):
        msg = f"Path must be under {r2}: {p2}"
        if hint:
            msg += "\n" + str(hint)
        raise ValueError(msg)

    return p2
