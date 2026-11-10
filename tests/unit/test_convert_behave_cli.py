"""Exercise the converter's argument-count boundary through its CLI."""

import json
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / "dashboard/scripts/convert_behave.py"


@pytest.mark.parametrize("operand_count", range(7))
def test_missing_operands_print_usage(operand_count, tmp_path):
    result = subprocess.run(
        [sys.executable, str(SCRIPT), *["missing"] * operand_count],
        cwd=tmp_path, capture_output=True, text=True,
    )

    assert result.returncode == 1
    assert result.stdout == (
        "Usage: convert_behave.py <behave_json> <run_id> <caller_repo> "
        "<slug> <suite> <timestamp> <output_dir>\n"
    )
    assert result.stderr == ""
    assert list(tmp_path.iterdir()) == []


def test_seven_operands_write_run_asset(tmp_path):
    source = tmp_path / "behave.json"
    source.write_text("[]")
    output = tmp_path / "output"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(source), "run-912",
         "projectbluefin/testsuite", "bluefin-testing", "smoke",
         "2026-09-30T00:00:00Z", str(output)],
        cwd=tmp_path, capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads((output / "run-912.json").read_text())["id"] == "run-912"
