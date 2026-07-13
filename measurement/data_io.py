"""Saving and loading sweep results.

CSV support only needs pandas (already a hard dependency). HDF5 support is
optional and needs ``h5py``; the HDF5 functions raise a clear
:class:`ImportError` if it is not installed, rather than being silently
unavailable.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Union

import pandas as pd

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
