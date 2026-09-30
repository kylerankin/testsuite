"""Unit tests for tests/shared/gnome_extensions_artifacts.py.

Covers every validation stage with synthetic ZIPs so the gate's contract logic
is proven without a GNOME OS guest or the ``gnome-extensions`` pack tool.
"""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from tests.shared import gnome_extensions_artifacts as art


def _make_zip(path: Path, members: dict[str, str], uuid: str = "test@uuid") -> Path:
    """Write a ZIP whose metadata.json declares ``uuid`` (honoured even if the
    caller also passes a ``metadata.json``)."""
    members = {**members}
    members["metadata.json"] = json.dumps({"uuid": uuid})
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

def test_sha256_matches_when_pinned(tmp_path):
    zip_path = _make_zip(tmp_path / "pinned.zip", {"extension.js": "x"}, uuid="test@uuid")
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    contract = art.ExtensionContract(
        uuid="test@uuid", source_repo="x/y", source_rev="abc",
        required_paths=("metadata.json", "extension.js"),
        zip_sha256=digest,
    )
    result = art.validate_extension_zip(zip_path, contract)
    assert result.valid, result.errors
    assert result.sha256_actual == digest
    assert art.classify(result) == "ok"


def test_sha256_pinned_in_uppercase_still_matches(tmp_path):
    zip_path = _make_zip(tmp_path / "upper.zip", {"extension.js": "x"}, uuid="test@uuid")
    digest = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    contract = art.ExtensionContract(
        uuid="test@uuid", source_repo="x/y", source_rev="abc",
        required_paths=("metadata.json", "extension.js"),
        zip_sha256=digest.upper(),
    )
    result = art.validate_extension_zip(zip_path, contract)
    assert result.valid, result.errors


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


def test_corrupt_archive_is_harness_failure(tmp_path):
    contract = art.ExtensionContract(uuid="test@uuid", source_repo="x/y", source_rev="abc")
    bad = _corrupt_zip(tmp_path / "corrupt.zip")

    # validate_extension_zip turns that harness failure into a classified result.
    result = art.validate_extension_zip(bad, contract)
    assert not result.valid
    assert art.classify(result) == "harness"


def test_missing_file_is_harness_failure(tmp_path):
    contract = art.ExtensionContract(uuid="test@uuid", source_repo="x/y", source_rev="abc")
    result = art.validate_extension_zip(tmp_path / "absent.zip", contract)
    assert not result.valid
    assert art.classify(result) == "harness"


def _rewrite_zip_member(zip_path: Path, name: str, content: bytes) -> Path:
    """Write a ZIP containing ``name`` with ``content`` (plus a dummy sibling so
    the archive is non-trivial)."""
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("extension.js", "x")
        zf.writestr(name, content)
    return zip_path


def test_malformed_metadata_json_is_metadata_failure(tmp_path):
    contract = art.ExtensionContract(uuid="test@uuid", source_repo="x/y", source_rev="abc")
    bad = _rewrite_zip_member(tmp_path / "bad.json.zip", "metadata.json", b"{not json")
    with pytest.raises(art.ArtifactValidationError):
        art._parse_metadata(b"{not json")
    # The gate classifies it as an unsupported-metadata (metadata) failure.
    result = art.validate_extension_zip(bad, contract)
    assert not result.valid
    assert art.classify(result) == "metadata"


def test_non_object_metadata_json_is_metadata_failure(tmp_path):
    contract = art.ExtensionContract(uuid="test@uuid", source_repo="x/y", source_rev="abc")
    bad = _rewrite_zip_member(tmp_path / "arr.zip", "metadata.json", b"[]")
    with pytest.raises(art.ArtifactValidationError):
        art._parse_metadata(b"[]")
    assert art.classify(art.validate_extension_zip(bad, contract)) == "metadata"


# --- hostile archives ----------------------------------------------------

def test_oversized_metadata_is_rejected_without_inflating(tmp_path):
    """A highly compressible metadata.json is refused on its declared size."""
    contract = art.ExtensionContract(uuid="test@uuid", source_repo="x/y", source_rev="abc")
    bomb = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("extension.js", "x")
        zf.writestr("metadata.json", b"\0" * (art._MAX_METADATA_BYTES + 1))
    assert bomb.stat().st_size < art._MAX_METADATA_BYTES  # compresses tiny

    result = art.validate_extension_zip(bomb, contract)
    assert not result.valid
    assert any("implausibly large" in e for e in result.errors)
    assert art.classify(result) == "metadata"


