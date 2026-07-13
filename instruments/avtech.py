"""Avtech pulse generator control class.

The Avtech supplies the voltage pulse that powers the laser device under
test; pulse amplitude (and possibly width/timing) is the parameter swept
during a measurement. See the top-level CLAUDE.md for the overall
experiment layout.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

import pyvisa

from . import config
from .base import InstrumentError, VisaInstrument

logger = logging.getLogger(__name__)


class AvtechError(InstrumentError):
    """Raised for Avtech-specific communication or command errors."""


class Avtech(VisaInstrument):
    """Control class for an Avtech AVR-3 series pulse generator.

    Args:
        resource: VISA resource string for the Avtech. Defaults to
            :data:`instruments.config.AVTECH_VISA_ADDRESS` (a GPIB
            connection in this lab's setup).
        resource_manager: An existing :class:`pyvisa.ResourceManager` to
            reuse instead of creating a new one.
        timeout_ms: VISA I/O timeout in milliseconds.
    """

    error_cls = AvtechError

    VALID_TRIGGER_MODES = {
        "INT": "INTERNAL",
        "EXT": "EXTERNAL",
        "MAN": "MANUAL",
        "HOLD": "HOLD",
        "IMM": "IMMEDIATE",
    }

    VALID_GATE_TYPES = frozenset({"SYNC", "ASYNC"})

    VALID_GATE_LEVELS = frozenset({"HIGH", "LOW"})

    VALID_SHAPES = frozenset(
        {"PULSE", "DC", "AMPLIFY", "SINUSOID", "SQUARE", "TRIANGLE"}
    )

    def __init__(
        self,
        resource: str = config.AVTECH_VISA_ADDRESS,
        *,
        resource_manager: Optional[pyvisa.ResourceManager] = None,
        timeout_ms: int = 5000,
    ) -> None:
        super().__init__(resource, resource_manager=resource_manager, timeout_ms=timeout_ms)

    def _query_float(self, cmd: str) -> float:
        """Send a query and parse the response as a float.

        Args:
            cmd: The SCPI query string to send.

        Returns:
            The response parsed as a float.

        Raises:
            AvtechError: If the underlying VISA query fails.
        """
        return float(self._query(cmd))

    # ------------------------------------------------------------------
    # Identification / remote-local
    # ------------------------------------------------------------------

    def idn(self) -> str:
        """Return the instrument's ``*IDN?`` identification string."""
        return self._query("*IDN?")

    def remote(self) -> None:
        """Enter remote control mode (disables the front panel)."""
        self._write("*REM")

    def local(self) -> None:
        """Return control to the front panel."""
        self._write("*LOC")

    # ------------------------------------------------------------------
    # Pulse width
    # ------------------------------------------------------------------

    def get_pulse_width_range(self) -> tuple[float, float]:
        """Return the instrument-reported ``(min, max)`` pulse width in seconds."""
        return (
            self._query_float("pulse:width? min"),
            self._query_float("pulse:width? max"),
        )

    def set_pulse_width(self, width: float) -> None:
        """Set the pulse width.

        Args:
            width: Pulse width in seconds (e.g. ``80e-6``).

        Raises:
            AvtechError: If ``width`` is outside the instrument's allowed
                range.
        """
        wmin, wmax = self.get_pulse_width_range()
        if not wmin <= width <= wmax:
            raise AvtechError(f"Pulse width {width} outside range [{wmin}, {wmax}]")
        self._write(f"pulse:width {width}")

    def get_pulse_width(self) -> float:
        """Return the currently set pulse width in seconds."""
        return self._query_float("pulse:width?")

    # ------------------------------------------------------------------
    # Duty cycle
    # ------------------------------------------------------------------

    def set_duty_cycle(self, duty: float) -> None:
        """Set the pulse duty cycle.

        Args:
            duty: Duty cycle in percent.

        Raises:
            AvtechError: If ``duty`` is outside the instrument's allowed
                range.
        """
        dmin = self._query_float("pulse:dcycle? min")
        dmax = self._query_float("pulse:dcycle? max")
        if not dmin <= duty <= dmax:
            raise AvtechError(f"Duty cycle {duty} outside range [{dmin}, {dmax}]")
        self._write(f"pulse:dcycle {duty}")

    def get_duty_cycle(self) -> float:
        """Return the currently set duty cycle in percent."""
        return self._query_float("pulse:dcycle?")

    def set_width_mode(self) -> None:
        """Hold pulse width fixed as other parameters (e.g. frequency) change."""
        self._write("pulse:hold width")

    def set_duty_mode(self) -> None:
        """Hold duty cycle fixed as other parameters (e.g. frequency) change."""
        self._write("pulse:hold dcycle")

    # ------------------------------------------------------------------
    # Voltage (pulse amplitude)
    # ------------------------------------------------------------------

    def get_voltage_range(self) -> tuple[float, float]:
        """Return the instrument-reported ``(min, max)`` pulse voltage in volts."""
        return (self._query_float("volt? min"), self._query_float("volt? max"))

    def set_voltage(self, voltage: float) -> None:
        """Set the pulse amplitude.

        This is the swept parameter for the I-V/optical-intensity sweep.

        Args:
            voltage: Pulse voltage in volts.

        Raises:
            AvtechError: If ``voltage`` is outside the instrument's allowed
                range.
        """
        vmin, vmax = self.get_voltage_range()
        if not vmin <= voltage <= vmax:
            raise AvtechError(f"Voltage {voltage} outside range [{vmin}, {vmax}]")
        self._write(f"volt {voltage}")

    def get_voltage(self) -> float:
        """Return the currently set pulse voltage in volts."""
        return self._query_float("volt?")

    def ramp_to_voltage(
        self, target: float, *, step_size: float = 1.0, sleep_time: float = 2.0
    ) -> None:
        """Gradually step the pulse voltage to ``target`` instead of jumping to it.

        Jumping the pulse amplitude directly to a large value can stress the
        device under test, so this walks the voltage to the target in
        increments of at most ``step_size``, pausing ``sleep_time`` seconds
        after each step to let the output settle.

        Args:
            target: Desired pulse voltage in volts.
            step_size: Maximum voltage change per step, in volts.
            sleep_time: Time to wait after each step, in seconds.

        Raises:
            AvtechError: If ``step_size`` is not positive, or if any step
                is rejected by the instrument's voltage range.
        """
        if step_size <= 0:
            raise AvtechError("step_size must be positive")
        step = abs(step_size)

        while self.get_voltage() < target:
            current = self.get_voltage()
            if target - current <= step:
                self.set_voltage(target)
            else:
                self.set_voltage(current + step)
            time.sleep(sleep_time)

        while self.get_voltage() > target:
            current = self.get_voltage()
            if current - target <= step:
                self.set_voltage(target)
            else:
                self.set_voltage(current - step)
            time.sleep(sleep_time)

    # ------------------------------------------------------------------
    # Frequency
    # ------------------------------------------------------------------

    def get_frequency_range(self) -> tuple[float, float]:
        """Return the instrument-reported ``(min, max)`` frequency in Hz."""
        return (self._query_float("freq? min"), self._query_float("freq? max"))

    def set_frequency(self, frequency: float) -> None:
        """Set the pulse repetition frequency.

        Args:
            frequency: Frequency in Hz.

        Raises:
            AvtechError: If ``frequency`` is outside the instrument's
                allowed range.
        """
        fmin, fmax = self.get_frequency_range()
        if not fmin <= frequency <= fmax:
            raise AvtechError(f"Frequency {frequency} outside range [{fmin}, {fmax}]")
        self._write(f"freq {frequency}")

    def get_frequency(self) -> float:
        """Return the currently set pulse repetition frequency in Hz."""
        return self._query_float("freq?")

    # ------------------------------------------------------------------
    # Delay
    # ------------------------------------------------------------------

    def get_delay_range(self) -> tuple[float, float]:
        """Return the instrument-reported ``(min, max)`` pulse delay in seconds."""
        return (
            self._query_float("pulse:delay? min"),
            self._query_float("pulse:delay? max"),
        )

    def set_delay(self, delay: float) -> None:
        """Set the pulse delay relative to the trigger.

        Args:
            delay: Delay in seconds.
        """
        self._write(f"pulse:delay {delay}")

    def get_delay(self) -> float:
        """Return the currently set pulse delay in seconds."""
        return self._query_float("pulse:delay?")

    # ------------------------------------------------------------------
    # Function shape
    # ------------------------------------------------------------------

    def set_shape(self, shape: str) -> None:
        """Set the output waveform shape.

        Args:
            shape: One of ``"PULSE"``, ``"DC"``, ``"AMPLIFY"``,
                ``"SINUSOID"``, ``"SQUARE"``, ``"TRIANGLE"`` (case
                insensitive).

        Raises:
            AvtechError: If ``shape`` is not a recognized shape.
        """
        shape = shape.upper()
        if shape not in self.VALID_SHAPES:
            raise AvtechError(f"Unsupported shape {shape!r}")
        self._write(f"func:shape {shape}")

    def get_shape(self) -> str:
        """Return the currently set output waveform shape."""
        return self._query("func:shape?")

    # ------------------------------------------------------------------
    # Trigger mode
    # ------------------------------------------------------------------

    def set_trigger(self, mode: str) -> None:
        """Set the trigger source mode.

        Args:
            mode: One of ``"INT"``, ``"EXT"``, ``"MAN"``, ``"HOLD"``,
                ``"IMM"`` (case insensitive). In this experiment the Avtech
                is typically triggered externally (``"EXT"``) by the QDac.

        Raises:
            AvtechError: If ``mode`` is not a recognized trigger mode.
        """
        mode = mode.upper()
        if mode not in self.VALID_TRIGGER_MODES:
            raise AvtechError(
                f"Invalid trigger mode {mode!r}; "
                f"must be one of {sorted(self.VALID_TRIGGER_MODES)}"
            )
        self._write(f"trigger:source {mode}")

    def get_trigger(self) -> str:
        """Return the currently set trigger source mode."""
        return self._query("trigger:source?")

    # ------------------------------------------------------------------
    # Gate
    # ------------------------------------------------------------------

    def set_gate(self, gate_type: str, level: str) -> None:
        """Set the pulse gate type and active level.

        Args:
            gate_type: ``"SYNC"`` or ``"ASYNC"``.
            level: ``"HIGH"`` or ``"LOW"``.

        Raises:
            AvtechError: If ``gate_type`` or ``level`` is not recognized.
        """
        gate_type = gate_type.upper()
        level = level.upper()

        if gate_type not in self.VALID_GATE_TYPES:
            raise AvtechError("Gate type must be SYNC/ASYNC")
        if level not in self.VALID_GATE_LEVELS:
            raise AvtechError("Gate level must be HIGH/LOW")

        self._write(f"pulse:gate:type {gate_type}")
        self._write(f"pulse:gate:level {level}")

    def get_gate(self) -> tuple[str, str]:
        """Return the currently set ``(gate_type, gate_level)``."""
        return (self._query("pulse:gate:type?"), self._query("pulse:gate:level?"))

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def output(self, state: bool) -> None:
        """Enable or disable the pulse output.

        Args:
            state: ``True`` to enable the output, ``False`` to disable it.
        """
        if state:
            self.output_on()
        else:
            self.output_off()

    def output_on(self) -> None:
        """Enable the pulse output."""
        self._write("output on")

    def output_off(self) -> None:
        """Disable the pulse output."""
        self._write("output off")

    def get_output(self) -> str:
        """Return the current output enable state as reported by the instrument."""
        return self._query("output?")

    # ------------------------------------------------------------------
    # Error checking
    # ------------------------------------------------------------------

    def check_error(self) -> None:
        """Raise if the instrument's error queue reports a pending error.

        Raises:
            AvtechError: If the instrument reports a non-zero error code.
        """
        err = self._query("system:error?")
        if not err.startswith("0"):
            raise AvtechError(err)
