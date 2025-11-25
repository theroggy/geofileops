"""Tests for the join operation."""

from pathlib import Path

import pandas as pd
import pytest

import geofileops as gfo
from tests import test_helper
from tests.test_helper import SUFFIXES_GEOOPS


@pytest.mark.parametrize("join_type", ["inner", "left"])
def test_join(tmp_path: Path, join_type):
    input1_path = test_helper.get_testfile("polygon-parcel")
    input2_path = tmp_path / "input2.gpkg"
    df2 = pd.DataFrame({"hfdtlt_code": ["60", "201"], "name": ["Grasland", "Silomaïs"]})
    gfo.to_file(df2, input2_path)
    input1_columns = ["lblhfdtlt", "hfdtlt"]
    input2_columns = ["name"]

    output_path = tmp_path / "output.gpkg"
    gfo.join(
        input1_path,
        input2_path,
        output_path,
        input1_on="hfdtlt",
        input2_on="hfdtlt_code",
        join_type=join_type,
        input1_columns=input1_columns,
        input2_columns=input2_columns,
        input1_columns_prefix="l1pr_",
        input2_columns_prefix="l2pr_",
    )

    # Check results
    input1_info = gfo.get_layerinfo(input1_path)
    output_info = gfo.get_layerinfo(output_path)
    input1_df = gfo.read_file(input1_path)

    inner_featurecount = len(
        input1_df[input1_df["HFDTLT"].isin(df2["hfdtlt_code"].tolist())]
    )
    exp_featurecount = (
        inner_featurecount if join_type == "inner" else input1_info.featurecount
    )
    assert output_info.featurecount == exp_featurecount
    assert output_info.geometrytypename == input1_info.geometrytypename
    exp_columns = len(input1_columns) + len(input2_columns)
    assert len(output_info.columns) == exp_columns

    # Check the result content
    output_df = gfo.read_file(output_path)
    if join_type == "left":
        # Check that non-matching rows have None in the joined columns
        assert (
            output_df["l2pr_name"].isna().sum()
            == output_info.featurecount - inner_featurecount
        )
    else:
        # Check that all rows have a match in the joined columns
        assert output_df["l2pr_name"].isna().sum() == 0
        # Check that the joined columns have correct values
        assert output_df["l2pr_name"].tolist() == output_df["l1pr_lblhfdtlt"].tolist()


@pytest.mark.parametrize(
    "input1_on, input2_on",
    [("fid", "fid"), (["fid"], ["fid"]), (["fid", "OIDN"], ["fid", "OIDN"])],
)
@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize("explodecollections", [False, True])
def test_join_self(tmp_path: Path, input1_on, input2_on, explodecollections, suffix):
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    output_path = tmp_path / "output.gpkg"
    gfo.join(
        input_path,
        input_path,
        output_path,
        input1_on=input1_on,
        input2_on=input2_on,
        explodecollections=explodecollections,
    )

    # Check results
    input_info = gfo.get_layerinfo(input_path)
    output_info = gfo.get_layerinfo(output_path)

    if not explodecollections:
        exp_featurecount = input_info.featurecount
    else:
        exp_featurecount = 50
        assert exp_featurecount > input_info.featurecount
    assert output_info.featurecount == exp_featurecount
    assert output_info.geometrytypename == input_info.geometrytypename
    assert len(output_info.columns) == 2 * len(input_info.columns)
    for column in output_info.columns:
        # The output columns will have the default prefixes "l1_" and "l2_"
        assert column.startswith(("l1_", "l2_"))


@pytest.mark.parametrize(
    "kwargs, error",
    [
        (
            {"input1_on": ["fid", "OIDN"], "input2_on": ["fid"]},
            "input1_on and input2_on must have the same length",
        ),
        (
            {"input1_on": ["fid"], "input2_on": ["fid", "OIDN"]},
            "input1_on and input2_on must have the same length",
        ),
        (
            {"input1_on": "fid", "input2_on": "fid", "join_type": "invalid"},
            "Unsupported join_type 'invalid'",
        ),
    ],
)
def test_join_invalid_params(tmp_path: Path, kwargs, error):
    input1_path = test_helper.get_testfile("polygon-parcel", tmp_path)
    input2_path = test_helper.get_testfile("polygon-twolayers", tmp_path)

    output_path = tmp_path / "output.gpkg"

    with pytest.raises(ValueError, match=error):
        gfo.join(
            input1_path,
            input2_path,
            output_path,
            input2_layer="parcels",
            **kwargs,
        )
