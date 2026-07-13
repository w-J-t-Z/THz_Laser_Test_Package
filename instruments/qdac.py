"""QDac multi-channel precision DC/trigger source control class.

In this experiment the QDac is used purely as a trigger/gate signal
generator that synchronizes the Avtech pulse generator and the MFLI lock-in
amplifier -- it does not itself supply the swept pulse voltage (that is the
Avtech's role). See the top-level CLAUDE.md for the overall experiment
layout.
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

import pyvisa

from . import config
from .base import InstrumentError, VisaInstrument

logger = logging.getLogger(__name__)


class QDacError(InstrumentError):
    """Raised for QDac-specific communication or command errors."""


class QDac(VisaInstrument):
    """Control class for a QDac multi-channel precision DC/trigger source.

    Args:
        resource: VISA resource string for the QDac. Defaults to
            :data:`instruments.config.QDAC_VISA_ADDRESS` (a serial
            connection in this lab's setup).
        resource_manager: An existing :class:`pyvisa.ResourceManager` to
            reuse instead of creating a new one.
        timeout_ms: VISA I/O timeout in milliseconds.
        baud_rate: Serial baud rate applied when ``resource`` is an
            ``ASRL`` (serial) address.
    """

    error_cls = QDacError

    def __init__(
        self,
        resource: str = config.QDAC_VISA_ADDRESS,
        *,
        resource_manager: Optional[pyvisa.ResourceManager] = None,
        timeout_ms: int = 5000,
        baud_rate: int = config.QDAC_BAUD_RATE,
    ) -> None:
        super().__init__(resource, resource_manager=resource_manager, timeout_ms=timeout_ms)
        self._baud_rate = baud_rate

    def connect(self) -> None:
        """Open the VISA session and apply QDac-specific line settings.

        Raises:
            QDacError: If the underlying VISA resource cannot be opened.
        """
        super().connect()
        session = self._require_session()
        session.write_termination = "\n"
        session.read_termination = "\n"
        if "ASRL" in self.resource:
            session.baud_rate = self._baud_rate
            session.send_end = False

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    def get_error(self) -> str:
        """Return the QDac's full error queue as a raw SCPI response string."""
        return self._query("syst:err:all?")

    def check_error(self) -> None:
        """Raise if the QDac error queue reports a pending error.

        Raises:
            QDacError: If the instrument's error queue is non-zero.
        """
        err = self.get_error()
        if not err.startswith("0"):
            raise QDacError(err)

    # ------------------------------------------------------------------
    # Channel configuration
    # ------------------------------------------------------------------

    def channel_init(self, channel: int) -> None:
        """Set a channel to fixed DC mode at 0 V.

        Args:
            channel: QDac channel number (1-indexed).
        """
        self._write(f"sour{channel}:mode fixed")
        self._write(f"sour{channel}:volt 0")

    def set_channel_slew_rate(self, channel: int, slew_rate: float = 10) -> None:
        """Set the voltage slew rate for a single channel.

        Args:
            channel: QDac channel number.
            slew_rate: Slew rate in V/s.
        """
        self._write(f"sour{channel}:volt:slew {slew_rate}")

    def set_slew_rate_for_channels(
        self, channels: Sequence[int], slew_rate: float
    ) -> None:
        """Set the voltage slew rate for multiple channels in one command.

        Uses the QDac channel-list syntax, e.g. ``(@1,24)``.

        Args:
            channels: Channel numbers to apply the slew rate to.
            slew_rate: Slew rate in V/s.
        """
        channel_list = ",".join(str(c) for c in channels)
        self._write(f"sour:volt:slew {slew_rate}, (@{channel_list})")

    def channel_set(
        self,
        channel: int,
        *,
        filter: str = "Med",
        vrange: str = "Low",
        crange: str = "High",
        slew_rate: float = 2e7,
        enhancement: str = "off",
    ) -> None:
        """Initialize a channel and apply its filter, range, and slew settings.

        Args:
            channel: QDac channel number.
            filter: Output filter bandwidth: ``"DC"`` (10 Hz), ``"Med"``
                (10 kHz), or ``"High"`` (230 kHz).
            vrange: Voltage range: ``"Low"`` (2 V) or ``"High"`` (10 V).
            crange: Current sense range.
            slew_rate: Slew rate (V/s) applied to DC, sine, and triangle
                waveforms on this channel.
            enhancement: DC range-enhancement setting, only sent when
                ``filter == "DC"``.
        """
        self.channel_init(channel)
        self._write(f"sour{channel}:filt {filter}")
        if filter == "DC":
            self._write(f"sour{channel}:DC:RENH {enhancement}")
        self._write(f"sour{channel}:range {vrange}")
        self._write(f"sour{channel}:volt:slew {slew_rate}")
        self._write(f"sour{channel}:sine:slew {slew_rate}")
        self._write(f"sour{channel}:tri:slew {slew_rate}")
        self._write(f"sens{channel}:range {crange}")

    def set_channel_voltage(self, channel: int, volt: float) -> None:
        """Set a channel's fixed DC output voltage.

        Args:
            channel: QDac channel number.
            volt: Target voltage in volts.
        """
        self._write(f"sour{channel}:volt {volt}")

    def get_channel_range(self, channel: int) -> str:
        """Query a channel's currently configured voltage range.

        Args:
            channel: QDac channel number.

        Returns:
            The range string reported by the instrument (e.g. ``"HIGH"``).
        """
        return self._query(f"sour{channel}:RANGE?")

    # ------------------------------------------------------------------
    # Square-wave trigger/gate generation
    #
    # In this setup, QDac channels are configured as square-wave sources
    # whose edges act as trigger/gate signals for the Avtech pulse
    # generator (external trigger) and the MFLI lock-in (external
    # reference) -- QDac does not supply the swept pulse voltage itself.
    # ------------------------------------------------------------------

    def configure_square_wave(
        self,
        channel: int,
        *,
        frequency: float,
        span: float,
        offset: float,
        trigger_source: str,
        delay: Optional[float] = None,
        duty_cycle: Optional[float] = None,
    ) -> None:
        """Configure, without starting, a square-wave trigger/gate generator.

        Args:
            channel: QDac channel number to configure.
            frequency: Square-wave frequency in Hz.
            span: Peak-to-peak voltage span in volts.
            offset: DC offset in volts (typically ``span / 2`` so the wave
                sits between 0 V and ``span``).
            trigger_source: Internal trigger group to arm on, e.g.
                ``"INT1"``, ``"INT2"``. Channels sharing the same trigger
                source fire together when :meth:`fire_internal_trigger` is
                called with the matching group index.
            delay: Optional delay in seconds between the trigger firing and
                the waveform starting.
            duty_cycle: Optional duty cycle in percent.
        """
        parts = [f"sour{channel}:squ:freq {frequency}"]
        if delay is not None:
            parts.append(f"delay {delay}")
        parts.append(f"span {span}")
        parts.append(f"offs {offset}")
        if duty_cycle is not None:
            parts.append(f"dcycle {duty_cycle}")
        parts.append(f"trig:sour {trigger_source}")
        self._write(";".join(parts))

    def start_square_wave(self, channel: int) -> None:
        """Arm a configured square-wave generator to wait for its trigger.

        Args:
            channel: QDac channel number.
        """
        self._write(f"sour{channel}:squ:init")

    def abort_square_wave(self, channel: int) -> None:
        """Stop a running or armed square-wave generator on a channel.

        Args:
            channel: QDac channel number.
        """
        self._write(f"sour{channel}:squ:ABORT")

    def abort_sine_wave(self, channel: int) -> None:
        """Stop a running or armed sine-wave generator on a channel.

        Args:
            channel: QDac channel number.
        """
        self._write(f"sour{channel}:sine:ABORT")

    def fire_internal_trigger(self, index: int) -> None:
        """Fire an internal trigger group, releasing any channels armed on it.

        Args:
            index: Internal trigger group index (e.g. ``1`` fires ``INT1``).
        """
        self._write(f"tint {index}")

    # ------------------------------------------------------------------
    # Hardware sweep table (not used by the current experiment)
    # ------------------------------------------------------------------

    def sweep_channel(
        self,
        channel: int,
        v_start: float,
        v_stop: float,
        points: int,
        *,
        dwell: float = 1e-2,
        mode: str = "Anal",
    ) -> None:
        """Configure a hardware voltage sweep table on a channel.

        Note:
            Not currently used in this experiment: here the QDac only
            generates trigger/gate signals, while the Avtech pulse
            generator performs the actual swept-voltage measurement. This
            is ported from the legacy ``Vsweep`` method for potential
            future use (e.g. a QDac-driven calibration sweep).

        Args:
            channel: QDac channel number.
            v_start: Sweep start voltage in volts.
            v_stop: Sweep stop voltage in volts.
            points: Number of sweep points.
            dwell: Dwell time per point in seconds.
            mode: Sweep generation mode (e.g. ``"Anal"``).
        """
        self._write(f"sour{channel}:swe:start {v_start};stop {v_stop}")
        self._write(f"sour{channel}:swe:points {points}")
        self._write(f"sour{channel}:swe:dwell {dwell}")
        self._write(f"sour{channel}:swe:gen {mode}")
