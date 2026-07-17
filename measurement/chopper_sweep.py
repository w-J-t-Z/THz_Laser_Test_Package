"""Chopper-frequency sweep orchestration.

Sweeps the QDac CH1 on/off chopper frequency (holding CH2's fast pulse
trigger frequency, the Avtech lasing voltage, and the MFLI's demodulator
filter/rate fixed) to find which chopper frequency gives the best lock-in
SNR. See the top-level CLAUDE.md for the overall experiment layout, and
``measurement/sweep.py`` for the related pulse-voltage sweep.

CH1 and CH2 share the same QDac internal trigger group so they stay
phase-locked with no timing jitter between them. Because of that, every
step in this sweep resets *both* channels together (abort, reconfigure,
re-arm, and fire the shared trigger) rather than touching CH1 alone --
touching only CH1 would risk disturbing CH2's already-running pulse train
if firing a trigger group affects channels beyond the one just re-armed.

This module assumes the Avtech, QDac, and MFLI are already connected
(Rigol is not used in this experiment); it only performs the per-step
sweep loop and instrument safety handling, not full initial instrument
setup.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from typing import Callable, Optional, Sequence

import pandas as pd

from instruments.avtech import Avtech
from instruments.mfli import MFLI
from instruments.qdac import QDac

logger = logging.getLogger(__name__)


@dataclass
class ChopperSweepPoint:
    """One point of a chopper-frequency sweep."""

    chopper_frequency_hz: float
    """QDac CH1 on/off chopper frequency for this point, in Hz."""

    lockin_x: float
    """Lock-in in-phase component, in volts."""

    lockin_x_std: float
    """Sample standard deviation of X across the averaged lock-in reads, in
    volts (``NaN`` if only one sample was read)."""

    lockin_y: float
    """Lock-in quadrature component, in volts."""

    lockin_y_std: float
    """Sample standard deviation of Y across the averaged lock-in reads, in
    volts (``NaN`` if only one sample was read)."""

    lockin_r: float
    """Lock-in magnitude (optical intensity proxy), in volts."""

    lockin_r_std: float
    """Sample standard deviation of R across the averaged lock-in reads, in
    volts (``NaN`` if only one sample was read). Computed empirically from
    the per-sample R values, not propagated from ``lockin_x_std``/
    ``lockin_y_std``."""

    lockin_phase: float
    """Lock-in phase, in radians."""


@dataclass
class ChopperSweepConfig:
    """Tunable parameters for a single :func:`run_chopper_frequency_sweep` call."""

    ch1_default_frequency_hz: float = 200.0
    """CH1 chopper frequency to reset to once the sweep finishes (normally,
    interrupted, or timed out)."""

    ch2_frequency_hz: float = 2000.0
    """CH2 pulse trigger frequency, fixed for the whole sweep (not swept)."""

    ch2_delay_s: float = 0.0125e-3
    """CH2 pulse delay relative to the shared trigger, in seconds."""

    ch2_duty_cycle: float = 50.0
    """CH2 duty cycle in percent."""

    gate_voltage: float = 5.0
    """Peak-to-peak voltage span for both CH1 and CH2 (offset is always
    ``gate_voltage / 2``)."""

    trigger_group: int = 1
    """Shared QDac internal trigger group (e.g. ``1`` for INT1) that both
    CH1 and CH2 are armed on, so they always start in lockstep."""

    lasing_voltage: float = 29.0
    """Avtech pulse voltage to hold during measurement at each chopper
    frequency."""

    ramp_step_size: float = 1.0
    """Maximum Avtech voltage change per ramp step, in volts."""

    ramp_sleep_time: float = 2.0
    """Seconds to wait after each Avtech ramp step."""

    n_settle_periods: float = 10.0
    """Minimum number of chopper periods to wait after switching frequency
    and ramping back up to ``lasing_voltage``, before measuring."""

    mfli_demod_index: int = 0
    """MFLI demodulator index used for the whole sweep."""

    mfli_time_constant: float = 0.1
    """Low-pass filter time constant, in seconds. Fixed across the whole
    sweep (not scaled with chopper frequency) so that the SNR comparison
    reflects the underlying noise environment at each frequency rather
    than a changing measurement bandwidth."""

    mfli_filter_order: int = 6
    """Low-pass filter order. Fixed across the whole sweep, same reasoning
    as ``mfli_time_constant``."""

    mfli_demod_rate_hz: float = 100.0
    """Demodulator output sample rate, in samples/second. Fixed across the
    whole sweep."""

    mfli_n_samples: int = 30
    """Number of MFLI samples averaged per chopper frequency."""

    mfli_delay: float = 0.3
    """Seconds between successive MFLI samples within one averaged read."""

    max_runtime_s: float = 10000.0
    """Maximum wall-clock time the sweep is allowed to run before it is
    stopped automatically (same emergency shutdown as an interrupt, with
    ``status="timed_out"``)."""


@dataclass
class ChopperSweepResult:
    """The outcome of a :func:`run_chopper_frequency_sweep` call: data plus run metadata."""

    data: pd.DataFrame
    """One row per completed chopper frequency, columns matching
    :class:`ChopperSweepPoint`."""

    start_time: str
    """ISO 8601 UTC timestamp when the sweep started."""

    end_time: str
    """ISO 8601 UTC timestamp when the sweep ended (normally, interrupted, or timed out)."""

    status: str
    """One of ``"completed"``, ``"interrupted"``, or ``"timed_out"``."""

    completed_points: int
    """Number of chopper frequencies actually completed."""

    total_points: int
    """Number of chopper frequencies that were planned."""

    sweep_config: ChopperSweepConfig
    """The :class:`ChopperSweepConfig` used for this run."""


def _reset_qdac_channels(qdac: QDac, cfg: ChopperSweepConfig, ch1_frequency_hz: float) -> None:
    """Abort, reconfigure, re-arm, and fire both CH1 and CH2 from the shared trigger.

    Resetting both channels together (rather than just CH1) keeps them
    phase-locked with no timing jitter between them, since they share the
    same trigger group.

    Args:
        qdac: Connected QDac.
        cfg: Sweep configuration providing CH2's fixed parameters, the
            shared gate voltage, and the trigger group.
        ch1_frequency_hz: Chopper frequency to configure CH1 to.
    """
    qdac.abort_square_wave(1)
    qdac.abort_square_wave(2)
    qdac.configure_square_wave(
        1,
        frequency=ch1_frequency_hz,
        span=cfg.gate_voltage,
        offset=cfg.gate_voltage / 2,
        trigger_source=cfg.trigger_group,
    )
    qdac.configure_square_wave(
        2,
        frequency=cfg.ch2_frequency_hz,
        span=cfg.gate_voltage,
        offset=cfg.gate_voltage / 2,
        trigger_source=cfg.trigger_group,
        delay=cfg.ch2_delay_s,
        duty_cycle=cfg.ch2_duty_cycle,
    )
    qdac.start_square_wave(1)
    qdac.start_square_wave(2)
    qdac.fire_internal_trigger(cfg.trigger_group)


def _emergency_stop(avtech: Avtech, cfg: ChopperSweepConfig) -> None:
    """Ramp the Avtech to 0 V and disable its output, tolerating a second interrupt.

    Same pattern as :func:`measurement.sweep._emergency_stop`: if a second
    interrupt arrives while this ramp-down itself is in progress, the
    gradual ramp is abandoned and the output is disabled immediately
    instead.

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


