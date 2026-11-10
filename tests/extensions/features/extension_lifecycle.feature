@extensions_suite
Feature: Hive extension lifecycle in a disposable GNOME session
  Installed candidate identity and lifecycle are prerequisites, not substitutes for functional tests.

  Scenario Outline: A candidate enables, disables and enables again
    Given Hive extension "<profile>" is installed
    When I enable the selected Hive extension
    Then the selected Hive extension is active
    When I disable the selected Hive extension
    Then the selected Hive extension is inactive
    When I enable the selected Hive extension
    Then the selected Hive extension is active

    @just_perfection
    Examples: Just Perfection
      | profile         |
      | just-perfection |

    @sjc_gold
    Examples: SJC Gold
      | profile  |
      | sjc-gold |

    @shade_inactive_windows
    Examples: Shade Inactive Windows Reborn
      | profile                |
      | shade-inactive-windows |

    @stock_market
    Examples: Stock Market
      | profile      |
      | stock-market |

  Scenario Outline: Candidate preferences are accessible
    Given Hive extension "<profile>" is installed
    When I enable the selected Hive extension
    Then the selected Hive extension preferences window is accessible

    @just_perfection
    Examples: Just Perfection
      | profile         |
      | just-perfection |

    @sjc_gold
    Examples: SJC Gold
      | profile  |
      | sjc-gold |

    @shade_inactive_windows
    Examples: Shade Inactive Windows Reborn
      | profile                |
      | shade-inactive-windows |

    @stock_market
    Examples: Stock Market
      | profile      |
      | stock-market |
