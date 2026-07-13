# QCL/THz Laser Test Package

Control software for a lab setup that characterizes a QCL/THz laser device
by sweeping a voltage pulse and simultaneously recording the device's
electrical response (voltage/current) and its optical response (lock-in
signal).

## Physical setup

- **QDac** -- multi-channel precision DC/trigger source. Here it is used
  purely as a trigger/gate signal generator that synchronizes the Avtech
  pulse generator and the MFLI lock-in amplifier; it does not itself
  supply the swept pulse voltage.
- **Avtech pulse generator** -- supplies the voltage pulse that powers the
  laser device under test. Pulse amplitude is the swept parameter.
- **Rigol oscilloscope** -- reads back the device's voltage waveform
  during each pulse. There is no separate current probe: current is
  derived from the voltage dropped across a known series/shunt resistor,
  measured across two channels.
- **Zurich Instruments MFLI lock-in amplifier** -- reads the lock-in
  signal, which corresponds to the optical intensity emitted by the
  device.

The experiment sweeps the pulse voltage and, at each step, acquires
(voltage, current, lock-in signal), then plots the resulting I-V and
optical-intensity-vs-voltage curves.

## Directory structure

```
instruments/
    base.py            # InstrumentError, InstrumentProtocol, VisaInstrument
    config.py           # default VISA addresses, channel roles, R0, MFLI defaults
    qdac.py             # QDac: trigger/gate signal generator
    avtech.py           # Avtech: swept pulse voltage source
    rigol.py            # Rigol: scope readout + GMM plateau extraction
    mfli.py             # MFLI: lock-in configuration + averaged readout
measurement/
    sweep.py            # run_voltage_sweep orchestration
    data_io.py          # save/load sweep results (CSV, optional HDF5)
    plotting.py         # I-V and optical-intensity-vs-voltage plots
notebooks/
    01_test_qdac.ipynb
    02_test_avtech.ipynb
    03_test_rigol.ipynb
    04_test_mfli.ipynb
    05_full_sweep_demo.ipynb
code_collection/        # legacy scripts, read-only reference, not modified
requirements.txt
CLAUDE.md                # persistent instructions/context for AI-assisted work
README.md
```

`code_collection/` holds the original, unorganized scripts this package was
refactored from. It is gitignored and untouched -- treat it as read-only
reference material, not part of the current codebase.

## Setup

This project uses a local virtual environment (`.venv/`) and a plain
`requirements.txt`:

```bash
python -m venv .venv
.venv/Scripts/activate      # Windows
pip install -r requirements.txt
```

HDF5 support in `measurement.data_io` is optional and needs `h5py`
(`pip install h5py`); everything else, including CSV support, works with
the base `requirements.txt`.

## Running the notebooks

Launch Jupyter from the project root (or from within `notebooks/` -- each
notebook adds the project root to `sys.path` automatically):

```bash
jupyter lab
```

- **`01_test_qdac.ipynb`** / **`02_test_avtech.ipynb`** /
  **`03_test_rigol.ipynb`** / **`04_test_mfli.ipynb`** each instantiate one
  instrument class, connect, and exercise its main methods. Every
  hardware-touching cell is wrapped in `try`/`except`, so these run
  cleanly end-to-end and print a clear "hardware not available" message
  on a machine with no instruments connected -- including this
  development environment.
- **`05_full_sweep_demo.ipynb`** demonstrates the full workflow: configure
  all four instruments, sweep the pulse voltage with
  `measurement.sweep.run_voltage_sweep`, save the result with
  `measurement.data_io`, and plot it with `measurement.plotting`. If any
  instrument is unavailable, it falls back to clearly-labeled synthetic
  `dummy_data` so the saving/plotting logic can still be demonstrated.

On the lab computer, with real instruments connected, the same cells
should run against actual hardware without any changes.

## Basic usage outside notebooks

```python
from instruments.qdac import QDac
from instruments.avtech import Avtech
from instruments.rigol import Rigol
from instruments.mfli import MFLI
from measurement.sweep import run_voltage_sweep, SweepConfig
from measurement import data_io, plotting
import numpy as np

with QDac() as qdac, Avtech() as avtech, Rigol() as rigol, MFLI() as mfli:
    # ... configure each instrument (trigger/gate channels, pulse trigger
    # source, scope timebase/channels/trigger, lock-in demodulator) ...
    df = run_voltage_sweep(
        avtech, rigol, mfli, qdac,
        voltages=np.linspace(2.0, 10.0, 5),
        sweep_config=SweepConfig(idle_voltage=5.0),
    )

data_io.save_csv(df, "data/sweep.csv")
plotting.plot_iv_curve(df, show=True)
plotting.plot_intensity_curve(df, show=True)
```

## Hardware status

No real instruments are connected to this development machine. Every
class in `instruments/` was verified with unit-level checks (synthetic
data, fake/injected sessions) and by executing the notebooks headlessly,
but never against real hardware. Several MFLI defaults in
`instruments/config.py` and `instruments/mfli.py` are explicitly flagged
**CONFIRM ON REAL HARDWARE** and should be checked on the lab computer
before relying on them.
