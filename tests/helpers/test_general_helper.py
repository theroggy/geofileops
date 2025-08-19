"""Tests for the general_helper module."""

import pytest

from geofileops.helpers import _general_helper
from geofileops.util import _general_util


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
