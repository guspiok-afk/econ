"""Tests for econmodels.base module functions and protocols."""

from __future__ import annotations

import pandas as pd
import pytest

from econmodels.base import PanelError, check_frequency


def test_weekly_frequency_check_with_real_icsa_and_totci_dates() -> None:
    """Verify that check_frequency accepts weekly panels anchored on any day of the week.

    fred:ICSA uses Saturday dates (1967-01-07, 1967-01-14, 1967-01-21) - weekly flow.
    fred:TOTCI uses Wednesday dates (1973-01-03, 1973-01-10, 1973-01-17) - weekly stock.
    Both must pass check_frequency(panel, "W") under the 7D convention.
    """
    icsa_dates = pd.date_range("1967-01-07", periods=3113, freq="7D")
    icsa_panel = pd.DataFrame({"initial_claims@US": range(len(icsa_dates))}, index=icsa_dates)
    check_frequency(icsa_panel, "W")

    totci_dates = pd.date_range("1973-01-03", periods=100, freq="7D")
    totci_panel = pd.DataFrame({"totci@US": range(len(totci_dates))}, index=totci_dates)
    check_frequency(totci_panel, "W")


def test_weekly_frequency_check_rejects_holes_and_non_7d_spacing() -> None:
    """Verify that check_frequency catches missing periods in weekly series."""
    dates_with_hole = pd.to_datetime(["1967-01-07", "1967-01-14", "1967-01-28"])
    panel_hole = pd.DataFrame({"x@US": [1.0, 2.0, 3.0]}, index=dates_with_hole)
    with pytest.raises(PanelError, match="hole"):
        check_frequency(panel_hole, "W")

    dates_off_grid = pd.to_datetime(["1967-01-07", "1967-01-14", "1967-01-20"])
    panel_off = pd.DataFrame({"x@US": [1.0, 2.0, 3.0]}, index=dates_off_grid)
    with pytest.raises(PanelError, match="not W"):
        check_frequency(panel_off, "W")


def test_old_w_mon_convention_fails_on_icsa_dates() -> None:
    """Demonstrate that ICSA dates fail when checked against a fixed Monday grid."""
    icsa_dates = pd.date_range("1967-01-07", periods=10, freq="7D")
    expected_mon_grid = pd.date_range(icsa_dates.min(), icsa_dates.max(), freq="W-MON")
    assert not icsa_dates.equals(expected_mon_grid)