def test_duplicate_member_names_are_rejected(tmp_path):
    """Two metadata.json members must never validate on one and install another."""
    contract = art.ExtensionContract(
        uuid="test@uuid", source_repo="x/y", source_rev="abc",
        required_paths=("metadata.json",),
    )
    dupe = tmp_path / "dupe.zip"
    with pytest.warns(UserWarning, match="Duplicate name"):
        with zipfile.ZipFile(dupe, "w") as zf:
            zf.writestr("metadata.json", json.dumps({"uuid": "evil@uuid"}))
            zf.writestr("metadata.json", json.dumps({"uuid": "test@uuid"}))

    result = art.validate_extension_zip(dupe, contract)
    assert not result.valid
    assert any("duplicate member names" in e for e in result.errors)
    assert art.classify(result) == "artifact"


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


def test_canonical_contracts_require_what_packaging_ships():
    """Contracts must cover the members the shell actually loads, not just the
    manifest — otherwise an unloadable ZIP validates and the guest failure is
    misattributed."""
    jp = art.find_contract("just-perfection-desktop@just-perfection")
    assert jp is not None
    # scripts/build.sh packs the compiled resource bundle and lib/ as extras.
    assert "data/resources.gresource" in jp.required_paths
    assert any(p.startswith("lib/") for p in jp.required_paths)
    assert any(p.startswith("schemas/") for p in jp.required_paths)

    # Both binhnguyensoft extensions that commit a compiled schema must require
    # it: gschemas.compiled is what the shell reads for their settings.
    for uuid in ("sjc-gold@binhnguyensoft.com", "stock-market@binhnguyensoft.com"):
        contract = art.find_contract(uuid)
        assert contract is not None
        assert "schemas/gschemas.compiled" in contract.required_paths


def test_canonical_contracts_pin_no_hash_yet():
    """Stage 0 is documented as inert today; assert that stays explicit so the
    TODO(#908) is retired deliberately rather than silently."""
    assert all(c.zip_sha256 is None for c in art.CANONICAL_CONTRACTS)


# --- explicit failure categories ----------------------------------------

def test_category_is_recorded_on_the_result(tmp_path):
    contract = art.ExtensionContract(uuid="real@uuid", source_repo="x/y", source_rev="abc")
    zip_path = _make_zip(tmp_path / "cat.zip", {"extension.js": "x"}, uuid="other@uuid")
    result = art.validate_extension_zip(zip_path, contract)
    assert result.category == art.CATEGORY_METADATA
    assert art.classify(result) == "metadata"


def test_classify_does_not_depend_on_message_wording(tmp_path):
    """Rewording an error must not reclassify the failure."""
    contract = art.ExtensionContract(uuid="real@uuid", source_repo="x/y", source_rev="abc")
    zip_path = _make_zip(tmp_path / "reword.zip", {"extension.js": "x"}, uuid="other@uuid")
    result = art.validate_extension_zip(zip_path, contract)
    result.errors[0] = "the archive names a different extension"
    assert art.classify(result) == "metadata"


def test_first_category_wins_when_several_checks_fail(tmp_path):
    contract = art.ExtensionContract(
        uuid="real@uuid", source_repo="x/y", source_rev="abc",
        required_paths=("metadata.json", "missing.js"),
    )
    zip_path = _make_zip(tmp_path / "both.zip", {"extension.js": "x"}, uuid="other@uuid")
    result = art.validate_extension_zip(zip_path, contract)
    assert len(result.errors) == 2
    assert art.classify(result) == "metadata"


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
    # One mismatch -> exit 1, and the report carries the classify() category.
    assert art.main([str(good_a), str(good_b), str(bad_c), str(good_d)]) == 1
    # Wrong arg count -> exit 2 (usage).
    assert art.main([str(good_a)]) == 2


def test_main_reports_classify_category(tmp_path, monkeypatch, capsys):
    contracts = (
        art.ExtensionContract(uuid="a@x", source_repo="r", source_rev="r" * 40,
                              required_paths=("metadata.json", "a.js")),
    )
    monkeypatch.setattr(art, "CANONICAL_CONTRACTS", contracts)

    wrong_uuid = _make_zip(tmp_path / "w.zip", {"a.js": "x"}, uuid="WRONG@x")
    assert art.main([str(wrong_uuid)]) == 1
    assert "[FAIL/metadata]" in capsys.readouterr().out

    broken = _corrupt_zip(tmp_path / "broken.zip")
    assert art.main([str(broken)]) == 1
    assert "[FAIL/harness]" in capsys.readouterr().out
