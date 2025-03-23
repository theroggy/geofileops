"""Module containing some utilities regarding io."""

import logging
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Union

import geofileops as gfo


def create_tempdir(base_dirname: str, parent_dir: Path | None = None) -> Path:
    """Creates a new tempdir in the default temp location.

    Remark: the temp dir won't be cleaned up automatically!

    Examples:
        - base_dirname="foo" -> /tmp/foo_000001
        - base_dirname="foo/bar" -> /tmp/foo/bar_000001

    Args:
        base_dirname (str): The name the tempdir will start with. The name will be
            suffixed with a number to make the directory name unique. If a "/" is part
            of the base_dirname a subdirectory will be created: e.g. "foo/bar".
        parent_dir (Path, optional): The dir to create the tempdir in. If None, the
            system temp dir is used. Defaults to None.

    Raises:
        Exception: if it wasn't possible to create the temp dir because there
            wasn't found a unique directory name.

    Returns:
        Path: the path to the temp dir created.
    """
    if parent_dir is None:
        parent_dir = Path(tempfile.gettempdir())

    for i in range(1, 999999):
        try:
            tempdir = parent_dir / f"{base_dirname}_{i:06d}"
            tempdir.mkdir(parents=True)
            return tempdir
        except FileExistsError:
            continue

    raise Exception(
        f"Wasn't able to create a temporary dir with basedir: "
        f"{parent_dir / base_dirname}"
    )


def get_tempfile_locked(
    base_filename: str,
    suffix: str = ".tmp",
    dirname: str | None = None,
    tempdir: Path | None = None,
) -> tuple[Path, Path]:
    """Formats a temp file path, and creates a corresponding lock file.

    This way you can treat it immediately as being locked.

    Args:
        base_filename (str): The base filename to use. A numeric suffix will be
            appended to make the filename unique.
        suffix (str, optional): The suffix/extension of the tempfile.
            Defaults to '.tmp'.
        dirname (str, optional): Name of the subdir to put the tempfile in.
            Defaults to None, then the tempfile created is put directly in the
            root of the tempdir.
        tempdir (Path, optional): Root temp dir to create the file in. If no
            tempdir is specified, the default temp dir will be used.
            Defaults to None.

    Raises:
        Exception: if it wasn't possible to create the temp dir because there
            wasn't found a unique file name.

    Returns:
        Tuple[Path, Path]: First path is the temp file, second one is the lock file.
    """
    # If no dir specified, use default temp dir
    if tempdir is None:
        tempdir = Path(tempfile.gettempdir())
    if dirname is not None:
        tempdir = tempdir / dirname
        tempdir.mkdir(parents=True, exist_ok=True)

    # Now look for a unique filename based on the base_filename and put a lock file
    for i in range(1, 999999):
        tempfile_path = tempdir / f"{base_filename}_{i:06d}{suffix}"
        tempfilelock_path = tempdir / f"{base_filename}_{i:06d}{suffix}.lock"
        result = create_file_atomic(tempfilelock_path)
        if result is True:
            if not tempfile_path.exists():
                # OK!
                return (tempfile_path, tempfilelock_path)
            else:
                # Apparently the lock file didn't exist yet, but the file did.
                # So delete lock file and try again.
                tempfilelock_path.unlink()

    raise Exception(
        f"Wasn't able to create a temporary file with base_filename: {base_filename}, "
        f"dir: {dir}"
    )


def create_file_atomic_wait(
    path: Union[str, "os.PathLike[Any]"],
    time_between_attempts: float = 1,
    timeout: float = 0,
):
    """Create a file in an atomic way.

    If it already exists, wait till it can be created.

    Returns once the file is created.

    Args:
        path (PathLike): path of the file to create.
        time_between_attempts (float, optional): time to wait between attempts.
            Defaults to 1.
        timeout (float, optional): maximum time in seconds to wait to create the file.
            Once the timeout has been reached, a RunTimeError is raised. If 0, there is
            no timeout. Defaults to 0.
    """
    start_time = datetime.now()
    while True:
        if create_file_atomic(path):
            return

        if timeout > 0:
            time_waiting = (datetime.now() - start_time).total_seconds()
            if time_waiting > timeout:
                raise RuntimeError(
                    f"timeout of {timeout} secs reached, couldn't create {path}"
                )

        # Wait 100ms
        time.sleep(time_between_attempts)


def create_file_atomic(path: Union[str, "os.PathLike[Any]"]) -> bool:
    """Create a file in an atomic way.

    Returns True if the file was created by this thread, False if the file existed
    already.
    """
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL)
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except OSError as ex:  # pragma: no cover
        if ex.errno == 13:
            return False
        else:
            raise RuntimeError(f"Error creating file {path}") from ex


def with_stem(path: Path, new_stem) -> Path:
    # Remark: from python 3.9 this is available on any Path, but to avoid
    # having to require 3.9 for this, this hack...
    return path.parent / f"{new_stem}{path.suffix}"


def output_exists(path: Path, remove_if_exists: bool) -> bool:
    """Checks and returns whether the file specified exists.

    If remove_if_exists is True, the file is removed and False is returned.

    Args:
        path (Path): Output file path to check.
        remove_if_exists (bool): If True, remove the output file if it exists.

    Raises:
        ValueError: raised when the output directory does not exist.

    Returns:
        bool: True if the output file exists.
              False if the file didn't exist or if it was removed
              because `remove_if_exists` is True.
    """
    if not path.parent.exists():
        raise ValueError(f"Output directory does not exist: {path.parent}")
    if path.exists():
        if remove_if_exists:
            gfo.remove(path)
            return False
        else:
            logging.info(msg=f"Stop, output already exists {path}", stacklevel=2)
            return True

    return False
