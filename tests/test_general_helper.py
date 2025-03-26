"""Tests for the general_helper module."""

import pytest

from geofileops.helpers import _general_helper
from geofileops.util import _general_util


@pytest.mark.parametrize(
    "worker_type, input_layer_featurecount",
    [("process", 1), ("thread", 101), ("auto", 1), ("auto", 100), ("auto", 101)],
)
def test_use_threads(worker_type, input_layer_featurecount):
    if worker_type == "process":
        expected = False
    elif worker_type == "thread":
        expected = True
    elif input_layer_featurecount <= 100:
        expected = True
    else:
        expected = False

    with _general_util.TempEnv({"GFO_WORKER_TYPE": worker_type}):
        assert _general_helper.use_threads(input_layer_featurecount) == expected
