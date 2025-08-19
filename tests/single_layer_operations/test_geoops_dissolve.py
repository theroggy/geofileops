"""
Tests for dissolve operation.
"""

import json
import math
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pygeoops
import pytest
import shapely
import shapely.geometry as sh_geom

import geofileops as gfo
from geofileops import GeometryType
from geofileops.util import _general_util, _geofileinfo, _geoops_sql
from geofileops.util._geofileinfo import GeofileInfo
from tests import test_helper
from tests.test_helper import (
    EPSGS,
    SUFFIXES_GEOOPS,
    TESTFILES,
    WHERE_AREA_GT_5000,
    WHERE_LENGTH_GT_1000,
    WHERE_LENGTH_GT_200000,
    assert_geodataframe_equal,
)


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize(
    "epsg, gridsize, explodecollections, where_post",
    [
        (31370, 0.01, True, WHERE_LENGTH_GT_1000),
        (31370, 0.01, False, WHERE_LENGTH_GT_200000),
        (31370, 0.01, True, ""),
        (4326, 0.0, False, None),
    ],
)
def test_dissolve_linestrings(
    tmp_path, suffix, epsg, gridsize, explodecollections, where_post
):
    # Prepare test data
    input_path = test_helper.get_testfile(
        "linestring-watercourse", suffix=suffix, epsg=epsg
    )
    output_basepath = tmp_path / f"{input_path.stem}-output{suffix}"
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Dissolve, no groupby
    output_path = (
        output_basepath.parent / f"{output_basepath.stem}_expl{output_basepath.suffix}"
    )
    gfo.dissolve(
        input_path=str(input_path),
        output_path=str(output_path),
        explodecollections=explodecollections,
        gridsize=gridsize,
        where_post=where_post,
        batchsize=batchsize,
    )

    # Check if the result file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.geometrytype in [
        GeometryType.LINESTRING,
        GeometryType.MULTILINESTRING,
    ]
    assert len(output_layerinfo.columns) >= 0

    if explodecollections:
        if where_post is None or where_post == "":
            assert output_layerinfo.featurecount == 83
        elif where_post == WHERE_LENGTH_GT_1000:
            assert output_layerinfo.featurecount == 13
        else:
            raise ValueError(f"check for where_post {where_post} not implemented")
    elif where_post is None or where_post == "":
        assert output_layerinfo.featurecount == 1
    elif where_post == WHERE_LENGTH_GT_200000:
        assert output_layerinfo.featurecount == 0
        # Output empty, so nothing more to check
        return
    else:
        raise ValueError(f"check for where_post {where_post} not implemented")

    # Check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == output_layerinfo.featurecount
    assert output_gdf["geometry"][0] is not None
    # TODO: add more in depth check of result


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize("epsg", EPSGS)
@pytest.mark.parametrize("groupby_columns", [["NiScoDe"], "NiScoDe"])
def test_dissolve_linestrings_groupby(tmp_path, suffix, epsg, groupby_columns):
    # Prepare test data
    input_path = test_helper.get_testfile(
        "linestring-watercourse", suffix=suffix, epsg=epsg
    )
    output_basepath = tmp_path / f"{input_path.stem}-output{suffix}"
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Dissolve, groupby, explodecollections=False
    # -------------------------------------------
    output_path = (
        output_basepath.parent
        / f"{output_basepath.stem}_groupby_noexpl{output_basepath.suffix}"
    )
    gfo.dissolve(
        input_path=str(input_path),
        output_path=str(output_path),
        groupby_columns=groupby_columns,
        explodecollections=False,
        batchsize=batchsize,
    )

    # Check if the result file is correctly created
    assert output_path.exists()
    input_layerinfo = gfo.get_layerinfo(input_path)

    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 26
    assert output_layerinfo.geometrytype is input_layerinfo.geometrytype
    assert len(output_layerinfo.columns) >= 0

    # Now check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == output_layerinfo.featurecount
    assert output_gdf["geometry"][0] is not None
    # TODO: add more in depth check of result


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize("epsg", EPSGS)
def test_dissolve_linestrings_aggcolumns_columns(tmp_path, suffix, epsg):
    # Prepare test data
    input_path = test_helper.get_testfile(
        "linestring-watercourse", suffix=suffix, epsg=epsg
    )
    output_basepath = tmp_path / f"{input_path.stem}-output{suffix}"
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Dissolve, groupby, explodecollections=False
    # -------------------------------------------
    output_path = (
        output_basepath.parent
        / f"{output_basepath.stem}_groupby_noexpl{output_basepath.suffix}"
    )
    # Also play a bit with casing to check case insnsitivity towards input file, but
    # retaining the casing used in the groupby_columns parameter in output.
    groupby_columns = ["NIScode"]
    agg_columns = {
        "columns": [
            {"column": "fid", "agg": "concat", "as": "fid_concat"},
            {"column": "NaaM", "agg": "max", "as": "naam_MAX"},
        ]
    }
    gfo.dissolve(
        input_path=input_path,
        output_path=output_path,
        groupby_columns=groupby_columns,
        agg_columns=agg_columns,
        explodecollections=False,
        batchsize=batchsize,
    )

    # Check if the result file is correctly created
    assert output_path.exists()
    input_layerinfo = gfo.get_layerinfo(input_path)

    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 26
    assert output_layerinfo.geometrytype is input_layerinfo.geometrytype
    assert len(output_layerinfo.columns) == (
        len(groupby_columns) + len(agg_columns["columns"])
    )

    # Now check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == output_layerinfo.featurecount
    assert output_gdf["geometry"][0] is not None

    # Some more default checks for NISCODE 12009
    niscode_idx = output_gdf[output_gdf["NIScode"] == "12009"].index.item()
    fid_concat_result = sorted(output_gdf["fid_concat"][niscode_idx].split(","))
    if _geofileinfo.get_geofileinfo(input_path).is_fid_zerobased:
        assert fid_concat_result == ["38", "42", "44", "54"]
    else:
        assert fid_concat_result == ["39", "43", "45", "55"]
    assert output_gdf["naam_MAX"][niscode_idx] == "Vosbergbeek"


