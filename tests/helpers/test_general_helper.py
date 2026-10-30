"""Tests for the general_helper module."""

import os
import sys
import tempfile

import pytest

from geofileops.helpers import _general_helper
from geofileops.util import _general_util, _io_util


def test_create_gfo_tmp_dir():
    """Test the creation of a temporary directory in the default tmp dir."""
    with (
        _general_util.TempEnv({"GFO_TMPDIR": None, "GFO_TMPDIR_COMPRESS": None}),
        _general_helper.create_gfo_tmp_dir("testje") as tmp_dir,
    ):
        assert tmp_dir.exists()
        assert tmp_dir.parent.name == "geofileops"
        assert tmp_dir.name.startswith("testje")
        tempdir = tempfile.gettempdir()
        assert str(tmp_dir).startswith(tempdir)


def test_create_gfo_tmp_dir_env(tmp_path):
    """Test the creation of a temporary directory in a dir specified via GFO_TMPDIR."""
    with (
        _general_util.TempEnv(
            {"GFO_TMPDIR": str(tmp_path), "GFO_TMPDIR_COMPRESS": None}
        ),
        _general_helper.create_gfo_tmp_dir("testje") as tmp_dir,
    ):
        assert tmp_dir.exists()
        assert str(tmp_dir).startswith(str(tmp_path))
        assert tmp_dir.name.startswith("testje")


def test_create_gfo_tmp_dir_compresses_parent_before_child(monkeypatch, tmp_path):
    events = []
    create_tempdir = _io_util.create_tempdir

    def enable_compression(path, compression):
        events.append(("compress", path, compression))

    def create_child(base_dirname, parent_dir):
        assert events == [("compress", tmp_path, True)]
        events.append(("create", parent_dir))
        return create_tempdir(base_dirname, parent_dir)

    monkeypatch.setattr(_io_util, "enable_directory_compression", enable_compression)
    monkeypatch.setattr(_io_util, "create_tempdir", create_child)

    with (
        _general_util.TempEnv(
            {"GFO_TMPDIR": str(tmp_path), "GFO_TMPDIR_COMPRESS": "TRUE"}
        ),
        _general_helper.create_gfo_tmp_dir("testje") as tmp_dir,
    ):
        assert tmp_dir.exists()

    assert events == [("compress", tmp_path, True), ("create", tmp_path)]


def test_create_gfo_tmp_dir_disables_compression_when_false(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        _io_util,
        "enable_directory_compression",
        lambda path, compression: calls.append((path, compression)),
    )

    with (
        _general_util.TempEnv(
            {"GFO_TMPDIR": str(tmp_path), "GFO_TMPDIR_COMPRESS": "FALSE"}
        ),
        _general_helper.create_gfo_tmp_dir("testje") as tmp_dir,
    ):
        assert tmp_dir.exists()

    assert calls == [(tmp_path, False)]


@pytest.mark.parametrize("value", [None, ""])
def test_create_gfo_tmp_dir_leaves_compression_unchanged(monkeypatch, tmp_path, value):
    monkeypatch.setattr(
        _io_util,
        "enable_directory_compression",
        lambda *_args, **_kwargs: pytest.fail(
            "compression helper should not be called"
        ),
    )

    with (
        _general_util.TempEnv(
            {"GFO_TMPDIR": str(tmp_path), "GFO_TMPDIR_COMPRESS": value}
        ),
        _general_helper.create_gfo_tmp_dir("testje") as tmp_dir,
    ):
        assert tmp_dir.exists()


@pytest.mark.skipif(
    sys.platform != "linux", reason="SQLite uses SQLITE_TMPDIR on Linux"
)
@pytest.mark.parametrize("sqlite_tmpdir_orig", [None, ""])
def test_create_gfo_tmp_dir_sqlite_tmpdir_linux(tmp_path, sqlite_tmpdir_orig):
    with _general_util.TempEnv(
        {
            "SQLITE_TMPDIR": sqlite_tmpdir_orig,
            "GFO_TMPDIR": str(tmp_path),
            "GFO_TMPDIR_COMPRESS": None,
        }
    ):
        tmpdir_orig = os.environ.get("TMPDIR")
        with _general_helper.create_gfo_tmp_dir("sqlite_tmpdir", tmp_path):
            expected_sqlite_tmpdir = str(tmp_path) if sqlite_tmpdir_orig is None else ""
            assert os.environ.get("SQLITE_TMPDIR") == expected_sqlite_tmpdir
            assert os.environ.get("TMPDIR") == tmpdir_orig
        assert os.environ.get("SQLITE_TMPDIR") == sqlite_tmpdir_orig


def test_create_gfo_tmp_dir_env_invalid():
    """Test the creation of a temporary directory if GFO_TMPDIR is invalid."""
    # GFO_TMPDIR set to an empty string is not supported.
    with (
        _general_util.TempEnv({"GFO_TMPDIR": "", "GFO_TMPDIR_COMPRESS": None}),
        pytest.raises(
            ValueError,
            match="GFO_TMPDIR='' environment variable found which is not supported",
        ),
        _general_helper.create_gfo_tmp_dir("testje") as _tmp_dir,
    ):
        pass


def test_create_gfo_tmp_dir_sqlite_tmpdir_invalid(tmp_path):
    """Test that a non-existent SQLITE_TMPDIR is rejected."""
    sqlite_tmpdir = tmp_path / "does_not_exist"
    with (
        _general_util.TempEnv(
            {
                "SQLITE_TMPDIR": str(sqlite_tmpdir),
                "GFO_TMPDIR_COMPRESS": None,
            }
        ),
        pytest.raises(
            ValueError,
            match=r"SQLITE_TMPDIR=.*path that does not exist",
        ),
        _general_helper.create_gfo_tmp_dir("testje") as _tmp_dir,
    ):
        pass


def test_warn_if_low_mem():
    """Test the low memory warning function."""
    # Set the threshold to a high value to trigger the warning
    min_memory_available = 9999 * 1024 * 1024 * 1024 * 1024  # 9999 TB
    with _general_util.TempEnv(
        {"GFO_LOW_MEM_AVAILABLE_WARN_THRESHOLD": str(min_memory_available)}
    ):
        with pytest.warns(UserWarning, match="Low memory available"):
            _general_helper.warn_if_low_mem(called_from="test_warn_if_low_mem")


@pytest.mark.parametrize(
    "worker_type, input_layer_featurecount, expected",
    [
        ("processes", 1, "processes"),
        ("threads", 101, "threads"),
        ("auto", 1, "threads"),
        ("auto", 100, "threads"),
        ("auto", 101, "processes"),
    ],
)
def test_worker_type_to_use(worker_type, input_layer_featurecount, expected):
    with _general_util.TempEnv({"GFO_WORKER_TYPE": worker_type}):
        assert _general_helper.worker_type_to_use(input_layer_featurecount) == expected
