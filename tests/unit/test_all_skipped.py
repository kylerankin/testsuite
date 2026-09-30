"""Unit tests for scripts/all_skipped.py.

The guard is the last line of defence against a false red: an all-skipped suite
(for example ``smoke-firefox`` on a Flatpak-only-Firefox image) has no passing
scenario and no failure to screenshot. behave already exits 0 for such a run,
but the "Promote desktop screenshot" step treats a missing screenshot as a hard
error. These tests lock in that an all-skipped suite is reported as a graceful
pass while a genuinely unrun or failing suite still fails.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.all_skipped import (  # noqa: E402
    format_breakdown,
    is_all_skipped,
    main,
)

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "all_skipped.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _scenario(status: str) -> dict:
    return {"type": "scenario", "name": f"scenario {status}", "status": status}


def _report(*statuses: str) -> list[dict]:
    return [
        {
            "name": "smoke-firefox",
            "elements": [_scenario(status) for status in statuses],
        }
    ]


def _write(tmp_path: Path, report) -> Path:
    path = tmp_path / "results.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# is_all_skipped
# ---------------------------------------------------------------------------


def test_is_all_skipped_true_when_everything_skipped():
    assert is_all_skipped(_report("skipped", "skipped", "skipped"))


def test_is_all_skipped_false_with_one_pass():
    assert not is_all_skipped(_report("passed", "skipped"))


def test_is_all_skipped_false_with_one_fail():
    assert not is_all_skipped(_report("failed", "skipped"))


def test_is_all_skipped_false_on_empty_report():
    """An empty report is a genuinely unrun suite, never a graceful pass."""
    assert not is_all_skipped([])


def test_is_all_skipped_false_on_backgrounds_only():
    report = [{"name": "f", "elements": [{"type": "background", "status": "skipped"}]}]
    assert not is_all_skipped(report)


# ---------------------------------------------------------------------------
# Exit-code behaviour
# ---------------------------------------------------------------------------


def test_all_skipped_exits_zero(tmp_path, capsys):
    path = _write(tmp_path, _report("skipped"))
    assert main([str(path)]) == 0
    assert "skipped=1" in capsys.readouterr().out


def test_some_passed_exits_one(tmp_path, capsys):
    path = _write(tmp_path, _report("passed", "skipped"))
    assert main([str(path)]) == 1
    assert "passed=1" in capsys.readouterr().out


def test_one_failed_exits_one(tmp_path, capsys):
    path = _write(tmp_path, _report("failed", "skipped"))
    assert main([str(path)]) == 1
    assert "failed=1" in capsys.readouterr().out


def test_empty_report_exits_one(tmp_path, capsys):
    path = _write(tmp_path, [])
    assert main([str(path)]) == 1
    assert "skipped=0" in capsys.readouterr().out


def test_mixed_all_passing_exits_one(tmp_path, capsys):
    """All-passing is not all-skipped: there is real coverage to screenshot."""
    path = _write(tmp_path, _report("passed", "passed"))
    assert main([str(path)]) == 1
    assert "passed=2" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Non-scenario elements
# ---------------------------------------------------------------------------


def test_backgrounds_are_not_counted(tmp_path):
    report = [
        {
            "name": "f",
            "elements": [
                {"type": "background", "status": "skipped"},
                {"type": "scenario", "status": "skipped"},
            ],
        }
    ]
    assert is_all_skipped(report)


def test_feature_without_elements_key_is_tolerated(tmp_path):
    path = _write(tmp_path, [{"name": "Empty feature"}, {"name": "Null", "elements": None}])
    assert main([str(path)]) == 1


# ---------------------------------------------------------------------------
# Bad input
# ---------------------------------------------------------------------------


def test_missing_results_file_exits_one(tmp_path, capsys):
    missing = tmp_path / "does-not-exist.json"
    assert main([str(missing)]) == 1
    assert "::error::No results.json found" in capsys.readouterr().out


def test_malformed_json_exits_one_without_traceback(tmp_path, capsys):
    path = tmp_path / "results.json"
    path.write_text("not json at all {{{", encoding="utf-8")
    assert main([str(path)]) == 1
    out = capsys.readouterr().out
    assert "::error::Could not parse" in out
    assert "Traceback" not in out


@pytest.mark.parametrize("payload", ['{"features": []}', "42", '"string"'])
def test_non_list_json_exits_one(tmp_path, capsys, payload):
    path = tmp_path / "results.json"
    path.write_text(payload, encoding="utf-8")
    assert main([str(path)]) == 1
    assert "::error::Could not parse" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Helpers and CLI
# ---------------------------------------------------------------------------


def test_format_breakdown_shape():
    counts = {"passed": 0, "failed": 0, "skipped": 2}
    assert format_breakdown(counts) == "Suite breakdown: passed=0 failed=0 skipped=2"


def test_cli_exits_zero_on_all_skipped(tmp_path):
    path = _write(tmp_path, _report("skipped"))
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(path)],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0
    assert "skipped=1" in completed.stdout


def test_cli_exits_one_on_some_passed(tmp_path):
    path = _write(tmp_path, _report("passed", "skipped"))
    completed = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), str(path)],
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 1
    assert "::error::" not in completed.stdout
    assert "Traceback" not in completed.stderr
