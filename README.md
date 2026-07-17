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
optical-intensity-vs-voltage curves. Each quantity's standard deviation is
also recorded (`*_std` columns) -- the DUT voltage/current from the spread
of the Rigol GMM plateau fit, and the lock-in X/Y/R from repeat MFLI
reads -- and plotted as error bars, to help spot noisy signal conditions.

## Directory structure

```
instruments/
    base.py            # InstrumentError, InstrumentProtocol, VisaInstrument
    config.py           # default VISA addresses, channel roles/offsets, R0, MFLI defaults
    qdac.py             # QDac: trigger/gate signal generator
    avtech.py           # Avtech: swept pulse voltage source
    rigol.py            # Rigol: scope readout + GMM plateau extraction
    mfli.py             # MFLI: lock-in configuration + averaged readout
measurement/
    sweep.py            # run_voltage_sweep orchestration (live-plot callback, interrupt/timeout safety)
    data_io.py          # save/load sweep results (CSV+JSON run folder; CSV/HDF5 standalone)
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

Standalone HDF5 support in `measurement.data_io` (`save_hdf5`/`load_hdf5`)
is optional and needs `h5py` (`pip install h5py`); everything else,
including `save_sweep_result`'s CSV+JSON output, works with the base
`requirements.txt`.

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
- **`05_full_sweep_demo.ipynb`** demonstrates the full workflow in a single
  cell: configure all four instruments, sweep the pulse voltage with
  `measurement.sweep.run_voltage_sweep` (live-plotting each point, with
  error bars, via a `clear_output`-based callback), and always end up with
  a saved result -- `data/<timestamped run folder>/sweep.csv` +
  `metadata.json` -- whether the sweep completes normally, is interrupted
  (Jupyter's "Interrupt Kernel", handled internally: the Avtech is ramped
  to 0 V and its output disabled, while the QDac trigger train, Rigol, and
  MFLI stay connected and running), or exceeds `SweepConfig.max_runtime_s`
  (default 1000 s). If any instrument is unavailable, it falls back to
  clearly-labeled synthetic `dummy_data` so the saving/plotting logic can
  still be demonstrated. A dedicated "Sweep settings" cell exposes the
  frequently-tuned `SweepConfig` fields (e.g. `mfli_n_samples`/
  `mfli_delay` -- raise these if the lock-in signal is noisy -- ramp/settle
  timing, `idle_voltage`, `max_runtime_s`) as plain editable variables.

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
    result = run_voltage_sweep(
        avtech, rigol, mfli, qdac,
        voltages=np.linspace(2.0, 10.0, 5),
        sweep_config=SweepConfig(idle_voltage=5.0),
    )
    # Interrupting this call (e.g. Ctrl-C) is caught internally: the
    # Avtech is ramped to 0 V and its output disabled, and `result` still
    # comes back with status="interrupted" and whatever data was collected.

run_dir = data_io.save_sweep_result(result, "data")  # -> data/<run>/sweep.csv + metadata.json
plotting.plot_iv_curve(result.data, show=True)
plotting.plot_intensity_curve(result.data, show=True)
```

## Hardware status

This package was originally developed with no real instruments connected,
and has since had its QDac, Rigol, and MFLI defaults confirmed against
the real lab hardware:

- **QDac**: trigger/gate square-wave configuration confirmed working.
- **Rigol**: the fixed default address
  (`instruments.config.RIGOL_VISA_ADDRESS`) connects successfully.
- **MFLI**: the `"PCIe"` interface (`instruments.config.MFLI_INTERFACE`)
  connects successfully.

Avtech has not yet been confirmed against real hardware from this
environment. Everything in `instruments/` and `measurement/` is also
covered by unit-level checks (synthetic data, fake/injected sessions) and
by executing the notebooks headlessly.
