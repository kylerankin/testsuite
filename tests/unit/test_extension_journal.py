"""Structured Shell journal failures and scenario-owned cleanup boundaries."""

import json
from types import SimpleNamespace

import pytest

from tests.extensions.features import environment
from tests.shared.extension_session import is_shell_journal_error


# Relevant fields from real journalctl --user -o json gnome-shell records.
# Messages have no GLib/Gjs severity prefix; the domain and priority carry it.
GOBJECT_WARNING = {
    "SYSLOG_IDENTIFIER": "gnome-shell", "_COMM": "gnome-shell",
    "GLIB_DOMAIN": "GLib-GObject", "PRIORITY": "4", "GLIB_OLD_LOG_API": "1",
    "MESSAGE": 'value "nan" of type \'gdouble\' is invalid or out of range for property \'clip\' of type \'gdouble\'',
}
DISPOSED_OBJECT_WARNING = {
    "SYSLOG_IDENTIFIER": "gnome-shell", "_COMM": "gnome-shell",
    "GLIB_DOMAIN": "Gjs", "PRIORITY": "4", "GLIB_OLD_LOG_API": "1",
    "MESSAGE": "Object Gjs_ui_popupMenu_PopupMenuItem (0x5633dab38880), has been already disposed — impossible to access it. This might be caused by the object having been destroyed from C code using something such as destroy(), dispose(), or remove() vfuncs.\n== Stack trace for context 0x5633cb6abec0 ==\n#0   5633cb77c528 i   resource:///org/gnome/shell/ui/popupMenu.js:130 (228f1e14e150 @ 73)\n#1   5633cb77c498 i   resource:///org/gnome/shell/ui/init.js:20 (1869218e8d0 @ 48)",
}


@pytest.mark.parametrize("record", [GOBJECT_WARNING, DISPOSED_OBJECT_WARNING])
def test_metadata_only_glib_warnings_fail_the_shell_gate(record):
    assert is_shell_journal_error(record) is True


@pytest.mark.parametrize("message", [None, list(b"JS ERROR: TypeError: invalid actor")])
def test_large_or_binary_gjs_errors_do_not_escape_the_gate(message):
    assert is_shell_journal_error(dict(DISPOSED_OBJECT_WARNING, MESSAGE=message)) is True


def test_binary_console_exception_is_decoded_before_classification():
    record = dict(DISPOSED_OBJECT_WARNING, GLIB_DOMAIN="GNOME Shell",
                  MESSAGE=list(b"TypeError: invalid actor"))
    assert is_shell_journal_error(record) is True


def test_hook_reports_null_warning_message_without_losing_the_failure(monkeypatch):
    context = SimpleNamespace(extension=None, extension_journal_cursor="cursor", extension_cleanups=[])
    monkeypatch.setattr(environment, "_journal", lambda *args: json.dumps(dict(DISPOSED_OBJECT_WARNING, MESSAGE=None)))
    with pytest.raises(AssertionError, match="GNOME Shell errors"):
        environment.after_scenario(context, SimpleNamespace())


@pytest.mark.parametrize("priority, expected", [("3", True), ("4", True), ("5", False), ("6", False)])
def test_glib_warning_priority_boundary(priority, expected):
    assert is_shell_journal_error(dict(GOBJECT_WARNING, PRIORITY=priority)) is expected


@pytest.mark.parametrize("message", [
    "JS ERROR: Error: extension could not initialize",
    "JS WARNING: unsafe object access",
    "SJC Gold: refresh failed: ReferenceError: response is not defined",
    "Extension: stock-market@binhnguyensoft.com: refresh failed: TypeError: data.prices is undefined",
    "SJC Gold: refresh failed: SyntaxError: unexpected token",
    "Unhandled promise rejection. Stack trace of the failed promise:\n@resource:///org/gnome/shell/ui/init.js:20:20",
])
def test_caught_or_uncaught_js_exceptions_fail_the_shell_gate(message):
    record = {"SYSLOG_IDENTIFIER": "gnome-shell", "_COMM": "gnome-shell", "GLIB_DOMAIN": "GNOME Shell", "PRIORITY": "3", "MESSAGE": message}
    assert is_shell_journal_error(record) is True


