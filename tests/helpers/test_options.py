"""Tests for functionalities in _configoptions_helper."""

import os
import tempfile

import pytest
from pyproj import CRS

import geofileops as gfo
from geofileops.helpers import _options
from geofileops.helpers._options import ConfigOptions


@pytest.mark.parametrize(
    "value, default, expected",
    [
        ("TruE", False, True),
        ("YeS", False, True),
        ("1", False, True),
        ("nO", True, False),
        ("FalsE", True, False),
        ("0", True, False),
        ("", True, True),
        ("", False, False),
        (None, True, True),
        (None, False, False),
    ],
)
def test_get_bool(value, default, expected):
    test_key = "GFO_TEST_BOOL"
    if value is None:
        if test_key in os.environ:
            del os.environ[test_key]
    else:
        os.environ[test_key] = value

    result = _options._get_bool(test_key, default=default)
    if test_key in os.environ:
        del os.environ[test_key]

    assert result is expected


def test_get_bool_invalidvalue():
    test_key = "GFO_TEST_BOOL"
    with (
        gfo.TempEnv({test_key: "INVALID"}),
        pytest.raises(ValueError, match="invalid value for bool configoption"),
    ):
        _ = _options._get_bool(test_key, default="")


@pytest.mark.parametrize(
    "key, value, expected",
    [
        ("GFO_IO_ENGINE", "PYOgrio", "pyogrio"),
        ("GFO_IO_ENGINE", "FIOna", "fiona"),
        ("GFO_IO_ENGINE", None, "pyogrio-arrow"),
        ("GFO_ON_DATA_ERROR", "RAIse", "raise"),
        ("GFO_ON_DATA_ERROR", "WARn", "warn"),
        ("GFO_ON_DATA_ERROR", None, "raise"),
        ("GFO_REMOVE_TEMP_FILES", "TRUe", True),
        ("GFO_REMOVE_TEMP_FILES", "FALse", False),
        ("GFO_REMOVE_TEMP_FILES", None, True),
        ("GFO_WORKER_TYPE", "THReads", "threads"),
        ("GFO_WORKER_TYPE", "PROcesses", "processes"),
        ("GFO_WORKER_TYPE", "AUTo", "auto"),
        ("GFO_WORKER_TYPE", None, "auto"),
    ],
)
def test_get_option(key, value, expected):
    """Test all ConfigOptions class properties."""
    with gfo.TempEnv({key: value}):
        if key == "GFO_IO_ENGINE":
            result = ConfigOptions.get_io_engine
        elif key == "GFO_ON_DATA_ERROR":
            result = ConfigOptions.get_on_data_error
        elif key == "GFO_REMOVE_TEMP_FILES":
            result = ConfigOptions.get_remove_temp_files
        elif key == "GFO_WORKER_TYPE":
            result = ConfigOptions.get_worker_type
        else:
            raise ValueError(f"Unexpected key: {key}")

    assert result == expected


@pytest.mark.parametrize(
    "key, invalid_value, expected_error",
    [
        ("GFO_IO_ENGINE", "invalid", "invalid value for configoption <GFO_IO_ENGINE>"),
        (
            "GFO_ON_DATA_ERROR",
            "invalid",
            "invalid value for configoption <GFO_ON_DATA_ERROR>",
        ),
        (
            "GFO_REMOVE_TEMP_FILES",
            "invalid",
            "invalid value for bool configoption <GFO_REMOVE_TEMP_FILES>",
        ),
        (
            "GFO_SLIVER_TOLERANCE",
            "not_a_number",
            "invalid value for configoption <GFO_SLIVER_TOLERANCE>",
        ),
        (
            "GFO_TMPDIR",
            "   ",
            "GFO_TMPDIR='' environment variable found which is not supported",
        ),
        (
            "GFO_WORKER_TYPE",
            "invalid",
            "invalid value for configoption <GFO_WORKER_TYPE>",
        ),
    ],
)
def test_get_option_invalid(key, invalid_value, expected_error):
    with (
        gfo.TempEnv({key: invalid_value}),
        pytest.raises(ValueError, match=expected_error),
    ):
        if key == "GFO_IO_ENGINE":
            _ = ConfigOptions.get_io_engine
        elif key == "GFO_ON_DATA_ERROR":
            _ = ConfigOptions.get_on_data_error
        elif key == "GFO_REMOVE_TEMP_FILES":
            _ = ConfigOptions.get_remove_temp_files
        elif key == "GFO_SLIVER_TOLERANCE":
            _ = ConfigOptions.get_sliver_tolerance(None)
        elif key == "GFO_TMPDIR":
            _ = ConfigOptions.get_tmp_dir
        elif key == "GFO_WORKER_TYPE":
            _ = ConfigOptions.get_worker_type
        else:
            raise ValueError(f"Unexpected key: {key}")