@pytest.mark.parametrize("agg_columns", [{"json": ["fid", "NaaM"]}, {"json": None}])
def test_dissolve_linestrings_aggcolumns_json(tmp_path, agg_columns):
    # Prepare test data
    input_path = test_helper.get_testfile("linestring-watercourse")
    output_basepath = tmp_path / f"{input_path.stem}-output.gpkg"
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Dissolve, groupby, explodecollections=False
    # -------------------------------------------
    output_path = (
        output_basepath.parent
        / f"{output_basepath.stem}_groupby_noexpl{output_basepath.suffix}"
    )
    # Also play a bit with casing to check case insnsitivity towards input file, but
    # retaining the casing used in the groupby_columns parameter in output.
    groupby_columns = ["NIScode"]
    gfo.dissolve(
        input_path=input_path,
        output_path=output_path,
        groupby_columns=groupby_columns,
        agg_columns=agg_columns,
        explodecollections=False,
        batchsize=batchsize,
    )

    # Check if the result file is correctly created
    assert output_path.exists()
    input_layerinfo = gfo.get_layerinfo(input_path)

    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 26
    assert output_layerinfo.geometrytype is input_layerinfo.geometrytype
    assert len(output_layerinfo.columns) == len(groupby_columns) + 1

    # Now check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == output_layerinfo.featurecount
    assert output_gdf["geometry"][0] is not None

    # Some more default checks for NISCODE 12009
    niscode_idx = output_gdf[output_gdf["NIScode"] == "12009"].index.item()
    json_value = json.loads(str(output_gdf["json"][niscode_idx]))

    # Check NAAM
    naam_result = sorted([value["NAAM"] for value in json_value])
    exp = [
        "Duffelse en Rumstse Scheibeek",
        "Grote Nete",
        "Maltaveldenloop",
        "Vosbergbeek",
    ]
    assert naam_result == exp
    fid_result = sorted([str(value["fid_orig"]) for value in json_value])
    if _geofileinfo.get_geofileinfo(input_path).is_fid_zerobased:
        assert fid_result == ["38", "42", "44", "54"]
    else:
        assert fid_result == ["39", "43", "45", "55"]

    # Some specific tests depending on whether all columns asked or not
    if agg_columns["json"] is None:
        # fid_orig is added to json
        assert len(json_value[0]) == len(input_layerinfo.columns) + 1
    else:
        # fid_orig is added to json
        assert len(json_value[0]) == len(agg_columns["json"]) + 1


