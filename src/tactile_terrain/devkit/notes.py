"""Workflow notes written by the model while the project is alpha tested."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

NOTES_FOLDER = "dev-notes"
SLUG_CHARS = 48  # file names stay short


def write_dev_note(models_path: Path, title: str, body: str) -> str:
    """Save one Markdown note under the models folder and return its path."""
    title = title.strip()
    if not title or not body.strip():
        raise ValueError("A dev note needs a title and a body.")
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:SLUG_CHARS] or "note"
    folder = models_path / NOTES_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = folder / f"{stamp}-{slug}.md"
    path.write_text(f"# {title}\n\n{body.strip()}\n", encoding="utf-8")
    return f"Saved dev note {path}"