@pytest.mark.parametrize(
    "tolerance, crs, expected",
    [
        ("0.1", None, 0.1),
        ("0.2", None, 0.2),
        (None, None, 0.0),
        (None, CRS.from_epsg(31370), 0.001),
        (None, CRS.from_epsg(3857), 0.001),
        (None, CRS.from_epsg(2277), 0.001),  # CRS in feet -> same tolerance
        (None, CRS.from_epsg(4326), 1e-7),
        ("0.5", CRS.from_epsg(31370), 0.5),
        ("-0.5", CRS.from_epsg(4326), -0.5),
    ],
)
def test_get_sliver_tolerance(tolerance, crs, expected):
    """Test ConfigOptions.sliver_tolerance method."""
    with gfo.TempEnv({"GFO_SLIVER_TOLERANCE": tolerance}):
        result = ConfigOptions.get_sliver_tolerance(crs)
        assert result == expected


def test_get_tmp_dir(tmp_path):
    """Test ConfigOptions.tmp_dir property."""
    with gfo.TempEnv({"GFO_TMPDIR": str(tmp_path)}):
        assert ConfigOptions.get_tmp_dir == tmp_path

    # If GFO_TMPDIR is not set, a "geofileops" subdirectory in the system temp dir is
    # used.
    with gfo.TempEnv({"GFO_TMPDIR": None}):
        tmp_dir = ConfigOptions.get_tmp_dir
        assert tmp_dir.exists()
        assert tmp_dir.name == "geofileops"
        tempdir = tempfile.gettempdir()
        assert str(tmp_dir).startswith(tempdir)


def test_set_copy_layer_sqlite_direct() -> None:
    """Test the copy_layer_sqlite_direct option setter."""
    # Make sure the environment variable is not set at the start of the test
    key = "GFO_COPY_LAYER_SQLITE_DIRECT"
    if key in os.environ:
        del os.environ[key]

    # Test setting the option permanently
    gfo.options.set_copy_layer_sqlite_direct(False)
    assert os.environ[key] == "FALSE"

    # Test setting the option temporarily using context manager
    with gfo.options.set_copy_layer_sqlite_direct(True):
        assert os.environ[key] == "TRUE"

    # After exiting the context manager, the value should be restored to the last
    # permanent setting (which was False)
    assert os.environ[key] == "FALSE"

    # Clean up by setting with None
    gfo.options.set_copy_layer_sqlite_direct(None)

    # Test setting the option temporarily using context manager
    with gfo.options.set_copy_layer_sqlite_direct(True):
        assert os.environ[key] == "TRUE"

    # After exiting the context manager, the environment variable should be removed
    assert key not in os.environ


