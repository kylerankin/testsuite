@smoke_suite @extensions @power_status
Feature: Power status color extension alerts
  Validates the power-status-color@projectbluefin.io GNOME Shell extension
  (from projectbluefin/bluefin-bling). It watches for a bootc "reboot
  required" flag file and, while the flag is present, adds a red/green CSS
  class to the Quick Settings power-off button so its colour reflects power
  status (reboot required = yellow, uptime overdue = red).

  The reboot-flag and disable scenarios are exercised here. The uptime
  overdue (red) path is covered by the extension's own unit tests: it is
  triggered by a stale /proc/uptime (30+ days), which the smoke VM cannot
  produce without faking kernel state.

  @extensions
  Scenario: Power status color extension is enabled
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "power-status-color@projectbluefin.io" is enabled

  @extensions
  Scenario: No shell journal errors on extension load
    * No gnome-shell extension load journal errors exist

  @extensions @power_status
  Scenario: Power button flags a required reboot
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "power-status-color@projectbluefin.io" is enabled
    * Quick Settings power button has no power alert class "power-status-reboot"
    * File "/run/reboot-required" is created
    * Quick Settings power button has power alert class "power-status-reboot"
    * File "/run/reboot-required" is removed
    * Quick Settings power button has no power alert class "power-status-reboot"

  @extensions @power_status
  Scenario: Extension removes power alert classes on disable
    * GNOME Shell is accessible via AT-SPI
    * GNOME extension "power-status-color@projectbluefin.io" is enabled
    * GNOME extension "power-status-color@projectbluefin.io" is disabled
    * Quick Settings power button has no power alert classes