def run_chopper_frequency_sweep(
    avtech: Avtech,
    qdac: QDac,
    mfli: MFLI,
    *,
    frequencies_hz: Sequence[float],
    sweep_config: Optional[ChopperSweepConfig] = None,
    on_step: Optional[Callable[[pd.DataFrame], None]] = None,
) -> ChopperSweepResult:
    """Sweep the QDac CH1 chopper frequency and record the lock-in signal at each step.

    At each frequency in ``frequencies_hz``, this ramps the Avtech down to
    0 V and disables its output, resets both CH1 (to the new frequency)
    and CH2 (unchanged) together from their shared trigger, ramps the
    Avtech back up to ``sweep_config.lasing_voltage`` and re-enables its
    output, re-runs the MFLI's automatic phase adjustment, waits at least
    ``sweep_config.n_settle_periods`` chopper periods, and then reads an
    averaged MFLI lock-in sample.

    If interrupted (``KeyboardInterrupt``, e.g. from a Jupyter cell
    interrupt) or if ``sweep_config.max_runtime_s`` is exceeded, the sweep
    loop stops early. Either way -- including normal completion -- this
    always ends by ramping the Avtech down to 0 V and disabling its
    output, and resetting CH1 back to ``sweep_config.ch1_default_frequency_hz``
    (CH2 unchanged), leaving the setup in a known, safe default state.
    This function then returns normally with whatever data was collected,
    rather than propagating the exception.

    Args:
        avtech: Connected Avtech pulse generator.
        qdac: Connected QDac.
        mfli: Connected MFLI lock-in amplifier.
        frequencies_hz: Sequence of CH1 chopper frequencies to sweep over,
            in Hz. Should be common factors of CH2's fixed frequency (see
            ``sweep_config.ch2_frequency_hz``) to keep the pulse train
            stable relative to the chopper.
        sweep_config: Sweep parameters; defaults to ``ChopperSweepConfig()``
            if omitted.
        on_step: Optional callback invoked after each completed step with
            the DataFrame of all points collected so far (e.g. to drive a
            live-updating plot in a notebook via
            ``IPython.display.clear_output``). Kept free of any notebook
            dependency here; the callback itself does the display work.

    Returns:
        A :class:`ChopperSweepResult` bundling the collected data with run
        metadata (timestamps, completion status, and the config used --
        including the fixed MFLI filter/rate settings, so they end up
        recorded alongside the data).
    """
    cfg = sweep_config or ChopperSweepConfig()
    columns = [f.name for f in fields(ChopperSweepPoint)]

    # Fixed MFLI configuration for the whole sweep -- not touched per-step.
    mfli.configure_demod(
        cfg.mfli_demod_index,
        enable=True,
        filter_order=cfg.mfli_filter_order,
        time_constant=cfg.mfli_time_constant,
    )
    mfli.configure_demod_rate(cfg.mfli_demod_index, rate_hz=cfg.mfli_demod_rate_hz)

    records: list[ChopperSweepPoint] = []
    total = len(frequencies_hz)
    start_time = datetime.now(timezone.utc)
    start_monotonic = time.monotonic()
    status = "completed"

    try:
        for step, frequency_hz in enumerate(frequencies_hz, start=1):
            if time.monotonic() - start_monotonic > cfg.max_runtime_s:
                logger.warning(
                    "Chopper sweep exceeded max_runtime_s=%s at step %d/%d; stopping.",
                    cfg.max_runtime_s,
                    step,
                    total,
                )
                status = "timed_out"
                break

            logger.info(
                "Chopper sweep step %d/%d: switching CH1 to %s Hz", step, total, frequency_hz
            )

            avtech.ramp_to_voltage(
                0.0, step_size=cfg.ramp_step_size, sleep_time=cfg.ramp_sleep_time
            )
            avtech.output_off()

            _reset_qdac_channels(qdac, cfg, frequency_hz)

            avtech.output_on()
            avtech.ramp_to_voltage(
                cfg.lasing_voltage,
                step_size=cfg.ramp_step_size,
                sleep_time=cfg.ramp_sleep_time,
            )

            mfli.auto_phase_adjust(cfg.mfli_demod_index)

            time.sleep(cfg.n_settle_periods / frequency_hz)

            lockin = mfli.read_averaged_sample(
                cfg.mfli_demod_index,
                n_samples=cfg.mfli_n_samples,
                delay=cfg.mfli_delay,
            )

            records.append(
                ChopperSweepPoint(
                    chopper_frequency_hz=frequency_hz,
                    lockin_x=lockin["x"],
                    lockin_x_std=lockin["x_std"],
                    lockin_y=lockin["y"],
                    lockin_y_std=lockin["y_std"],
                    lockin_r=lockin["r"],
                    lockin_r_std=lockin["r_std"],
                    lockin_phase=lockin["phase"],
                )
            )

            if on_step is not None:
                on_step(pd.DataFrame([asdict(point) for point in records], columns=columns))
    except KeyboardInterrupt:
        logger.warning(
            "Chopper sweep interrupted by user at step %d/%d.", len(records) + 1, total
        )
        status = "interrupted"

    # Always end in a known, safe state: Avtech off, CH1 back to default.
    _emergency_stop(avtech, cfg)
    _reset_qdac_channels(qdac, cfg, cfg.ch1_default_frequency_hz)

    end_time = datetime.now(timezone.utc)
    df = pd.DataFrame([asdict(point) for point in records], columns=columns)

    return ChopperSweepResult(
        data=df,
        start_time=start_time.isoformat(),
        end_time=end_time.isoformat(),
        status=status,
        completed_points=len(records),
        total_points=total,
        sweep_config=cfg,
    )