def test_set_io_engine() -> None:
    """Test the io_engine option setter."""
    # Make sure the environment variable is not set at the start of the test
    key = "GFO_IO_ENGINE"
    if key in os.environ:
        del os.environ[key]

    # Test setting the option permanently
    gfo.options.set_io_engine("fiona")
    assert os.environ[key] == "FIONA"

    # Test setting the option temporarily using context manager
    with gfo.options.set_io_engine("pyogrio"):
        assert os.environ[key] == "PYOGRIO"

    # After exiting the context manager, the value should be restored to the last
    # permanent setting (which was "fiona")
    assert os.environ[key] == "FIONA"

    # Clean up by setting with None
    gfo.options.set_io_engine(None)

    # Test setting the option temporarily using context manager
    with gfo.options.set_io_engine("pyogrio-arrow"):
        assert os.environ[key] == "PYOGRIO-ARROW"

    # After exiting the context manager, the environment variable should be removed
    assert key not in os.environ


def test_set_on_data_error() -> None:
    """Test the on_data_error option setter."""
    # Make sure the environment variable is not set at the start of the test
    key = "GFO_ON_DATA_ERROR"
    if key in os.environ:
        del os.environ[key]

    # Test setting the option permanently
    gfo.options.set_on_data_error("warn")
    assert os.environ[key] == "WARN"

    # Test setting the option temporarily using context manager
    with gfo.options.set_on_data_error("raise"):
        assert os.environ[key] == "RAISE"

    # After exiting the context manager, the value should be restored to the last
    # permanent setting (which was "warn")
    assert os.environ[key] == "WARN"

    # Clean up by setting with None
    gfo.options.set_on_data_error(None)

    # Test setting the option temporarily using context manager
    with gfo.options.set_on_data_error("raise"):
        assert os.environ[key] == "RAISE"

    # After exiting the context manager, the environment variable should be removed
    assert key not in os.environ


def test_set_remove_temp_files() -> None:
    """Test the remove_temp_files option setter."""
    # Make sure the environment variable is not set at the start of the test
    key = "GFO_REMOVE_TEMP_FILES"
    if key in os.environ:
        del os.environ[key]

    # Test setting the option permanently
    gfo.options.set_remove_temp_files(False)
    assert os.environ[key] == "FALSE"

    # Test setting the option temporarily using context manager
    with gfo.options.set_remove_temp_files(True):
        assert os.environ[key] == "TRUE"

    # After exiting the context manager, the value should be restored to the last
    # permanent setting (which was False)
    assert os.environ[key] == "FALSE"

    # Clean up by setting with None
    gfo.options.set_remove_temp_files(None)

    # Test setting the option temporarily using context manager
    with gfo.options.set_remove_temp_files(True):
        assert os.environ[key] == "TRUE"

    # After exiting the context manager, the environment variable should be removed
    assert key not in os.environ


def test_set_sliver_tolerance() -> None:
    """Test the sliver_tolerance option setter."""
    # Make sure the environment variable is not set at the start of the test
    key = "GFO_SLIVER_TOLERANCE"
    if key in os.environ:
        del os.environ[key]

    # Test setting the option permanently
    gfo.options.set_sliver_tolerance(0.001)
    assert os.environ[key] == "0.001"

    # Test setting the option temporarily using context manager
    with gfo.options.set_sliver_tolerance(0.0001):
        assert os.environ[key] == "0.0001"

    # After exiting the context manager, the value should be restored to the last
    # permanent setting (which was 0.001)
    assert os.environ[key] == "0.001"

    # Clean up by setting with None
    gfo.options.set_sliver_tolerance(None)

    # Test setting the option temporarily using context manager
    with gfo.options.set_sliver_tolerance(-0.0005):
        assert os.environ[key] == "-0.0005"

    # After exiting the context manager, the environment variable should be removed
    assert key not in os.environ


