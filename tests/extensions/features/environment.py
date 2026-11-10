"""Extension suite hooks: guest-local execution and fail-closed cleanup.

Provisioning the guest and installing candidate artifacts belong to issues #908/#909.
The opt-in prevents accidental extension/settings changes on a maintainer's desktop.
"""

import json
import re
import subprocess

from tests.shared.extension_session import is_shell_journal_error, load_collection
from tests.shared.quarantine import skip_quarantine


def _journal(*args):
    result = subprocess.run(
        ["journalctl", "--user", "--no-pager", *args],
        capture_output=True, text=True, timeout=15,
    )
    if result.returncode:
        raise AssertionError(f"Cannot inspect guest session journal: {result.stderr}")
    return result.stdout


def before_all(context):
    if context.config.userdata.get("disposable_guest") != "true":
        raise AssertionError("Run only inside a disposable guest with -D disposable_guest=true; no host desktop tests")

    context.extensions_collection = load_collection()


def before_scenario(context, scenario):
    context.extension = None
    context.extension_journal_cursor = None
    context.extension_cleanups = []
    if skip_quarantine(scenario):
        return
    cursor = re.search(r"^-- cursor: (.+)$", _journal("-n", "0", "--show-cursor"), re.MULTILINE)
    if cursor is None:
        raise AssertionError("Guest journal cursor is unavailable; cannot scope errors to the scenario")
    context.extension_journal_cursor = cursor.group(1)


def after_scenario(context, scenario):
    failures = []
    cleanups = getattr(context, "extension_cleanups", [])
    while cleanups:
        callback, args = cleanups.pop()
        try:
            callback(*args)
        except Exception as exc:
            failures.append(f"Scenario cleanup failed: {type(exc).__name__}: {exc}")

    extension = getattr(context, "extension", None)
    if extension is not None:
        try:
            extension.cleanup()
        except Exception as exc:
            failures.append(f"Extension restoration failed: {type(exc).__name__}: {exc}")

    cursor = getattr(context, "extension_journal_cursor", None)
    if cursor is not None:
        try:
            output = _journal("--after-cursor", cursor, "--all", "-o", "json")
            errors = []
            for line in output.splitlines():
                record = json.loads(line)
                if is_shell_journal_error(record):
                    errors.append(str(record.get("MESSAGE")))
            if errors:
                failures.append("GNOME Shell errors during extension scenario:\n" + "\n".join(errors))
        except Exception as exc:
            failures.append(f"Journal inspection failed: {type(exc).__name__}: {exc}")
    # No cursor means before_scenario failed or quarantined the scenario.
    if failures:
        raise AssertionError("Extension scenario cleanup/journal failures:\n" + "\n".join(failures))
