"""MFLI lock-in amplifier control class.

The MFLI reads the lock-in (demodulator) signal that corresponds to the
optical intensity emitted by the device under test.

This module is newly written, not ported from an existing wrapper:
``code_collection/MFLI_test.ipynb`` has no reusable class, only a short,
mostly vendor-example-style script (a handful of ``zhinst.core.ziDAQServer``
node writes and a single ``getSample`` call, with no connection lifecycle,
error handling, or averaging). The node paths and values below are carried
over from that notebook; the class structure, error wrapping, and averaged
readout are new.

Design choice -- zhinst.core vs. zhinst.toolkit:
    CLAUDE.md prefers the newer, object-oriented ``zhinst.toolkit`` Session
    API when available, falling back to ``zhinst.core`` (formerly
    ``zhinst.ziPython``) otherwise. The only tested MFLI code available
    (the legacy notebook) uses ``zhinst.core.ziDAQServer`` directly, and
    ``zhinst.toolkit``'s availability on the lab computer was not confirmed
    at the time this was written. To avoid introducing node paths and
    session semantics that have never actually been exercised against the
    real instrument, this class is built on ``zhinst.core``. If
    ``zhinst.toolkit`` is later confirmed available, a Session-based
    reimplementation can be swapped in behind the same
    :class:`instruments.base.InstrumentProtocol` interface without changing
    any calling code.
"""

from __future__ import annotations

import logging
import time
from types import TracebackType
from typing import Optional

import numpy as np
import zhinst.core
import zhinst.core.errors as zi_errors

from . import config
from .base import InstrumentError

logger = logging.getLogger(__name__)


class MFLIError(InstrumentError):
    """Raised for MFLI-specific communication or command errors."""


