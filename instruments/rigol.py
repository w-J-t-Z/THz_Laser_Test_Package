"""Rigol oscilloscope control class.

The Rigol scope reads back the device-under-test's voltage waveform during
each pulse. There is no separate current probe in this setup: current is
derived from the voltage dropped across a known series/shunt resistor,
measured across two channels. See the top-level CLAUDE.md for the overall
experiment layout.
"""

from __future__ import annotations

import logging
import time
from typing import Optional, Sequence

import numpy as np
import pyvisa
from sklearn.mixture import GaussianMixture

from . import config
from .base import InstrumentError, VisaInstrument

logger = logging.getLogger(__name__)


class RigolError(InstrumentError):
    """Raised for Rigol-specific communication or command errors."""


def _fit_two_gaussians(
    data: np.ndarray,
    *,
    n_init: int = 10,
    random_state: int = 42,
    robust_trim: bool = False,
    trim_quantile: float = 0.01,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fit a 2-component Gaussian Mixture Model to 1D waveform samples.

    Waveforms in this setup are treated as a mixture of two voltage levels
    (a baseline and the pulse plateau) plus a small amount of noise; the
    GMM's expectation-maximization fit recovers both levels' means, standard
    deviations, and mixing weights. Ported from
    ``code_collection/fit_two_gaussians.py``.

    Args:
        data: 1D array of waveform sample values.
        n_init: Number of random GMM initializations; larger values reduce
            the risk of converging to a local optimum, at the cost of
            speed.
        random_state: Random seed for reproducible fits.
        robust_trim: Whether to remove outlier/noise samples at both tails
            before fitting.
        trim_quantile: Fraction trimmed from each tail when
            ``robust_trim`` is True.

    Returns:
        ``(means, stds, weights)``, each a length-2 array describing the
        two fitted components, sorted ascending by mean.
    """
    values = np.asarray(data, dtype=float).ravel()
    values = values[~np.isnan(values)]

    if robust_trim:
        lo, hi = np.quantile(values, [trim_quantile, 1 - trim_quantile])
        values = values[(values >= lo) & (values <= hi)]

    gmm = GaussianMixture(
        n_components=2,
        n_init=n_init,
        random_state=random_state,
        covariance_type="full",
    )
    gmm.fit(values.reshape(-1, 1))

    means = gmm.means_.ravel()
    stds = np.sqrt(gmm.covariances_.ravel())
    weights = gmm.weights_.ravel()

    order = np.argsort(means)
    return means[order], stds[order], weights[order]


class Rigol(VisaInstrument):
    """Control class for a Rigol digital oscilloscope.

    Args:
        resource: VISA resource string for the scope. If omitted (the
            default), the single USB VISA resource is auto-detected when
            :meth:`connect` is called, mirroring the working notebooks.
        resource_manager: An existing :class:`pyvisa.ResourceManager` to
            reuse instead of creating a new one.
        timeout_ms: VISA I/O timeout in milliseconds. Waveform transfers
            are slow, so this defaults higher than the other instruments.
        chunk_size: VISA read chunk size in bytes; must be large enough to
            hold one full waveform transfer.
    """

    error_cls = RigolError

    _WAVEFORM_HEADER_BYTES = 12

    def __init__(
        self,
        resource: Optional[str] = None,
        *,
        resource_manager: Optional[pyvisa.ResourceManager] = None,
        timeout_ms: int = 20000,
        chunk_size: int = 1024000,
    ) -> None:
        super().__init__(
            resource, resource_manager=resource_manager, timeout_ms=timeout_ms
        )
        self._chunk_size = chunk_size

    def connect(self) -> None:
        """Auto-detect the scope's VISA resource (if not given) and connect.

        Raises:
            RigolError: If no resource was given and auto-detection does
                not find exactly one USB VISA resource, or if the
                connection itself fails.
        """
        if self.resource is None:
            self.resource = self._auto_detect_usb_resource()
        super().connect()
        self._require_session().chunk_size = self._chunk_size

    def _auto_detect_usb_resource(self) -> str:
        """Find the single USB VISA resource among all available resources.

        Returns:
            The matching VISA resource string.

        Raises:
            RigolError: If zero or more than one USB resource is found.
        """
        if self._resource_manager is None:
            self._resource_manager = pyvisa.ResourceManager()
        resources = self._resource_manager.list_resources()
        usb_resources = [r for r in resources if "USB" in r]
        if len(usb_resources) != 1:
            raise RigolError(
                f"Expected exactly one USB VISA resource, found "
                f"{usb_resources!r} among {resources!r}"
            )
        return usb_resources[0]

    # ------------------------------------------------------------------
    # Timebase / channel / trigger configuration
    # ------------------------------------------------------------------

    def configure_timebase(self, scale: float, *, offset: Optional[float] = None) -> None:
        """Set the horizontal timebase scale and, optionally, offset.

        Args:
            scale: Timebase scale in seconds/division.
            offset: Timebase offset in seconds, if given.
        """
        self._write(f":TIMEBASE:SCALE {scale}")
        if offset is not None:
            self._write(f":TIM:OFFS {offset}")

    def configure_channel(self, channel: int, scale: float) -> None:
        """Set a channel's vertical scale.

        Args:
            channel: Channel number.
            scale: Vertical scale in volts/division.
        """
        self._write(f":CHANNEL{channel}:SCALE {scale}")

    def configure_trigger(
        self, source_channel: int, *, level: float, slope: str = "POSITIVE"
    ) -> None:
        """Configure edge triggering from a channel.

        Args:
            source_channel: Channel number to trigger from.
            level: Trigger level in volts.
            slope: ``"POSITIVE"`` or ``"NEGATIVE"`` (case insensitive).

        Raises:
            RigolError: If ``slope`` is not recognized.
        """
        slope = slope.upper()
        if slope not in {"POSITIVE", "NEGATIVE"}:
            raise RigolError(f"Invalid trigger slope {slope!r}")
        self._write(f":TRIGger:EDGE:SLOPe {slope}")
        self._write(f":TRIGger:EDGE:LEVel {level}")
        self._write(f":TRIGger:EDGE:SOURce CHANnel{source_channel}")

    # ------------------------------------------------------------------
    # Waveform acquisition
    # ------------------------------------------------------------------

    def get_waveform(self, channel: int) -> tuple[np.ndarray, np.ndarray]:
        """Read one channel's most recent waveform as ``(time_s, voltage_v)``.

        Stops acquisition first so the waveform buffer does not change
        mid-read, then downloads the raw waveform bytes and converts them
        to volts using this lab's calibrated linear mapping (see
        ``code_collection/QCL_IVL_sweep.ipynb``).

        Args:
            channel: Channel number to read.

        Returns:
            ``(time_s, voltage_v)`` arrays of equal length.

        Raises:
            RigolError: If any underlying VISA call fails.
        """
        self._write(":STOP")

        timescale = float(self._query(":TIM:SCAL?"))
        try:
            timeoffset = float(self._query(":TIM:OFFS?"))
        except (RigolError, ValueError):
            timeoffset = 0.0

        voltscale = float(self._query(f":CHAN{channel}:SCAL?"))
        try:
            voltoffset = float(self._query(f":CHAN{channel}:OFFS?"))
        except (RigolError, ValueError):
            voltoffset = 0.0

        self._write(f":WAV:SOUR CHAN{channel}")
        self._write(":WAV:DATA?")
        raw = self._read_raw()[self._WAVEFORM_HEADER_BYTES :]
        raw_samples = np.frombuffer(raw, dtype=np.uint8)

        voltage = (raw_samples.astype(float) - 127.685) * 0.03408 * voltscale - voltoffset
        time_axis = np.linspace(
            timeoffset - 5 * timescale, timeoffset + 5 * timescale, num=len(voltage)
        )
        return time_axis[:-1], voltage[:-1]

    def acquire_single_shot(
        self, channels: Sequence[int], *, settle_time: float = 1.0
    ) -> dict[int, tuple[np.ndarray, np.ndarray]]:
        """Trigger one single-shot acquisition and read back given channels.

        Mirrors the ``:RUN`` / ``:SINGLE`` / ``:STOP`` timing used in the
        working notebooks.

        Args:
            channels: Channel numbers to read after the shot.
            settle_time: Seconds to wait after arming the single-shot
                trigger, and again after reading all channels, to let the
                acquisition and downstream instruments settle.

        Returns:
            Mapping from channel number to ``(time_s, voltage_v)``.
        """
        self._write(":RUN")
        self._write(":SINGLE")
        time.sleep(settle_time)
        self._write(":STOP")

        waveforms = {channel: self.get_waveform(channel) for channel in channels}
        time.sleep(settle_time)
        return waveforms

    # ------------------------------------------------------------------
    # GMM-based plateau extraction and derived current measurement
    # ------------------------------------------------------------------

    def extract_plateau_voltage(
        self,
        voltage: np.ndarray,
        *,
        robust_trim: bool = False,
        trim_quantile: float = 0.01,
        n_init: int = 10,
        random_state: int = 42,
    ) -> float:
        """Extract the pulse-plateau voltage from a waveform via a 2-Gaussian fit.

        A waveform is modeled as a mixture of two levels -- the baseline
        and the pulse plateau -- plus a small amount of noise; the higher
        of the two fitted Gaussian means is returned as the plateau value.
        This is the GMM approach used in
        ``code_collection/QCL_IVL_sweep.ipynb``.

        Args:
            voltage: 1D array of waveform samples in volts, as returned by
                :meth:`get_waveform`.
            robust_trim: Whether to remove outlier samples at both tails
                before fitting.
            trim_quantile: Fraction trimmed from each tail when
                ``robust_trim`` is True.
            n_init: Number of random GMM initializations.
            random_state: Random seed for reproducible fits.

        Returns:
            The higher of the two fitted Gaussian component means, in
            volts.
        """
        means, _stds, _weights = _fit_two_gaussians(
            voltage,
            n_init=n_init,
            random_state=random_state,
            robust_trim=robust_trim,
            trim_quantile=trim_quantile,
        )
        return float(means[-1])

    def measure_plateau_voltage(
        self,
        channel: int,
        *,
        settle_time: float = 1.0,
        robust_trim: bool = False,
    ) -> float:
        """Acquire one single-shot pulse and extract a channel's plateau voltage.

        Args:
            channel: Channel to acquire and fit.
            settle_time: Passed through to :meth:`acquire_single_shot`.
            robust_trim: Passed through to :meth:`extract_plateau_voltage`.

        Returns:
            The channel's fitted plateau voltage, in volts.
        """
        waveforms = self.acquire_single_shot([channel], settle_time=settle_time)
        _time_axis, voltage = waveforms[channel]
        return self.extract_plateau_voltage(voltage, robust_trim=robust_trim)

    def measure_series_resistor_current(
        self,
        *,
        upstream_channel: int,
        downstream_channel: int,
        series_resistance_ohm: float = config.DEFAULT_SERIES_RESISTANCE_OHM,
        settle_time: float = 1.0,
        robust_trim: bool = False,
    ) -> float:
        """Derive DUT current from the voltage dropped across a known series resistor.

        This setup has no separate current probe: current is inferred from
        the difference between two channel voltages measured across a
        known series/shunt resistor, following the approach in
        ``code_collection/QCL_IVL_sweep.ipynb``
        (``current = (V_upstream - V_downstream) / series_resistance_ohm``).

        Args:
            upstream_channel: Channel on the side of the resistor closer
                to the pulse source.
            downstream_channel: Channel on the side of the resistor closer
                to the DUT.
            series_resistance_ohm: Known series/shunt resistance in ohms
                (``R0`` in the notebook; defaults to the lab's usual
                50 ohm, see :data:`instruments.config.DEFAULT_SERIES_RESISTANCE_OHM`).
            settle_time: Passed through to :meth:`acquire_single_shot`.
            robust_trim: Passed through to :meth:`extract_plateau_voltage`.

        Returns:
            The derived current in amps.
        """
        waveforms = self.acquire_single_shot(
            [upstream_channel, downstream_channel], settle_time=settle_time
        )
        upstream_voltage = self.extract_plateau_voltage(
            waveforms[upstream_channel][1], robust_trim=robust_trim
        )
        downstream_voltage = self.extract_plateau_voltage(
            waveforms[downstream_channel][1], robust_trim=robust_trim
        )
        return (upstream_voltage - downstream_voltage) / series_resistance_ohm
