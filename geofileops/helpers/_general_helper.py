"""General helper functions, specific for geofileops."""

import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from geofileops.helpers._options import ConfigOptions
from geofileops.util import _io_util


@contextmanager
def create_gfo_tmp_dir(
    base_dirname: str, parent_dir: Path | None = None
) -> Iterator[Path]:
    """Context manager that creates a temporary directory for geofileops operations.

    The directory and its contents are removed when the context is exited, unless
    `ConfigOptions.remove_temp_files` is set to False.

    Args:
        base_dirname (str): The base name of the temporary directory to create. The
            following characters are replaced to "_": "/", " ".
        parent_dir (Path | None, optional): The parent directory to create the
            temporary directory in. If None, the directory specified in the environment
            variable `GFO_TMPDIR` is used. If that  that does not exist, a "geofileops"
            subdirectory in :func:`tempfile.gettempdir` is used. Defaults to None.

    Returns:
        Path: The path to the created temporary directory.
    """
    if parent_dir is None:
        parent_dir = ConfigOptions.get_tmp_dir
    base_dirname = base_dirname.replace("/", "_").replace(" ", "_")

    tmp_dir = _io_util.create_tempdir(base_dirname, parent_dir)
    try:
        yield tmp_dir
    finally:
        if ConfigOptions.get_remove_temp_files:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def worker_type_to_use(input_layer_featurecount: int) -> str:
    worker_type = ConfigOptions.get_worker_type
    if worker_type in ("threads", "processes"):
        return worker_type

    # Processing in threads is 2x faster for small datasets
    if input_layer_featurecount <= 100:
        return "threads"

    return "processes"
