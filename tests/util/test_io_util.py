"""Tests for functionalities in _io_util."""

import subprocess
import sys
import tempfile

import pytest

from geofileops.util import _io_util


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


@pytest.mark.parametrize(
    "compression, expected_algorithm",
    [
        (True, "zstd"),
        (False, "none"),
        ("zlib", "zlib"),
        ("lzo", "lzo"),
        ("zstd", "zstd"),
    ],
)
@pytest.mark.skipif(sys.platform != "linux", reason="Btrfs compression is Linux-only")
def test_enable_directory_compression_btrfs(
    monkeypatch, tmp_path, compression, expected_algorithm
):
    commands = []
    monkeypatch.setattr(
        _io_util.subprocess,
        "run",
        lambda command, **kwargs: commands.append((command, kwargs)),
    )

    _io_util.enable_directory_compression(tmp_path, compression)

    assert commands == [
        (
            [
                "btrfs",
                "property",
                "set",
                str(tmp_path),
                "compression",
                expected_algorithm,
            ],
            {"check": True, "capture_output": True, "text": True},
        )
    ]


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS compression is Windows-only")
def test_enable_directory_compression_windows(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(
        _io_util.subprocess,
        "run",
        lambda command, **kwargs: commands.append((command, kwargs)),
    )

    _io_util.enable_directory_compression(tmp_path)

    assert commands == [
        (
            ["compact.exe", "/c", "/q", str(tmp_path)],
            {"check": True, "capture_output": True, "text": True},
        )
    ]


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS compression is Windows-only")
def test_disable_directory_compression_windows(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(
        _io_util.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command),
    )

    _io_util.enable_directory_compression(tmp_path, False)

    assert commands == [["compact.exe", "/u", "/q", str(tmp_path)]]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only option behavior")
def test_enable_directory_compression_windows_rejects_algorithm(tmp_path):
    with pytest.raises(ValueError, match="algorithm strings are not supported"):
        _io_util.enable_directory_compression(tmp_path, "zstd")


@pytest.mark.skipif(sys.platform != "linux", reason="Btrfs compression is Linux-only")
def test_enable_directory_compression_btrfs_warns_on_failure(monkeypatch, tmp_path):
    def fail(command, **_kwargs):
        raise subprocess.CalledProcessError(1, command, stderr="not a Btrfs filesystem")

    monkeypatch.setattr(_io_util.subprocess, "run", fail)

    with pytest.warns(UserWarning, match="not a Btrfs filesystem"):
        _io_util.enable_directory_compression(tmp_path)


@pytest.mark.skipif(sys.platform != "linux", reason="Btrfs compression is Linux-only")
def test_enable_directory_compression_runs_each_call(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(
        _io_util.subprocess,
        "run",
        lambda command, **_kwargs: commands.append(command),
    )

    _io_util.enable_directory_compression(tmp_path)
    _io_util.enable_directory_compression(tmp_path)

    assert len(commands) == 2


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS compression is Windows-only")
def test_enable_directory_compression_windows_propagates_failure(monkeypatch, tmp_path):
    def fail(command, **_kwargs):
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(_io_util.subprocess, "run", fail)

    with pytest.raises(subprocess.CalledProcessError):
        _io_util.enable_directory_compression(tmp_path)


def test_enable_directory_compression_unset_is_noop(monkeypatch, tmp_path):
    monkeypatch.setattr(
        _io_util.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("subprocess should not be called"),
    )

    _io_util.enable_directory_compression(tmp_path, None)


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
