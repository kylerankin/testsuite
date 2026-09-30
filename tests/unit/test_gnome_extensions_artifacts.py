"""Unit tests for tests/shared/gnome_extensions_artifacts.py.

Covers every validation stage with synthetic ZIPs so the gate's contract logic
is proven without a GNOME OS guest or the ``gnome-extensions`` pack tool.
"""

import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.shared import gnome_extensions_artifacts as art  # noqa: E402


def _make_zip(path: Path, members: dict[str, str], uuid: str = "test@uuid") -> Path:
    """Write a ZIP whose metadata.json declares ``uuid``."""
    members = {**members}
    members.setdefault("metadata.json", json.dumps({"uuid": uuid}))
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in members.items():
            zf.writestr(name, content)
    return path


def _corrupt_zip(path: Path) -> Path:
    """A file that is neither a valid ZIP nor plain text."""
    path.write_bytes(bytes(range(256)) * 4)
    return path


# --- happy path ----------------------------------------------------------

def test_valid_archive_passes(tmp_path):
    contract = art.ExtensionContract(
        uuid="test@uuid",
        source_repo="x/y",
        source_rev="abc123",
        required_paths=("metadata.json", "extension.js"),
    )
    zip_path = _make_zip(tmp_path / "ok.zip", {"extension.js": "x"}, uuid="test@uuid")
    result = art.validate_extension_zip(zip_path, contract)
    assert result.valid
    assert result.uuid_found == "test@uuid"
    assert art.classify(result) == "ok"


# --- UUID mismatch -------------------------------------------------------

def test_uuid_mismatch_is_metadata_failure(tmp_path):
    contract = art.ExtensionContract(uuid="real@uuid", source_repo="x/y", source_rev="abc")
    zip_path = _make_zip(tmp_path / "wrong.zip", {"metadata.json": "{}"}, uuid="other@uuid")
    result = art.validate_extension_zip(zip_path, contract)
    assert not result.valid
    assert not result.metadata_ok
    assert any("UUID mismatch" in e for e in result.errors)
    assert art.classify(result) == "metadata"


# --- missing required paths ----------------------------------------------

def test_missing_required_path_is_artifact_failure(tmp_path):
    contract = art.ExtensionContract(
        uuid="test@uuid", source_repo="x/y", source_rev="abc",
        required_paths=("metadata.json", "extension.js", "missing.js"),
    )
    zip_path = _make_zip(tmp_path / "partial.zip", {"extension.js": "x"}, uuid="test@uuid")
    result = art.validate_extension_zip(zip_path, contract)
    assert not result.valid
    assert "missing.js" in result.required_missing
    assert art.classify(result) == "artifact"


# --- SHA256 --------------------------------------------------------------

def test_sha256_mismatch(tmp_path):
    contract = art.ExtensionContract(
        uuid="test@uuid", source_repo="x/y", source_rev="abc",
        zip_sha256="0" * 64,
    )
    zip_path = _make_zip(tmp_path / "h.zip", {"metadata.json": "{}"}, uuid="test@uuid")
    result = art.validate_extension_zip(zip_path, contract)
    assert not result.valid
    assert any("SHA256 mismatch" in e for e in result.errors)
    assert result.sha256_actual is not None


def test_sha256_is_skipped_when_unpinned(tmp_path):
    contract = art.ExtensionContract(uuid="test@uuid", source_repo="x/y", source_rev="abc")
    zip_path = _make_zip(tmp_path / "n.hash.zip", {"extension.js": "x"}, uuid="test@uuid")
    result = art.validate_extension_zip(zip_path, contract)
    assert result.valid
    assert result.sha256_actual is None


# --- unreadable archive --------------------------------------------------

def test_unreadable_archive_is_harness_failure(tmp_path):
    contract = art.ExtensionContract(uuid="test@uuid", source_repo="x/y", source_rev="abc")
    bad = _corrupt_zip(tmp_path / "not-a-zip.zip")
    result = art.validate_extension_zip(bad, contract)
    assert not result.valid
    assert art.classify(result) == "harness"


def test_read_metadata_raises_on_non_zip(tmp_path):
    contract = art.ExtensionContract(uuid="test@uuid", source_repo="x/y", source_rev="abc")
    bad = _corrupt_zip(tmp_path / "corrupt.zip")
    with pytest.raises(art.ArtifactValidationError):
        art._read_metadata(bad)

    # validate_extension_zip turns that harness failure into a classified result.
    result = art.validate_extension_zip(bad, contract)
    assert not result.valid
    assert art.classify(result) == "harness"


# --- canonical contracts -------------------------------------------------

def test_canonical_contracts_have_uuids_and_revs():
    assert len(art.CANONICAL_CONTRACTS) == 4
    for contract in art.CANONICAL_CONTRACTS:
        assert "@" in contract.uuid
        assert len(contract.source_rev) == 40
        assert contract.required_paths
        assert "metadata.json" in contract.required_paths


def test_find_contract_roundtrip():
    contract = art.find_contract("stock-market@binhnguyensoft.com")
    assert contract is not None
    assert "stocks_fetch.py" in contract.required_paths
    assert art.find_contract("does-not-exist@uuid") is None


def test_validate_all_reports_unknown_uuid(tmp_path):
    zip_path = _make_zip(tmp_path / "x.zip", {"metadata.json": "{}"}, uuid="test@uuid")
    results = art.validate_all({"unknown@uuid": zip_path})
    assert len(results) == 1
    assert not results[0].valid
    assert results[0].errors[0].startswith("no canonical contract")


def test_main_exit_codes(tmp_path, monkeypatch):
    contracts = (
        art.ExtensionContract(uuid="a@x", source_repo="r", source_rev="r" * 40,
                              required_paths=("metadata.json", "a.js")),
        art.ExtensionContract(uuid="b@x", source_repo="r", source_rev="r" * 40,
                              required_paths=("metadata.json", "b.js")),
        art.ExtensionContract(uuid="c@x", source_repo="r", source_rev="r" * 40,
                              required_paths=("metadata.json", "c.js")),
        art.ExtensionContract(uuid="d@x", source_repo="r", source_rev="r" * 40,
                              required_paths=("metadata.json", "d.js")),
    )
    monkeypatch.setattr(art, "CANONICAL_CONTRACTS", contracts)

    good_a = _make_zip(tmp_path / "a.zip", {"a.js": "x"}, uuid="a@x")
    good_b = _make_zip(tmp_path / "b.zip", {"b.js": "x"}, uuid="b@x")
    good_c = _make_zip(tmp_path / "c.zip", {"c.js": "x"}, uuid="c@x")
    good_d = _make_zip(tmp_path / "d.zip", {"d.js": "x"}, uuid="d@x")
    bad_c = _make_zip(tmp_path / "cbad.zip", {"c.js": "x"}, uuid="WRONG@x")

    # All pass -> exit 0.
    assert art.main([str(good_a), str(good_b), str(good_c), str(good_d)]) == 0
    # One mismatch -> exit 1.
    assert art.main([str(good_a), str(good_b), str(bad_c), str(good_d)]) == 1
    # Wrong arg count -> exit 2 (usage).
    assert art.main([str(good_a)]) == 2
