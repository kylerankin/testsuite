@extensions_suite @just_perfection
Feature: Just Perfection changes rendered GNOME Shell controls
  Visibility preferences must affect the real panel and overview actors, and
  disabling the extension must restore the Shell state recorded before enable.

  Background:
    Given Hive extension "just-perfection" is installed
    And the unmodified Shell baseline for Just Perfection is recorded
    And Just Perfection starts with its panel, search and dash visible

  Scenario: Hiding the panel removes it from the desktop and overview
    When I enable the selected Hive extension
    Then the Just Perfection panel is "rendered"
    When I set Just Perfection "panel" to "false"
    Then the Just Perfection panel is "not rendered"
    When I open the overview for Just Perfection
    Then the Just Perfection panel is "not rendered"
    When I set Just Perfection "panel" to "true"
    Then the Just Perfection panel is "rendered"
    When I close the overview for Just Perfection
    Then the Just Perfection panel matches its desktop baseline

  Scenario: The panel-in-overview option hides the panel only on the desktop
    When I enable the selected Hive extension
    And I set Just Perfection "panel-in-overview" to "true"
    And I set Just Perfection "panel" to "false"
    Then the Just Perfection panel is "not rendered"
    When I open the overview for Just Perfection
    Then the Just Perfection panel is "rendered"
    When I close the overview for Just Perfection
    Then the Just Perfection panel is "not rendered"
    When I set Just Perfection "panel" to "true"
    Then the Just Perfection panel matches its desktop baseline

  Scenario: Search visibility changes the rendered overview search entry
    When I enable the selected Hive extension
    And I open the overview for Just Perfection
    Then the Just Perfection search entry is "rendered"
    When I set Just Perfection "search" to "false"
    Then the Just Perfection search entry is "not rendered"
    When I set Just Perfection "search" to "true"
    Then the Just Perfection search entry matches its overview baseline

  Scenario: Hiding the dash removes its height and restoring it renders its launcher
    When I enable the selected Hive extension
    And I open the overview for Just Perfection
    Then the Just Perfection dash and Show Applications button are rendered
    When I set Just Perfection "dash" to "false"
    Then the Just Perfection dash is hidden with zero height
    When I set Just Perfection "dash" to "true"
    Then the Just Perfection dash and Show Applications button are rendered
    And the Just Perfection dash matches its overview baseline

  Scenario: Disabling restores the captured panel, search and dash state
    When I enable the selected Hive extension
    And I set Just Perfection "panel" to "false"
    Then the Just Perfection panel is "not rendered"
    When I open the overview for Just Perfection
    And I set Just Perfection "search" to "false"
    And I set Just Perfection "dash" to "false"
    Then the Just Perfection panel is "not rendered"
    And the Just Perfection search entry is "not rendered"
    And the Just Perfection dash is hidden with zero height
    When I disable the selected Hive extension
    Then the Just Perfection overview controls match their initial baseline
    When I close the overview for Just Perfection
    Then the Just Perfection panel matches its desktop baseline
