"""Tests for union_full_self operation."""

import math
from itertools import product
from pathlib import Path

import geopandas as gpd
import pytest
from shapely import MultiPolygon, box

import geofileops as gfo
from geofileops import GeometryType
from geofileops.geoops_sql import _union_full
from geofileops.util._geofileinfo import GeofileInfo
from geofileops.util._geopath_util import GeoPath
from tests import test_helper
from tests.test_helper import SUFFIXES_GEOOPS


@pytest.mark.parametrize(
    "intersections_as, columns",
    [
        ("COLUMNS", ["fid", "value"]),
        ("LISTS", ["fid", "value"]),
        ("COLUMNS", []),
        ("LISTS", []),
    ],
)
def test_get_union_full_attr_sql_stmt_no_cols(tmp_path, intersections_as, columns):
    # Having an existing file with a union_fid column is needed for intersections_as
    # NO_INTERSECTIONS_ATTRIBUTE_COLUMNS with columns.
    test_path = test_helper.get_testfile(
        "polygon-3overlappingcircles", dst_dir=tmp_path
    )
    gfo.add_column(test_path, name="union_fid", type="INT", expression=1)
    stmt = _union_full._get_union_full_attr_sql_stmt(
        union_multirow_path=test_path,
        intersections_as=intersections_as,
        columns=columns,
    )

    if columns == []:
        # When no columns are asked, no attribute handling should be done
        assert "CASE WHEN" not in stmt
        assert "json_group_array" not in stmt
    elif intersections_as == "COLUMNS":
        assert "CASE WHEN" in stmt
    elif intersections_as == "LISTS":
        assert "json_group_array" in stmt
    else:
        raise ValueError(f"Unsupported union_type for this test: {intersections_as}")


