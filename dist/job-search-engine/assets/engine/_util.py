"""Shared low-level helpers with no engine dependencies.

Lives here (not in main.py) so modules main.py imports — e.g. company_enrich —
can reuse them without a circular import. main.py re-exports atomic_write_json
for backward compatibility.
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def atomic_write_json(path: Path, obj) -> None:
    """Write JSON atomically: temp file in the same dir, fsync, os.replace.

    Hardening ported from the uiux pipeline 2026-07-06: its Phase 2 found
    candidates.json with a second stale array concatenated after the fresh one
    ("Extra data" on json.loads). A plain write_text() leaves a window where
    readers/sync layers can observe a partially rewritten file; os.replace
    guarantees readers only ever see one complete document.
    """
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)
