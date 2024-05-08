"""
Tests for operations that are executed using a sql statement on two layers.
"""

from contextlib import nullcontext
import math
from pathlib import Path
import sys
from typing import Optional

import geopandas as gpd
import pandas as pd
import pytest
import shapely
import shapely.geometry as sh_geom

import geofileops as gfo
from geofileops import GeometryType
from geofileops._compat import SPATIALITE_GTE_51
from geofileops.util import _geofileinfo
from geofileops.util._geofileinfo import GeofileInfo
from geofileops.util import _geoops_sql as geoops_sql
from tests import test_helper
from tests.test_helper import SUFFIXES_GEOOPS, TESTFILES
from tests.test_helper import assert_geodataframe_equal


@pytest.mark.parametrize("testfile", TESTFILES)
@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
def test_clip(tmp_path, testfile, suffix):
    input_path = test_helper.get_testfile(testfile, suffix=suffix)
    clip_path = test_helper.get_testfile("polygon-zone", suffix=suffix)
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    gfo.clip(
        input_path=str(input_path),
        clip_path=str(clip_path),
        output_path=str(output_path),
        where_post=None,
        batchsize=batchsize,
    )

    # Compare result with geopandas
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_gdf = gfo.read_file(output_path)
    input_gdf = gfo.read_file(input_path)
    clip_gdf = gfo.read_file(clip_path)
    output_gpd_gdf = gpd.clip(input_gdf, clip_gdf, keep_geom_type=True)
    assert_geodataframe_equal(
        output_gdf, output_gpd_gdf, promote_to_multi=True, sort_values=True
    )