def test_get_union_full_attr_sql_stmt_invalid():
    with pytest.raises(ValueError, match="Unsupported union_type"):
        _ = _union_full._get_union_full_attr_sql_stmt(
            union_multirow_path=Path("file"),
            intersections_as="INVALID_TYPE",
            columns=[],
        )


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize(
    "testfile, nb_intersecting, intersections_as, exp_features",
    [
        ("polygon-3overlappingcircles", 3, "COLUMNS", 7),
        ("polygon-3overlappingcircles", 3, "LISTS", 7),
        ("polygon-3overlappingcircles", 3, "ROWS", 17),
        ("polygon-4overlappingcircles", 4, "COLUMNS", 11),
        ("polygon-4overlappingcircles", 4, "LISTS", 11),
        ("polygon-4overlappingcircles", 4, "ROWS", 28),
    ],
)
def test_union_full_self_circles(
    tmp_path,
    testfile: str,
    nb_intersecting,
    suffix: str,
    intersections_as,
    exp_features,
):
    # Prepare test data
    input_path = test_helper.get_testfile(testfile, suffix=suffix)
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    output_path = tmp_path / f"{GeoPath(input_path).stem}-output{suffix}"

    # Also run some tests on basic data with circles
    # Union the single circle towards the 2 circles
    gfo.union_full_self(
        input_path=input_path,
        output_path=output_path,
        intersections_as=intersections_as,
        batchsize=batchsize,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == exp_features
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Check columns
    nb_intersecting_column = None
    if intersections_as == "COLUMNS":
        # asked columns * nb_intersecting (=circles)
        asked_columns = list(input_layerinfo.columns)
        exp_columns = [
            f"i{idx}_{col}"
            for idx, col in product(range(1, nb_intersecting + 1), asked_columns)
        ]
    elif intersections_as == "LISTS":
        # asked columns + "nb_intersecting"
        asked_columns = list(input_layerinfo.columns)
        exp_columns = [col if col != "fid" else "fid_1" for col in asked_columns]
        nb_intersecting_column = (
            "nb_interse" if suffix in (".shp", ".shp.zip") else "nb_intersecting"
        )
        exp_columns += [nb_intersecting_column]
    elif intersections_as == "ROWS":
        # asked columns + "union_fid"
        asked_columns = list(input_layerinfo.columns)
        exp_columns = [col if col != "fid" else "fid_1" for col in asked_columns]
        exp_columns += ["union_fid"]
    else:
        raise ValueError(f"Unsupported for this test: {intersections_as=}")

    assert sorted(output_layerinfo.columns) == sorted(exp_columns)

    # Check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None

    # If there is a nb_intersecting column, check its max value
    if nb_intersecting_column is not None:
        assert nb_intersecting_column in output_gdf.columns
        assert output_gdf[nb_intersecting_column].max().item() == nb_intersecting
    else:
        assert nb_intersecting_column not in output_gdf.columns

    # For intersections_as="ROWS", the maximum number of rows with equal union_fid
    # should be the number of intersecting features in the input
    if intersections_as == "ROWS":
        assert (
            output_gdf.groupby("union_fid")["name"].count().max().item()
            == nb_intersecting
        )


@pytest.mark.parametrize("suffix", [".gpkg"])
@pytest.mark.parametrize(
    "nb_boxes, intersections_as, columns, explodecollections, exp_features",
    [
        (2, "COLUMNS", None, False, 3),
        (2, "COLUMNS", None, True, 4),
        (2, "COLUMNS", ["name"], False, 3),
        (2, "COLUMNS", ["fid", "value", "name"], False, 3),
        (3, "COLUMNS", None, False, 7),
        (4, "COLUMNS", None, False, 9),
        (5, "COLUMNS", ["fid", "value", "name"], False, 17),
        (2, "COLUMNS", [], False, 3),
        (3, "COLUMNS", [], False, 7),
        (4, "COLUMNS", [], False, 9),
        (5, "COLUMNS", [], False, 17),
        (5, "COLUMNS", [], True, 18),
        (2, "LISTS", None, False, 3),
        (2, "LISTS", [], False, 3),
        (3, "LISTS", None, False, 7),
        (4, "LISTS", None, False, 9),
        (4, "LISTS", None, True, 10),
        (4, "LISTS", [], True, 10),
        (5, "LISTS", ["fid", "value", "name"], False, 17),
        (2, "ROWS", None, False, 4),
        (3, "ROWS", None, False, 12),
        (4, "ROWS", None, False, 16),
        (4, "ROWS", None, True, 17),
        (5, "ROWS", ["fid", "value", "name"], False, 37),
    ],
)
def test_union_full_self_boxes(
    tmp_path,
    suffix,
    nb_boxes,
    intersections_as,
    columns,
    explodecollections,
    exp_features,
):
    # Prepare test data
    if nb_boxes == 2:
        boxes = [
            box(0, 0, 10, 10),
            MultiPolygon([box(8, 0, 18, 10), box(28, 0, 38, 10)]),
        ]
    elif nb_boxes == 3:
        boxes = [
            box(0, 0, 10, 10),
            MultiPolygon([box(8, 0, 18, 10), box(28, 0, 38, 10)]),
            box(5, 8, 15, 18),
        ]
    elif nb_boxes == 4:
        boxes = [
            box(0, 0, 10, 10),
            MultiPolygon([box(8, 0, 18, 10), box(28, 0, 38, 10)]),
            box(0, 8, 10, 18),
            box(8, 8, 18, 18),
        ]
    elif nb_boxes == 5:
        boxes = [
            box(0, 0, 10, 10),
            MultiPolygon([box(8, 0, 18, 10), box(28, 0, 38, 10)]),
            box(0, 8, 10, 18),
            box(8, 8, 18, 18),
            box(5, 5, 15, 15),
        ]
    else:
        raise ValueError(f"Unsupported number of boxes for this test {nb_boxes}.")

    batchsize = math.ceil(nb_boxes / 2)
    input_gdf = gpd.GeoDataFrame(
        {
            "geometry": boxes,
            "value": range(len(boxes)),
            "name": [f"box_{i}" for i in range(len(boxes))],
        },
        crs="EPSG:31370",
    )
    input_path = tmp_path / f"input_boxes-{nb_boxes}{suffix}"
    input_gdf.to_file(input_path)

    # Run test
    output_path = tmp_path / f"output_boxes-{nb_boxes}_{intersections_as}{suffix}"
    gfo.union_full_self(
        input_path=input_path,
        output_path=output_path,
        intersections_as=intersections_as,
        columns=columns,
        explodecollections=explodecollections,
        batchsize=batchsize,
    )

    # Check if the output file is correctly created
    input_layerinfo = gfo.get_layerinfo(input_path)
    asked_columns = columns if columns is not None else list(input_layerinfo.columns)
    nb_intersecting_column = None
    if intersections_as == "COLUMNS":
        # asked columns * nb_intersecting (=boxes)
        exp_columns = [
            f"i{idx + 1}_{col}"
            for idx, col in product(range(len(boxes)), asked_columns)
        ]
    elif intersections_as == "LISTS":
        # asked columns + "nb_intersecting"
        nb_intersecting_column = "nb_intersecting"
        exp_columns = [col if col != "fid" else "fid_1" for col in asked_columns]
        exp_columns += [nb_intersecting_column]
    elif intersections_as == "ROWS":
        # asked columns + "union_fid"
        exp_columns = [col if col != "fid" else "fid_1" for col in asked_columns]
        exp_columns += ["union_fid"]
    else:
        raise ValueError(f"Unsupported for this test: {intersections_as=}")

    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == exp_features
    assert sorted(output_layerinfo.columns) == sorted(exp_columns)

    if explodecollections:
        assert output_layerinfo.geometrytype == GeometryType.POLYGON
    else:
        assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
    if nb_intersecting_column is not None:
        assert nb_intersecting_column in output_gdf.columns
        assert output_gdf[nb_intersecting_column].max().item() == nb_boxes
    else:
        assert nb_intersecting_column not in output_gdf.columns

    # For intersections_as="ROWS", the maximum number of rows with equal union_fid
    # should be the number of intersecting features in the input
    if intersections_as == "ROWS":
        assert output_gdf.groupby("union_fid")["name"].count().max().item() == nb_boxes


@pytest.mark.parametrize(
    "intersections_as, exp_features",
    [
        ("COLUMNS", 3),
        ("LISTS", 3),
        ("ROWS", 4),
    ],
)
def test_union_full_self_fid_1_in_input(tmp_path, intersections_as, exp_features):
    """Test behaviour if the input file has already a column "fid_1."""
    # Prepare test data
    input_gdf = gpd.GeoDataFrame(
        {
            "geometry": [box(0, 0, 10, 10), box(8, 0, 18, 10)],
            "fid_1": [100, 200],
            "value": [1, 2],
            "name": ["box_1", "box_2"],
        },
        crs="EPSG:31370",
    )
    input_path = tmp_path / "input_fid_1.gpkg"
    input_gdf.to_file(input_path)

    # Run test
    output_path = tmp_path / "output_fid_1.gpkg"
    gfo.union_full_self(
        input_path=input_path,
        output_path=output_path,
        intersections_as=intersections_as,
        columns=["fid", "fid_1", "value", "name"],
    )

    # Check if the output file is correctly created
    assert output_path.exists()
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == exp_features

    # Check that the values for fid and fid_1 are correctly stored
    output_gdf = gfo.read_file(output_path)
    if intersections_as == "COLUMNS":
        assert "i1_fid" in output_gdf.columns
        assert "i2_fid" in output_gdf.columns
        assert "i1_fid_1" in output_gdf.columns
        assert "i2_fid_1" in output_gdf.columns
        assert all(output_gdf["i1_fid"] * 100 == output_gdf["i1_fid_1"])
    elif intersections_as == "LISTS":
        # The original "fid_1" column should stay "fid_1"
        assert "fid_1" in output_gdf.columns
        all(value in ["[100]", "[200]", "[100,200]"] for value in output_gdf["fid_1"])
        # The "fid" column asked will be aliased to "fid_2" as "fid_1" is already in use
        assert "fid_2" in output_gdf.columns
        all(value in ["[1]", "[2]", "[1,2]"] for value in output_gdf["fid_1"])
    elif intersections_as == "ROWS":
        # The original "fid_1" column should stay "fid_1"
        assert "fid_1" in output_gdf.columns
        all(value in ["100", "200"] for value in output_gdf["fid_1"])
        # The "fid" column asked will be aliased to "fid_2" as "fid_1" is already in use
        assert "fid_2" in output_gdf.columns
        all(value in ["1", "2"] for value in output_gdf["fid_2"])
    else:
        raise ValueError(f"Unsupported for this test: {intersections_as=}")


def test_union_full_self_force(tmp_path):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-3overlappingcircles", suffix=".gpkg")
    output_path = tmp_path / "output_force.gpkg"
    output_path.touch()

    # Test with force False (the default): existing output file should stay the same
    mtime_orig = output_path.stat().st_mtime
    gfo.union_full_self(
        input_path=input_path, output_path=output_path, intersections_as="COLUMNS"
    )
    assert output_path.stat().st_mtime == mtime_orig

    # With force=True
    gfo.union_full_self(
        input_path=input_path,
        output_path=output_path,
        intersections_as="COLUMNS",
        force=True,
    )
    assert output_path.stat().st_mtime != mtime_orig


@pytest.mark.parametrize(
    "kwargs, error_msg",
    [
        ({"subdivide_coords": -5}, "subdivide_coords < 0 is not allowed"),
        ({"intersections_as": "INVALID_TYPE"}, "intersections_as should be one of"),
    ],
)
def test_union_full_self_invalid_args(tmp_path, kwargs, error_msg):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-3overlappingcircles", suffix=".gpkg")
    output_path = tmp_path / "output_invalid.gpkg"

    if "intersections_as" not in kwargs:
        kwargs["intersections_as"] = "COLUMNS"
    with pytest.raises(ValueError, match=error_msg):
        gfo.union_full_self(
            input_path=input_path,
            output_path=output_path,
            **kwargs,
        )
