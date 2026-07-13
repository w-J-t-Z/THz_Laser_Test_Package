"""Default configuration values for lab instruments.

Every instrument class also accepts an explicit resource/address argument in
its constructor to override these when the physical setup differs from the
values below.
"""

QDAC_VISA_ADDRESS = "ASRL4::INSTR"
"""Default QDac VISA resource address (serial connection)."""

QDAC_BAUD_RATE = 921600
"""Default serial baud rate used for QDac ASRL connections."""
