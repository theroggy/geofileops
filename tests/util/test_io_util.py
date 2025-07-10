"""
Tests for functionalities in _io_util.
"""

import tempfile

import pytest

from geofileops.util import _general_util, _io_util


def test_create_tempdir():
    """Test the creation of a temporary directory in the default python temp dir."""
    # Test
    tempdir1 = _io_util.create_tempdir("testje")
    tempdir2 = _io_util.create_tempdir("testje")

    # Checks
    tmp_dir = tempfile.gettempdir()
    assert tempdir1.exists()
    assert str(tempdir1).startswith(tmp_dir)
    assert tempdir2.exists()
    assert str(tempdir2).startswith(tmp_dir)

    # Cleanup
    tempdir1.rmdir()
    tempdir2.rmdir()


def test_create_tempdir_custom_dir(tmp_path):
    """Test the creation of a temporary directory in a dir specified via GFO_TMPDIR."""
    # Test
    tempdir = _io_util.create_tempdir("testje", parent_dir=tmp_path)
    assert tempdir.exists()
    assert str(tempdir).startswith(str(tmp_path))


def test_create_tempdir_gfo_tmpdir(tmp_path):
    """Test the creation of a temporary directory in a dir specified via GFO_TMPDIR."""
    with _general_util.TempEnv({"GFO_TMPDIR": str(tmp_path)}):
        tempdir = _io_util.create_tempdir("testje")

    assert tempdir.exists()
    assert str(tempdir).startswith(str(tmp_path))


def test_create_tempdir_gfo_tmpdir_invalid(tmp_path):
    """Test the creation of a temporary directory if GFO_TMPDIR is invalid."""
    # GFO_TMPDIR set to an empty string is not supported.
    with _general_util.TempEnv({"GFO_TMPDIR": ""}):
        with pytest.raises(
            RuntimeError,
            match="GFO_TMPDIR='' environment variable found which is not supported",
        ):
            _io_util.create_tempdir("testje")


def test_create_file_atomic(tmp_path):
    path = tmp_path / "testje_atomic.txt"
    file_created = _io_util.create_file_atomic(path)
    assert file_created
    file_created = _io_util.create_file_atomic(path)
    assert not file_created


def test_get_tempfile_locked():
    tempfile1lock_path = None
    tempfile2lock_path = None
    tempfile3lock_path = None

    try:
        tempfile1_path, tempfile1lock_path = _io_util.get_tempfile_locked("testje")
        assert not tempfile1_path.exists()
        assert tempfile1lock_path.exists()
        tempfile2_path, tempfile2lock_path = _io_util.get_tempfile_locked("testje")
        assert not tempfile2_path.exists()
        assert tempfile2lock_path.exists()
        tempfile3_path, tempfile3lock_path = _io_util.get_tempfile_locked(
            "testje", dirname="dir"
        )
        assert not tempfile3_path.exists()
        assert tempfile3lock_path.exists()
    finally:
        # Cleanup
        if tempfile1lock_path is not None:
            tempfile1lock_path.unlink()
        if tempfile2lock_path is not None:
            tempfile2lock_path.unlink()
        if tempfile3lock_path is not None:
            tempfile3lock_path.unlink()
