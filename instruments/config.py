"""Default configuration values for lab instruments.

Every instrument class also accepts an explicit resource/address argument in
its constructor to override these when the physical setup differs from the
values below.
"""

QDAC_VISA_ADDRESS = "ASRL4::INSTR"
"""Default QDac VISA resource address (serial connection)."""

QDAC_BAUD_RATE = 921600
"""Default serial baud rate used for QDac ASRL connections."""

AVTECH_VISA_ADDRESS = "GPIB0::9::INSTR"
"""Default Avtech pulse generator VISA resource address (GPIB connection)."""

RIGOL_VISA_ADDRESS = "USB0::0x1AB1::0x0610::HDO4A244301030::INSTR"
"""Default Rigol oscilloscope VISA resource address, confirmed against the
real instrument. Pass ``resource=None`` to ``Rigol()`` to auto-detect the
USB VISA resource instead (see ``Rigol.connect``)."""

DEFAULT_SERIES_RESISTANCE_OHM = 50.0
"""Default known series/shunt resistance (R0) used to derive DUT current
from two scope channel voltages, in ohms."""

DEFAULT_CHANNEL_ROLES = {"voltage": 2, "current": 1, "trigger": 3}
"""Default Rigol channel-to-role mapping for the pulse-voltage sweep.

"voltage" is the channel whose fitted plateau value is reported as the DUT
voltage. "current" is the channel read alongside "voltage" to derive DUT
current via Ohm's law across the known series resistor:
``current = (V[current] - V[voltage]) / series_resistance_ohm``. "trigger"
is the channel the scope's edge trigger is configured from. Override the
channel arguments on :func:`measurement.sweep.run_voltage_sweep` if the
physical wiring differs."""

DEFAULT_CHANNEL_OFFSETS_V = {"voltage": 0.0, "current": 0.0, "trigger": 0.0}
"""Default per-role vertical offset (volts) passed to
``Rigol.configure_channel``'s ``offset`` argument, keyed the same way as
:data:`DEFAULT_CHANNEL_ROLES`. All zero by default; adjust per-run (e.g. in
``05_full_sweep_demo.ipynb``) if a channel's signal needs to be recentered
on the scope display."""

# MFLI lock-in amplifier defaults.
# Pulled directly from code_collection/MFLI_test.ipynb. That notebook has
# no reusable wrapper (only a short vendor-example-style script), so these
# values are carried over as-is. CONFIRM ON REAL HARDWARE: the host/device
# ID are specific to this lab's MFLI unit and network and may have changed.
MFLI_HOST = "192.168.118.186"
"""Default LabOne data server host address for the MFLI."""

MFLI_PORT = 8004
"""Default LabOne data server port."""

MFLI_API_LEVEL = 6
"""Default ziDAQServer API level used in the legacy MFLI notebook."""

MFLI_DEVICE_ID = "dev7598"
"""Default MFLI device serial as seen in the legacy MFLI notebook."""

MFLI_INTERFACE = "PCIe"
"""Default device interface passed to connectDevice(). Confirmed working
against the real instrument."""
