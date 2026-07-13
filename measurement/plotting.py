"""Plotting helpers for pulse-voltage sweep results.

Produces the I-V and optical-intensity-vs-voltage curves described in the
top-level CLAUDE.md project summary, from the DataFrame returned by
:func:`measurement.sweep.run_voltage_sweep`.
"""

from __future__ import annotations

import logging
from typing import Optional

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.axes import Axes

logger = logging.getLogger(__name__)


def plot_iv_curve(
    df: pd.DataFrame,
    *,
    voltage_column: str = "dut_voltage",
    current_column: str = "dut_current",
    ax: Optional[Axes] = None,
    show: bool = False,
) -> Axes:
    """Plot DUT current vs. voltage from a sweep result.

    Args:
        df: Sweep result, e.g. as returned by
            :func:`measurement.sweep.run_voltage_sweep`.
        voltage_column: DataFrame column to use for the x-axis.
        current_column: DataFrame column to use for the y-axis.
        ax: Existing axes to plot into; a new figure/axes pair is created
            if omitted.
        show: Whether to call ``plt.show()`` after plotting.

    Returns:
        The axes the curve was plotted on.
    """
    if ax is None:
        _fig, ax = plt.subplots()
    ax.plot(df[voltage_column], df[current_column], marker="o")
    ax.set_xlabel("Voltage (V)")
    ax.set_ylabel("Current (A)")
    ax.set_title("I-V curve")
    if show:
        plt.show()
    return ax


def plot_intensity_curve(
    df: pd.DataFrame,
    *,
    voltage_column: str = "dut_voltage",
    intensity_column: str = "lockin_r",
    ax: Optional[Axes] = None,
    show: bool = False,
) -> Axes:
    """Plot the lock-in (optical intensity) signal vs. voltage from a sweep result.

    Args:
        df: Sweep result, e.g. as returned by
            :func:`measurement.sweep.run_voltage_sweep`.
        voltage_column: DataFrame column to use for the x-axis.
        intensity_column: DataFrame column to use for the y-axis, e.g.
            ``"lockin_r"`` for magnitude or ``"lockin_x"`` for the
            in-phase component.
        ax: Existing axes to plot into; a new figure/axes pair is created
            if omitted.
        show: Whether to call ``plt.show()`` after plotting.

    Returns:
        The axes the curve was plotted on.
    """
    if ax is None:
        _fig, ax = plt.subplots()
    ax.plot(df[voltage_column], df[intensity_column], marker="o", color="tab:orange")
    ax.set_xlabel("Voltage (V)")
    ax.set_ylabel("Lock-in signal (a.u.)")
    ax.set_title("Optical intensity vs. voltage")
    if show:
        plt.show()
    return ax
