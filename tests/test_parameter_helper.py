# -*- coding: utf-8 -*-
"""
Tests for functionalities in _processing_util.
"""

import re

import pytest

from geofileops.helpers import _parameter_helper


@pytest.mark.parametrize(
    "agg_columns_value",
    [
        None,
        {"columns": [{"column": "UIDN", "agg": "count", "as": "123"}]},
        {"json": ["UIDN", "OIDN"]},
        {"json": None},
    ],
)
def test_validate_agg_columns(agg_columns_value):
    _parameter_helper.validate_agg_columns(agg_columns=agg_columns_value)


@pytest.mark.parametrize(
    "expected_error, agg_columns_value",
    [
        ("agg_columns must be a dict with exactly one top-level key", {"a": 1, "b": 2}),
        ("agg_columns has invalid top-level key", {"a": 1}),
        ('agg_columns["columns"] does not contain a list of dicts', {"columns": 1}),
        (
            'agg_columns["columns"] does not contain a list of dicts',
            {"columns": {"column": "abc"}},
        ),
        (
            'agg_columns["columns"] list contains a non-dict element',
            {"columns": ["column", "abc"]},
        ),
        (
            'each dict in agg_columns["columns"] needs a "column" element',
            {"columns": [{"agg": "mean", "as": "uidn"}]},
        ),
        (
            'each dict in agg_columns["columns"] needs an "agg" element',
            {"columns": [{"column": "UIDN", "as": "uidn"}]},
        ),
        (
            'each dict in agg_columns["columns"] needs an "as" element',
            {"columns": [{"column": "UIDN", "agg": "mean"}]},
        ),
        (
            'agg_columns["columns"] contains unsupported aggregation NOK',
            {"columns": [{"column": "UIDN", "agg": "NOK", "as": "uidn"}]},
        ),
        (
            'agg_columns["columns"], "as" value should be string',
            {"columns": [{"column": "UIDN", "agg": "count", "as": 123}]},
        ),
        (
            'agg_columns["json"] does not contain a list of strings',
            {"json": {"column": "UIDN", "agg": "count", "as": 123}},
        ),
        (
            'agg_columns["json"] list contains a non-string element',
            {"json": [{"column": "UIDN", "agg": "count", "as": 123}]},
        ),
        (
            'agg_columns["json"] list contains a non-string element',
            {"json": ["UIDN", 123]},
        ),
    ],
)
def test_validate_agg_columns_invalid(expected_error, agg_columns_value):
    with pytest.raises(ValueError, match=re.escape(expected_error)):
        _parameter_helper.validate_agg_columns(agg_columns_value)
