# CLAUDE.md — Lab Instrument Control Refactor

This file gives Claude Code the persistent context and rules it should follow
while working on this repository. Read this before making any changes.

## 1. Project Summary

This repository controls a laboratory setup used to characterize a laser
device by sweeping a voltage pulse and simultaneously recording the device's
electrical response and its optical (lock-in) response.

Physical setup:

- A **QDac** (multi-channel precision DC/trigger source) supplies stable
  trigger signals that synchronize the **pulse generator** and the
  **lock-in amplifier**.
- An **Avtech pulse generator** supplies the voltage pulse that powers the
  laser device under test. Pulse amplitude (and possibly width/timing) is
  the swept parameter.
- A **Rigol oscilloscope** reads back the device's voltage and current
  waveforms during each pulse.
- A **Zurich Instruments MFLI lock-in amplifier** reads the lock-in signal,
  which corresponds to the optical intensity emitted by the device.

Experiment goal: sweep the pulse voltage, and at each step acquire
(voltage, current, lock-in signal), then plot the results
(e.g. I-V and optical-intensity-vs-voltage curves).

## 2. Current State

- `code_collection/` contains working but unorganized scripts. Treat this
  folder as **read-only source material** — do not edit files in it directly.
  Read it to recover working logic (SCPI commands, timing, sequences,
  parameter names, working values) and port that logic into the new
  structure below.
- QDac and Avtech control is already implemented informally via `pyvisa`.
- Rigol scope readout is already implemented informally via `pyvisa`.
- MFLI (lock-in) control does **not** exist yet in a reusable form and must
  be newly written using the `zhinst` package (prefer the modern
  `zhinst.toolkit` session-based API if available in the environment;
  fall back to `zhinst.ziPython` only if necessary, and note the choice).
- **No real instruments are connected to this development machine.**
  Do not attempt to run code against real hardware. Do not add tests that
  require a live connection to pass. The user will test and debug on the
  lab computer and report results back.

## 3. Target Directory Structure

Produce a layout roughly like this (adjust names if the existing code
suggests better ones, but keep it flat and predictable):

```
instruments/
    __init__.py
    base.py            # shared Instrument base class / interfaces
    qdac.py            # QDac class
    avtech.py          # Avtech pulse generator class
    rigol.py           # Rigol oscilloscope class
    mfli.py            # MFLI lock-in amplifier class
measurement/
    __init__.py
    sweep.py           # orchestration: voltage sweep + data collection
    data_io.py          # saving results (csv / hdf5) 
    plotting.py         # plotting helpers for I-V / intensity-V curves
notebooks/
    01_test_qdac.ipynb
    02_test_avtech.ipynb
    03_test_rigol.ipynb
    04_test_mfli.ipynb
    05_full_sweep_demo.ipynb
code_collection/        # legacy, read-only reference, do not modify
README.md
CLAUDE.md
```

## 4. Coding Conventions

- **Language: English only.** All code, comments, docstrings, log/print
  strings, commit messages, and markdown documentation must be written in
  English, with no exceptions. This applies even though the user may
  communicate with you in Chinese.
- Target Python 3.10+, use type hints everywhere (function signatures and
  class attributes).
- Use `logging` (module-level `logger = logging.getLogger(__name__)`)
  instead of `print` for anything other than notebook demo output.
- Docstrings: Google style. Every public class and public method gets a
  docstring describing purpose, args, returns, and raised exceptions.
- Each instrument class must support use as a context manager
  (`__enter__` / `__exit__`) so connections are always closed cleanly, in
  addition to explicit `connect()` / `disconnect()` methods.
- Wrap raw `pyvisa`/`zhinst` calls with clear, instrument-specific
  exceptions (e.g. `QDacError`, `AvtechError`) rather than letting raw
  low-level exceptions propagate uncaught.
- No hard-coded VISA resource strings or device IDs inside class bodies —
  accept them as constructor arguments with sensible optional defaults
  pulled from a small `config.py` or keyword arguments.
- Prefer composition over inheritance among instruments; a shared
  `base.py` should only capture the truly common connect/write/query/
  close pattern (this can be built around `pyvisa` for the three VISA
  instruments; MFLI will have its own connection pattern via `zhinst` but
  can still implement the same base interface/protocol so it's
  interchangeable in the orchestration layer).
- Because there is no hardware available for testing here, design classes
  so they are easy to test later with mocks: avoid tight coupling to a
  single global VISA resource manager, allow an existing session/handle to
  be injected via constructor, and keep hardware I/O calls thin and
  isolated (small private methods) so they're easy to monkeypatch.

## 5. Git Workflow

- Work in small, reviewable increments. **Commit after each meaningful
  step** described in the prompt sequence (see the accompanying prompts
  document), not all at once at the end.
- Commit messages: short imperative English summary line (<= 72 chars),
  optionally a body explaining what/why. Example:
  `Add Avtech pulse generator class with amplitude/width control`
- Do not commit code_collection changes — that folder should remain
  untouched throughout the whole refactor.
- Before starting structural/architecture decisions (e.g. the shared base
  class design in Step 1), summarize the proposed design in chat and wait
  for confirmation before writing code, since this shapes every class
  after it.

## 6. Notebook Requirements

- One notebook per instrument first (`01_test_qdac.ipynb`, etc.), each
  demonstrating: instantiate the class, connect, run its core operations
  (e.g. set trigger, set pulse parameters, read a waveform, read a lock-in
  value), and print results — all wrapped so the notebook does not crash
  if hardware is absent (e.g. try/except around the live-hardware calls
  with a clear "hardware not available" message), since this machine has
  none connected.
- Final notebook (`05_full_sweep_demo.ipynb`) demonstrates the integrated
  workflow: configure all four instruments, sweep pulse voltage over a
  user-defined range, collect (V, I, lock-in signal) at each step, save
  the dataset, and plot the resulting curves.
- Do not fabricate or hardcode fake "successful" hardware output as if it
  were real data; if demonstrating plotting logic without hardware, use
  clearly-labeled synthetic/dummy data (e.g. variable name
  `dummy_data`, and a printed note that it is synthetic).

## 7. Out of Scope For Now

- No live hardware testing or debugging in this environment.
- No packaging/distribution (setup.py, pyproject build config) unless the
  user asks for it later.
- No GUI work.
