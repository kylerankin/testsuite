"""Single source of truth for recording a ``before_all`` harness failure.

When a suite's ``before_all`` blows up, every scenario is skipped and
``after_all`` returns early, so no in-VM screenshot is taken. That looks
identical to a legitimately all-skipped suite (``smoke-firefox`` on a
Flatpak-only-Firefox image), which ``scripts/all_skipped.py`` lets pass the
"Promote desktop screenshot" gate. The marker file written here is what tells
the two apart: ``scripts/all_skipped.py`` vetoes the graceful pass when
``results/failed_setup.txt`` exists.

Every ``context.failed_setup = ...`` assignment must go through
``record_failed_setup`` so the marker can never be forgotten.
"""

from __future__ import annotations

import os
from typing import Any

from tests.shared.results_dir import resolve_results_dir

MARKER_FILENAME = "failed_setup.txt"


def write_failed_setup_marker(context: Any, detail: str) -> str | None:
    """Write the harness-failure marker into the resolved results dir.

    Returns the marker path, or ``None`` when it could not be written (a
    best-effort artifact must never mask the original setup error).
    """
    try:
        results_dir = resolve_results_dir(context)
        os.makedirs(results_dir, exist_ok=True)
        marker_path = os.path.join(results_dir, MARKER_FILENAME)
        with open(marker_path, "w", encoding="utf-8") as handle:
            handle.write(detail)
        return marker_path
    except OSError as error:
        print(f"WARNING: could not write {MARKER_FILENAME}: {error}", flush=True)
        return None


def record_failed_setup(context: Any, detail: str) -> str:
    """Set ``context.failed_setup`` and write the marker file. Returns detail."""
    context.failed_setup = detail
    write_failed_setup_marker(context, detail)
    return detail
