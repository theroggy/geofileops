"""
Tests for functionalities in _general_util.
"""

import datetime
import os
import time

import pytest

import geofileops as gfo
from geofileops.util import _general_util


def test_formatbytes():
    bytes_str = _general_util.formatbytes(1)
    assert bytes_str == "1.0 Byte"
    bytes_str = _general_util.formatbytes(2)
    assert bytes_str == "2.0 Bytes"
    bytes_str = _general_util.formatbytes(1024.0)
    assert bytes_str == "1.00 KB"
    bytes_str = _general_util.formatbytes(1024.0**2)
    assert bytes_str == "1.00 MB"
    bytes_str = _general_util.formatbytes(1024.0**3)
    assert bytes_str == "1.00 GB"
    bytes_str = _general_util.formatbytes(1024.0**4)
    assert bytes_str == "1.00 TB"


def test_format_progress():
    start_time = datetime.datetime.now()
    nb_todo = 10000
    for nb_done in range(0, nb_todo + 1, 2000):
        message = _general_util.format_progress(
            start_time=start_time,
            nb_done=nb_done,
            nb_todo=nb_todo,
            operation="test",
            nb_parallel=2,
        )
        time.sleep(0.5)
        if message is not None:
            print(message)


@pytest.mark.parametrize(
    "key, value_orig, value_context, expected_context",
    [
        ("INT_IN_CONTEXT", "NUMERIC_VALUE_orig", 1234, "1234"),
        ("STRING_IN_CONTEXT", None, "STRING_VALUE_context", "STRING_VALUE_context"),
        ("NONE_IN_CONTEXT", "NONE_VALUE_orig", None, None),
        ("NONE_ALWAYS", None, None, None),
    ],
)
def test_TempEnv(key, value_orig, value_context, expected_context):
    """Test TempEnv context manager.

    This test checks if the environment variables are set correctly in the context
    and restored after the context ends.

    Also checks if multiple environment variables can be set in the context.
    """
    # Set the original value in the environment variable if needed
    assert key not in os.environ
    if value_orig is not None:
        os.environ[key] = value_orig

    # Test with 2 environment variables as TempEnv should support multiple keys
    key2 = "SECOND_KEY"
    value2_orig = "SECOND_VALUE_orig"
    value2_context = "SECOND_VALUE_context"
    os.environ[key2] = value2_orig

    # Check if the environment variables are properly set in the context
    with gfo.TempEnv({key: value_context, key2: value2_context}):
        if value_context is not None:
            assert os.environ[key] == expected_context
        else:
            assert key not in os.environ
        assert os.environ[key2] == value2_context

    # Check if the environment variables are restored after the context
    if value_orig is not None:
        assert os.environ[key] == value_orig
    else:
        assert key not in os.environ
    assert os.environ[key2] == value2_orig
