"""Pulse-voltage sweep orchestration.

Sweeps the Avtech pulse voltage over a user-defined range and, at each
step, acquires the DUT voltage and current from the Rigol scope and the
optical-intensity signal from the MFLI lock-in. See the top-level
CLAUDE.md for the overall experiment layout.

This module assumes all instruments passed in are already connected and
pre-configured (Avtech in remote mode with its trigger source set, QDac's
trigger/gate channels armed if a continuous trigger train is used, Rigol's
timebase/channel scales/edge trigger set, MFLI's demodulator configured) --
it only performs the per-step measurement loop, not full instrument setup.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, fields
from typing import Optional, Sequence

import pandas as pd

from instruments import config
from instruments.avtech import Avtech
from instruments.mfli import MFLI
from instruments.qdac import QDac
from instruments.rigol import Rigol

logger = logging.getLogger(__name__)


@dataclass
class SweepPoint:
    """One point of a pulse-voltage sweep."""

    set_voltage: float
    """Commanded Avtech pulse voltage, in volts."""

    dut_voltage: float
    """DUT voltage measured on the scope's "voltage" channel, in volts."""

    dut_current: float
    """DUT current derived from the "current"/"voltage" channel pair via
    Ohm's law across the known series resistor, in amps."""

    lockin_x: float
    """Lock-in in-phase component, in volts."""

    lockin_y: float
    """Lock-in quadrature component, in volts."""

    lockin_r: float
    """Lock-in magnitude (optical intensity proxy), in volts."""

    lockin_phase: float
    """Lock-in phase, in radians."""


@dataclass
class SweepConfig:
    """Tunable parameters for a single :func:`run_voltage_sweep` call."""

    voltage_channel: int = config.DEFAULT_CHANNEL_ROLES["voltage"]
    """Rigol channel reporting the DUT voltage."""

    current_channel: int = config.DEFAULT_CHANNEL_ROLES["current"]
    """Rigol channel used with ``voltage_channel`` to derive DUT current."""

    series_resistance_ohm: float = config.DEFAULT_SERIES_RESISTANCE_OHM
    """Known series/shunt resistance (R0) in ohms."""

    ramp_step_size: float = 1.0
    """Maximum Avtech voltage change per ramp step, in volts. See
    :meth:`instruments.avtech.Avtech.ramp_to_voltage`."""

    ramp_sleep_time: float = 2.0
    """Seconds to wait after each Avtech ramp step."""

    settle_time: float = 1.0
    """Seconds to wait around the Rigol single-shot trigger. See
    :meth:`instruments.rigol.Rigol.acquire_single_shot`."""

    robust_trim: bool = False
    """Whether to trim outlier samples before the GMM plateau fit. See
    :meth:`instruments.rigol.Rigol.extract_plateau_voltage`."""

    mfli_demod_index: int = 0
    """MFLI demodulator index to read at each step."""

    mfli_n_samples: int = 10
    """Number of MFLI samples to average per step. See
    :meth:`instruments.mfli.MFLI.read_averaged_sample`."""

    mfli_delay: float = 0.05
    """Seconds between successive MFLI samples within one averaged read."""

    idle_voltage: Optional[float] = None
    """If given, the Avtech is ramped to this voltage after the sweep
    finishes (e.g. to leave the device under test in a safe idle state)."""

    trigger_group: Optional[int] = None
    """If given and ``qdac`` is provided to :func:`run_voltage_sweep`, this
    internal trigger group is fired once before the sweep starts, to begin
    a continuous QDac trigger/gate train (see
    :meth:`instruments.qdac.QDac.fire_internal_trigger`). Left ``None`` if
    the trigger train is already running or is started separately by the
    caller."""


def run_voltage_sweep(
    avtech: Avtech,
    rigol: Rigol,
    mfli: MFLI,
    qdac: Optional[QDac] = None,
    *,
    voltages: Sequence[float],
    sweep_config: Optional[SweepConfig] = None,
) -> pd.DataFrame:
    """Sweep the Avtech pulse voltage and record (V, I, lock-in) at each step.

    At each voltage in ``voltages``, this ramps the Avtech to that voltage,
    triggers a single-shot Rigol acquisition on the configured
    voltage/current channels, derives the DUT voltage and current, and
    reads an averaged MFLI lock-in sample.

    Args:
        avtech: Connected, pre-configured Avtech pulse generator.
        rigol: Connected, pre-configured Rigol oscilloscope.
        mfli: Connected, pre-configured MFLI lock-in amplifier.
        qdac: Connected QDac, if a one-time trigger fire is requested via
            ``sweep_config.trigger_group``. Otherwise unused by this
            function -- passed in for lifecycle/interface completeness
            alongside the other three instruments.
        voltages: Sequence of pulse voltages to sweep over, in volts.
        sweep_config: Sweep parameters; defaults to ``SweepConfig()`` if
            omitted.

    Returns:
        A :class:`pandas.DataFrame` with one row per swept voltage and
        columns matching the fields of :class:`SweepPoint`.
    """
    cfg = sweep_config or SweepConfig()

    if qdac is not None and cfg.trigger_group is not None:
        qdac.fire_internal_trigger(cfg.trigger_group)

    records: list[SweepPoint] = []
    total = len(voltages)
    for step, target_voltage in enumerate(voltages, start=1):
        logger.info(
            "Sweep step %d/%d: ramping pulse voltage to %s V", step, total, target_voltage
        )
        avtech.ramp_to_voltage(
            target_voltage,
            step_size=cfg.ramp_step_size,
            sleep_time=cfg.ramp_sleep_time,
        )

        waveforms = rigol.acquire_single_shot(
            [cfg.voltage_channel, cfg.current_channel], settle_time=cfg.settle_time
        )
        dut_voltage = rigol.extract_plateau_voltage(
            waveforms[cfg.voltage_channel][1], robust_trim=cfg.robust_trim
        )
        upstream_voltage = rigol.extract_plateau_voltage(
            waveforms[cfg.current_channel][1], robust_trim=cfg.robust_trim
        )
        dut_current = (upstream_voltage - dut_voltage) / cfg.series_resistance_ohm

        lockin = mfli.read_averaged_sample(
            cfg.mfli_demod_index,
            n_samples=cfg.mfli_n_samples,
            delay=cfg.mfli_delay,
        )

        records.append(
            SweepPoint(
                set_voltage=target_voltage,
                dut_voltage=dut_voltage,
                dut_current=dut_current,
                lockin_x=lockin["x"],
                lockin_y=lockin["y"],
                lockin_r=lockin["r"],
                lockin_phase=lockin["phase"],
            )
        )

    if cfg.idle_voltage is not None:
        logger.info("Sweep finished: ramping pulse voltage to idle %s V", cfg.idle_voltage)
        avtech.ramp_to_voltage(
            cfg.idle_voltage,
            step_size=cfg.ramp_step_size,
            sleep_time=cfg.ramp_sleep_time,
        )

    columns = [f.name for f in fields(SweepPoint)]
    return pd.DataFrame([asdict(point) for point in records], columns=columns)