def test_set_subdivide_check_parallel_fraction() -> None:
    """Test the subdivide_check_parallel_fraction option setter."""
    # Make sure the environment variable is not set at the start of the test
    key = "GFO_SUBDIVIDE_CHECK_PARALLEL_FRACTION"
    if key in os.environ:
        del os.environ[key]

    # Test setting the option permanently
    gfo.options.set_subdivide_check_parallel_fraction(10)
    assert os.environ[key] == "10"

    # Test setting the option temporarily using context manager
    with gfo.options.set_subdivide_check_parallel_fraction(5):
        assert os.environ[key] == "5"

    # After exiting the context manager, the value should be restored to the last
    # permanent setting (which was 10)
    assert os.environ[key] == "10"

    # Clean up by setting with None
    gfo.options.set_subdivide_check_parallel_fraction(None)

    # Test setting the option temporarily using context manager
    with gfo.options.set_subdivide_check_parallel_fraction(20):
        assert os.environ[key] == "20"

    # After exiting the context manager, the environment variable should be removed
    assert key not in os.environ


def test_set_subdivide_check_parallel_rows() -> None:
    """Test the subdivide_check_parallel_rows option setter."""
    # Make sure the environment variable is not set at the start of the test
    key = "GFO_SUBDIVIDE_CHECK_PARALLEL_ROWS"
    if key in os.environ:
        del os.environ[key]

    # Test setting the option permanently
    gfo.options.set_subdivide_check_parallel_rows(100000)
    assert os.environ[key] == "100000"

    # Test setting the option temporarily using context manager
    with gfo.options.set_subdivide_check_parallel_rows(50000):
        assert os.environ[key] == "50000"

    # After exiting the context manager, the value should be restored to the last
    # permanent setting (which was 100000)
    assert os.environ[key] == "100000"

    # Clean up by setting with None
    gfo.options.set_subdivide_check_parallel_rows(None)

    # Test setting the option temporarily using context manager
    with gfo.options.set_subdivide_check_parallel_rows(200000):
        assert os.environ[key] == "200000"

    # After exiting the context manager, the environment variable should be removed
    assert key not in os.environ


def test_set_tmp_dir() -> None:
    """Test the tmp_dir option setter."""
    # Make sure the environment variable is not set at the start of the test
    key = "GFO_TMPDIR"
    if key in os.environ:
        del os.environ[key]

    # Test setting the option permanently
    gfo.options.set_tmp_dir("/tmp/geofileops_test")
    assert os.environ[key] == "/tmp/geofileops_test"

    # Test setting the option temporarily using context manager
    with gfo.options.set_tmp_dir("/tmp/geofileops_temp"):
        assert os.environ[key] == "/tmp/geofileops_temp"

    # After exiting the context manager, the value should be restored to the last
    # permanent setting (which was "/tmp/geofileops_test")
    assert os.environ[key] == "/tmp/geofileops_test"

    # Clean up by setting with None
    gfo.options.set_tmp_dir(None)

    # Test setting the option temporarily using context manager
    with gfo.options.set_tmp_dir("/tmp/geofileops_temp2"):
        assert os.environ[key] == "/tmp/geofileops_temp2"

    # After exiting the context manager, the environment variable should be removed
    assert key not in os.environ


def test_set_worker_type() -> None:
    """Test the worker_type option setter."""
    # Make sure the environment variable is not set at the start of the test
    key = "GFO_WORKER_TYPE"
    if key in os.environ:
        del os.environ[key]

    # Test setting the option permanently
    gfo.options.set_worker_type("threads")
    assert os.environ[key] == "THREADS"

    # Test setting the option temporarily using context manager
    with gfo.options.set_worker_type("processes"):
        assert os.environ[key] == "PROCESSES"

    # After exiting the context manager, the value should be restored to the last
    # permanent setting (which was "threads")
    assert os.environ[key] == "THREADS"

    # Clean up by setting with None
    gfo.options.set_worker_type(None)

    # Test setting the option temporarily using context manager
    with gfo.options.set_worker_type("auto"):
        assert os.environ[key] == "AUTO"

    # After exiting the context manager, the environment variable should be removed
    assert key not in os.environ
