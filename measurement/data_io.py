"""Saving and loading sweep results.

CSV support only needs pandas (already a hard dependency). HDF5 support is
optional and needs ``h5py``; the HDF5 functions raise a clear
:class:`ImportError` if it is not installed, rather than being silently
unavailable.

:func:`save_sweep_result` is the primary entry point for a
:class:`measurement.sweep.SweepResult`: it writes a timestamped run folder
containing both ``sweep.csv`` (the data) and ``metadata.json`` (start/end
time, completion status, and the sweep configuration used).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Union

import pandas as pd

if TYPE_CHECKING:
    from measurement.sweep import SweepResult

logger = logging.getLogger(__name__)

PathLike = Union[str, Path]


def save_csv(df: pd.DataFrame, path: PathLike) -> None:
    """Save a sweep result to a CSV file.

    Args:
        df: Sweep result, e.g. as returned by
            :func:`measurement.sweep.run_voltage_sweep`.
        path: Output file path. Parent directories are created if needed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    logger.info("Saved sweep result to %s", path)


def load_csv(path: PathLike) -> pd.DataFrame:
    """Load a sweep result previously saved with :func:`save_csv`.

    Args:
        path: Path to the CSV file.

    Returns:
        The loaded sweep result.
    """
    return pd.read_csv(Path(path))


def save_hdf5(df: pd.DataFrame, path: PathLike, *, dataset_name: str = "sweep") -> None:
    """Save a sweep result to an HDF5 file using ``h5py``.

    Each DataFrame column is stored as a separate dataset under a single
    top-level group.

    Args:
        df: Sweep result to save.
        path: Output file path. Parent directories are created if needed.
        dataset_name: Name of the HDF5 group to store columns under.

    Raises:
        ImportError: If ``h5py`` is not installed.
    """
    try:
        import h5py
    except ImportError as exc:
        raise ImportError(
            "h5py is required for HDF5 support (pip install h5py); "
            "use save_csv/load_csv instead if it is not available."
        ) from exc

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with h5py.File(path, "w") as h5_file:
        group = h5_file.create_group(dataset_name)
        for column in df.columns:
            group.create_dataset(column, data=df[column].to_numpy())
    logger.info("Saved sweep result to %s (HDF5 group %r)", path, dataset_name)


def load_hdf5(path: PathLike, *, dataset_name: str = "sweep") -> pd.DataFrame:
    """Load a sweep result previously saved with :func:`save_hdf5`.

    Args:
        path: Path to the HDF5 file.
        dataset_name: Name of the HDF5 group the columns were stored under.

    Returns:
        The loaded sweep result.

    Raises:
        ImportError: If ``h5py`` is not installed.
    """
    try:
        import h5py
    except ImportError as exc:
        raise ImportError(
            "h5py is required for HDF5 support (pip install h5py); "
            "use save_csv/load_csv instead if it is not available."
        ) from exc

    with h5py.File(Path(path), "r") as h5_file:
        group = h5_file[dataset_name]
        data = {name: group[name][()] for name in group.keys()}
    return pd.DataFrame(data)


def save_sweep_result(
    result: "SweepResult",
    output_dir: PathLike = "data",
    *,
    run_name: Optional[str] = None,
) -> Path:
    """Save a sweep result as a timestamped run folder with CSV data and JSON metadata.

    Creates ``output_dir/run_name/sweep.csv`` (the data) and
    ``output_dir/run_name/metadata.json`` (start/end time, completion
    status, completed/total point counts, and the
    :class:`measurement.sweep.SweepConfig` used). Always writes both files,
    whether the sweep completed normally, was interrupted, or timed out --
    see :func:`measurement.sweep.run_voltage_sweep`.

    Args:
        result: The :class:`measurement.sweep.SweepResult` to save.
        output_dir: Parent directory to create the run folder under.
        run_name: Folder name to use. Defaults to a name derived from
            ``result.start_time``, e.g. ``sweep_20260714_153000``.

    Returns:
        The path to the created run folder.
    """
    output_dir = Path(output_dir)
    if run_name is None:
        start = datetime.fromisoformat(result.start_time)
        run_name = f"sweep_{start.strftime('%Y%m%d_%H%M%S')}"
    run_dir = output_dir / run_name
    run_dir.mkdir(parents=True, exist_ok=True)

    save_csv(result.data, run_dir / "sweep.csv")

    metadata = {
        "start_time": result.start_time,
        "end_time": result.end_time,
        "status": result.status,
        "completed_points": result.completed_points,
        "total_points": result.total_points,
        "sweep_config": asdict(result.sweep_config),
    }
    with open(run_dir / "metadata.json", "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2)

    logger.info("Saved sweep result to %s", run_dir)
    return run_dir


def load_sweep_result(run_dir: PathLike) -> tuple[pd.DataFrame, dict]:
    """Load a sweep result previously saved with :func:`save_sweep_result`.

    Args:
        run_dir: Path to the run folder created by :func:`save_sweep_result`.

    Returns:
        ``(data, metadata)``: the sweep DataFrame and the metadata dict
        (start/end time, status, completed/total points, sweep config).
    """
    run_dir = Path(run_dir)
    data = load_csv(run_dir / "sweep.csv")
    with open(run_dir / "metadata.json", encoding="utf-8") as f:
        metadata = json.load(f)
    return data, metadata
