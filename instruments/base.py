"""Shared base classes and interfaces for lab instrument control.

This module defines the common connect/write/query/close pattern used by the
VISA-backed instruments (QDac, Avtech, Rigol) and a structural protocol that
all instruments -- VISA-backed or not (e.g. the MFLI, which talks to hardware
over the zhinst API instead of pyvisa) -- can be type-checked against.
"""

from __future__ import annotations

import logging
from types import TracebackType
from typing import Optional, Protocol, runtime_checkable

import pyvisa

logger = logging.getLogger(__name__)


class InstrumentError(Exception):
    """Base exception for all instrument-related errors in this package."""


@runtime_checkable
class InstrumentProtocol(Protocol):
    """Structural interface every instrument class must satisfy.

    This is a :class:`typing.Protocol` rather than a base class so that
    instruments with fundamentally different transports (e.g. the MFLI,
    which uses ``zhinst`` instead of ``pyvisa``) can implement the same
    lifecycle interface without being forced into a VISA-shaped inheritance
    hierarchy. Orchestration code (``measurement/sweep.py``) can type-hint
    against this protocol to treat all instruments interchangeably.
    """

    def connect(self) -> None:
        """Open the connection to the instrument."""
        ...

    def disconnect(self) -> None:
        """Close the connection to the instrument."""
        ...

    def __enter__(self) -> "InstrumentProtocol":
        ...

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        ...


class VisaInstrument:
    """Common connect/write/query/close pattern for VISA-backed instruments.

    Subclasses (QDac, Avtech, Rigol) should set the class attribute
    ``error_cls`` to their own :class:`InstrumentError` subclass, and build
    their public API on top of the protected :meth:`_write` and
    :meth:`_query` helpers so that raw ``pyvisa`` exceptions never leak past
    this class.

    Args:
        resource: VISA resource string identifying the instrument
            (e.g. ``"ASRL4::INSTR"`` or ``"GPIB0::9::INSTR"``).
        resource_manager: An existing :class:`pyvisa.ResourceManager` to use
            instead of creating a new one. Passing one in makes it easy to
            share a manager across instruments or to inject a mocked/fake
            manager in tests. If omitted, a new manager is created on
            :meth:`connect` and closed on :meth:`disconnect`.
        timeout_ms: VISA I/O timeout in milliseconds, applied after opening
            the resource.
    """

    error_cls: type[InstrumentError] = InstrumentError

    def __init__(
        self,
        resource: str,
        *,
        resource_manager: Optional[pyvisa.ResourceManager] = None,
        timeout_ms: int = 5000,
    ) -> None:
        self.resource = resource
        self.timeout_ms = timeout_ms
        self._resource_manager = resource_manager
        self._owns_resource_manager = resource_manager is None
        self._session: Optional[pyvisa.resources.MessageBasedResource] = None

    @property
    def is_connected(self) -> bool:
        """Whether the VISA session is currently open."""
        return self._session is not None

    def connect(self) -> None:
        """Open the VISA resource manager (if needed) and the instrument session.

        Raises:
            InstrumentError: If the resource manager or resource cannot be
                opened.
        """
        if self.is_connected:
            logger.debug("%s already connected to %s", type(self).__name__, self.resource)
            return

        try:
            if self._resource_manager is None:
                self._resource_manager = pyvisa.ResourceManager()
            session = self._resource_manager.open_resource(self.resource)
        except pyvisa.errors.VisaIOError as exc:
            raise self.error_cls(
                f"Failed to open VISA resource {self.resource!r}: {exc}"
            ) from exc

        session.timeout = self.timeout_ms
        self._session = session
        logger.info("Connected to %s at %s", type(self).__name__, self.resource)

    def disconnect(self) -> None:
        """Close the instrument session and, if owned, the resource manager."""
        if self._session is not None:
            try:
                self._session.close()
            except pyvisa.errors.VisaIOError as exc:
                logger.warning("Error closing session for %s: %s", self.resource, exc)
            finally:
                self._session = None

        if self._owns_resource_manager and self._resource_manager is not None:
            self._resource_manager.close()
            self._resource_manager = None

        logger.info("Disconnected from %s at %s", type(self).__name__, self.resource)

    def __enter__(self) -> "VisaInstrument":
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        self.disconnect()

    def _require_session(self) -> pyvisa.resources.MessageBasedResource:
        """Return the open session, raising if not connected.

        Raises:
            InstrumentError: If :meth:`connect` has not been called yet.
        """
        if self._session is None:
            raise self.error_cls(
                f"{type(self).__name__} is not connected; call connect() first."
            )
        return self._session

    def _write(self, cmd: str) -> None:
        """Send a SCPI command, wrapping low-level VISA errors.

        Args:
            cmd: The SCPI command string to write.

        Raises:
            InstrumentError: If the underlying VISA write fails.
        """
        session = self._require_session()
        try:
            session.write(cmd)
        except pyvisa.errors.VisaIOError as exc:
            raise self.error_cls(f"Write failed for command {cmd!r}: {exc}") from exc

    def _query(self, cmd: str) -> str:
        """Send a SCPI query and return the (stripped) response.

        Args:
            cmd: The SCPI query string to send.

        Returns:
            The instrument's response with surrounding whitespace stripped.

        Raises:
            InstrumentError: If the underlying VISA query fails.
        """
        session = self._require_session()
        try:
            return session.query(cmd).strip()
        except pyvisa.errors.VisaIOError as exc:
            raise self.error_cls(f"Query failed for command {cmd!r}: {exc}") from exc

    def _read_raw(self) -> bytes:
        """Read a raw (binary) response, wrapping low-level VISA errors.

        Returns:
            The raw bytes read from the instrument.

        Raises:
            InstrumentError: If the underlying VISA read fails.
        """
        session = self._require_session()
        try:
            return session.read_raw()
        except pyvisa.errors.VisaIOError as exc:
            raise self.error_cls(f"Raw read failed: {exc}") from exc

    def _write_binary_values(self, cmd: str, values: object) -> None:
        """Send a SCPI command followed by binary-encoded values.

        Args:
            cmd: The SCPI command string prefix.
            values: Values to encode and append, as accepted by
                ``pyvisa``'s ``write_binary_values``.

        Raises:
            InstrumentError: If the underlying VISA write fails.
        """
        session = self._require_session()
        try:
            session.write_binary_values(cmd, values)
        except pyvisa.errors.VisaIOError as exc:
            raise self.error_cls(
                f"Binary write failed for command {cmd!r}: {exc}"
            ) from exc
