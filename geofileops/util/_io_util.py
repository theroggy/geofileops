# -*- coding: utf-8 -*-
"""
Module containing some utilities regarding io.
"""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Optional, Tuple, Union


def create_tempdir(base_dirname: str) -> Path:
    """
    Creates a new tempdir in the default temp location.

    Remark: the temp dir won't be cleaned up automatically!

    Args:
        base_dirname (str): The name the tempdir will start with. A number will
            be attended to this to make the directory name unique.

    Raises:
        Exception: if it wasn't possible to create the temp dir because there
            wasn't found a unique directory name.

    Returns:
        Path: the path to the temp dir created.
    """

    defaulttempdir = Path(tempfile.gettempdir())

    for i in range(1, 999999):
        try:
            tempdir = defaulttempdir / f"{base_dirname}_{i:06d}"
            tempdir.mkdir(parents=True)
            return Path(tempdir)
        except FileExistsError:
            continue

    raise Exception(
        f"Wasn't able to create a temporary dir with basedir: {defaulttempdir / base_dirname}"
    )


def get_tempfile_locked(
    base_filename: str,
    suffix: str = ".tmp",
    dirname: Optional[str] = None,
    tempdir: Optional[Path] = None,
) -> Tuple[Path, Path]:
    """
    Formats a temp file path, and creates a corresponding lock file so you can
    treat it immediately as being locked.

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
        f"Wasn't able to create a temporary file with base_filename: {base_filename}, dir: {dir}"
    )


def copyfile(src: Union[str, "os.PathLike[Any]"], dst: Union[str, "os.PathLike[Any]"]):
    """
    Copy the source file to the destination specified.

    Standard shutil.copyfile is very slow on windows for large files.

    Args:
        src (PathLike): the source file to copy.
        dst (PathLike): the destination file or directory to copy to.

    Raises:
        Exception: when anything went wrong.
    """
    if os.name == "nt":
        # On windows, this is a lot faster than all shutil alternatives
        # command = f'copy "{src}" "{dst}"'
        command = f'xcopy /j "{src}" "{dst}*"'
        output = ""
        try:
            output = subprocess.check_output(command, shell=True)
        except Exception as ex:
            raise Exception(f"Error executing {command}, with output {output}") from ex

    else:
        # If the destination is a dir, make it a full file path
        dst_p = Path(dst)
        if dst_p.is_dir():
            src_p = Path(src)
            dst_p = dst_p / src_p.name

        buffer_size = 1024 * 1024 * 5
        with open(src, "rb") as fsrc, open(dst_p, "wb") as fdest:
            shutil.copyfileobj(fsrc, fdest, buffer_size)


'''
def is_locked(filepath):
    """
    Checks if a file is locked by another process.
    """
    if os.name == 'nt':
        import msvcrt
        try:
            fd = os.open(filepath, os.O_APPEND | os.O_EXCL | os.O_RDWR)
        except OSError:
            return True

        try:
            filesize = os.path.getsize(filepath)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, filesize)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, filesize)
            os.close(fd)
            return False
        except (OSError, IOError):
            os.close(fd)
            return True
    else:
        raise Exception(f"Not implemented on os: {os.name}")
'''


def create_file_atomic(filename) -> bool:
    """
    Create a lock file in an atomic way, so it is threadsafe.

    Returns True if the file was created by this thread, False if the file existed already.
    """
    try:
        fd = os.open(filename, os.O_CREAT | os.O_EXCL)
        os.close(fd)
        return True
    except FileExistsError:
        return False
    except IOError as ex:
        if ex.errno == 13:
            return False
        else:
            raise Exception("Error creating lock file {filename}") from ex


def with_stem(path: Path, new_stem) -> Path:
    # Remark: from python 3.9 this is available on any Path, but to evade
    # having to require 3.9 for this, this hack...
    return path.parent / f"{new_stem}{path.suffix}"
