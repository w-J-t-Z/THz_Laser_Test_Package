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
import time
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from typing import Callable, Optional, Sequence

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
    """Maximum Avtech voltage change per ramp step, in volts. Also used for
    the emergency ramp-down on interrupt/timeout. See
    :meth:`instruments.avtech.Avtech.ramp_to_voltage`."""

    ramp_sleep_time: float = 2.0
    """Seconds to wait after each Avtech ramp step (including the
    emergency ramp-down)."""

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
    finishes normally (e.g. to leave the device under test in a safe idle
    state). Not used on interrupt/timeout -- see the module docstring on
    :func:`run_voltage_sweep` for the emergency shutdown behavior instead."""

    trigger_group: Optional[int] = None
    """If given and ``qdac`` is provided to :func:`run_voltage_sweep`, this
    internal trigger group is fired once before the sweep starts, to begin
    a continuous QDac trigger/gate train (see
    :meth:`instruments.qdac.QDac.fire_internal_trigger`). Left ``None`` if
    the trigger train is already running or is started separately by the
    caller."""

    max_runtime_s: float = 1000.0
    """Maximum wall-clock time the sweep is allowed to run before it is
    stopped automatically (same emergency shutdown as an interrupt, with
    ``status="timed_out"``). Guards against a sweep left running
    unattended for far longer than intended."""


@dataclass
class SweepResult:
    """The outcome of a :func:`run_voltage_sweep` call: data plus run metadata."""

    data: pd.DataFrame
    """One row per completed voltage step, columns matching :class:`SweepPoint`."""

    start_time: str
    """ISO 8601 UTC timestamp when the sweep started."""

    end_time: str
    """ISO 8601 UTC timestamp when the sweep ended (normally, interrupted, or timed out)."""

    status: str
    """One of ``"completed"``, ``"interrupted"``, or ``"timed_out"``."""

    completed_points: int
    """Number of voltage steps actually completed."""

    total_points: int
    """Number of voltage steps that were planned."""

    sweep_config: SweepConfig
    """The :class:`SweepConfig` used for this run."""


def _emergency_stop(avtech: Avtech, cfg: SweepConfig) -> None:
    """Ramp the Avtech to 0 V and disable its output, tolerating a second interrupt.

    Uses the same step size/sleep time as the sweep's normal ramp. If a
    second interrupt arrives while this ramp-down itself is in progress,
    the gradual ramp is abandoned and the output is disabled immediately
    instead, rather than leaving the pulse generator in an ambiguous
    half-ramped state.

    Args:
        avtech: The Avtech pulse generator to shut down.
        cfg: Sweep configuration providing the ramp step size/sleep time.
    """
    try:
        avtech.ramp_to_voltage(
            0.0, step_size=cfg.ramp_step_size, sleep_time=cfg.ramp_sleep_time
        )
    except KeyboardInterrupt:
        logger.warning(
            "Second interrupt during emergency ramp-down; disabling output immediately."
        )
    finally:
        avtech.output_off()


def run_voltage_sweep(
    avtech: Avtech,
    rigol: Rigol,
    mfli: MFLI,
    qdac: Optional[QDac] = None,
    *,
    voltages: Sequence[float],
    sweep_config: Optional[SweepConfig] = None,
    on_step: Optional[Callable[[pd.DataFrame], None]] = None,
) -> SweepResult:
    """Sweep the Avtech pulse voltage and record (V, I, lock-in) at each step.

    At each voltage in ``voltages``, this ramps the Avtech to that voltage,
    triggers a single-shot Rigol acquisition on the configured
    voltage/current channels, derives the DUT voltage and current, and
    reads an averaged MFLI lock-in sample.

    If interrupted (``KeyboardInterrupt``, e.g. from a Jupyter cell
    interrupt) or if ``sweep_config.max_runtime_s`` is exceeded, this
    immediately ramps the Avtech down to 0 V and disables its output
    (leaving the QDac trigger train, Rigol, and MFLI connected and
    untouched), then returns normally with whatever data was collected so
    far rather than propagating the exception -- so a single call always
    produces a result, whether the sweep finished naturally or was cut
    short.

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
        on_step: Optional callback invoked after each completed step with
            the DataFrame of all points collected so far (e.g. to drive a
            live-updating plot in a notebook via
            ``IPython.display.clear_output``). Kept free of any notebook
            dependency here; the callback itself does the display work.

    Returns:
        A :class:`SweepResult` bundling the collected data with run
        metadata (timestamps, completion status, and the config used).
    """
    cfg = sweep_config or SweepConfig()
    columns = [f.name for f in fields(SweepPoint)]

    if qdac is not None and cfg.trigger_group is not None:
        qdac.fire_internal_trigger(cfg.trigger_group)

    records: list[SweepPoint] = []
    total = len(voltages)
    start_time = datetime.now(timezone.utc)
    start_monotonic = time.monotonic()
    status = "completed"

    try:
        for step, target_voltage in enumerate(voltages, start=1):
            if time.monotonic() - start_monotonic > cfg.max_runtime_s:
                logger.warning(
                    "Sweep exceeded max_runtime_s=%s at step %d/%d; stopping.",
                    cfg.max_runtime_s,
                    step,
                    total,
                )
                status = "timed_out"
                break

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

            if on_step is not None:
                on_step(pd.DataFrame([asdict(point) for point in records], columns=columns))
    except KeyboardInterrupt:
        logger.warning("Sweep interrupted by user at step %d/%d.", len(records) + 1, total)
        status = "interrupted"

    if status in ("interrupted", "timed_out"):
        _emergency_stop(avtech, cfg)
    elif cfg.idle_voltage is not None:
        logger.info("Sweep finished: ramping pulse voltage to idle %s V", cfg.idle_voltage)
        avtech.ramp_to_voltage(
            cfg.idle_voltage,
            step_size=cfg.ramp_step_size,
            sleep_time=cfg.ramp_sleep_time,
        )

    end_time = datetime.now(timezone.utc)
    df = pd.DataFrame([asdict(point) for point in records], columns=columns)

    return SweepResult(
        data=df,
        start_time=start_time.isoformat(),
        end_time=end_time.isoformat(),
        status=status,
        completed_points=len(records),
        total_points=total,
        sweep_config=cfg,
    )
