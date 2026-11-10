"""Guest-local operations for the extension collection, never a VM provisioner.

The suite must opt into disposable-guest execution before constructing a session.
Read-only Shell probes inspect rendered actors rather than extension-private state.
"""

import ast
import json
import os
from pathlib import Path
import re
import subprocess
import time


COLLECTION_PATH = Path(__file__).resolve().parents[1] / "extensions" / "collection.json"
SHELL_ERROR = re.compile(
    r"\bJS (?:ERROR|WARNING)\b|\b(?:Gjs|GLib-GObject)-(?:CRITICAL|WARNING)\b"
    r"|\b(?:Reference|Type|Syntax|Range|Eval|URI)Error\s*:|\bUnhandled promise rejection\b"
)


def is_shell_journal_error(record):
    """Reject Shell API/JS failures, not a provider's caught console.error.

    GLib warnings carry their severity in GLIB_DOMAIN and PRIORITY, not
    necessarily MESSAGE. Shell console errors (domain "GNOME Shell") may be
    expected provider outages; only JS/API exception text fails that gate.
    """
    if record.get("SYSLOG_IDENTIFIER") != "gnome-shell" and record.get("_COMM") != "gnome-shell":
        return False
    if record.get("GLIB_DOMAIN") in ("Gjs", "GLib-GObject"):
        try:
            if 0 <= int(record.get("PRIORITY")) <= 4:
                return True
        except (TypeError, ValueError):
            pass
    message = record.get("MESSAGE", "")
    if isinstance(message, list):
        try:
            message = bytes(message).decode("utf-8", errors="replace")
        except (TypeError, ValueError):
            return False
    return isinstance(message, str) and SHELL_ERROR.search(message) is not None


def load_collection(path=COLLECTION_PATH):
    with Path(path).open(encoding="utf-8") as source:
        return json.load(source)


def parse_shell_json(output):
    """Decode Shell.Eval's success flag and JSON string; rejected Eval is failure."""
    match = re.fullmatch(r"\(\s*(true|false),\s*(.+)\)\s*", output.strip(), re.DOTALL)
    if not match or match.group(1) != "true":
        raise AssertionError(f"Shell.Eval did not succeed: {output!r}")
    try:
        payload = ast.literal_eval(match.group(2))
        if not isinstance(payload, str):
            raise ValueError("Eval result is not a string")
        return json.loads(payload)
    except (SyntaxError, ValueError, TypeError) as exc:
        raise AssertionError(f"Invalid JSON from Shell.Eval: {output!r}") from exc


def installed_path(info):
    """Resolve the public CLI's Path field, not a guessed system-extension path."""
    match = re.search(r"^\s*Path:\s*(.+?)\s*$", info, re.MULTILINE)
    if not match or not Path(match.group(1)).is_absolute():
        raise AssertionError(f"Extension info has no absolute Path: {info!r}")
    return Path(match.group(1))


class ExtensionSession:
    def __init__(self, profile):
        self.profile = profile
        self.uuid = profile["uuid"]
        self.schema = profile["schema"]
        self.package_path = None
        self._saved_settings = {}
        self._original_enabled = None

    def command(self, argv, check=True, timeout=30):
        env = dict(os.environ, LC_ALL="C.UTF-8")
        if self.package_path is not None:
            env["GSETTINGS_SCHEMA_DIR"] = str(self.package_path / "schemas")
        result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
        if check and result.returncode:
            raise AssertionError(f"Guest command failed ({result.returncode}): {argv!r}\n{result.stderr}")
        return result

    def shell_json(self, expression):
        # Shell's EvalAsync already JSON.stringify()s the evaluated result.
        script = f"global.context.unsafe_mode = true; ({expression})"
        result = self.command([
            "gdbus", "call", "--session", "--dest", "org.gnome.Shell",
            "--object-path", "/org/gnome/Shell", "--method", "org.gnome.Shell.Eval", script,
        ])
        return parse_shell_json(result.stdout)

    def wait_for(self, expression, expected=True, timeout=10):
        deadline = time.monotonic() + timeout
        actual = None
        while time.monotonic() < deadline:
            actual = self.shell_json(expression)
            if actual == expected:
                return actual
            time.sleep(0.1)
        raise AssertionError(f"Shell condition not reached: {expression}; expected {expected!r}, got {actual!r}")

    def is_enabled(self):
        result = self.command(["gnome-extensions", "list", "--enabled"])
        return self.uuid in result.stdout.splitlines()

    def ensure_installed(self):
        info = self.command(["gnome-extensions", "info", self.uuid]).stdout
        self.package_path = installed_path(info)
        metadata = json.loads((self.package_path / "metadata.json").read_text(encoding="utf-8"))
        if metadata.get("uuid") != self.uuid or metadata.get("settings-schema") != self.schema:
            raise AssertionError(f"Installed candidate identity does not match collection profile: {metadata!r}")
        self._original_enabled = self.is_enabled()
        # Trusted test probe is a prerequisite, not a skipped test.
        if self.shell_json("true") is not True:
            raise AssertionError("Shell.Eval prerequisite did not return boolean true")

    def _wait_enabled(self, enabled):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.is_enabled() == enabled:
                return
            time.sleep(0.1)
        raise AssertionError(f"Extension {self.uuid} did not become {'enabled' if enabled else 'disabled'}")

    def enable(self):
        self.command(["gnome-extensions", "enable", self.uuid])
        self._wait_enabled(True)
        deadline = time.monotonic() + 10
        info = ""
        while time.monotonic() < deadline:
            info = self.command(["gnome-extensions", "info", self.uuid]).stdout
            state = re.search(r"^\s*State:\s*([A-Z_ ]+)\s*$", info, re.MULTILINE)
            if state and state.group(1).strip() in ("ACTIVE", "ENABLED"):
                return state.group(1).strip()
            if state and state.group(1).strip() in ("ERROR", "OUT OF DATE", "OUT_OF_DATE"):
                raise AssertionError(f"Extension cannot activate: {info}")
            time.sleep(0.1)
        raise AssertionError(f"Extension was enabled but not active: {info}")

    def disable(self):
        self.command(["gnome-extensions", "disable", self.uuid])
        self._wait_enabled(False)

    def set_setting(self, key, gvariant_value):
        if key not in self._saved_settings:
            self._saved_settings[key] = self.command(["gsettings", "get", self.schema, key]).stdout.strip()
        self.command(["gsettings", "set", self.schema, key, gvariant_value])

    def cleanup(self):
        failures = []
        for key, original in self._saved_settings.items():
            try:
                self.command(["gsettings", "set", self.schema, key, original])
            except (AssertionError, subprocess.SubprocessError) as exc:
                failures.append(str(exc))
        if self._original_enabled is not None:
            try:
                if self._original_enabled:
                    self.enable()
                else:
                    self.disable()
            except (AssertionError, subprocess.SubprocessError) as exc:
                failures.append(str(exc))
        if failures:
            raise AssertionError("Extension cleanup failed:\n" + "\n".join(failures))
        self._saved_settings.clear()
