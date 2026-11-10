"""Observe Just Perfection through GSettings and public Shell actors.

Source: src/lib/Manager.js applyPanel/applySearch/applyDash and revertAll;
src/lib/API.js panelShow/panelHide, searchEntryShow/searchEntryHide, dashShow/
dashHide. Panel hiding reparents/translates the panel; its visible flag alone
cannot establish whether it is rendered on screen.
"""

import json

from behave import given, then, when


_SHELL_STATE = """(() => {
    const monitor = Main.layoutManager.primaryMonitor;
    if (!monitor)
        throw new Error('Just Perfection requires a primary monitor');
    const observe = actor => {
        if (!actor || actor.get_stage() !== global.stage)
            throw new Error('Required public Shell actor is missing from the stage');
        const [x, y] = actor.get_transformed_position();
        const [width, height] = actor.get_transformed_size();
        const paintOpacity = actor.get_paint_opacity();
        const intersectsMonitor = x < monitor.x + monitor.width &&
            x + width > monitor.x && y < monitor.y + monitor.height &&
            y + height > monitor.y;
        return {
            x: Math.round(x), y: Math.round(y),
            width: Math.round(width), height: Math.round(height),
            visible: actor.visible,
            mapped: actor.mapped,
            paintOpacity,
            rendered: actor.visible && actor.mapped && actor.has_allocation() &&
                paintOpacity > 0 && width > 0 && height > 0 && intersectsMonitor,
        };
    };
    const panel = Main.layoutManager.panelBox;
    const dash = Main.overview.dash;
    return {
        panel: {
            ...observe(panel),
            translationY: panel.translation_y,
            chromeParent: panel.get_parent() === Main.layoutManager.uiGroup,
            overviewParent: panel.get_parent() === Main.layoutManager.overviewGroup,
        },
        search: observe(Main.overview.searchEntry),
        dash: {...observe(dash), height: dash.height},
        launcher: observe(dash.showAppsButton),
    };
})()"""


def _actor_expression(name):
    return f"({_SHELL_STATE})[{json.dumps(name)}]"


def _wait_rendered(session, name):
    expression = _actor_expression(name)
    session.wait_for(
        f"(() => {{ const actor = {expression}; "
        "return actor.rendered && actor.paintOpacity === 255; })()"
    )


def _set_overview(session, visible):
    action = "show" if visible else "hide"
    session.shell_json(f"(() => {{ Main.overview.{action}(); return true; }})()")
    if visible:
        expression = (
            "Main.overview.visible && Main.layoutManager.overviewGroup.mapped && "
            "Main.layoutManager.overviewGroup.get_paint_opacity() === 255"
        )
    else:
        expression = "!Main.overview.visible && !Main.layoutManager.overviewGroup.mapped"
    session.wait_for(expression)


def _restore_shell(session, initial):
    text = json.dumps(initial["searchText"])
    session.shell_json(
        "(() => { Main.overview.searchEntry.get_clutter_text().set_text("
        f"{text}); return true; }})()"
    )
    _set_overview(session, initial["overviewVisible"])


@given("the unmodified Shell baseline for Just Perfection is recorded")
def record_shell_baseline(context):
    session = context.extension
    initial = session.shell_json(
        "({overviewVisible: Main.overview.visible, "
        "searchText: Main.overview.searchEntry.get_clutter_text().get_text()})"
    )
    context.extension_cleanups.append((_restore_shell, (session, initial)))
    session.disable()
    session.shell_json(
        "(() => { Main.overview.searchEntry.get_clutter_text().set_text(''); "
        "return true; })()"
    )
    _set_overview(session, False)
    _wait_rendered(session, "panel")
    desktop = session.shell_json(_actor_expression("panel"))
    assert desktop["chromeParent"], "Baseline panel is not in the normal Shell chrome"
    _set_overview(session, True)
    for name in ("panel", "search", "dash", "launcher"):
        _wait_rendered(session, name)
    context.just_perfection_baseline = {
        "desktop": desktop,
        "overview": session.shell_json(_SHELL_STATE),
    }
    _set_overview(session, False)


@given("Just Perfection starts with its panel, search and dash visible")
def set_initial_visibility(context):
    # set_setting saves each previous GVariant for the shared cleanup hook.
    for key, value in (
        ("panel", "true"),
        ("panel-in-overview", "false"),
        ("top-panel-position", "0"),
        ("search", "true"),
        ("dash", "true"),
        ("show-apps-button", "true"),
        ("type-to-search", "false"),
    ):
        context.extension.set_setting(key, value)


@when('I set Just Perfection "{key}" to "{value}"')
def set_visibility(context, key, value):
    assert key in {"panel", "panel-in-overview", "search", "dash"}, key
    assert value in {"true", "false"}, value
    context.extension.set_setting(key, value)


@when("I open the overview for Just Perfection")
def open_overview(context):
    _set_overview(context.extension, True)


@when("I close the overview for Just Perfection")
def close_overview(context):
    _set_overview(context.extension, False)


@then('the Just Perfection panel is "{visibility}"')
def panel_visibility(context, visibility):
    assert visibility in {"rendered", "not rendered"}, visibility
    if visibility == "rendered":
        _wait_rendered(context.extension, "panel")
    else:
        context.extension.wait_for(
            f"(() => {{ const panel = {_actor_expression('panel')}; "
            "return panel.overviewParent && !panel.rendered && "
            "(!panel.mapped || panel.translationY < 0); })()"
        )


@then('the Just Perfection search entry is "{visibility}"')
def search_visibility(context, visibility):
    assert visibility in {"rendered", "not rendered"}, visibility
    if visibility == "rendered":
        _wait_rendered(context.extension, "search")
    else:
        context.extension.wait_for(
            f"(() => {{ const search = {_actor_expression('search')}; "
            "return !search.visible && !search.mapped && !search.rendered; })()"
        )


@then("the Just Perfection dash and Show Applications button are rendered")
def dash_and_launcher_rendered(context):
    _wait_rendered(context.extension, "dash")
    _wait_rendered(context.extension, "launcher")
    context.extension.wait_for(f"({_actor_expression('dash')}).height > 0")


@then("the Just Perfection dash is hidden with zero height")
def dash_hidden(context):
    context.extension.wait_for(
        f"(() => {{ const state = {_SHELL_STATE}; "
        "return !state.dash.visible && !state.dash.mapped && "
        "!state.dash.rendered && state.dash.height === 0 && "
        "!state.launcher.rendered; })()"
    )


@then("the Just Perfection panel matches its desktop baseline")
def panel_restored(context):
    context.extension.wait_for(
        _actor_expression("panel"),
        expected=context.just_perfection_baseline["desktop"],
    )


@then("the Just Perfection search entry matches its overview baseline")
def search_restored(context):
    context.extension.wait_for(
        _actor_expression("search"),
        expected=context.just_perfection_baseline["overview"]["search"],
    )


@then("the Just Perfection dash matches its overview baseline")
def dash_restored(context):
    context.extension.wait_for(
        _actor_expression("dash"),
        expected=context.just_perfection_baseline["overview"]["dash"],
    )


@then("the Just Perfection overview controls match their initial baseline")
def overview_restored(context):
    context.extension.wait_for(
        _SHELL_STATE,
        expected=context.just_perfection_baseline["overview"],
    )