@pytest.mark.parametrize(
    "suffix, epsg, explode_input, groupby_columns, explode, gridsize, where_post, "
    "expected_featurecount",
    [
        (".gpkg", 31370, False, ["GEWASgroep"], True, 0.0, "", 26),
        (".gpkg", 31370, False, "GEWASgroep", True, 0.0, "", 26),
        (".gpkg", 31370, False, ["GEWASgroep"], True, 0.01, "", 24),
        (".gpkg", 31370, False, ["GEWASGROEP"], False, 0.0, "", 6),
        (".gpkg", 31370, True, ["GEWASGROEP"], False, 0.0, "", 6),
        (".gpkg", 31370, False, ["gewasGROEP"], False, 0.01, WHERE_AREA_GT_5000, 4),
        (".gpkg", 31370, False, ["gewasGROEP"], True, 0.01, WHERE_AREA_GT_5000, 13),
        (".gpkg", 31370, False, [], True, 0.0, None, 24),
        (".gpkg", 31370, False, None, False, 0.0, None, 1),
        (".gpkg", 4326, False, ["GEWASGROEP"], True, 0.0, None, 26),
        (".shp", 31370, False, ["GEWASGROEP"], True, 0.0, None, 26),
        (".shp", 31370, False, [], True, 0.0, None, 24),
    ],
)
def test_dissolve_polygons(
    tmp_path,
    suffix,
    epsg,
    explode_input,
    groupby_columns,
    explode,
    gridsize,
    where_post,
    expected_featurecount,
):
    if gridsize > 0.0:
        pytest.xfail("Geopandas doesn't support dissolve with gridsize yet")

    # Prepare test data
    dst_dir = tmp_path if suffix == ".shp" else None
    test_path = test_helper.get_testfile(
        "polygon-parcel", suffix=suffix, epsg=epsg, dst_dir=dst_dir
    )
    if explode_input:
        # A bug caused in the past that the output was forced to the same type as the
        # input. If input was simple Polygon, this cause invalid output because
        # MultiPolygons were forced to Simple Polygons.
        input_path = tmp_path / f"input{suffix}"
        gfo.copy_layer(
            src=test_path,
            dst=input_path,
            explodecollections=True,
            force_output_geometrytype=GeometryType.POLYGON,
        )
    else:
        input_path = test_path

    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Test dissolve polygons with different options for groupby and explodecollections
    # --------------------------------------------------------------------------------
    groupby = True if (groupby_columns is None or len(groupby_columns) == 0) else False
    name = f"{input_path.stem}_groupby-{groupby}_explode-{explode}_gridsize-{gridsize}"
    output_path = tmp_path / f"{name}{suffix}"
    gfo.dissolve(
        input_path=input_path,
        output_path=output_path,
        groupby_columns=groupby_columns,
        explodecollections=explode,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Now check if the tmp file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    assert gfo.isvalid(output_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == expected_featurecount

    if groupby_columns is not None and isinstance(groupby_columns, str):
        groupby_columns = [groupby_columns]
    if groupby:
        # No groupby -> normally no columns.
        # Shapefile needs at least one column, if no columns: fid
        if suffix == ".shp":
            assert len(output_layerinfo.columns) == 1
        else:
            assert len(output_layerinfo.columns) == 0
    else:
        assert len(output_layerinfo.columns) == len(groupby_columns)

    if not explode or suffix == ".shp":
        # Shapefile always returns MultiPolygon
        assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON
    else:
        assert output_layerinfo.geometrytype == GeometryType.POLYGON

    # Now check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == output_layerinfo.featurecount
    assert output_gdf["geometry"][0] is not None

    # Compare result expected values using geopandas
    columns = ["geometry"]
    if gridsize > 0.0:
        input_gdf.geometry = shapely.set_precision(
            input_gdf.geometry, grid_size=gridsize
        )
    if groupby_columns is None or len(groupby_columns) == 0:
        expected_gdf = input_gdf[columns].dissolve()
    else:
        groupby_columns_upper = {column.upper(): column for column in groupby_columns}
        columns += list(groupby_columns_upper)
        expected_gdf = (
            input_gdf[columns].dissolve(by=list(groupby_columns_upper)).reset_index()
        ).rename(columns=groupby_columns_upper)
    expected_gdf = test_helper.prepare_expected_result(
        expected_gdf,
        explodecollections=explode,
        gridsize=gridsize,
        keep_empty_geoms=False,
        where_post=where_post,
    )
    expected_path = tmp_path / f"{input_path.stem}_gpd-output{suffix}"
    gfo.to_file(expected_gdf, expected_path)

    # Small differences with the geopandas result are expected, because gfo
    # adds points in the tiling process. So only basic checks possible.
    # output_gdf.geometry = output_gdf.geometry.simplify(0.01)
    # expected_gdf.geometry = expected_gdf.geometry.simplify(0.01)
    # assert_geodataframe_equal(
    #     output_gdf, expected_gdf, promote_to_multi=True, sort_values=True,
    #     normalize=True, check_less_precise=True
    # )
    if suffix != ".shp":
        # Shapefile needs at least one column, if no columns: fid
        assert list(output_gdf.columns) == list(expected_gdf.columns)
    assert len(output_gdf) == len(expected_gdf)
    output_area = output_gdf.geometry.area.sort_values().reset_index(drop=True)
    expected_area = expected_gdf.geometry.area.sort_values().reset_index(drop=True)
    pd.testing.assert_series_equal(output_area, expected_area)


def test_dissolve_empty_onborder_result(tmp_path):
    """
    Test case where the 1st pass of dissolve does not result in any onborder features.
    """
    test_gdf = gpd.GeoDataFrame(
        geometry=[sh_geom.box(5, 5, 10, 10), sh_geom.box(20, 5, 25, 10)], crs=31370
    )
    test_path = tmp_path / "test.gpkg"
    gfo.to_file(test_gdf, test_path)

    output_path = tmp_path / "output.gpkg"
    gfo.dissolve(
        test_path, output_path=output_path, explodecollections=True, batchsize=1
    )

    assert output_path.exists()
    output_gdf = gfo.read_file(output_path)
    assert_geodataframe_equal(test_gdf, output_gdf, normalize=True, sort_values=True)


@pytest.mark.parametrize("explodecollections", [True, False])
@pytest.mark.parametrize("testfile", TESTFILES)
@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
def test_dissolve_emptyfile(tmp_path, testfile, suffix, explodecollections):
    # Prepare test data
    input_path = test_helper.get_testfile(testfile, suffix=suffix, empty=True)

    # Test dissolve polygons with different options for groupby and explodecollections
    output_path = tmp_path / f"{input_path.stem}_dissolve-emptyfile{suffix}"
    if testfile == "polygon-parcel":
        groupby_columns = ["GEWASGROEP"]
        expected_geometrytype = GeometryType.POLYGON
    elif testfile == "linestring-row-trees":
        groupby_columns = ["rowtype"]
        expected_geometrytype = GeometryType.LINESTRING
    elif testfile == "point":
        groupby_columns = ["type"]
        expected_geometrytype = GeometryType.POINT
    else:
        raise ValueError(f"unimplimented testfile: {testfile}")
    if not explodecollections or suffix == ".shp":
        expected_geometrytype = expected_geometrytype.to_multitype

    gfo.dissolve(
        input_path=input_path,
        output_path=output_path,
        explodecollections=explodecollections,
        groupby_columns=groupby_columns,
    )

    # Now check if the tmp file is correctly created
    assert output_path.exists()
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 0
    assert output_layerinfo.geometrytype == expected_geometrytype
    assert list(output_layerinfo.columns) == groupby_columns


@pytest.mark.parametrize("sql_singlethread", [True, False])
@pytest.mark.parametrize(
    "exp_error, exp_ex, invalid_params",
    [
        (
            "column in groupby_columns not",
            ValueError,
            {"groupby_columns": "NON_EXISTING_COLUMN"},
        ),
        (
            "input_path not found: ",
            FileNotFoundError,
            {"input_path": Path("nonexisting.abc")},
        ),
        (
            "output_path must not equal input_path",
            ValueError,
            {
                "input_path": Path("nonexisting.abc"),
                "output_path": Path("nonexisting.abc"),
            },
        ),
        (
            "Dissolve to tiles is not supported for GeometryType.MULTILINESTRING, ",
            ValueError,
            {
                "input_path": test_helper.get_testfile("linestring-watercourse"),
                "nb_squarish_tiles": 2,
            },
        ),
        (
            "abc not available in: ",
            ValueError,
            {
                "agg_columns": {
                    "columns": [{"column": "abc", "agg": "count", "as": "cba"}]
                }
            },
        ),
    ],
)
def test_dissolve_invalid_params(
    tmp_path, sql_singlethread, invalid_params, exp_ex, exp_error
):
    """Test dissolve with some invalid input params.

    Remark: the structure of agg_columns parameter is tested in
      test_parameter_helper.test_validate_agg_columns_invalid.
    """
    # Prepare test data / params
    input_path = test_helper.get_testfile("polygon-parcel")
    groupby_columns = ["GEWASGROEP"]
    nb_squarish_tiles = 1
    agg_columns = None
    output_path = tmp_path / "output.gpkg"
    for invalid_param in invalid_params:
        if invalid_param == "input_path":
            input_path = invalid_params[invalid_param]
        elif invalid_param == "groupby_columns":
            groupby_columns = invalid_params[invalid_param]
        elif invalid_param == "nb_squarish_tiles":
            nb_squarish_tiles = invalid_params[invalid_param]
        elif invalid_param == "agg_columns":
            agg_columns = invalid_params[invalid_param]
        elif invalid_param == "output_path":
            output_path = invalid_params[invalid_param]
        else:
            raise ValueError(f"unsupported invalid_param: {invalid_param}")

    # Run test
    with pytest.raises(exp_ex, match=exp_error):
        if sql_singlethread:
            if nb_squarish_tiles > 1:
                pytest.skip("nb_squarish_tiles not relevant for dissolve_singlethread")

            _geoops_sql.dissolve_singlethread(
                input_path=input_path,
                output_path=output_path,
                groupby_columns=groupby_columns,
                explodecollections=True,
                agg_columns=agg_columns,
                gridsize=0.0,
            )
        else:
            gfo.dissolve(
                input_path=input_path,
                output_path=output_path,
                groupby_columns=groupby_columns,
                explodecollections=True,
                nb_squarish_tiles=nb_squarish_tiles,
                agg_columns=agg_columns,
            )


def test_dissolve_polygons_groupby_None(tmp_path):
    """
    Test dissolve polygons with a column with None values. There was once an issue
    that the type of the column with None Values always ended up as a REAL column after
    the dissolve/group by instead of the original type.
    """

    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    gfo.add_column(input_path, name="none_values", type=gfo.DataType.TEXT)
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Run test
    output_path = tmp_path / "output.gpkg"
    gfo.dissolve(
        input_path=input_path,
        output_path=output_path,
        groupby_columns="none_values",
        explodecollections=True,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Now check if the tmp file is correctly created
    assert output_path.exists()
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.geometrytype == GeometryType.POLYGON
    assert (
        output_layerinfo.columns["none_values"].gdal_type
        == input_layerinfo.columns["none_values"].gdal_type
    )


@pytest.mark.parametrize("worker_type", ["threads", "processes"])
def test_dissolve_polygons_process_threads(tmp_path, worker_type):
    """
    Test dissolve polygons with different worker types.
    """
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Run test
    output_path = tmp_path / "output.gpkg"
    with _general_util.TempEnv({"GFO_WORKER_TYPE": worker_type}):
        gfo.dissolve(
            input_path=input_path,
            output_path=output_path,
            groupby_columns="GEWASGROEP",
            explodecollections=True,
            nb_parallel=2,
            batchsize=batchsize,
        )

    # Now check if the tmp file is correctly created
    assert output_path.exists()
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.geometrytype == GeometryType.POLYGON


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
def test_dissolve_polygons_specialcases(tmp_path, suffix):
    # Prepare test data
    dst_dir = tmp_path if suffix == ".shp" else None
    input_path = test_helper.get_testfile(
        "polygon-parcel", suffix=suffix, dst_dir=dst_dir
    )
    output_basepath = tmp_path / f"{input_path.stem}-output{suffix}"
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Test dissolve polygons with specified output layer
    # --------------------------------------------------
    # A different output layer is not supported for shapefile!!!
    output_path = (
        output_basepath.parent
        / f"{output_basepath.stem}_group_outputlayer{output_basepath.suffix}"
    )
    try:
        gfo.dissolve(
            input_path=input_path,
            output_path=output_path,
            groupby_columns=["GEWASGROEP"],
            output_layer="banana",
            explodecollections=True,
            nb_parallel=2,
            batchsize=batchsize,
        )
    except Exception:
        # A different output_layer is not supported for shapefile, so normal
        # that an exception is thrown!
        assert output_path.suffix.lower() == ".shp"

    # Now check if the tmp file is correctly created
    if output_path.suffix.lower() != ".shp":
        assert output_path.exists()
        output_layerinfo = gfo.get_layerinfo(output_path)
        assert output_layerinfo.featurecount == 26
        assert len(output_layerinfo.columns) == 1
        assert output_layerinfo.name == "banana"
        assert output_layerinfo.geometrytype == GeometryType.POLYGON

        # Now check the contents of the result file
        input_gdf = gfo.read_file(input_path)
        output_gdf = gfo.read_file(output_path)
        assert input_gdf.crs == output_gdf.crs
        assert len(output_gdf) == output_layerinfo.featurecount
        assert output_gdf["geometry"][0] is not None

    # Test dissolve to existing output path without and without force
    # ---------------------------------------------------------------
    for force in [True, False]:
        assert output_path.exists() is True
        mtime_orig = output_path.stat().st_mtime
        gfo.dissolve(
            input_path=input_path,
            output_path=output_path,
            explodecollections=True,
            nb_parallel=2,
            batchsize=batchsize,
            force=force,
        )
        if force is False:
            assert output_path.stat().st_mtime == mtime_orig
        else:
            assert output_path.stat().st_mtime != mtime_orig


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize("nb_parallel", [-1, 2])
def test_dissolve_polygons_tiles_empty(tmp_path, suffix, nb_parallel):
    # Prepare test data
    dst_dir = tmp_path if suffix == ".shp" else None
    input_path = test_helper.get_testfile(
        "polygon-parcel", suffix=suffix, dst_dir=dst_dir
    )
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    output_path = tmp_path / f"{input_path.stem}-tilesoutput{suffix}"
    tiles_path = tmp_path / "tiles.gpkg"

    # Make the bounds large enough so there are also empty tiles
    bounds = input_layerinfo.total_bounds
    width = bounds[2] - bounds[0]
    bounds = (
        bounds[0] - 1,
        bounds[1] - 1,
        bounds[2] + 1 + width,
        bounds[3] + 1,
    )
    tiles_gdf = gpd.GeoDataFrame(
        geometry=pygeoops.create_grid2(bounds, nb_squarish_tiles=8), crs=31370
    )
    gfo.to_file(tiles_gdf, tiles_path)

    # Test!
    gfo.dissolve(
        input_path=input_path,
        output_path=output_path,
        tiles_path=tiles_path,
        explodecollections=False,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=True,
    )

    # Now check if the result file is correctly created
    assert output_path.exists()
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 4
    if suffix == ".shp":
        # Shapefile always has an FID field
        # but only if there is no other column???
        # TODO: think about whether this should also be the case for geopackage???
        assert len(output_layerinfo.columns) == 1
    else:
        assert len(output_layerinfo.columns) == 1
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == output_layerinfo.featurecount
    assert output_gdf["geometry"][0] is not None


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.filterwarnings("ignore: .* field lbl_conc has been truncated to 254")
def test_dissolve_polygons_aggcolumns_columns(tmp_path, suffix):
    # Prepare test data
    dst_dir = tmp_path if suffix == ".shp" else None
    input_path = test_helper.get_testfile(
        "polygon-parcel", suffix=suffix, dst_dir=dst_dir
    )
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    output_basepath = tmp_path / f"{input_path.stem}-output{suffix}"

    # Test dissolve polygons with groupby + agg_columns to columns
    output_path = (
        output_basepath.parent
        / f"{output_basepath.stem}_group_aggcolumns{output_basepath.suffix}"
    )
    # Remarks:
    #     - column names are shortened so it also works for shapefile!
    #     - the columns for agg_columns are choosen so they do not contain
    #       unique values, to be a better test case!
    agg_columns = {
        "columns": [
            {"column": "lblHFDtlt", "agg": "max", "as": "lbl_max"},
            {"column": "GEWASGROEP", "agg": "count", "as": "gwsgrp_cnt"},
            {"column": "lblhfdTLT", "agg": "count", "as": "lbl_count"},
            {
                "column": "lblhfdtlt",
                "agg": "count",
                "distinct": True,
                "as": "lbl_cnt_d",
            },
            {"column": "lblhfdtlt", "agg": "concat", "as": "lbl_conc"},
            {
                "column": "lblhfdtlt",
                "agg": "concat",
                "sep": ";",
                "as": "lbl_conc_s",
            },
            {
                "column": "lblhfdtlt",
                "agg": "concat",
                "distinct": True,
                "as": "lbl_conc_d",
            },
            {"column": "hfdtlt", "agg": "mean", "as": "tlt_mea"},
            {"column": "hfdtlt", "agg": "min", "as": "tlt_min"},
            {"column": "hfdtlt", "agg": "sum", "as": "tlt_sum"},
            {"column": "fid", "agg": "concat", "as": "fid_concat"},
            {"column": "lblhfdtlt", "agg": "concat", "as": "lblhfdtlt"},
        ]
    }
    groupby_columns = ["GEWASgroep"]

    # Force use of processes as workers
    with gfo.TempEnv({"GFO_WORKER_TYPE": "processes"}):
        gfo.dissolve(
            input_path=input_path,
            output_path=output_path,
            groupby_columns=groupby_columns,
            agg_columns=agg_columns,
            explodecollections=False,
            nb_parallel=2,
            batchsize=batchsize,
        )

    # Now check if the tmp file is correctly created
    assert output_path.exists()
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 6
    assert len(output_layerinfo.columns) == (
        len(groupby_columns) + len(agg_columns["columns"])
    )
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == output_layerinfo.featurecount
    assert output_gdf["geometry"][0] is not None
    assert "lblhfdtlt" in output_gdf.columns

    # Check agg_columns results
    grasland_idx = output_gdf[output_gdf["GEWASgroep"] == "Grasland"].index.to_list()[0]
    assert output_gdf["lbl_max"][grasland_idx] == "Grasland"
    assert output_gdf["gwsgrp_cnt"][grasland_idx] == 31
    assert output_gdf["lbl_count"][grasland_idx] == 31
    print(f"output_gdf.lbl_concat_distinct: {output_gdf['lbl_conc_d'][grasland_idx]}")
    assert output_gdf["lbl_cnt_d"][grasland_idx] == 1
    assert output_gdf["lbl_conc"][grasland_idx].startswith("Grasland,Grasland,")
    assert output_gdf["lbl_conc_s"][grasland_idx].startswith("Grasland;Grasland;")
    assert output_gdf["lbl_conc_d"][grasland_idx] == "Grasland"
    assert output_gdf["tlt_mea"][grasland_idx] == 60
    assert int(output_gdf["tlt_min"][grasland_idx]) == 60
    assert output_gdf["tlt_sum"][grasland_idx] == 1860

    groenten_idx = output_gdf[
        output_gdf["GEWASgroep"] == "Groenten, kruiden en sierplanten"
    ].index.to_list()[0]
    assert output_gdf["lbl_count"][groenten_idx] == 5
    print(
        "groenten.lblhfdtlt_concat_distinct: f{output_gdf['lbl_conc_d'][groenten_idx]}"
    )
    assert output_gdf["lbl_cnt_d"][groenten_idx] == 4
    fid_concat_result = sorted(output_gdf["fid_concat"][groenten_idx].split(","))
    if _geofileinfo.get_geofileinfo(input_path).is_fid_zerobased:
        assert fid_concat_result == ["41", "42", "43", "44", "45"]
    else:
        assert fid_concat_result == ["42", "43", "44", "45", "46"]


@pytest.mark.parametrize(
    "agg_columns", [{"json": ["lengte", "oppervl", "lblhfdtlt"]}, {"json": None}]
)
def test_dissolve_polygons_aggcolumns_json(tmp_path, agg_columns):
    # In shapefiles, the length of str columns is very limited, so the json
    # test would fail.
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel")
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    output_basepath = tmp_path / f"{input_path.stem}-output.gpkg"

    # Test dissolve polygons with groupby + agg_columns to json
    output_path = (
        output_basepath.parent
        / f"{output_basepath.stem}_group_aggjson{output_basepath.suffix}"
    )
    gfo.dissolve(
        input_path=input_path,
        output_path=output_path,
        groupby_columns=["GEWASgroep"],
        agg_columns=agg_columns,
        explodecollections=False,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Now check if the tmp file is correctly created
    assert output_path.exists()
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 6
    assert len(output_layerinfo.columns) == 2
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == output_layerinfo.featurecount
    assert output_gdf["geometry"][0] is not None
    grasland_json = json.loads(str(output_gdf["json"][0]))
    assert len(grasland_json) == 31
    grasland_json_firstrow = json.loads(str(grasland_json[0]))
    if agg_columns["json"] is None:
        # fid_orig column is added in json, but index column disappeared ???
        assert len(grasland_json_firstrow) == len(input_layerinfo.columns)
    else:
        # fid_orig column is added in json
        assert len(grasland_json_firstrow) == len(agg_columns["json"]) + 1
