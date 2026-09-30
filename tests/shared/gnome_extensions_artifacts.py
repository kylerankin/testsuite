"""Validate packaged GNOME Shell extension ZIPs against a pinned contract.

Used by the four-profile GNOME OS gate (issue #909) to reject an extension
artifact *before* it is extracted or installed, so a Bluefin smoke failure can
never be misattributed to an extension that was never actually installed.

This is the "reviewed builder isolated from the trusted scheduler" validation
from agent-plan step 1: it only inspects the archive, it never extracts to the
host and it carries no EGO credentials or upload path. The actual GNOME OS
guest that consumes the validated artifact comes from #908, so this module is
fully testable without a VM.

Validation stages, in order:

1. ``metadata.json`` inside the ZIP must declare the contract ``uuid``.
2. Every path in ``required_paths`` must be present in the ZIP.
3. If ``zip_sha256`` is set on the contract, the archive SHA256 must match.

A failure in stage 1 is an *unsupported-metadata* problem (the artifact does
not even claim to be the right extension); a failure in stage 2 or 3 is an
*artifact* problem (the wrong or corrupt ZIP was staged). Callers can tell the
two apart via :func:`classify`.
"""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# metadata.json is the single source of truth for an extension's UUID. It lives
# at the ZIP root for theinhnguyensoft.com widgets and for the packed
# just-perfection archive; both are checked.
_METADATA_PATHS = ("metadata.json", "src/metadata.json")


def _parse_metadata(raw: bytes) -> dict:
    """Parse ``metadata.json`` bytes, raising on malformed/non-object JSON.

    A well-formed archive always carries a JSON object here; anything else
    (invalid JSON, a JSON array/list) is an unsupported-metadata problem and
    is reported rather than escaping as an uncaught exception.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ArtifactValidationError(f"malformed metadata.json: {exc}") from exc
    if not isinstance(data, dict):
        raise ArtifactValidationError(
            f"metadata.json is not a JSON object: {type(data).__name__}"
        )
    return data


def _metadata_in(zf: zipfile.ZipFile, names: set[str]) -> dict:
    """Return the first ``metadata.json`` found in an open archive, else raise."""
    for meta in _METADATA_PATHS:
        if meta in names:
            return _parse_metadata(zf.read(meta))
    raise ArtifactValidationError("no metadata.json found in archive")


class ArtifactValidationError(Exception):
    """Raised when the ZIP cannot be opened or is not a valid extension archive."""


@dataclass(frozen=True)
class ExtensionContract:
    """The pinned identity of one packaged extension.

    ``zip_sha256`` is optional: structural validation (UUID + required paths)
    always runs, but the hash check is skipped until the pinned build produces
    an immutable ZIP. See :data:`CANONICAL_CONTRACTS`.
    """

    uuid: str
    source_repo: str
    source_rev: str
    required_paths: tuple[str, ...] = ()
    optional_paths: tuple[str, ...] = ()
    zip_sha256: str | None = None
    package_recipe: str = ""
    shell_version: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return f"{self.uuid} ({self.source_repo}@{self.source_rev[:8]})"


@dataclass
class ExtensionValidationResult:
    """Outcome of validating one artifact against one contract."""

    contract: ExtensionContract
    uuid_found: str | None = None
    required_missing: list[str] = field(default_factory=list)
    sha256_expected: str | None = None
    sha256_actual: str | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def metadata_ok(self) -> bool:
        return self.uuid_found == self.contract.uuid


def _read_metadata(zip_path: str | Path) -> dict:
    """Return the first ``metadata.json`` found in the ZIP, else raise."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            return _metadata_in(zf, set(zf.namelist()))
    except zipfile.BadZipFile as exc:
        raise ArtifactValidationError(f"not a valid ZIP archive: {exc}") from exc
    except OSError as exc:
        raise ArtifactValidationError(f"cannot read {zip_path}: {exc}") from exc
    raise ArtifactValidationError("no metadata.json found in archive")


