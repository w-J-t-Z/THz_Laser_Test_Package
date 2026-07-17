"""Plotting helpers for pulse-voltage and chopper-frequency sweep results.

Produces the I-V and optical-intensity-vs-voltage curves described in the
top-level CLAUDE.md project summary, from the DataFrame returned by
:func:`measurement.sweep.run_voltage_sweep`, plus R-vs-frequency and
SNR-vs-frequency curves for
:func:`measurement.chopper_sweep.run_chopper_frequency_sweep`.
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

import matplotlib.pyplot as plt
import pandas as pd
from matplotlib.axes import Axes

logger = logging.getLogger(__name__)


def _std_column(df: pd.DataFrame, column: str) -> Optional[pd.Series]:
    """Return ``df[f"{column}_std"]`` if that column exists, else ``None``."""
    std_column = f"{column}_std"
    return df[std_column] if std_column in df.columns else None


def plot_iv_curve(
    df: pd.DataFrame,
    *,
    voltage_column: str = "dut_voltage",
    current_column: str = "dut_current",
    ax: Optional[Axes] = None,
    show: bool = False,
) -> Axes:
    """Plot DUT current vs. voltage from a sweep result.

    If columns named ``f"{voltage_column}_std"`` / ``f"{current_column}_std"``
    are present, they are drawn as x/y error bars.

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

    xerr = _std_column(df, voltage_column)
    yerr = _std_column(df, current_column)
    if xerr is not None or yerr is not None:
        ax.errorbar(
            df[voltage_column], df[current_column], xerr=xerr, yerr=yerr, marker="o", capsize=3
        )
    else:
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

    If columns named ``f"{voltage_column}_std"`` / ``f"{intensity_column}_std"``
    are present, they are drawn as x/y error bars.

    Args:
        df: Sweep result, e.g. as returned by
            :func:`measurement.sweep.run_voltage_sweep`.
        voltage_column: DataFrame column to use for the x-axis.
        intensity_column: DataFrame column to use for the y-axis, e.g.
            ``"lockin_r"`` for magnitude or ``"lockin_x"`` for the
            in-phase component. Note there is no std for ``"lockin_phase"``
            (phase is a circular quantity, see
            :meth:`instruments.mfli.MFLI.read_averaged_sample`).
        ax: Existing axes to plot into; a new figure/axes pair is created
            if omitted.
        show: Whether to call ``plt.show()`` after plotting.

    Returns:
        The axes the curve was plotted on.
    """
    if ax is None:
        _fig, ax = plt.subplots()

    xerr = _std_column(df, voltage_column)
    yerr = _std_column(df, intensity_column)
    if xerr is not None or yerr is not None:
        ax.errorbar(
            df[voltage_column],
            df[intensity_column],
            xerr=xerr,
            yerr=yerr,
            marker="o",
            capsize=3,
            color="tab:orange",
        )
    else:
        ax.plot(df[voltage_column], df[intensity_column], marker="o", color="tab:orange")

    ax.set_xlabel("Voltage (V)")
    ax.set_ylabel("Lock-in signal (a.u.)")
    ax.set_title("Optical intensity vs. voltage")
    if show:
        plt.show()
    return ax


def plot_r_vs_frequency(
    df: pd.DataFrame,
    *,
    frequency_column: str = "chopper_frequency_hz",
    r_column: str = "lockin_r",
    log_x: bool = True,
    ax: Optional[Axes] = None,
    show: bool = False,
) -> Axes:
    """Plot lock-in R vs. chopper frequency from a chopper-frequency sweep result.

    If a column named ``f"{r_column}_std"`` is present, it is drawn as y
    error bars.

    Args:
        df: Chopper-frequency sweep result, e.g. as returned by
            :func:`measurement.chopper_sweep.run_chopper_frequency_sweep`.
        frequency_column: DataFrame column to use for the x-axis.
        r_column: DataFrame column to use for the y-axis.
        log_x: Whether to use a log scale on the x-axis.
        ax: Existing axes to plot into; a new figure/axes pair is created
            if omitted.
        show: Whether to call ``plt.show()`` after plotting.

    Returns:
        The axes the curve was plotted on.
    """
    if ax is None:
        _fig, ax = plt.subplots()

    yerr = _std_column(df, r_column)
    if yerr is not None:
        ax.errorbar(df[frequency_column], df[r_column], yerr=yerr, marker="o", capsize=3)
    else:
        ax.plot(df[frequency_column], df[r_column], marker="o")

    if log_x:
        ax.set_xscale("log")
    ax.set_xlabel("Chopper frequency (Hz)")
    ax.set_ylabel("Lock-in R (V)")
    ax.set_title("Lock-in R vs. chopper frequency")
    if show:
        plt.show()
    return ax


def plot_snr_vs_frequency(
    df: pd.DataFrame,
    *,
    frequency_column: str = "chopper_frequency_hz",
    quantities: Sequence[str] = ("r", "x", "y"),
    log_x: bool = True,
    log_y: bool = False,
    ax: Optional[Axes] = None,
    show: bool = False,
) -> Axes:
    """Plot lock-in SNR (mean / std) vs. chopper frequency for selected quantities.

    Args:
        df: Chopper-frequency sweep result, e.g. as returned by
            :func:`measurement.chopper_sweep.run_chopper_frequency_sweep`.
        frequency_column: DataFrame column to use for the x-axis.
        quantities: Which of ``"r"``, ``"x"``, ``"y"`` to plot as separate
            lines; SNR for each is computed as
            ``df[f"lockin_{q}"] / df[f"lockin_{q}_std"]``.
        log_x: Whether to use a log scale on the x-axis.
        log_y: Whether to use a log scale on the y-axis.
        ax: Existing axes to plot into; a new figure/axes pair is created
            if omitted.
        show: Whether to call ``plt.show()`` after plotting.

    Returns:
        The axes the curves were plotted on.

    Raises:
        ValueError: If ``quantities`` contains anything other than
            ``"r"``, ``"x"``, or ``"y"``.
    """
    valid_quantities = {"r", "x", "y"}
    invalid = [q for q in quantities if q not in valid_quantities]
    if invalid:
        raise ValueError(
            f"Unsupported quantities {invalid!r}; must be one of {sorted(valid_quantities)}"
        )

    if ax is None:
        _fig, ax = plt.subplots()

    for quantity in quantities:
        mean_column = f"lockin_{quantity}"
        std_column = f"lockin_{quantity}_std"
        snr = df[mean_column] / df[std_column]
        ax.plot(df[frequency_column], snr, marker="o", label=quantity.upper())

    if log_x:
        ax.set_xscale("log")
    if log_y:
        ax.set_yscale("log")
    ax.set_xlabel("Chopper frequency (Hz)")
    ax.set_ylabel("SNR (mean / std)")
    ax.set_title("Lock-in SNR vs. chopper frequency")
    ax.legend()
    if show:
        plt.show()
    return ax
