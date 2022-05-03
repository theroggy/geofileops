# -*- coding: utf-8 -*-
"""
Tests for functionalities in ogr_util.
"""

from pathlib import Path
import sys

# Add path so the local geofileops packages are found
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from geofileops.util import _io_util
from tests import test_helper


def test_copyfile(tmp_path):
    src_file = test_helper.get_testfile(testfile="polygon-parcel")
    dst_file = tmp_path / f"{src_file.stem}_dst{src_file.suffix}"

    assert src_file.exists() is True
    assert dst_file.exists() is False
    _io_util.copyfile(src_file, dst_file)
    assert dst_file.exists() is True


def test_create_tempdir():
    # Test
    tempdir1 = _io_util.create_tempdir("testje")
    assert tempdir1.exists() is True
    tempdir2 = _io_util.create_tempdir("testje")
    assert tempdir2.exists() is True

    # Cleanup
    tempdir1.rmdir()
    tempdir2.rmdir()


def test_create_file_atomic(tmp_path):
    path = tmp_path / "testje_atomic.txt"
    file_created = _io_util.create_file_atomic(path)
    assert file_created is True
    file_created = _io_util.create_file_atomic(path)
    assert file_created is False


def test_get_tempfile_locked():
    tempfile1lock_path = None
    tempfile2lock_path = None
    tempfile3lock_path = None

    try:
        tempfile1_path, tempfile1lock_path = _io_util.get_tempfile_locked("testje")
        assert tempfile1_path.exists() is False
        assert tempfile1lock_path.exists() is True
        tempfile2_path, tempfile2lock_path = _io_util.get_tempfile_locked("testje")
        assert tempfile2_path.exists() is False
        assert tempfile2lock_path.exists() is True
        tempfile3_path, tempfile3lock_path = _io_util.get_tempfile_locked(
            "testje", dirname="dir"
        )
        assert tempfile3_path.exists() is False
        assert tempfile3lock_path.exists() is True
    finally:
        # Cleanup
        if tempfile1lock_path is not None:
            tempfile1lock_path.unlink()
        if tempfile2lock_path is not None:
            tempfile2lock_path.unlink()
        if tempfile3lock_path is not None:
            tempfile3lock_path.unlink()