def _sha256_zip(zip_path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(zip_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_extension_zip(zip_path: str | Path, contract: ExtensionContract) -> ExtensionValidationResult:
    """Validate ``zip_path`` against ``contract``.

    Never raises for a contract mismatch — structural problems are reported on
    the returned :class:`ExtensionValidationResult` so the caller can decide
    whether they block the gate. Only an unreadable archive raises
    :class:`ArtifactValidationError`.
    """
    zip_path = Path(zip_path)
    result = ExtensionValidationResult(
        contract=contract,
        sha256_expected=contract.zip_sha256,
    )

    try:
        with zipfile.ZipFile(zip_path) as zf:  # single handle for read + namelist
            names = set(zf.namelist())
            try:
                metadata = _metadata_in(zf, names)
            except ArtifactValidationError as exc:
                # Stage-1 metadata problem: the archive is readable but its
                # metadata.json is missing or malformed, so it declares no usable
                # UUID. Report it as a metadata failure, not a harness one.
                result.errors.append(
                    f"UUID mismatch: archive metadata could not be read ({exc}), "
                    f"contract expects {contract.uuid!r}"
                )
                return result
    except zipfile.BadZipFile as exc:
        result.errors.append(f"archive unreadable: {exc}")
        return result
    except OSError as exc:
        result.errors.append(f"archive unreadable: {exc}")
        return result

    result.uuid_found = metadata.get("uuid")
    if result.uuid_found != contract.uuid:
        result.errors.append(
            f"UUID mismatch: archive declares {metadata.get('uuid')!r}, "
            f"contract expects {contract.uuid!r}"
        )

    result.required_missing = [p for p in contract.required_paths if p not in names]
    if result.required_missing:
        result.errors.append(
            "missing required paths: " + ", ".join(sorted(result.required_missing))
        )

    if contract.zip_sha256:
        result.sha256_actual = _sha256_zip(zip_path)
        if result.sha256_actual != contract.zip_sha256:
            result.errors.append(
                f"SHA256 mismatch: expected {contract.zip_sha256}, "
                f"got {result.sha256_actual}"
            )

    return result


def classify(result: ExtensionValidationResult) -> str:
    """Classify a failure for the gate report.

    Returns one of:

    * ``"ok"`` — the artifact passed every check.
    * ``"harness"`` — the archive could not be read (infra/provisioning fault).
    * ``"metadata"`` — the wrong extension was staged (unsupported metadata).
    * ``"artifact"`` — the right extension but wrong/corrupt ZIP (hash or paths).
    """
    if result.valid:
        return "ok"
    if not result.metadata_ok and (
        not result.errors or result.errors[0].startswith("UUID mismatch")
    ):
        return "metadata"
    if result.errors and result.errors[0].startswith("archive unreadable"):
        return "harness"
    return "artifact"


#: Canonical contract for the four extensions in issue #909.
#:
#: ``source_rev`` is the pinned HEAD of each hive repo (verified immutable at
#: commit time). ``zip_sha256`` is ``None`` until #908's builder produces the
#: immutable packaged ZIP for that revision — structural validation runs in the
#: meantime so a mis-attributed smoke failure is still caught.
CANONICAL_CONTRACTS: tuple[ExtensionContract, ...] = (
    ExtensionContract(
        uuid="just-perfection-desktop@just-perfection",
        source_repo="gnome-extensions-hive/just-perfection",
        source_rev="6e82a6ebf8e9578f2ffe4e06b88f5d23f600b947",
        required_paths=("metadata.json", "extension.js", "stylesheet.css"),
        package_recipe="scripts/build.sh",
    ),
    ExtensionContract(
        uuid="sjc-gold@binhnguyensoft.com",
        source_repo="gnome-extensions-hive/sjc-gold-binhnguyensoft.com",
        source_rev="1588c7683d113e42d2f36a69165a9bacd6b1d95b",
        required_paths=("metadata.json", "extension.js", "sjc_price.py"),
        package_recipe="root metadata",
    ),
    ExtensionContract(
        uuid="shade-inactive-windows-reborn@binhnguyensoft.com",
        source_repo="gnome-extensions-hive/Shade-Inactive-Windows-Reborn",
        source_rev="59b0afaf7320f72ef408621dafac19ec0214705b",
        required_paths=("metadata.json", "extension.js"),
        package_recipe="root metadata",
    ),
    ExtensionContract(
        uuid="stock-market@binhnguyensoft.com",
        source_repo="gnome-extensions-hive/stock-market-binhnguyensoft.com",
        source_rev="667e40171ca6249b846e72cf28e314c5f3a79832",
        required_paths=(
            "metadata.json",
            "extension.js",
            "prefs.js",
            "language.js",
            "stocks_fetch.py",
            "schemas/org.gnome.shell.extensions.stock-market-binhnguyensoft-com.gschema.xml",
        ),
        package_recipe="root metadata",
    ),
)


def find_contract(uuid: str) -> ExtensionContract | None:
    """Return the canonical contract matching ``uuid``, if any."""
    for contract in CANONICAL_CONTRACTS:
        if contract.uuid == uuid:
            return contract
    return None


def validate_all(zip_by_uuid: dict[str, str | Path]) -> list[ExtensionValidationResult]:
    """Validate one staged ZIP per contract key in ``zip_by_uuid``.

    Keys are contract ``uuid`` values; unknown keys are reported as an error and
    classified as ``"artifact"`` rather than silently ignored, so a mis-staged
    file is never missed.
    """
    by_uuid = {c.uuid: c for c in CANONICAL_CONTRACTS}
    results: list[ExtensionValidationResult] = []
    for uuid, zip_path in zip_by_uuid.items():
        contract = by_uuid.get(uuid)
        if contract is None:
            result = ExtensionValidationResult(contract=ExtensionContract(
                uuid=uuid, source_repo="?", source_rev="?"
            ))
            result.errors.append("no canonical contract for this UUID")
            results.append(result)
            continue
        results.append(validate_extension_zip(zip_path, contract))
    return results


def main(argv: list[str] | None = None) -> int:
    """CLI gate: validate staged ZIPs against the canonical contracts.

    Usage: ``python -m tests.shared.gnome_extensions_artifacts path/to/*.zip``
    One positional per expected extension, in canonical order. Prints a
    per-extension line and exits non-zero if any fails.
    """
    import sys

    args = sys.argv[1:] if argv is None else argv
    if len(args) != len(CANONICAL_CONTRACTS):
        print(
            f"usage: {sys.argv[0]} <zip> x{len(CANONICAL_CONTRACTS)} "
            f"(one per canonical extension, in order)",
            file=sys.stderr,
        )
        return 2

    failures = 0
    for contract, zip_path in zip(CANONICAL_CONTRACTS, args):
        result = validate_extension_zip(zip_path, contract)
        status = "OK" if result.valid else "FAIL"
        print(f"[{status}] {contract.label}")
        if not result.valid:
            failures += 1
            for error in result.errors:
                print(f"        {error}")
    print(f"{len(CANONICAL_CONTRACTS) - failures}/{len(CANONICAL_CONTRACTS)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
