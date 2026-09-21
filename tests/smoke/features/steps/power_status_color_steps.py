"""Custom step definitions for the power-status-color extension.

Covers the power-status-color@projectbluefin.io GNOME Shell extension
(projectbluefin/bluefin-bling). It watches for a bootc "reboot required"
flag file and, while the flag is present, adds a red/green CSS class to the
Quick Settings power-off button so its colour reflects power status
(reboot required = yellow, uptime overdue = red).

The reboot-flag and disable scenarios are exercised here. The uptime-overdue
(red) path is intentionally left to the extension's own unit tests: it is
triggered by a stale ``/proc/uptime`` (30+ days) which the smoke VM cannot
produce without faking kernel state.
"""

import json
import re
import shlex
import time

from behave import step

from tests.shared.gnome_shell_steps import _shell_eval
from tests.smoke.features.steps.gnome_extensions_steps import (
    _extension_state,
    _run_host,
)

# CSS classes the extension applies to the Quick Settings power button.
REBOOT_CLASS = "power-status-reboot"
OVERDUE_CLASS = "power-status-overdue"
POWER_BUTTON_CLASSES = (REBOOT_CLASS, OVERDUE_CLASS)

# The file monitor fires asynchronously (bootc status call + style apply);
# allow more than the documented 2s so slow CI does not flake.
_POLL_DEADLINE_S = 5.0
_POLL_INTERVAL_S = 0.2


def _power_button_has_class(context, target):
    """Return True when the Quick Settings power button carries ``target``.

    Inspects the button actor's live style classes through
    ``org.gnome.Shell.Eval`` (the same Shell.Eval bridge used for the rest
    of the Quick Settings smoke steps). Returns False if the button cannot
    be located, so callers can poll to a definite answer.
    """
    js = (
        "(function(target){"
        "try{"
        "var qs=Main.panel&&Main.panel.statusArea&&Main.panel.statusArea.quickSettings;"
        "if(!qs)return false;"
        "var btn=null;"
        "if(qs._system&&qs._system._systemItem&&qs._system._systemItem.menu&&"
        "qs._system._systemItem.menu.sourceActor)"
        "btn=qs._system._systemItem.menu.sourceActor;"
        "if(!btn&&qs.menu){"
        "var root=qs.menu._grid||qs.menu.actor||qs.menu.box||qs;"
        "var find=function(actor){"
        "if(!actor)return null;"
        "try{"
        "if(actor.has_style_class_name&&"
        "actor.has_style_class_name('icon-button')&&"
        "(actor.icon_name==='system-shutdown-symbolic'||"
        "(actor.accessible_name&&"
        "actor.accessible_name.toLowerCase().indexOf('power off')>=0)))"
        "return actor;"
        "}"
        "catch(e){}"
        "if(actor.get_children){var k=actor.get_children();"
        "for(var i=0;i<k.length;i++){var m=find(k[i]);if(m)return m;}}"
        "return null;"
        "};btn=find(root);"
        "}"
        "if(!btn)return false;"
        "var c=(btn.getStyleClassName()||'').split(/\\s+/);"
        "return c.indexOf(target)>=0;"
        "}"
        "catch(e){return false;}"
        "})(" + json.dumps(target) + ")"
    )
    out = _shell_eval(js)
    match = re.search(
        r"\((?:true|false),\s*\"?((?:true|false)|[^)]*)\"?\)", out, re.IGNORECASE
    )
    if not match:
        raise AssertionError(
            f"Could not parse power-button class check from Shell.Eval: {out!r}"
        )
    return match.group(1).lower() == "true"


def _wait_for_power_class(context, target, want_present, deadline_s=_POLL_DEADLINE_S):
    """Poll the power button until the class state settles or the deadline passes."""
    start = time.monotonic()
    while time.monotonic() - start < deadline_s:
        present = _power_button_has_class(context, target)
        if present == want_present:
            return
        time.sleep(_POLL_INTERVAL_S)
    present = _power_button_has_class(context, target)
    if present != want_present:
        raise AssertionError(
            f"Power button did not reach expected class state "
            f"(want_present={want_present}) within {deadline_s}s; "
            f"still {'present' if present else 'absent'}"
        )


# --- reboot-required flag file (privileged; needs sudo on the host) --------

@step('File "{path}" is created')
def step_create_flag_file(context, path):
    _run_host(f"sudo touch {shlex.quote(path)}")


@step('File "{path}" is removed')
def step_remove_flag_file(context, path):
    _run_host(f"sudo rm -f {shlex.quote(path)}")


# --- Quick Settings power-button style class -------------------------------

@step('Quick Settings power button has power alert class "{css_class}"')
def step_power_button_has_class(context, css_class):
    _wait_for_power_class(context, css_class, want_present=True)


@step('Quick Settings power button has no power alert class "{css_class}"')
def step_power_button_no_class(context, css_class):
    _wait_for_power_class(context, css_class, want_present=False)


@step("Quick Settings power button has no power alert classes")
def step_power_button_no_classes(context):
    for cls in POWER_BUTTON_CLASSES:
        _wait_for_power_class(context, cls, want_present=False)


# --- extension disable / teardown ------------------------------------------

@step('GNOME extension "{uuid}" is disabled')
def step_disable_extension(context, uuid):
    _run_host(f"gnome-extensions disable {shlex.quote(uuid)}")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if _extension_state(uuid) == "2":  # DISABLED
            return
        time.sleep(0.2)
    raise AssertionError(
        f"GNOME extension {uuid} did not reach DISABLED state after disabling"
    )
