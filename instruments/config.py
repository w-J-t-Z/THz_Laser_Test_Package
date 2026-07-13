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

DEFAULT_SERIES_RESISTANCE_OHM = 50.0
"""Default known series/shunt resistance (R0) used to derive DUT current
from two scope channel voltages, in ohms."""

DEFAULT_CHANNEL_ROLES = {"voltage": 1, "current": 2, "trigger": 3}
"""Default Rigol channel-to-role mapping for the pulse-voltage sweep.

"voltage" is the channel whose fitted plateau value is reported as the DUT
voltage. "current" is the channel read alongside "voltage" to derive DUT
current via Ohm's law across the known series resistor:
``current = (V[current] - V[voltage]) / series_resistance_ohm``. "trigger"
is the channel the scope's edge trigger is configured from. Override the
channel arguments on :func:`measurement.sweep.run_voltage_sweep` if the
physical wiring differs."""

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

MFLI_INTERFACE = "1GbE"
"""Default device interface passed to connectDevice(). CONFIRM ON REAL
HARDWARE: the legacy notebook never called connectDevice() explicitly (the
device may have already been connected via the LabOne UI), so this
interface string ("1GbE" vs. "USB", etc.) has not actually been exercised
against the physical instrument."""