class MFLI:
    """Control class for a Zurich Instruments MFLI lock-in amplifier.

    Implements the same connect/disconnect/context-manager lifecycle as
    :class:`instruments.base.InstrumentProtocol`, but is not built on
    :class:`instruments.base.VisaInstrument` since the MFLI communicates
    over the ``zhinst`` LabOne data server API rather than VISA.

    Args:
        device_id: MFLI device serial, e.g. ``"dev7598"``. Defaults to
            :data:`instruments.config.MFLI_DEVICE_ID`.
        host: LabOne data server host address. Defaults to
            :data:`instruments.config.MFLI_HOST`.
        port: LabOne data server port. Defaults to
            :data:`instruments.config.MFLI_PORT`.
        api_level: ziDAQServer API level. Defaults to
            :data:`instruments.config.MFLI_API_LEVEL`.
        interface: Device interface string passed to ``connectDevice``
            (e.g. ``"1GbE"``, ``"USB"``). Defaults to
            :data:`instruments.config.MFLI_INTERFACE`.
            **Confirm on real hardware** -- see the note on that constant.
        allow_version_mismatch: If True, connect even if the data server
            is running a different LabOne version than this client.
        daq_server: An existing :class:`zhinst.core.ziDAQServer` instance
            to reuse instead of creating a new one, e.g. to share one
            server connection across multiple devices, or to inject a
            fake/mocked server in tests.
    """

    error_cls = MFLIError

    def __init__(
        self,
        device_id: str = config.MFLI_DEVICE_ID,
        *,
        host: str = config.MFLI_HOST,
        port: int = config.MFLI_PORT,
        api_level: int = config.MFLI_API_LEVEL,
        interface: str = config.MFLI_INTERFACE,
        allow_version_mismatch: bool = True,
        daq_server: Optional[zhinst.core.ziDAQServer] = None,
    ) -> None:
        self.device_id = device_id
        self.host = host
        self.port = port
        self.api_level = api_level
        self.interface = interface
        self.allow_version_mismatch = allow_version_mismatch
        self._daq = daq_server
        self._owns_daq = daq_server is None
        self._device_connected = False

    @property
    def is_connected(self) -> bool:
        """Whether the data server connection and device attachment are both up."""
        return self._daq is not None and self._device_connected

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Connect to the LabOne data server and attach the MFLI device.

        Raises:
            MFLIError: If connecting to the data server or attaching the
                device fails.
        """
        if self.is_connected:
            logger.debug("MFLI %s already connected", self.device_id)
            return

        try:
            if self._daq is None:
                self._daq = zhinst.core.ziDAQServer(
                    self.host,
                    self.port,
                    self.api_level,
                    allow_version_mismatch=self.allow_version_mismatch,
                )
            # connectDevice() is a no-op if the device is already attached,
            # so this is safe to call even if it was connected out-of-band
            # (e.g. via the LabOne UI).
            self._daq.connectDevice(self.device_id, self.interface)
        except zi_errors.CoreError as exc:
            raise MFLIError(
                f"Failed to connect to MFLI {self.device_id!r} via "
                f"{self.host}:{self.port} (interface={self.interface!r}): {exc}"
            ) from exc

        self._device_connected = True
        logger.info("Connected to MFLI %s via %s:%s", self.device_id, self.host, self.port)

    def disconnect(self) -> None:
        """Detach the device and, if owned, close the data server connection."""
        if self._daq is not None and self._device_connected:
            try:
                self._daq.disconnectDevice(self.device_id)
            except zi_errors.CoreError as exc:
                logger.warning("Error disconnecting MFLI %s: %s", self.device_id, exc)
            self._device_connected = False

        if self._owns_daq and self._daq is not None:
            self._daq.disconnect()
            self._daq = None

        logger.info("Disconnected from MFLI %s", self.device_id)

    def __enter__(self) -> "MFLI":
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        self.disconnect()

    def _require_daq(self) -> zhinst.core.ziDAQServer:
        """Return the connected ziDAQServer, raising if not connected.

        Raises:
            MFLIError: If :meth:`connect` has not been called yet.
        """
        if not self.is_connected:
            raise MFLIError("MFLI is not connected; call connect() first.")
        assert self._daq is not None
        return self._daq

    def _node(self, *parts: str) -> str:
        """Build a full node path for this device, e.g. ``demods/0/enable``."""
        return "/" + "/".join((self.device_id, *parts))

    def _set(self, path: str, value: object) -> None:
        """Set a single node value, wrapping low-level zhinst errors.

        Raises:
            MFLIError: If the underlying ``set`` call fails.
        """
        daq = self._require_daq()
        try:
            daq.set(path, value)
        except zi_errors.CoreError as exc:
            raise MFLIError(f"Failed to set {path!r} to {value!r}: {exc}") from exc

    def _get_sample(self, path: str) -> dict[str, np.ndarray]:
        """Read a single demodulator sample, wrapping low-level zhinst errors.

        Raises:
            MFLIError: If the underlying ``getSample`` call fails.
        """
        daq = self._require_daq()
        try:
            return daq.getSample(path)
        except zi_errors.CoreError as exc:
            raise MFLIError(f"Failed to read sample from {path!r}: {exc}") from exc

    # ------------------------------------------------------------------
    # Demodulator / input / reference configuration
    #
    # Defaults below match the values written in
    # code_collection/MFLI_test.ipynb. CONFIRM ON REAL HARDWARE: they were
    # never validated against the actual apparatus from this environment,
    # since no MFLI is connected here.
    # ------------------------------------------------------------------

    def configure_input(
        self, input_channel: int = 0, *, range_v: float = 3.0, autorange: bool = True
    ) -> None:
        """Configure a signal input's voltage range.

        Args:
            input_channel: Signal input index (0-based).
            range_v: Input range in volts. CONFIRM ON REAL HARDWARE -- 3.0 V
                is the value used in the legacy notebook; the correct range
                depends on the lock-in signal's actual amplitude.
            autorange: Whether to enable automatic range adjustment.
        """
        self._set(self._node("sigins", str(input_channel), "range"), range_v)
        self._set(self._node("sigins", str(input_channel), "autorange"), int(autorange))

    def configure_demod(
        self,
        demod_index: int = 0,
        *,
        enable: bool = True,
        filter_order: int = 6,
        time_constant: float = 0.1,
    ) -> None:
        """Configure a demodulator's filter and enable state.

        Args:
            demod_index: Demodulator index (0-based).
            enable: Whether to enable this demodulator.
            filter_order: Low-pass filter order. CONFIRM ON REAL HARDWARE --
                6 is the value used in the legacy notebook; higher orders
                give steeper roll-off at the cost of a slower effective
                response.
            time_constant: Low-pass filter time constant in seconds.
                CONFIRM ON REAL HARDWARE -- 0.1 s is the legacy notebook's
                value; it should be chosen relative to the pulse
                repetition period so the filter has settled by the time a
                sample is read.
        """
        self._set(self._node("demods", str(demod_index), "enable"), int(enable))
        self._set(self._node("demods", str(demod_index), "order"), filter_order)
        self._set(self._node("demods", str(demod_index), "timeconstant"), time_constant)

    def configure_external_reference(self, ref_index: int = 0, *, enable: bool = True) -> None:
        """Enable or disable locking an internal oscillator to an external reference.

        In this experiment, the external reference is expected to be
        synchronized to the QDac trigger/gate signal so the lock-in
        demodulates in phase with the pulsed measurement. CONFIRM ON REAL
        HARDWARE -- the exact reference wiring/oscillator assignment was
        not verified from this environment.

        Args:
            ref_index: External reference index (0-based).
            enable: Whether to enable the external reference.
        """
        self._set(self._node("extrefs", str(ref_index), "enable"), int(enable))

    def configure_signal_output_autorange(
        self, output_index: int = 0, *, enable: bool = True
    ) -> None:
        """Enable or disable automatic ranging on a signal output.

        Args:
            output_index: Signal output index (0-based).
            enable: Whether to enable automatic output ranging.
        """
        self._set(self._node("sigouts", str(output_index), "autorange"), int(enable))

    def configure_aux_output_demod_select(self, aux_channel: int, demod_index: int = 0) -> None:
        """Route a demodulator's output to an auxiliary output channel.

        The legacy notebook routes demodulator 0 to aux outputs 2 and 3
        (e.g. for external monitoring). Call this once per aux channel
        that needs to be routed.

        Args:
            aux_channel: Auxiliary output channel index (0-based).
            demod_index: Demodulator index to route to this aux output.
        """
        self._set(self._node("auxouts", str(aux_channel), "demodselect"), demod_index)

    def auto_phase_adjust(self, demod_index: int = 0) -> None:
        """Trigger the instrument's automatic phase-adjust routine.

        Unlike the other ``configure_*`` methods, this is a one-shot
        action: writing this node starts an automatic adjustment that the
        instrument itself resets when done, rather than a persistent
        setting.

        Args:
            demod_index: Demodulator index to phase-adjust.
        """
        self._set(self._node("demods", str(demod_index), "phaseadjust"), 1)

    def apply_default_configuration(self) -> None:
        """Apply the full set of defaults used in the legacy MFLI notebook.

        Convenience entry point that reproduces
        ``code_collection/MFLI_test.ipynb``'s configuration in one call:
        input 0 ranged at 3.0 V with autorange, demodulator 0 enabled
        (order 6, time constant 0.1 s) routed to aux outputs 2 and 3,
        external reference 0 enabled, and signal output 0 autoranged.
        CONFIRM ON REAL HARDWARE before relying on these values.
        """
        self.configure_aux_output_demod_select(2, demod_index=0)
        self.configure_aux_output_demod_select(3, demod_index=0)
        self.configure_input(0, range_v=3.0, autorange=True)
        self.configure_demod(0, enable=True, filter_order=6, time_constant=0.1)
        self.configure_external_reference(0, enable=True)
        self.configure_signal_output_autorange(0, enable=True)

    # ------------------------------------------------------------------
    # Readout
    # ------------------------------------------------------------------

    def read_sample(self, demod_index: int = 0) -> dict[str, float]:
        """Read one instantaneous demodulator sample.

        ``getSample`` returns each component (X, Y, ...) as a small
        ``numpy`` array rather than a single scalar; this averages that
        array down to one value per component.

        Args:
            demod_index: Demodulator index to read.

        Returns:
            Dict with keys ``"x"``, ``"y"`` (both in volts), ``"r"``
            (magnitude, in volts), and ``"phase"`` (radians).
        """
        sample = self._get_sample(self._node("demods", str(demod_index), "sample"))
        x = float(np.mean(np.asarray(sample["x"])))
        y = float(np.mean(np.asarray(sample["y"])))
        return {"x": x, "y": y, "r": float(np.hypot(x, y)), "phase": float(np.arctan2(y, x))}

    def read_averaged_sample(
        self, demod_index: int = 0, *, n_samples: int = 10, delay: float = 0.05
    ) -> dict[str, float | int]:
        """Read several samples and average X/Y to reduce noise.

        This is the intended readout for the sweep: rather than trusting a
        single instantaneous ``getSample`` call, X and Y are each averaged
        over ``n_samples`` reads before deriving R and phase, giving a
        lower-noise estimate of the optical-intensity signal at each pulse
        voltage step. The spread across those ``n_samples`` reads is also
        reported, to help spot noisy signal conditions.

        Args:
            demod_index: Demodulator index to read.
            n_samples: Number of samples to average.
            delay: Seconds to wait between successive reads.

        Returns:
            Dict with keys ``"x"``, ``"y"``, ``"r"``, ``"phase"`` (as in
            :meth:`read_sample`), ``"x_std"``, ``"y_std"``, ``"r_std"``
            (sample standard deviation, ``ddof=1``, across the
            ``n_samples`` reads; ``NaN`` if ``n_samples == 1``), and
            ``"n_samples"``. ``r_std`` is computed empirically from the
            per-sample ``R = hypot(x, y)`` values, not propagated
            analytically from ``x_std``/``y_std``. There is no
            ``"phase_std"``: phase is a circular quantity and a plain
            linear std would be misleading near the +/-pi wraparound.

        Raises:
            MFLIError: If ``n_samples`` is not positive.
        """
        if n_samples <= 0:
            raise MFLIError("n_samples must be positive")

        x_values = []
        y_values = []
        for _ in range(n_samples):
            sample = self.read_sample(demod_index)
            x_values.append(sample["x"])
            y_values.append(sample["y"])
            if delay:
                time.sleep(delay)

        x_array = np.asarray(x_values)
        y_array = np.asarray(y_values)
        r_array = np.hypot(x_array, y_array)

        x_mean = float(np.mean(x_array))
        y_mean = float(np.mean(y_array))

        if n_samples > 1:
            x_std = float(np.std(x_array, ddof=1))
            y_std = float(np.std(y_array, ddof=1))
            r_std = float(np.std(r_array, ddof=1))
        else:
            x_std = y_std = r_std = float("nan")

        return {
            "x": x_mean,
            "y": y_mean,
            "r": float(np.hypot(x_mean, y_mean)),
            "phase": float(np.arctan2(y_mean, x_mean)),
            "x_std": x_std,
            "y_std": y_std,
            "r_std": r_std,
            "n_samples": n_samples,
        }