@pytest.mark.parametrize("suffix", [".gpkg", ".shp"])
@pytest.mark.parametrize("clip_empty", [True, False])
def test_clip_resultempty(tmp_path, suffix, clip_empty):
    # Prepare test data
    # -----------------
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    if clip_empty:
        clip_path = test_helper.get_testfile(
            "polygon-zone", suffix=suffix, dst_dir=tmp_path, empty=True
        )
    else:
        input2_data = [
            {"desc": "input2_1", "geometry": shapely.box(5, 5, 1000, 1000)},
            {"desc": "input2_2", "geometry": shapely.box(2000, 5, 3000, 1000)},
        ]
        clip_gdf = gpd.GeoDataFrame(input2_data, crs=31370)
        clip_path = tmp_path / f"input2{suffix}"
        gfo.to_file(clip_gdf, clip_path)

    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Now run test
    # ------------
    output_path = tmp_path / f"{input_path.stem}_clip_{clip_path.stem}{suffix}"
    gfo.clip(
        input_path=input_path,
        clip_path=clip_path,
        output_path=output_path,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Check if the output file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 0
    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize(
    "testfile, gridsize, where_post, subdivide_coords",
    [
        ("linestring-row-trees", 0.0, "ST_Length(geom) > 100", None),
        ("linestring-row-trees", 0.01, None, 0),
        ("point", 0.0, None, None),
        ("point", 0.01, None, 0),
        ("polygon-parcel", 0.0, None, None),
        ("polygon-parcel", 0.0, "ST_Area(geom) > 2000", 0),
        ("polygon-parcel", 0.01, None, 0),
    ],
)
def test_erase(tmp_path, suffix, testfile, gridsize, where_post, subdivide_coords):
    input_path = test_helper.get_testfile(testfile, suffix=suffix)
    if suffix == ".shp":
        erase_path = test_helper.get_testfile("polygon-zone", suffix=suffix)
        erase_layer = None
    else:
        erase_path = test_helper.get_testfile("polygon-twolayers", suffix=suffix)
        erase_layer = "zones"
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"

    kwargs = {}
    if subdivide_coords is not None:
        kwargs["subdivide_coords"] = subdivide_coords

    gfo.erase(
        input_path=str(input_path),
        erase_path=str(erase_path),
        erase_layer=erase_layer,
        output_path=str(output_path),
        gridsize=gridsize,
        where_post=where_post,
        batchsize=batchsize,
        **kwargs,
    )

    # Compare result with geopandas
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_gdf = gfo.read_file(output_path)
    input_gdf = gfo.read_file(input_path)
    erase_gdf = gfo.read_file(erase_path, layer=erase_layer)

    # Prepare expected gdf
    exp_gdf = gpd.overlay(input_gdf, erase_gdf, how="difference", keep_geom_type=True)
    if gridsize != 0.0:
        exp_gdf.geometry = shapely.set_precision(exp_gdf.geometry, grid_size=gridsize)
    if where_post is not None:
        if where_post == "ST_Area(geom) > 2000":
            exp_gdf = exp_gdf[exp_gdf.geometry.area > 2000]
        elif where_post == "ST_Length(geom) > 100":
            exp_gdf = exp_gdf[exp_gdf.geometry.length > 100]
        else:
            raise ValueError(f"where_post filter not implemented: {where_post}")
    # Remove rows where geometry is empty or None
    exp_gdf = exp_gdf[~exp_gdf.geometry.isna()]
    exp_gdf = exp_gdf[~exp_gdf.geometry.is_empty]

    if test_helper.RUNS_LOCAL:
        output_exp_path = tmp_path / f"{input_path.stem}-expected{suffix}"
        gfo.to_file(exp_gdf, output_exp_path)

    assert_geodataframe_equal(
        output_gdf,
        exp_gdf,
        promote_to_multi=True,
        sort_values=True,
        check_less_precise=True,
        normalize=True,
    )

    # Make sure the output still has rows, otherwise the test isn't super useful
    assert len(output_gdf) > 0


def test_erase_explodecollections(tmp_path):
    input_path = test_helper.get_testfile("polygon-parcel")
    erase_path = test_helper.get_testfile("polygon-zone")
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    output_path = tmp_path / f"{input_path.stem}-output_exploded{input_path.suffix}"
    gfo.erase(
        input_path=input_path,
        erase_path=erase_path,
        output_path=output_path,
        explodecollections=True,
        batchsize=batchsize,
    )

    # Compare result with geopandas
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_gdf = gfo.read_file(output_path)
    input_gdf = gfo.read_file(input_path)
    erase_gdf = gfo.read_file(erase_path)
    output_gpd_gdf = gpd.overlay(
        input_gdf, erase_gdf, how="difference", keep_geom_type=True
    )
    output_gpd_gdf = output_gpd_gdf.explode(ignore_index=True)
    assert_geodataframe_equal(
        output_gdf,
        output_gpd_gdf,
        promote_to_multi=True,
        sort_values=True,
        check_less_precise=True,
        normalize=True,
    )


def test_erase_force(tmp_path):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel")
    erase_path = test_helper.get_testfile("polygon-zone")
    output_path = tmp_path / f"output{input_path.suffix}"
    output_path.touch()

    # Test with force False (the default): existing output file should stay the same
    mtime_orig = output_path.stat().st_mtime
    gfo.erase(
        input_path=input_path,
        erase_path=erase_path,
        output_path=output_path,
    )
    assert output_path.stat().st_mtime == mtime_orig

    # With force=True
    gfo.erase(
        input_path=input_path,
        erase_path=erase_path,
        output_path=output_path,
        force=True,
    )
    assert output_path.stat().st_mtime != mtime_orig


@pytest.mark.parametrize(
    "kwargs, expected_error",
    [
        ({"erase_path": None}, "erase_layer must be None if erase_path is None"),
        ({"subdivide_coords": -1}, "subdivide_coords < 0 is not allowed"),
    ],
)
def test_erase_invalid_params(kwargs, expected_error):
    if "erase_path" not in kwargs:
        kwargs["erase_path"] = "erase.gpkg"
    with pytest.raises(ValueError, match=expected_error):
        gfo.erase(
            input_path="input.gpkg",
            output_path="output.gpkg",
            erase_layer="invalid",
            **kwargs,
        )


@pytest.mark.parametrize("subdivide_coords", [2000, 5])
def test_erase_self(tmp_path, subdivide_coords):
    input_path = test_helper.get_testfile("polygon-overlappingcircles-all")
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Now run test
    output_path = tmp_path / f"{input_path.stem}_erase_self.gpkg"
    gfo.erase(
        input_path=input_path,
        erase_path=None,
        output_path=output_path,
        subdivide_coords=subdivide_coords,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)
    assert output_layerinfo.featurecount == 3


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
def test_erase_subdivide_multipolygons(tmp_path, suffix):
    """
    Test if erase with subdivide also works if the erase layer contains multipolygons.

    It seems spatialite function ST_AsBinary, ST_GeomFromWKB and/or ST_Collect have
    issues processing nested multi-types (e.g. a GeometryCollection containing e.g.
    MultiPolygons).
    """
    # Prepare test data
    input_path = test_helper.get_testfile("point", suffix=suffix)
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Prepare erase test data: should be multipolygons for good test coverage
    zone_path = test_helper.get_testfile("polygon-zone", suffix=suffix)
    zones_gdf = gfo.read_file(zone_path)

    erase_geometries = [
        {"desc": "erase1", "geometry": zones_gdf.geometry[4]},
        {
            "desc": "erase2",
            "geometry": sh_geom.MultiPolygon(
                [
                    zones_gdf.geometry[0],
                    zones_gdf.geometry[1],
                    zones_gdf.geometry[2],
                    zones_gdf.geometry[3],
                ]
            ),
        },
    ]
    erase_gdf = gpd.GeoDataFrame(erase_geometries, crs=31370)
    erase_path = tmp_path / f"{zone_path.stem}_multi{suffix}"
    gfo.to_file(erase_gdf, erase_path)

    output_path = tmp_path / f"{input_path.stem}-output_exploded{suffix}"
    gfo.erase(
        input_path=input_path,
        erase_path=erase_path,
        output_path=output_path,
        batchsize=batchsize,
        subdivide_coords=10,
    )

    # Compare result with geopandas
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_gdf = gfo.read_file(output_path)
    input_gdf = gfo.read_file(input_path)
    output_gpd_gdf = gpd.overlay(
        input_gdf, erase_gdf, how="difference", keep_geom_type=True
    )
    output_gpd_gdf = output_gpd_gdf.explode(ignore_index=True)
    assert_geodataframe_equal(
        output_gdf,
        output_gpd_gdf,
        promote_to_multi=True,
        sort_values=True,
        check_less_precise=True,
        normalize=True,
    )


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize(
    "columns, gridsize, where_post, subdivide_coords, exp_featurecount",
    [
        (["OIDN", "UIDN"], 0.0, "ST_Area(geom) > 2000", 0, 25),
        (None, 0.01, None, 10, 27),
    ],
)
def test_export_by_location(
    tmp_path,
    suffix,
    columns,
    gridsize,
    where_post,
    subdivide_coords,
    exp_featurecount,
):
    input_to_select_from_path = test_helper.get_testfile(
        "polygon-parcel", suffix=suffix
    )
    input_to_compare_with_path = test_helper.get_testfile("polygon-zone", suffix=suffix)
    output_path = tmp_path / f"{input_to_select_from_path.stem}-output{suffix}"
    input_layerinfo = gfo.get_layerinfo(input_to_select_from_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Test
    gfo.export_by_location(
        input_to_select_from_path=str(input_to_select_from_path),
        input_to_compare_with_path=str(input_to_compare_with_path),
        output_path=str(output_path),
        input1_columns=columns,
        gridsize=gridsize,
        where_post=where_post,
        subdivide_coords=subdivide_coords,
        batchsize=batchsize,
    )

    # Check if the output file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(output_path)
    exp_columns = len(input_layerinfo.columns) if columns is None else len(columns)
    assert len(output_layerinfo.columns) == exp_columns
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON
    assert output_layerinfo.featurecount == exp_featurecount

    # Check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None


@pytest.mark.parametrize(
    "query, area_inters_column_name, min_area_intersect, subdivide_coords, "
    "exp_featurecount",
    [
        (None, None, None, 10, 27),
        (None, "area_custom", None, 0, 27),
        ("within is False", "area_custom", None, 0, 39),
        (None, None, 1000, 10, 24),
        ("within is False", None, 1000, 0, 15),
    ],
)
def test_export_by_location_area(
    tmp_path,
    query,
    area_inters_column_name,
    min_area_intersect,
    subdivide_coords,
    exp_featurecount,
):
    input_to_select_from_path = test_helper.get_testfile("polygon-parcel")
    input_to_compare_with_path = test_helper.get_testfile("polygon-zone")
    output_path = tmp_path / f"{input_to_select_from_path.stem}-output.gpkg"
    input_layerinfo = gfo.get_layerinfo(input_to_select_from_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Test
    kwargs = {}
    if query is not None:
        kwargs["spatial_relations_query"] = query
    gfo.export_by_location(
        input_to_select_from_path=str(input_to_select_from_path),
        input_to_compare_with_path=str(input_to_compare_with_path),
        output_path=str(output_path),
        area_inters_column_name=area_inters_column_name,
        min_area_intersect=min_area_intersect,
        batchsize=batchsize,
        subdivide_coords=subdivide_coords,
        **kwargs,
    )

    # Check if the output file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(output_path)
    exp_columns = len(input_layerinfo.columns)
    exp_area_inters_column_name = area_inters_column_name
    if exp_area_inters_column_name is None and min_area_intersect is not None:
        exp_area_inters_column_name = "area_inters"
    if exp_area_inters_column_name is not None:
        exp_columns += 1
        assert exp_area_inters_column_name in output_layerinfo.columns
    assert len(output_layerinfo.columns) == exp_columns
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON
    assert output_layerinfo.featurecount == exp_featurecount

    # Check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None

    # If an area column name is specified, check the number of None values
    # (= number features without intersection)
    if area_inters_column_name is not None:
        exp_nb_None = 21 if query == "within is False" else 0
        assert len(output_gdf[output_gdf.area_custom.isna()]) == exp_nb_None


def test_export_by_location_force(tmp_path):
    # Prepare test data
    input1_path = test_helper.get_testfile("polygon-parcel")
    input2_path = test_helper.get_testfile("polygon-zone")
    output_path = tmp_path / f"output{input1_path.suffix}"
    output_path.touch()

    # Test with force False (the default): existing output file should stay the same
    mtime_orig = output_path.stat().st_mtime
    gfo.export_by_location(
        input_to_select_from_path=input1_path,
        input_to_compare_with_path=input2_path,
        output_path=output_path,
    )
    assert output_path.stat().st_mtime == mtime_orig

    # With force=True
    gfo.export_by_location(
        input_to_select_from_path=input1_path,
        input_to_compare_with_path=input2_path,
        output_path=output_path,
        force=True,
    )
    assert output_path.stat().st_mtime != mtime_orig


@pytest.mark.parametrize(
    "kwargs, expected_error",
    [
        ({"subdivide_coords": -1}, "subdivide_coords < 0 is not allowed"),
    ],
)
def test_export_by_location_invalid_params(kwargs, expected_error):
    with pytest.raises(ValueError, match=expected_error):
        gfo.export_by_location(
            input_to_select_from_path="input.gpkg",
            input_to_compare_with_path="input2.gpkg",
            output_path="output.gpkg",
            **kwargs,
        )


@pytest.mark.parametrize(
    "query, subdivide_coords, exp_featurecount",
    [
        ("intersects is True or intersects is False", 0, 48),
        ("intersects is True", 10, 27),
        ("within is True", 0, 8),
        ("intersects is False", 10, 21),
        ("within is False", 10, 39),
        ("disjoint is True", 0, 21),
    ],
)
def test_export_by_location_query(tmp_path, query, subdivide_coords, exp_featurecount):
    input_to_select_from_path = test_helper.get_testfile("polygon-parcel")
    input_to_compare_with_path = test_helper.get_testfile("polygon-zone")
    output_path = tmp_path / f"{input_to_select_from_path.stem}-output.gpkg"
    input_layerinfo = gfo.get_layerinfo(input_to_select_from_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Test
    gfo.export_by_location(
        input_to_select_from_path=str(input_to_select_from_path),
        input_to_compare_with_path=str(input_to_compare_with_path),
        output_path=str(output_path),
        spatial_relations_query=query,
        batchsize=batchsize,
        subdivide_coords=subdivide_coords,
    )

    # Check if the output file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(output_path)
    exp_columns = len(input_layerinfo.columns)
    assert len(output_layerinfo.columns) == exp_columns
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON
    assert output_layerinfo.featurecount == exp_featurecount

    # Check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None


@pytest.mark.parametrize("testfile", ["polygon-parcel"])
@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
def test_export_by_distance(tmp_path, testfile, suffix):
    input_to_select_from_path = test_helper.get_testfile(testfile, suffix=suffix)
    input_to_compare_with_path = test_helper.get_testfile("polygon-zone", suffix=suffix)
    input_layerinfo = gfo.get_layerinfo(input_to_select_from_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    output_path = tmp_path / f"{input_to_select_from_path.stem}-output{suffix}"

    # Test
    gfo.export_by_distance(
        input_to_select_from_path=str(input_to_select_from_path),
        input_to_compare_with_path=str(input_to_compare_with_path),
        max_distance=10,
        output_path=str(output_path),
        batchsize=batchsize,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(input_to_select_from_path)
    assert input_layerinfo.featurecount == output_layerinfo.featurecount
    assert len(input_layerinfo.columns) == len(output_layerinfo.columns)
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Check the contents of the result file
    # TODO: this test should be more elaborate...
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None


@pytest.mark.parametrize(
    "suffix, epsg, gridsize",
    [(".gpkg", 31370, 0.01), (".gpkg", 4326, 0.0), (".shp", 31370, 0.01)],
)
def test_identity(tmp_path, suffix, epsg, gridsize):
    # Prepare test data
    input1_path = test_helper.get_testfile("polygon-parcel", suffix=suffix, epsg=epsg)
    input2_path = test_helper.get_testfile("polygon-zone", suffix=suffix, epsg=epsg)
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)
    output_path = tmp_path / f"{input1_path.stem}-output{suffix}"

    # Test
    gfo.identity(
        input1_path=str(input1_path),
        input2_path=str(input2_path),
        output_path=str(output_path),
        gridsize=gridsize,
        batchsize=batchsize,
    )

    # Check if the output file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    input2_layerinfo = gfo.get_layerinfo(input2_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert (len(input1_layerinfo.columns) + len(input2_layerinfo.columns)) == len(
        output_layerinfo.columns
    )
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None

    # Prepare expected gdf
    input1_gdf = gfo.read_file(input1_path)
    input2_gdf = gfo.read_file(input2_path)
    exp_gdf = input1_gdf.overlay(input2_gdf, how="identity", keep_geom_type=True)
    renames = dict(zip(exp_gdf.columns, output_gdf.columns))
    exp_gdf = exp_gdf.rename(columns=renames)
    if gridsize != 0.0:
        exp_gdf.geometry = shapely.set_precision(exp_gdf.geometry, grid_size=gridsize)
    # Remove rows where geometry is empty or None
    exp_gdf = exp_gdf[~exp_gdf.geometry.isna()]
    exp_gdf = exp_gdf[~exp_gdf.geometry.is_empty]

    # OIDN is float vs int? -> check_column_type=False
    assert_geodataframe_equal(
        output_gdf,
        exp_gdf,
        promote_to_multi=True,
        sort_values=True,
        check_less_precise=True,
        normalize=True,
        check_dtype=False,
    )


def test_identity_force(tmp_path):
    # Prepare test data
    input1_path = test_helper.get_testfile("polygon-parcel")
    input2_path = test_helper.get_testfile("polygon-zone")
    output_path = tmp_path / f"output{input1_path.suffix}"
    output_path.touch()

    # Test with force False (the default): existing output file should stay the same
    mtime_orig = output_path.stat().st_mtime
    gfo.identity(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
    )
    assert output_path.stat().st_mtime == mtime_orig

    # With force=True
    gfo.identity(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        force=True,
    )
    assert output_path.stat().st_mtime != mtime_orig


@pytest.mark.parametrize(
    "kwargs, expected_error",
    [
        (
            {"input2_path": None, "input2_layer": "invalid"},
            "input2_layer must be None if input2_path is None",
        ),
        ({"subdivide_coords": -1}, "subdivide_coords < 0 is not allowed"),
    ],
)
def test_identity_invalid_params(kwargs, expected_error):
    if "input2_path" not in kwargs:
        kwargs["input2_path"] = "input2.gpkg"
    with pytest.raises(ValueError, match=expected_error):
        gfo.identity(
            input1_path="input1.gpkg",
            output_path="output.gpkg",
            **kwargs,
        )


def test_identity_self(tmp_path):
    input1_path = test_helper.get_testfile("polygon-overlappingcircles-all")
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)

    # Now run test
    output_path = tmp_path / f"{input1_path.stem}_identity_self.gpkg"
    gfo.identity(
        input1_path=input1_path,
        input2_path=None,
        output_path=output_path,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert len(output_layerinfo.columns) == 2 * len(input1_layerinfo.columns)
    assert output_layerinfo.featurecount == 9


@pytest.mark.parametrize("testfile", ["polygon-parcel"])
@pytest.mark.parametrize(
    "suffix, epsg, gridsize, explodecollections, nb_parallel",
    [
        (".gpkg", 31370, 0.0, True, 1),
        (".gpkg", 31370, 0.01, True, 1),
        (".gpkg", 31370, 0.0, False, 2),
        (".gpkg", 4326, 0.0, True, 2),
        (".shp", 31370, 0.0, True, 1),
        (".shp", 31370, 0.0, False, 2),
    ],
)
def test_intersection(
    tmp_path, testfile, suffix, epsg, explodecollections, gridsize, nb_parallel
):
    input1_path = test_helper.get_testfile(testfile, suffix=suffix, epsg=epsg)
    input2_path = test_helper.get_testfile("polygon-zone", suffix=suffix, epsg=epsg)

    # Now run test
    output_path = (
        tmp_path / f"{input1_path.stem}_intersection_{input2_path.stem}{suffix}"
    )
    batchsize = -1
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    if nb_parallel > 1:
        batchsize = math.ceil(input1_layerinfo.featurecount / 2)
    gfo.intersection(
        input1_path=str(input1_path),
        input2_path=str(input2_path),
        output_path=str(output_path),
        gridsize=gridsize,
        explodecollections=explodecollections,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    input2_layerinfo = gfo.get_layerinfo(input2_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert len(output_layerinfo.columns) == (
        len(input1_layerinfo.columns) + len(input2_layerinfo.columns)
    )

    if explodecollections and suffix != ".shp":
        assert output_layerinfo.geometrytype == GeometryType.POLYGON
    else:
        assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    if explodecollections:
        assert output_layerinfo.featurecount == 31
    else:
        assert output_layerinfo.featurecount == 30

    # Check the contents of the result file by comparing with geopandas
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None

    input1_gdf = gfo.read_file(input1_path)
    input2_gdf = gfo.read_file(input2_path)
    overlay_operation = "intersection"
    expected_gdf = input1_gdf.overlay(
        input2_gdf, how=overlay_operation, keep_geom_type=True
    )
    renames = dict(zip(expected_gdf.columns, output_gdf.columns))
    expected_gdf = expected_gdf.rename(columns=renames)
    if gridsize != 0.0:
        expected_gdf.geometry = shapely.set_precision(
            expected_gdf.geometry, grid_size=gridsize
        )
    if explodecollections:
        expected_gdf = expected_gdf.explode(ignore_index=True)
    assert_geodataframe_equal(
        output_gdf, expected_gdf, check_dtype=False, sort_values=True
    )


def test_intersection_input_no_index(tmp_path):
    """
    Test if intersection works if the input gpkg files don't have a spatial index.
    """
    input1_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    input2_path = test_helper.get_testfile("polygon-zone", dst_dir=tmp_path)
    gfo.remove_spatial_index(input1_path)
    gfo.remove_spatial_index(input2_path)

    # Now run test
    output_path = tmp_path / f"{input1_path.stem}_intersection_{input2_path.stem}.gpkg"
    gfo.intersection(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()


@pytest.mark.parametrize(
    "expected_error, expected_exception, input1_path, input2_path, output_path",
    [
        (
            "intersection: output_path must not equal one of input paths",
            ValueError,
            test_helper.get_testfile("polygon-parcel"),
            test_helper.get_testfile("polygon-zone"),
            test_helper.get_testfile("polygon-parcel"),
        ),
        (
            "intersection: output_path must not equal one of input paths",
            ValueError,
            test_helper.get_testfile("polygon-parcel"),
            test_helper.get_testfile("polygon-zone"),
            test_helper.get_testfile("polygon-zone"),
        ),
        (
            "not_existing_path: No such file or directory",
            RuntimeError,
            "not_existing_path",
            test_helper.get_testfile("polygon-zone"),
            "output.gpkg",
        ),
        (
            "not_existing_path: No such file or directory",
            RuntimeError,
            test_helper.get_testfile("polygon-zone"),
            "not_existing_path",
            "output.gpkg",
        ),
        (
            "Output directory does not exist:",
            ValueError,
            test_helper.get_testfile("polygon-parcel"),
            test_helper.get_testfile("polygon-zone"),
            "output/output.gpkg",
        ),
    ],
)
def test_intersection_invalid_params(
    tmp_path, input1_path, input2_path, output_path, expected_exception, expected_error
):
    if isinstance(output_path, str):
        output_path = tmp_path / output_path
    with pytest.raises(expected_exception, match=expected_error):
        gfo.intersection(
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=output_path,
        )


@pytest.mark.parametrize(
    "kwargs, expected_error",
    [
        (
            {"input2_path": None, "input2_layer": "invalid"},
            "input2_layer must be None if input2_path is None",
        )
    ],
)
def test_intersection_invalid_params2(kwargs, expected_error):
    if "input2_path" not in kwargs:
        kwargs["input2_path"] = "input2.gpkg"
    with pytest.raises(ValueError, match=expected_error):
        gfo.intersection(
            input1_path="input1.gpkg",
            output_path="output.gpkg",
            **kwargs,
        )


def test_intersection_output_path_exists(tmp_path):
    # Prepare test data
    input1_path = test_helper.get_testfile("polygon-parcel")
    input2_path = test_helper.get_testfile("polygon-parcel")

    # Now run test
    output_path = test_helper.get_testfile("polygon-zone")
    assert output_path.exists()
    gfo.intersection(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        force=False,
    )

    # The output file should still be there
    assert output_path.exists()


@pytest.mark.parametrize("suffix", [".gpkg", ".shp"])
@pytest.mark.parametrize("input2_empty", [True, False])
def test_intersection_resultempty(tmp_path, suffix, input2_empty):
    # Prepare test data
    # -----------------
    input1_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    if input2_empty:
        input2_path = test_helper.get_testfile(
            "polygon-zone", suffix=suffix, dst_dir=tmp_path, empty=True
        )
    else:
        input2_data = [
            {"desc": "input2_1", "geometry": shapely.box(5, 5, 1000, 1000)},
            {"desc": "input2_2", "geometry": shapely.box(2000, 5, 3000, 1000)},
        ]
        input2_gdf = gpd.GeoDataFrame(input2_data, crs=31370)
        input2_path = tmp_path / f"input2{suffix}"
        gfo.to_file(input2_gdf, input2_path)

    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)

    # Now run test
    # ------------
    output_path = (
        tmp_path / f"{input1_path.stem}_intersection_{input2_path.stem}{suffix}"
    )
    gfo.intersection(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Check if the output file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 0
    input2_layerinfo = gfo.get_layerinfo(input2_path)
    assert len(output_layerinfo.columns) == (
        len(input1_layerinfo.columns) + len(input2_layerinfo.columns)
    )
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON


def test_intersection_self(tmp_path):
    input1_path = test_helper.get_testfile("polygon-overlappingcircles-all")
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)

    # Now run test
    output_path = tmp_path / f"{input1_path.stem}_inters_self.gpkg"
    gfo.intersection(
        input1_path=input1_path,
        input2_path=None,
        output_path=output_path,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert len(output_layerinfo.columns) == 2 * len(input1_layerinfo.columns)
    assert output_layerinfo.featurecount == 6


@pytest.mark.parametrize("testfile", ["polygon-parcel"])
@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
def test_intersection_columns_fid(tmp_path, testfile, suffix):
    input1_path = test_helper.get_testfile(testfile, suffix=suffix)
    input2_path = test_helper.get_testfile("polygon-zone", suffix=suffix)
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)

    # Now run test
    output_path = (
        tmp_path / f"{input1_path.stem}_intersection_{input2_path.stem}{suffix}"
    )
    # Also check if fid casing is preserved in output
    input1_columns = ["lblhfdtlt", "fid"]
    input2_columns = ["naam", "FiD"]
    gfo.intersection(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        input1_columns=input1_columns,
        input2_columns=input2_columns,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert len(output_layerinfo.columns) == len(input1_columns) + len(input2_columns)
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON
    assert output_layerinfo.featurecount == 30

    # Check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
    assert "l1_fid" in output_gdf.columns
    assert "l2_FiD" in output_gdf.columns
    if _geofileinfo.get_geofileinfo(input2_path).is_fid_zerobased:
        assert sorted(output_gdf.l2_FiD.unique().tolist()) == [0, 1, 2, 3, 4]
    else:
        assert sorted(output_gdf.l2_FiD.unique().tolist()) == [1, 2, 3, 4, 5]


@pytest.mark.parametrize(
    "suffix, explodecollections, where_post, exp_featurecount",
    [
        (".gpkg", False, None, 30),
        (".gpkg", True, None, 31),
        (".gpkg", False, "ST_Area(geom) > 1000", 26),
        (".shp", False, "ST_Area(geom) > 1000", 26),
        (".gpkg", True, "ST_Area(geom) > 1000", 27),
        (".shp", True, "ST_Area(geom) > 1000", 27),
    ],
)
def test_intersection_where_post(
    tmp_path, suffix, explodecollections, where_post, exp_featurecount
):
    """Test intersection with where_post parameter."""
    # TODO: test data should be changed so explodecollections results in more rows
    # without where_post already!!!
    input1_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    input2_path = test_helper.get_testfile("polygon-zone", suffix=suffix)

    # Now run test
    output_path = (
        tmp_path / f"{input1_path.stem}_intersection_{input2_path.stem}{suffix}"
    )
    batchsize = -1
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)
    gfo.intersection(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        explodecollections=explodecollections,
        where_post=where_post,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    input2_layerinfo = gfo.get_layerinfo(input2_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert len(output_layerinfo.columns) == (
        len(input1_layerinfo.columns) + len(input2_layerinfo.columns)
    )
    if explodecollections and suffix != ".shp":
        assert output_layerinfo.geometrytype == GeometryType.POLYGON
    else:
        assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    assert output_layerinfo.featurecount == exp_featurecount

    # Check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None


def test_prepare_spatial_relations_filter():
    # Test all existing named relations
    named_relations = [
        "equals",
        "touches",
        "within",
        "overlaps",
        "crosses",
        "intersects",
        "contains",
        "covers",
        "coveredby",
    ]
    for relation in named_relations:
        query = f"{relation} is True"
        filter = geoops_sql._prepare_spatial_relations_filter(query)
        assert filter is not None and filter != ""

    # Test extra queries that should work
    ok_queries = [
        "intersects is False",
        "(intersects is False and within is True) and crosses is False"
        "(((T******** is False)))",
    ]
    for query in ok_queries:
        filter = geoops_sql._prepare_spatial_relations_filter(query)
        assert filter is not None and filter != ""

    # Test queries that should fail
    error_queries = [
        ("Intersects is False", "named relations should be in lowercase"),
        ("intersects Is False", "is should be in lowercase"),
        ("intersects is false", "false should be False"),
        ("intersects = false", "= should be is"),
        ("(intersects is False", "not all brackets are closed"),
        ("intersects is False)", "more closing brackets then opened ones"),
        ("T**T**T* is False", "predicate should be 9 characters, not 8"),
        ("T**T**T**T is False", "predicate should be 9 characters, not 10"),
        ("A**T**T** is False", "A is not a valid character in a predicate"),
        ("'T**T**T**' is False", "predicates should not be quoted"),
        ("[T**T**T** is False ]", "square brackets are not supported"),
    ]
    for query, error_reason in error_queries:
        try:
            _ = geoops_sql._prepare_spatial_relations_filter(query)
            error = False
        except Exception:
            error = True
        assert error is True, error_reason


@pytest.mark.parametrize(
    "suffix, epsg, spatial_relations_query, discard_nonmatching, min_area_intersect, "
    "area_inters_column_name, exp_disjoint_warning, exp_featurecount",
    [
        (".gpkg", 31370, "intersects is False", False, None, None, True, 48),
        (".gpkg", 31370, "intersects is False", True, None, None, True, 0),
        (".gpkg", 31370, "intersects is True", False, 1000, "area_test", False, 50),
        (".gpkg", 31370, "intersects is True", False, None, None, False, 51),
        (".gpkg", 31370, "intersects is True", True, 1000, None, False, 26),
        (".gpkg", 31370, "intersects is True", True, None, None, False, 30),
        (
            ".gpkg",
            4326,
            "T******** is True or *T******* is True",
            True,
            None,
            None,
            False,
            30,
        ),
        (".gpkg", 4326, "intersects is True", False, None, None, False, 51),
        (".shp", 31370, "intersects is True", False, None, None, False, 51),
    ],
)
def test_join_by_location(
    tmp_path,
    recwarn,
    suffix: str,
    spatial_relations_query: str,
    epsg: int,
    discard_nonmatching: bool,
    min_area_intersect: float,
    area_inters_column_name: str,
    exp_disjoint_warning: bool,
    exp_featurecount: int,
):
    input1_path = test_helper.get_testfile("polygon-parcel", suffix=suffix, epsg=epsg)
    input2_path = test_helper.get_testfile("polygon-zone", suffix=suffix, epsg=epsg)
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)
    name = f"{input1_path.stem}_{discard_nonmatching}_{min_area_intersect}{suffix}"
    output_path = tmp_path / name

    if exp_disjoint_warning:
        handler = pytest.warns(
            UserWarning,
            match="The spatial relation query specified evaluated to True for disjoint",
        )
    else:
        handler = nullcontext()  # type: ignore[assignment]

    with handler:
        gfo.join_by_location(
            input1_path=str(input1_path),
            input2_path=str(input2_path),
            output_path=str(output_path),
            spatial_relations_query=spatial_relations_query,
            discard_nonmatching=discard_nonmatching,
            min_area_intersect=min_area_intersect,
            area_inters_column_name=area_inters_column_name,
            batchsize=batchsize,
        )

    # Check if the output file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    input2_layerinfo = gfo.get_layerinfo(input2_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == exp_featurecount

    exp_nb_columns = len(input1_layerinfo.columns) + len(input2_layerinfo.columns)
    if area_inters_column_name is not None:
        assert area_inters_column_name in output_layerinfo.columns
        exp_nb_columns += 1
    assert len(output_layerinfo.columns) == exp_nb_columns
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Check the contents of the result file
    # TODO: this test should be more elaborate...
    output_gdf = gfo.read_file(output_path)
    assert len(output_gdf) == exp_featurecount
    if exp_featurecount > 0:
        assert output_gdf["geometry"][0] is not None


@pytest.mark.parametrize(
    "suffix, epsg",
    [(".gpkg", 31370), (".gpkg", 4326), (".shp", 31370)],
)
def test_join_nearest(tmp_path, suffix, epsg):
    # Prepare test data
    input1_path = test_helper.get_testfile("polygon-parcel", suffix=suffix, epsg=epsg)
    input2_path = test_helper.get_testfile("polygon-zone", suffix=suffix, epsg=epsg)
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)

    # Now run test
    output_path = tmp_path / f"{input1_path.stem}-output{suffix}"
    nb_nearest = 2
    input1_columns = ["OIDN", "UIDN", "HFDTLT", "fid"]
    gfo.join_nearest(
        input1_path=str(input1_path),
        input1_columns=input1_columns,
        input2_path=str(input2_path),
        output_path=str(output_path),
        nb_nearest=nb_nearest,
        distance=1000,
        expand=True,
        batchsize=batchsize,
        force=True,
    )

    # Check if the output file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    input2_layerinfo = gfo.get_layerinfo(input2_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    expected_featurecount = nb_nearest * (input1_layerinfo.featurecount - 1)
    assert output_layerinfo.featurecount == expected_featurecount
    exp_columns = len(input1_columns) + len(input2_layerinfo.columns) + 2
    if SPATIALITE_GTE_51:
        exp_columns += 1
    assert len(output_layerinfo.columns) == exp_columns
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Check the contents of the result file
    # TODO: this test should be more elaborate...
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
    if _geofileinfo.get_geofileinfo(input1_path).is_fid_zerobased:
        assert output_gdf.l1_fid.min() == 0
    else:
        assert output_gdf.l1_fid.min() == 1


@pytest.mark.parametrize(
    "kwargs, error_spatialite51, error_spatialite50",
    [
        ({"expand": True}, "distance is mandatory", None),
        (
            {"expand": False},
            "distance is mandatory with spatialite >= 5.1",
            "expand=False is not supported with spatialite < 5.1",
        ),
        ({"distance": 1000}, "expand is mandatory with spatialite >= 5.1", None),
        ({"distance": 1000, "expand": True}, None, None),
    ],
)
def test_join_nearest_invalid_params(
    tmp_path, kwargs, error_spatialite51, error_spatialite50
):
    # Check what version of spatialite we are dealing with
    error = error_spatialite51 if SPATIALITE_GTE_51 else error_spatialite50

    # Prepare test data
    input1_path = test_helper.get_testfile("polygon-parcel")
    input2_path = test_helper.get_testfile("polygon-zone")
    output_path = tmp_path / "output.gpkg"

    # Test
    if error is not None:
        with pytest.raises(ValueError, match=error):
            gfo.join_nearest(
                input1_path=input1_path,
                input2_path=input2_path,
                output_path=output_path,
                nb_nearest=1,
                **kwargs,
            )
    else:
        gfo.join_nearest(
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=output_path,
            nb_nearest=1,
            **kwargs,
        )


@pytest.mark.parametrize(
    "suffix, epsg, gridsize",
    [(".gpkg", 31370, 0.01), (".gpkg", 4326, 0.0), (".shp", 31370, 0.01)],
)
def test_select_two_layers(tmp_path, suffix, epsg, gridsize):
    # Prepare test data
    input1_path = test_helper.get_testfile("polygon-parcel", suffix=suffix, epsg=epsg)
    input2_path = test_helper.get_testfile("polygon-zone", suffix=suffix, epsg=epsg)
    output_path = tmp_path / f"{input1_path.stem}-output{suffix}"

    # Prepare query to execute.
    rtree_layer1 = "rtree_{input1_layer}_{input1_geometrycolumn}"
    rtree_layer2 = "rtree_{input2_layer}_{input2_geometrycolumn}"
    sql_stmt = f"""
        SELECT layer1."{{input1_geometrycolumn}}" AS geom
              {{layer1_columns_prefix_alias_str}}
              {{layer2_columns_prefix_alias_str}}
          FROM {{input1_databasename}}."{{input1_layer}}" layer1
          JOIN {{input1_databasename}}."{rtree_layer1}" layer1tree
            ON layer1.fid = layer1tree.id
          JOIN {{input2_databasename}}."{{input2_layer}}" layer2
          JOIN {{input2_databasename}}."{rtree_layer2}" layer2tree
            ON layer2.fid = layer2tree.id
         WHERE 1=1
           {{batch_filter}}
           AND layer1tree.minx <= layer2tree.maxx
           AND layer1tree.maxx >= layer2tree.minx
           AND layer1tree.miny <= layer2tree.maxy
           AND layer1tree.maxy >= layer2tree.miny
           AND ST_Intersects(
                  layer1.{{input1_geometrycolumn}},
                  layer2.{{input2_geometrycolumn}}) = 1
           AND ST_Touches(
                  layer1.{{input1_geometrycolumn}},
                  layer2.{{input2_geometrycolumn}}) = 0
    """
    gfo.select_two_layers(
        input1_path=str(input1_path),
        input2_path=str(input2_path),
        output_path=str(output_path),
        gridsize=gridsize,
        sql_stmt=sql_stmt,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    input2_layerinfo = gfo.get_layerinfo(input2_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 30
    assert len(output_layerinfo.columns) == (
        len(input1_layerinfo.columns) + len(input2_layerinfo.columns)
    )
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize("input_nogeom", ["input1", "input2", "both"])
def test_select_two_layers_input_without_geom(tmp_path, suffix, input_nogeom):
    # Prepare test file with geom
    input_geom_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Prepare test file without geometry
    if suffix == ".shp":
        # For shapefiles, if there is no geometry only the .dbf file is written
        input_nogeom_path = tmp_path / "input_nogeom.dbf"
    else:
        input_nogeom_path = tmp_path / f"input_nogeom{suffix}"

    input_nogeom_df = pd.DataFrame(
        {
            "GEWASGROEP": ["Landbouwinfrastructuur", "Grasland"],
            "JOINFIELD": ["Landbouwinfrastructuur_joined", "Grasland_joined"],
        }
    )
    gfo.to_file(input_nogeom_df, input_nogeom_path)

    if input_nogeom == "input1":
        input1_path = input_nogeom_path
        input2_path = input_geom_path
        geom_column = '"{input2_geometrycolumn}" AS geom'
        order_by_geom = "ORDER BY geom IS NULL"
        layer1 = "input_nogeom layer1"
        layer2 = '"{input2_layer}" layer2'
        exp_output_geom = True
        exp_featurecount = 37
    elif input_nogeom == "input2":
        input1_path = input_geom_path
        input2_path = input_nogeom_path
        geom_column = '"{input1_geometrycolumn}" AS geom'
        order_by_geom = "ORDER BY geom IS NULL"
        layer1 = '"{input1_layer}" layer1'
        layer2 = "input_nogeom layer2"
        exp_output_geom = True
        exp_featurecount = 37
    elif input_nogeom == "both":
        input1_path = input_nogeom_path
        input2_path = input_nogeom_path
        geom_column = "NULL AS TEST"
        order_by_geom = ""
        layer1 = "input_nogeom layer1"
        layer2 = "input_nogeom layer2"
        exp_output_geom = False
        exp_featurecount = 2

    if suffix == ".shp" and not exp_output_geom:
        # For shapefiles, if there is no geometry only the .dbf file is written
        output_path = tmp_path / f"{input1_path.stem}-output.dbf"
    else:
        output_path = tmp_path / f"{input1_path.stem}-output{suffix}"

    # Prepare query to execute.
    # order_by_geom is needed to avoid creating GEOMETRY type output, as a NULL geometry
    # value will be the first to be returned by this query.
    sql_stmt = f"""
        SELECT {geom_column}
              {{layer1_columns_prefix_alias_str}}
              {{layer2_columns_prefix_alias_str}}
          FROM {{input1_databasename}}.{layer1}
          JOIN {{input2_databasename}}.{layer2}
            ON layer2.gewasgroep = layer1.gewasgroep
         WHERE 1=1
           {{batch_filter}}
         {order_by_geom}
    """
    gfo.select_two_layers(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        sql_stmt=sql_stmt,
        batchsize=exp_featurecount / 2,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    if exp_output_geom:
        exp_spatial_index = GeofileInfo(output_path).default_spatial_index
        assert gfo.has_spatial_index(output_path) is exp_spatial_index

    input1_layerinfo = gfo.get_layerinfo(input1_path, raise_on_nogeom=False)
    input2_layerinfo = gfo.get_layerinfo(input2_path, raise_on_nogeom=False)
    output_layerinfo = gfo.get_layerinfo(output_path, raise_on_nogeom=exp_output_geom)

    exp_columns = len(input1_layerinfo.columns) + len(input2_layerinfo.columns)
    if input_nogeom == "both":
        assert output_layerinfo.featurecount == exp_featurecount
        assert len(output_layerinfo.columns) == exp_columns + 1
        assert output_layerinfo.geometrycolumn is None
        assert output_layerinfo.geometrytype is None
        assert output_layerinfo.crs is None
    else:
        assert output_layerinfo.featurecount == exp_featurecount
        assert len(output_layerinfo.columns) == exp_columns
        assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON
        assert output_layerinfo.crs.to_epsg() == 31370

    # Check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    if exp_output_geom:
        assert output_gdf["geometry"][0] is not None


@pytest.mark.parametrize(
    "expected_error, input1_path, input2_path, output_path",
    [
        (
            "select_two_layers: output_path must not equal one of input paths",
            test_helper.get_testfile("polygon-parcel"),
            test_helper.get_testfile("polygon-zone"),
            test_helper.get_testfile("polygon-parcel"),
        ),
        (
            "select_two_layers: output_path must not equal one of input paths",
            test_helper.get_testfile("polygon-parcel"),
            test_helper.get_testfile("polygon-zone"),
            test_helper.get_testfile("polygon-zone"),
        ),
        (
            "select_two_layers: input1_path doesn't exist: not_existing_path",
            "not_existing_path",
            test_helper.get_testfile("polygon-zone"),
            "output.gpkg",
        ),
        (
            "select_two_layers: input2_path doesn't exist: not_existing_path",
            test_helper.get_testfile("polygon-zone"),
            "not_existing_path",
            "output.gpkg",
        ),
    ],
)
def test_select_two_layers_invalid_paths(
    tmp_path, input1_path, input2_path, output_path, expected_error
):
    """
    select_two_layers doesn't get info on input layers up-front, so this is the best
    function to test the lower level checks in _two_layer_vector_operation.
    """
    # Prepare query to execute. Doesn't really matter what the error is as it is
    # raised before it gets executed.
    sql_stmt = """
        SELECT layer1.{input1_geometrycolumn}
              {layer1_columns_prefix_alias_str}
              {layer2_columns_prefix_alias_str}
          FROM {input1_databasename}."{input1_layer}" layer1
          LEFT OUTER JOIN {input2_databasename}."{input2_layer}" layer2
            ON layer1.join_id = layer2.join_id
         WHERE 1=1
           AND ST_Area(layer1.{input1_geometrycolumn}) > 5
    """
    with pytest.raises(ValueError, match=expected_error):
        gfo.select_two_layers(
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=output_path,
            sql_stmt=sql_stmt,
        )


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
def test_select_two_layers_invalid_sql(tmp_path, suffix):
    # Prepare test data
    input1_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    input2_path = test_helper.get_testfile("polygon-zone", suffix=suffix)

    # Now run test
    output_path = tmp_path / f"output{suffix}"
    sql_stmt = """
        SELECT layer1.{input1_geometrycolumn}
              {layer1_columns_prefix_alias_str}
              {layer2_columns_prefix_alias_str}
              layer1.invalid_column
          FROM {input1_databasename}."{input1_layer}" layer1
          CROSS JOIN {input2_databasename}."{input2_layer}" layer2
         WHERE 1=1
           AND ST_Area(layer1.{input1_geometrycolumn}) > 5
    """
    with pytest.raises(RuntimeError, match='Error near "layer1": syntax error'):
        gfo.select_two_layers(
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=output_path,
            sql_stmt=sql_stmt,
        )


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize(
    "nb_parallel, has_batch_filter, exp_raise",
    [(1, False, False), (2, True, False), (2, False, True)],
)
def test_select_two_layers_batch_filter(
    tmp_path, suffix, nb_parallel, has_batch_filter, exp_raise
):
    """
    Test if batch_filter checks are OK.
    """
    input1_path = test_helper.get_testfile("polygon-parcel", tmp_path, suffix)
    input2_path = input1_path
    output_path = tmp_path / f"{input1_path.stem}-output{suffix}"
    sql_stmt = """
        SELECT layer1.{input1_geometrycolumn}
              {layer1_columns_prefix_alias_str}
              {layer2_columns_prefix_alias_str}
          FROM "{input1_layer}" layer1
          CROSS JOIN "{input2_layer}" layer2
         WHERE 1=1
    """
    if has_batch_filter:
        sql_stmt += "{batch_filter}"

    if exp_raise:
        with pytest.raises(
            ValueError,
            match="Number batches > 1 requires a batch_filter placeholder in ",
        ):
            gfo.select_two_layers(
                input1_path, input2_path, output_path, sql_stmt, nb_parallel=nb_parallel
            )
    else:
        gfo.select_two_layers(
            input1_path, input2_path, output_path, sql_stmt, nb_parallel=nb_parallel
        )


def test_select_two_layers_no_databasename_placeholder(tmp_path):
    # Prepare test data
    input1_path = test_helper.get_testfile("polygon-parcel")
    input2_path = test_helper.get_testfile("polygon-zone")
    output_path = tmp_path / f"{input1_path.stem}-output.gpkg"

    # Prepare query to execute.
    rtree_layer1 = "rtree_{input1_layer}_{input1_geometrycolumn}"
    rtree_layer2 = "rtree_{input2_layer}_{input2_geometrycolumn}"
    sql_stmt = f"""
        SELECT layer1."{{input1_geometrycolumn}}" AS geom
              {{layer1_columns_prefix_alias_str}}
              {{layer2_columns_prefix_alias_str}}
          FROM "{{input1_layer}}" layer1
          JOIN "{rtree_layer1}" layer1tree ON layer1.fid = layer1tree.id
          JOIN "{{input2_layer}}" layer2
          JOIN "{rtree_layer2}" layer2tree ON layer2.fid = layer2tree.id
         WHERE 1=1
           {{batch_filter}}
           AND layer1tree.minx <= layer2tree.maxx
           AND layer1tree.maxx >= layer2tree.minx
           AND layer1tree.miny <= layer2tree.maxy
           AND layer1tree.maxy >= layer2tree.miny
           AND ST_Intersects(
                  layer1.{{input1_geometrycolumn}},
                  layer2.{{input2_geometrycolumn}}) = 1
           AND ST_Touches(
                  layer1.{{input1_geometrycolumn}},
                  layer2.{{input2_geometrycolumn}}) = 0
    """
    output_layer = "test_output_layer"
    gfo.select_two_layers(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        output_layer=output_layer,
        sql_stmt=sql_stmt,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    input2_layerinfo = gfo.get_layerinfo(input2_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 30
    assert len(output_layerinfo.columns) == (
        len(input1_layerinfo.columns) + len(input2_layerinfo.columns)
    )
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
def test_select_two_layers_select_star_fids_not_unique(tmp_path, suffix):
    # Prepare test data
    input1_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    input2_path = test_helper.get_testfile("polygon-zone", suffix=suffix)

    # Now run test
    output_path = tmp_path / f"output{suffix}"
    sql_stmt = """
        SELECT layer1.*
          FROM {input1_databasename}."{input1_layer}" layer1
          CROSS JOIN {input2_databasename}."{input2_layer}" layer2
         WHERE 1=1
           AND ST_Area(layer1.{input1_geometrycolumn}) > 5
    """
    with pytest.raises(Exception, match="Error <Error UNIQUE constraint failed"):
        gfo.select_two_layers(
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=output_path,
            sql_stmt=sql_stmt,
        )


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
def test_select_two_layers_select_star_fids_unique(tmp_path, suffix):
    """
    Test for a join where the fid of one layer is selected (select *), but where this
    fid will stay unique because the rows in this layer won't be duplicated.
    """
    # Prepare test data
    input1_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    input2_path = test_helper.get_testfile("polygon-zone", suffix=suffix)
    one_zone_path = tmp_path / f"one_zone{suffix}"
    input2_gdf = gfo.read_file(input2_path)
    gfo.to_file(input2_gdf.iloc[[0]], one_zone_path)
    one_zone_layerinfo = gfo.get_layerinfo(one_zone_path)
    assert one_zone_layerinfo.featurecount == 1

    # Test with 1 * in the select
    # ---------------------------
    output_path = tmp_path / f"output_1star{suffix}"
    sql_stmt = """
        SELECT layer1.*
          FROM {input1_databasename}."{input1_layer}" layer1
          CROSS JOIN {input2_databasename}."{input2_layer}" layer2
         WHERE 1=1
    """
    gfo.select_two_layers(
        input1_path=input1_path,
        input2_path=one_zone_path,
        output_path=output_path,
        sql_stmt=sql_stmt,
    )
    assert output_path.exists()
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    # Same number of columns expected as layer1: fid is "reused"
    assert len(output_layerinfo.columns) == len(input1_layerinfo.columns)

    # Test with 2 *'s in select
    # -------------------------
    output_path = tmp_path / f"output_2stars{suffix}"
    sql_stmt = """
        SELECT layer1.*, layer2.*
          FROM {input1_databasename}."{input1_layer}" layer1
          CROSS JOIN {input2_databasename}."{input2_layer}" layer2
         WHERE 1=1
    """
    gfo.select_two_layers(
        input1_path=input1_path,
        input2_path=one_zone_path,
        output_path=output_path,
        sql_stmt=sql_stmt,
    )
    assert output_path.exists()
    output_layerinfo = gfo.get_layerinfo(output_path)
    # 2 extra columns expected: layer2.fid is aliased + the layer2.geom is aliased
    exp_nb_columns = len(input1_layerinfo.columns) + len(one_zone_layerinfo.columns) + 2
    assert len(output_layerinfo.columns) == exp_nb_columns

    # Test with 2 fid's in select
    # -------------------------
    output_path = tmp_path / f"output_2fids{suffix}"
    sql_stmt = """
        SELECT layer1.{input1_geometrycolumn}, layer1.fid, layer2.fid
          FROM {input1_databasename}."{input1_layer}" layer1
          CROSS JOIN {input2_databasename}."{input2_layer}" layer2
         WHERE 1=1
    """
    gfo.select_two_layers(
        input1_path=input1_path,
        input2_path=one_zone_path,
        output_path=output_path,
        sql_stmt=sql_stmt,
    )
    assert output_path.exists()
    output_layerinfo = gfo.get_layerinfo(output_path)
    # 1 attribute column expected: layer2.fid is aliased
    exp_nb_columns = 1
    assert len(output_layerinfo.columns) == exp_nb_columns


def test_split(tmp_path):
    """Is deprecated, but keep minimal test."""
    # Prepare test data
    input1_path = test_helper.get_testfile("polygon-parcel")
    input2_path = test_helper.get_testfile("polygon-zone")
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)
    output_path = tmp_path / f"{input1_path.stem}-output.gpkg"

    # Test
    gfo.split(
        input1_path=str(input1_path),
        input2_path=str(input2_path),
        output_path=str(output_path),
        batchsize=batchsize,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    input2_layerinfo = gfo.get_layerinfo(input2_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 68
    assert (len(input1_layerinfo.columns) + len(input2_layerinfo.columns)) == len(
        output_layerinfo.columns
    )
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Check the contents of the result file
    output_gfo_gdf = gfo.read_file(output_path)
    assert output_gfo_gdf["geometry"][0] is not None
    input1_gdf = gfo.read_file(input1_path)
    input2_gdf = gfo.read_file(input2_path)
    output_gpd_gdf = input1_gdf.overlay(input2_gdf, how="identity", keep_geom_type=True)
    renames = dict(zip(output_gpd_gdf.columns, output_gfo_gdf.columns))
    output_gpd_gdf = output_gpd_gdf.rename(columns=renames)

    # OIDN is float vs int? -> check_column_type=False
    assert_geodataframe_equal(
        output_gfo_gdf,
        output_gpd_gdf,
        promote_to_multi=True,
        sort_values=True,
        check_less_precise=True,
        normalize=True,
        check_dtype=False,
    )


@pytest.mark.parametrize(
    "suffix, epsg, gridsize",
    [(".gpkg", 31370, 0.01), (".gpkg", 4326, 0.0), (".shp", 31370, 0.0)],
)
def test_symmetric_difference(tmp_path, request, suffix, epsg, gridsize):
    if epsg == 4326 and sys.platform == "darwin":
        request.node.add_marker(
            pytest.mark.xfail(
                reason="epsg 4326 gives precision issues on MacOS14 on arm64"
            )
        )

    # Prepare test data
    input1_path = test_helper.get_testfile("polygon-zone", suffix=suffix, epsg=epsg)
    input2_path = test_helper.get_testfile("polygon-parcel", suffix=suffix, epsg=epsg)
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)

    # Test
    output_path = tmp_path / f"{input1_path.stem}_symmdiff_{input2_path.stem}{suffix}"
    gfo.symmetric_difference(
        input1_path=str(input1_path),
        input2_path=str(input2_path),
        output_path=str(output_path),
        gridsize=gridsize,
        batchsize=batchsize,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None

    # Prepare expected gdf
    input1_gdf = gfo.read_file(input1_path)
    input2_gdf = gfo.read_file(input2_path)
    exp_gdf = input1_gdf.overlay(
        input2_gdf, how="symmetric_difference", keep_geom_type=True
    )
    renames = dict(zip(exp_gdf.columns, output_gdf.columns))
    exp_gdf = exp_gdf.rename(columns=renames)
    if gridsize != 0.0:
        exp_gdf.geometry = shapely.set_precision(exp_gdf.geometry, grid_size=gridsize)
    # Remove rows where geometry is empty or None
    exp_gdf = exp_gdf[~exp_gdf.geometry.isna()]
    exp_gdf = exp_gdf[~exp_gdf.geometry.is_empty]

    assert_geodataframe_equal(
        output_gdf,
        exp_gdf,
        promote_to_multi=True,
        sort_values=True,
        check_column_type=False,
        check_dtype=False,
        check_less_precise=True,
        normalize=True,
    )


@pytest.mark.parametrize(
    "kwargs, expected_error",
    [
        (
            {"input2_path": None, "input2_layer": "invalid"},
            "input2_layer must be None if input2_path is None",
        ),
        ({"subdivide_coords": -1}, "subdivide_coords < 0 is not allowed"),
    ],
)
def test_symmetric_difference_invalid_params(kwargs, expected_error):
    if "input2_path" not in kwargs:
        kwargs["input2_path"] = "input2.gpkg"
    with pytest.raises(ValueError, match=expected_error):
        gfo.symmetric_difference(
            input1_path="input1.gpkg",
            output_path="output.gpkg",
            **kwargs,
        )


def test_symmetric_difference_self(tmp_path):
    input1_path = test_helper.get_testfile("polygon-overlappingcircles-all")
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)

    # Now run test
    output_path = tmp_path / f"{input1_path.stem}_symmetric_difference_self.gpkg"
    gfo.symmetric_difference(
        input1_path=input1_path,
        input2_path=None,
        output_path=output_path,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert len(output_layerinfo.columns) == 2 * len(input1_layerinfo.columns)
    assert output_layerinfo.featurecount == 6


@pytest.mark.parametrize(
    "suffix, epsg, gridsize, where_post, explodecollections, keep_fid, "
    "exp_featurecount",
    [
        (".gpkg", 31370, 0.01, "ST_Area(geom) > 1000", True, True, 62),
        (".shp", 31370, 0.0, "ST_Area(geom) > 1000", False, True, 59),
        (".gpkg", 4326, 0.0, None, False, False, 73),
    ],
)
def test_union(
    tmp_path: Path,
    request: pytest.FixtureRequest,
    suffix: str,
    epsg: int,
    gridsize: float,
    where_post: Optional[str],
    explodecollections: bool,
    keep_fid: bool,
    exp_featurecount: int,
):
    if epsg == 4326 and sys.platform == "darwin":
        request.node.add_marker(
            pytest.mark.xfail(
                reason="epsg 4326 gives precision issues on MacOS14 on arm64"
            )
        )

    # Prepare test files
    input1_path = test_helper.get_testfile(
        "polygon-parcel", dst_dir=tmp_path, suffix=suffix, epsg=epsg
    )
    input2_path = test_helper.get_testfile(
        "polygon-zone", dst_dir=tmp_path, suffix=suffix, epsg=epsg
    )
    # Add null TEXT column to each file to make sure it stays TEXT type after union
    gfo.add_column(input1_path, name="test1_null", type=gfo.DataType.TEXT)
    gfo.add_column(input2_path, name="test2_null", type=gfo.DataType.TEXT)

    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)
    output_path = tmp_path / f"{input1_path.stem}_union_{input2_path.stem}{suffix}"

    input1_columns = None
    input2_columns = None
    input2_layerinfo = gfo.get_layerinfo(input2_path)
    if keep_fid:
        input1_columns = list(input1_layerinfo.columns) + ["fid"]
        input2_columns = list(input2_layerinfo.columns) + ["fid"]

    # Test
    gfo.union(
        input1_path=str(input1_path),
        input2_path=str(input2_path),
        output_path=str(output_path),
        input1_columns=input1_columns,
        input2_columns=input2_columns,
        gridsize=gridsize,
        explodecollections=explodecollections,
        where_post=where_post,
        batchsize=batchsize,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(output_path)
    exp_columns = len(input1_layerinfo.columns) + len(input2_layerinfo.columns)
    if keep_fid:
        exp_columns += 2
    assert len(output_layerinfo.columns) == exp_columns

    if explodecollections and suffix != ".shp":
        assert output_layerinfo.geometrytype == GeometryType.POLYGON
    else:
        assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    assert output_layerinfo.featurecount == exp_featurecount

    # Check the contents of the result file
    output_gfo_gdf = gfo.read_file(output_path)
    assert output_gfo_gdf["geometry"][0] is not None

    # Prepare expected result
    input1_gdf = gfo.read_file(input1_path, fid_as_index=keep_fid)
    input2_gdf = gfo.read_file(input2_path, fid_as_index=keep_fid)
    if keep_fid:
        input1_gdf["l1_fid"] = input1_gdf.index
        input2_gdf["l2_fid"] = input2_gdf.index
    output_gpd_gdf = input1_gdf.overlay(input2_gdf, how="union", keep_geom_type=True)
    renames = dict(zip(output_gpd_gdf.columns, output_gfo_gdf.columns))
    output_gpd_gdf = output_gpd_gdf.rename(columns=renames)
    output_gpd_gdf["l1_DATUM"] = pd.to_datetime(output_gpd_gdf["l1_DATUM"])
    if gridsize != 0.0:
        output_gpd_gdf.geometry = shapely.set_precision(
            output_gpd_gdf.geometry, grid_size=gridsize
        )
    if explodecollections:
        output_gpd_gdf = output_gpd_gdf.explode(ignore_index=True)
    if where_post is not None:
        output_gpd_gdf = output_gpd_gdf[output_gpd_gdf.geometry.area > 1000]

    # Compare result with expected result
    assert_geodataframe_equal(
        output_gfo_gdf,
        output_gpd_gdf,
        promote_to_multi=True,
        sort_values=True,
        check_less_precise=True,
        normalize=True,
    )


@pytest.mark.parametrize(
    "suffix, epsg", [(".gpkg", 31370), (".gpkg", 4326), (".shp", 31370)]
)
def test_union_circles(tmp_path, suffix, epsg):
    # Prepare test data
    input1_path = test_helper.get_testfile(
        "polygon-overlappingcircles-one", suffix=suffix, epsg=epsg
    )
    input2_path = test_helper.get_testfile(
        "polygon-overlappingcircles-two+three", suffix=suffix, epsg=epsg
    )
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)
    output_path = tmp_path / f"{input1_path.stem}-output{suffix}"

    # Also run some tests on basic data with circles
    # Union the single circle towards the 2 circles
    gfo.union(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        batchsize=batchsize,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    input2_layerinfo = gfo.get_layerinfo(input2_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 5
    assert (len(input1_layerinfo.columns) + len(input2_layerinfo.columns)) == len(
        output_layerinfo.columns
    )
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
    input1_gdf = gfo.read_file(input1_path)
    input2_gdf = gfo.read_file(input2_path)
    output_gpd_gdf = input1_gdf.overlay(input2_gdf, how="union", keep_geom_type=True)
    renames = dict(zip(output_gpd_gdf.columns, output_gdf.columns))
    output_gpd_gdf = output_gpd_gdf.rename(columns=renames)
    assert_geodataframe_equal(
        output_gdf,
        output_gpd_gdf,
        promote_to_multi=True,
        sort_values=True,
        check_less_precise=True,
        normalize=True,
    )

    # Union the two circles towards the single circle
    # Prepare test data
    input1_path = test_helper.get_testfile(
        "polygon-overlappingcircles-two+three", suffix=suffix, epsg=epsg
    )
    input2_path = test_helper.get_testfile(
        "polygon-overlappingcircles-one", suffix=suffix, epsg=epsg
    )
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)
    output_path = tmp_path / f"{input1_path.stem}_union_{input2_path.stem}.gpkg"
    gfo.union(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        batchsize=batchsize,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    input2_layerinfo = gfo.get_layerinfo(input2_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 5
    assert (len(input1_layerinfo.columns) + len(input2_layerinfo.columns)) == len(
        output_layerinfo.columns
    )

    # Check geometry type
    if output_path.suffix.lower() == ".shp":
        # For shapefiles the type stays POLYGON anyway
        assert output_layerinfo.geometrytype == GeometryType.POLYGON
    elif output_path.suffix.lower() == ".gpkg":
        assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
    input1_gdf = gfo.read_file(input1_path)
    input2_gdf = gfo.read_file(input2_path)
    output_gpd_gdf = input1_gdf.overlay(input2_gdf, how="union", keep_geom_type=True)
    renames = dict(zip(output_gpd_gdf.columns, output_gdf.columns))
    output_gpd_gdf = output_gpd_gdf.rename(columns=renames)
    assert_geodataframe_equal(
        output_gdf,
        output_gpd_gdf,
        promote_to_multi=True,
        sort_values=True,
        check_less_precise=True,
        normalize=True,
    )


def test_union_force(tmp_path):
    # Prepare test data
    input1_path = test_helper.get_testfile("polygon-parcel")
    input2_path = test_helper.get_testfile("polygon-zone")
    output_path = tmp_path / f"output{input1_path.suffix}"
    output_path.touch()

    # Test with force False (the default): existing output file should stay the same
    mtime_orig = output_path.stat().st_mtime
    gfo.union(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
    )
    assert output_path.stat().st_mtime == mtime_orig

    # With force=True
    gfo.union(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        force=True,
    )
    assert output_path.stat().st_mtime != mtime_orig


@pytest.mark.parametrize(
    "kwargs, expected_error",
    [
        (
            {"input2_path": None, "input2_layer": "invalid"},
            "input2_layer must be None if input2_path is None",
        ),
        ({"subdivide_coords": -1}, "subdivide_coords < 0 is not allowed"),
    ],
)
def test_union_invalid_params(kwargs, expected_error):
    if "input2_path" not in kwargs:
        kwargs["input2_path"] = "input2.gpkg"
    with pytest.raises(ValueError, match=expected_error):
        gfo.union(
            input1_path="input.gpkg",
            output_path="output.gpkg",
            **kwargs,
        )


def test_union_self(tmp_path):
    input1_path = test_helper.get_testfile("polygon-overlappingcircles-all")
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)

    # Now run test
    output_path = tmp_path / f"{input1_path.stem}_union_self.gpkg"
    gfo.union(
        input1_path=input1_path,
        input2_path=None,
        output_path=output_path,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert len(output_layerinfo.columns) == 2 * len(input1_layerinfo.columns)
    assert output_layerinfo.featurecount == 12