@pytest.mark.parametrize("message", [
    "SJC Gold: refresh failed: Error: HTTP 503",
    "Extension: stock-market@binhnguyensoft.com: refresh failed: Error: Tiến trình lấy giá quá thời gian",
])
def test_expected_provider_outage_console_error_is_not_an_api_exception(message):
    record = {"SYSLOG_IDENTIFIER": "gnome-shell", "_COMM": "gnome-shell", "GLIB_DOMAIN": "GNOME Shell", "PRIORITY": "3", "MESSAGE": message}
    assert is_shell_journal_error(record) is False


def test_other_process_warning_is_not_attributed_to_shell():
    record = dict(GOBJECT_WARNING, SYSLOG_IDENTIFIER="gnome-extensions", _COMM="gjs")
    assert is_shell_journal_error(record) is False


def test_comm_identifies_shell_when_syslog_identifier_is_absent():
    record = dict(GOBJECT_WARNING)
    del record["SYSLOG_IDENTIFIER"]
    assert is_shell_journal_error(record) is True


def test_quarantine_clears_stale_scenario_state_without_reading_journal(monkeypatch):
    context = SimpleNamespace(extension=object(), extension_journal_cursor="old", extension_cleanups=[object()])
    scenario = SimpleNamespace(tags=["quarantine"], skipped=False)

    def skip(reason):
        scenario.skipped = True

    def unavailable_journal(*args):
        raise AssertionError("quarantined scenario must not inspect the session")

    scenario.skip = skip
    monkeypatch.setattr(environment, "_journal", unavailable_journal)

    environment.before_scenario(context, scenario)
    environment.after_scenario(context, scenario)

    assert scenario.skipped is True
    assert context.extension is None
    assert context.extension_journal_cursor is None
    assert context.extension_cleanups == []


def test_scenario_cleanup_is_lifo_before_settings_and_journal(monkeypatch):
    events = []
    context = SimpleNamespace(
        extension=SimpleNamespace(cleanup=lambda: events.append("settings")),
        extension_journal_cursor="scenario-cursor",
        extension_cleanups=[(events.append, ("overview",)), (events.append, ("windows",))],
    )

    def journal(*args):
        events.append("journal")
        return ""

    monkeypatch.setattr(environment, "_journal", journal)
    environment.after_scenario(context, SimpleNamespace())

    assert events == ["windows", "overview", "settings", "journal"]
    assert context.extension_cleanups == []


def test_cleanup_failures_do_not_hide_other_cleanup_or_journal_errors(monkeypatch):
    def fail(message):
        raise RuntimeError(message)

    context = SimpleNamespace(
        extension=SimpleNamespace(cleanup=lambda: fail("settings unavailable")),
        extension_journal_cursor="scenario-cursor",
        extension_cleanups=[(fail, ("overview stuck",)), (fail, ("window still mapped",))],
    )
    monkeypatch.setattr(environment, "_journal", lambda *args: json.dumps(GOBJECT_WARNING))

    with pytest.raises(AssertionError) as failure:
        environment.after_scenario(context, SimpleNamespace())

    for error in ("window still mapped", "overview stuck", "settings unavailable", GOBJECT_WARNING["MESSAGE"]):
        assert error in str(failure.value)
    assert context.extension_cleanups == []


def test_journal_inspection_failure_is_reported_alongside_cleanup_failure(monkeypatch):
    def fail_cleanup():
        raise AssertionError("window still mapped")

    def fail_journal(*args):
        raise AssertionError("journal service unavailable")

    context = SimpleNamespace(
        extension=None, extension_journal_cursor="scenario-cursor",
        extension_cleanups=[(fail_cleanup, ())],
    )
    monkeypatch.setattr(environment, "_journal", fail_journal)

    with pytest.raises(AssertionError) as failure:
        environment.after_scenario(context, SimpleNamespace())

    assert "window still mapped" in str(failure.value)
    assert "journal service unavailable" in str(failure.value)
