#!/usr/bin/env python3
"""Exit 0 when a behave run is entirely skipped, else 1.

Backstop against a false red: an all-skipped suite (for example
``smoke-firefox`` on an image that ships Firefox only as a Flatpak) has no
passing scenario and no failure to screenshot. behave already exits 0 for such
a run, but the "Promote desktop screenshot" step treats a missing screenshot as
a hard error. This guard lets that step skip the screenshot requirement when the
suite legitimately has nothing to capture, while still failing a suite that has
neither passed nor skipped anything (an empty or unrun report).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

# e2e_summary.py is a sibling script, not a package. Add this directory so the
# import works both when run as ``python3 scripts/all_skipped.py`` and when
# imported as a module (pytest, other scripts).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from e2e_summary import count_scenarios, load_report  # noqa: E402

DEFAULT_RESULTS = Path("results/results.json")
DEFAULT_FAILED_SETUP_MARKER = Path("results/failed_setup.txt")


def is_all_skipped(report: Any) -> bool:
    """Return True when every counted scenario was skipped and nothing else ran.

    ``sum(counts.values()) == counts['skipped'] > 0`` — an empty report, an
    unrun suite, or one with undefined/untested/other scenarios returns False
    so failures or harness problems are never treated as a graceful pass.
    """
    counts = count_scenarios(report)
    skipped = counts.get("skipped", 0)
    total = sum(counts.values())
    return skipped > 0 and total == skipped

def format_breakdown(counts: dict[str, int]) -> str:
    return (
        "Suite breakdown: "
        f"passed={counts['passed']} failed={counts['failed']} "
        f"skipped={counts['skipped']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "results_json",
        nargs="?",
        default=DEFAULT_RESULTS,
        type=Path,
        help="Path to behave JSON output (default: results/results.json)",
    )
    parser.add_argument(
        "--failed-setup-marker",
        default=DEFAULT_FAILED_SETUP_MARKER,
        type=Path,
        help="Path to failed_setup marker file (default: results/failed_setup.txt)",
    )
    args = parser.parse_args(argv)

    if args.failed_setup_marker.is_file():
        print(f"::error::Harness before_all setup failed: {args.failed_setup_marker}")
        return 1

    if not args.results_json.is_file():
        print(f"::error::No results.json found: {args.results_json}")
        return 1

    try:
        text = args.results_json.read_text(encoding="utf-8")
        report, complete = load_report(text)
        if not complete:
            print(f"::error::Could not parse {args.results_json}: incomplete or truncated JSON report")
            return 1
        counts = count_scenarios(report)
    except (ValueError, OSError, TypeError, AttributeError) as error:
        print(f"::error::Could not parse {args.results_json}: {error}")
        return 1

    print(format_breakdown(counts))

    if is_all_skipped(report):
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
