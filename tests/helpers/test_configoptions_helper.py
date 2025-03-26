"""
Tests for functionalities in _configoptions_helper.
"""

import os

import pytest

import geofileops as gfo
from geofileops.helpers import _configoptions_helper
from geofileops.helpers._configoptions_helper import ConfigOptions


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

    result = _configoptions_helper.get_bool(test_key, default=default)
    if test_key in os.environ:
        del os.environ[test_key]

    assert result is expected


def test_get_bool_invalidvalue():
    test_key = "GFO_TEST_BOOL"
    with gfo.TempEnv({test_key: "INVALID"}):
        with pytest.raises(ValueError, match="invalid value for bool configoption"):
            _ = _configoptions_helper.get_bool(test_key, default="")


@pytest.mark.parametrize(
    "value, expected",
    [("TRUE", True), ("FALSE", False), (None, True)],
)
def test_remove_temp_files(value, expected):
    test_key = "GFO_REMOVE_TEMP_FILES"
    if value is None:
        if test_key in os.environ:
            del os.environ[test_key]
    else:
        os.environ[test_key] = value

    result = ConfigOptions.remove_temp_files
    if test_key in os.environ:
        del os.environ[test_key]

    assert result is expected
