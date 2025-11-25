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


@pytest.mark.parametrize(
    "input_stem, output_stem, exp_error",
    [
        ("input", "input", "test: output_path must not equal input_path"),
        ("input", "output", "test: input_path not found"),
    ],
)
def test_validate_params_single_layer_errors(
    tmp_path, input_stem, output_stem, exp_error
):
    input_path = tmp_path / f"{input_stem}.gpkg"
    output_path = tmp_path / f"{output_stem}.gpkg"

    if "output_path must not equal" in exp_error:
        input_path.touch()

    with pytest.raises(Exception, match=exp_error):
        _parameter_helper.validate_params_single_layer(
            input_path=input_path,
            output_path=output_path,
            input_layer=None,
            output_layer=None,
            operation_name="test",
        )


@pytest.mark.parametrize(
    "input1_stem, input2_stem, output_stem, exp_error",
    [
        ("in1", "in2", "in1", "test: output_path must not equal one of input paths"),
        ("in1", "in2", "in2", "test: output_path must not equal one of input paths"),
        ("in1", "in2", "output", "test: input1_path not found"),
        ("in1", "in2", "output", "test: input2_path not found"),
    ],
)
def test_validate_params_two_layers_errors(
    tmp_path, input1_stem, input2_stem, output_stem, exp_error
):
    input1_path = tmp_path / f"{input1_stem}.gpkg"
    input2_path = tmp_path / f"{input2_stem}.gpkg"
    output_path = tmp_path / f"{output_stem}.gpkg"

    if "output_path must not equal" in exp_error:
        input1_path.touch()
        input2_path.touch()
    elif "input2_path not found" in exp_error:
        input1_path.touch()

    with pytest.raises(Exception, match=re.escape(exp_error)):
        _parameter_helper.validate_params_two_layers(
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=output_path,
            input1_layer=None,
            input2_layer=None,
            output_layer=None,
            operation_name="test",
        )
