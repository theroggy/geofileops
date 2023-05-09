# -*- coding: utf-8 -*-
"""
Tests for operations using GeoPandas.
"""

import json
import math
from pathlib import Path
import sys

import geopandas as gpd
import pytest
import shapely.geometry as sh_geom

# Add path so the local geofileops packages are found
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import geofileops as gfo
from geofileops import GeometryType
from geofileops.util import _geoops_gpd, grid_util
from geofileops.util import geometry_util
from tests import test_helper
from tests.test_helper import DEFAULT_EPSGS, DEFAULT_SUFFIXES


def test_get_parallelization_params():
    parallelization_params = _geoops_gpd.get_parallelization_params(500000)
    assert parallelization_params is not None


@pytest.mark.parametrize("suffix", DEFAULT_SUFFIXES)
@pytest.mark.parametrize("only_geom_input", [True, False])
@pytest.mark.parametrize("force_output_geometrytype", [None, GeometryType.POLYGON])
def test_apply(tmp_path, suffix, only_geom_input, force_output_geometrytype):
    # Prepare test data
    test_gdf = gpd.GeoDataFrame(
        geometry=[  # type: ignore
            test_helper.TestData.polygon_small_island,
            test_helper.TestData.polygon_with_island,
            None,
        ],
        crs=31370,  # type: ignore
    )
    input_path = tmp_path / f"polygons_small_holes_{suffix}"
    gfo.to_file(test_gdf, input_path)
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    if only_geom_input:
        gfo.apply(
            input_path=input_path,
            output_path=output_path,
            func=lambda geom: geometry_util.remove_inner_rings(
                geometry=geom, min_area_to_keep=2, crs=input_layerinfo.crs
            ),
            only_geom_input=True,
            force_output_geometrytype=force_output_geometrytype,
            batchsize=batchsize,
        )
    else:
        gfo.apply(
            input_path=input_path,
            output_path=output_path,
            func=lambda row: geometry_util.remove_inner_rings(
                row.geometry, min_area_to_keep=2, crs=input_layerinfo.crs
            ),
            only_geom_input=False,
            force_output_geometrytype=force_output_geometrytype,
            batchsize=batchsize,
        )

    # Now check if the output file is correctly created
    assert output_path.exists()
    assert gfo.has_spatial_index(output_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert input_layerinfo.featurecount == (output_layerinfo.featurecount + 1)
    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)
    if force_output_geometrytype is None or suffix == ".shp":
        assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON
    else:
        assert output_layerinfo.geometrytype == GeometryType.POLYGON

    # Read result for some more detailed checks
    output_gdf = gfo.read_file(output_path)
    for index in range(0, 2):
        output_geometry = output_gdf["geometry"][index]
        assert output_geometry is not None
        if isinstance(output_geometry, sh_geom.MultiPolygon):
            assert len(output_geometry.geoms) == 1
            output_geometry = output_geometry.geoms[0]
        assert isinstance(output_geometry, sh_geom.Polygon)

        if index == 0:
            # In the 1st polygon the island must be removed
            assert len(output_geometry.interiors) == 0
        elif index == 1:
            # In the 2nd polygon the island is larger, so should be there
            assert len(output_geometry.interiors) == 1


def test_apply_geooperation_invalid_operation(tmp_path):
    with pytest.raises(ValueError, match="operation not supported: INVALID"):
        _geoops_gpd._apply_geooperation(
            input_path=test_helper.get_testfile("polygon-parcel"),
            output_path=tmp_path / "output.gpkg",
            operation="INVALID",  # type: ignore
            operation_params={},
        )


@pytest.mark.parametrize(
    "suffix, epsg", [(".gpkg", 31370), (".gpkg", 4326), (".shp", 31370)]
)
def test_buffer_styles(tmp_path, suffix, epsg):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix, epsg=epsg)
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    input_layerinfo = gfo.get_layerinfo(input_path)
    assert input_layerinfo.crs is not None
    distance = 1
    if input_layerinfo.crs.is_projected is False:
        # 1 degree = 111 km or 111000 m
        distance /= 111000
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Run standard buffer to compare with
    gfo.buffer(
        input_path=input_path,
        output_path=output_path,
        distance=distance,
        batchsize=batchsize,
    )

    # Read result
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
    area_default_buffer = sum(output_gdf.area)

    # Test polygon buffer with square endcaps
    output_path = (
        output_path.parent / f"{output_path.stem}_endcap_join{output_path.suffix}"
    )
    gfo.buffer(
        input_path=input_path,
        output_path=output_path,
        distance=distance,
        endcap_style=geometry_util.BufferEndCapStyle.SQUARE,
        join_style=geometry_util.BufferJoinStyle.MITRE,
        batchsize=batchsize,
    )

    # Now check if the output file is correctly created
    assert output_path.exists()
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert input_layerinfo.featurecount == output_layerinfo.featurecount
    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Read result for some more detailed checks
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
    area_square_buffer = sum(output_gdf.area)
    assert area_square_buffer > area_default_buffer


@pytest.mark.parametrize("suffix", DEFAULT_SUFFIXES)
@pytest.mark.parametrize("epsg", DEFAULT_EPSGS)
def test_dissolve_linestrings(tmp_path, suffix, epsg):
    # Prepare test data
    input_path = test_helper.get_testfile(
        "linestring-watercourse", suffix=suffix, epsg=epsg
    )
    output_basepath = tmp_path / f"{input_path.stem}-output{suffix}"
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Dissolve, no groupby, explodecollections=True
    # ---------------------------------------------
    output_path = (
        output_basepath.parent / f"{output_basepath.stem}_expl{output_basepath.suffix}"
    )
    gfo.dissolve(
        input_path=input_path,
        output_path=output_path,
        explodecollections=True,
        batchsize=batchsize,
    )

    # Check if the result file is correctly created
    assert output_path.exists()
    assert gfo.has_spatial_index(output_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 83
    assert output_layerinfo.geometrytype in [
        GeometryType.LINESTRING,
        GeometryType.MULTILINESTRING,
    ]
    assert len(output_layerinfo.columns) >= 0

    # Now check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == output_layerinfo.featurecount
    assert output_gdf["geometry"][0] is not None
    # TODO: add more in depth check of result

    # Dissolve, no groupby, explodecollections=False
    # ----------------------------------------------
    output_path = (
        output_basepath.parent
        / f"{output_basepath.stem}_noexpl{output_basepath.suffix}"
    )
    gfo.dissolve(
        input_path=input_path,
        output_path=output_path,
        explodecollections=False,
        batchsize=batchsize,
    )

    # Check if the result file is correctly created
    assert output_path.exists()
    input_layerinfo = gfo.get_layerinfo(input_path)

    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 1
    assert output_layerinfo.geometrytype is input_layerinfo.geometrytype
    assert len(output_layerinfo.columns) >= 0

    # Now check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == output_layerinfo.featurecount
    assert output_gdf["geometry"][0] is not None
    # TODO: add more in depth check of result


@pytest.mark.parametrize("suffix", DEFAULT_SUFFIXES)
@pytest.mark.parametrize("epsg", DEFAULT_EPSGS)
def test_dissolve_linestrings_groupby(tmp_path, suffix, epsg):
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
    groupby_columns = ["NISCODE"]
    gfo.dissolve(
        input_path=input_path,
        output_path=output_path,
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


@pytest.mark.parametrize("suffix", DEFAULT_SUFFIXES)
@pytest.mark.parametrize("epsg", DEFAULT_EPSGS)
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
    if gfo.GeofileType(input_path).is_fid_zerobased:
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
    if gfo.GeofileType(input_path).is_fid_zerobased:
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
    "suffix, epsg, groupby_columns, explode, expected_featurecount",
    [
        (".gpkg", 31370, ["GEWASGROEP"], True, 25),
        (".gpkg", 31370, ["GEWASGROEP"], False, 6),
        (".gpkg", 31370, ["gewasGROEP"], False, 6),
        (".gpkg", 31370, [], True, 23),
        (".gpkg", 31370, None, False, 1),
        (".gpkg", 4326, ["GEWASGROEP"], True, 25),
        (".shp", 31370, ["GEWASGROEP"], True, 25),
        (".shp", 31370, [], True, 23),
    ],
)
def test_dissolve_polygons(
    tmp_path, suffix, epsg, groupby_columns, explode, expected_featurecount
):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix, epsg=epsg)
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Test dissolve polygons with different options for groupby and explodecollections
    # --------------------------------------------------------------------------------
    groupby = True if (groupby_columns is None or len(groupby_columns) == 0) else False
    output_path = (
        tmp_path / f"{input_path.stem}_groupby-{groupby}_explode-{explode}{suffix}"
    )
    gfo.dissolve(
        input_path=input_path,
        output_path=output_path,
        groupby_columns=groupby_columns,
        explodecollections=explode,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Now check if the tmp file is correctly created
    assert output_path.exists()
    assert gfo.has_spatial_index(output_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == expected_featurecount
    if groupby is True:
        # No groupby -> normally no columns.
        # Shapefile needs at least one column, if no columns: fid
        if suffix == ".shp":
            assert len(output_layerinfo.columns) == 1
        else:
            assert len(output_layerinfo.columns) == 0
    else:
        assert len(output_layerinfo.columns) == len(groupby_columns)
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == output_layerinfo.featurecount
    assert output_gdf["geometry"][0] is not None

    # Compare result with geopandas
    columns = ["geometry"]
    if groupby_columns is None or len(groupby_columns) == 0:
        output_gpd_gdf = input_gdf[columns].dissolve()  # type: ignore
    else:
        groupby_columns_upper = {column.upper(): column for column in groupby_columns}
        columns += list(groupby_columns_upper)
        output_gpd_gdf = (
            input_gdf[columns]
            .dissolve(by=list(groupby_columns_upper))  # type: ignore
            .reset_index()
        ).rename(columns=groupby_columns_upper)
    if explode:
        output_gpd_gdf = output_gpd_gdf.explode(ignore_index=True)
    output_gpd_path = tmp_path / f"{input_path.stem}_gpd-output{suffix}"
    gfo.to_file(output_gpd_gdf, output_gpd_path)

    # Small differences with the geopandas result are expected, because gfo
    # adds points in the tiling process. So only basic checks possible.
    # assert_geodataframe_equal(
    #        output_gdf, output_gpd_gdf, promote_to_multi=True, sort_values=True,
    #        normalize=True, check_less_precise=True, output_dir=tmp_path)
    if suffix != ".shp":
        # Shapefile needs at least one column, if no columns: fid
        assert list(output_gdf.columns) == list(output_gpd_gdf.columns)
    assert len(output_gdf) == len(output_gpd_gdf)


@pytest.mark.parametrize("suffix", DEFAULT_SUFFIXES)
def test_dissolve_emptyfile(tmp_path, suffix):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix, empty=True)

    # Test dissolve polygons with different options for groupby and explodecollections
    output_path = tmp_path / f"{input_path.stem}_dissolve-emptyfile{suffix}"
    groupby_columns = ["GEWASGROEP"]
    gfo.dissolve(
        input_path=input_path,
        output_path=output_path,
        explodecollections=True,
        groupby_columns=groupby_columns,
    )

    # Now check if the tmp file is correctly created
    assert output_path.exists()
    input_layerinfo = gfo.get_layerinfo(input_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 0
    assert output_layerinfo.geometrytype == input_layerinfo.geometrytype
    assert list(output_layerinfo.columns) == groupby_columns


@pytest.mark.parametrize("sql_singlethread", [True, False])
@pytest.mark.parametrize(
    "exp_match, invalid_params",
    [
        ("column in groupby_columns not", {"groupby_columns": "NON_EXISTING_COLUMN"}),
        ("input_path doesn't exist: ", {"input_path": Path("nonexisting.abc")}),
        (
            "output_path must not equal input_path",
            {
                "input_path": test_helper.get_testfile("polygon-parcel"),
                "output_path": test_helper.get_testfile("polygon-parcel"),
            },
        ),
        (
            "Dissolve to tiles is not supported for GeometryType.MULTILINESTRING, ",
            {
                "input_path": test_helper.get_testfile("linestring-watercourse"),
                "nb_squarish_tiles": 2,
            },
        ),
        (
            "abc not available in: ",
            {
                "agg_columns": {
                    "columns": [{"column": "abc", "agg": "count", "as": "cba"}]
                }
            },
        ),
    ],
)
def test_dissolve_invalid_params(tmp_path, sql_singlethread, invalid_params, exp_match):
    """
    Test dissolve with some invalid input params.

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
            ValueError(f"unsupported invalid_param: {invalid_param}")

    # Run test
    with pytest.raises(ValueError, match=exp_match):
        if sql_singlethread:
            if nb_squarish_tiles > 1:
                pytest.skip("nb_squarish_tiles not relevant for dissolve_singlethread")
            from geofileops.util import _geoops_sql

            _geoops_sql.dissolve_singlethread(
                input_path=input_path,
                output_path=output_path,
                groupby_columns=groupby_columns,
                explodecollections=True,
                agg_columns=agg_columns,
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
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON
    assert (
        output_layerinfo.columns["none_values"].gdal_type
        == input_layerinfo.columns["none_values"].gdal_type
    )


@pytest.mark.parametrize("suffix", DEFAULT_SUFFIXES)
def test_dissolve_polygons_specialcases(tmp_path, suffix):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)
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
        assert output_layerinfo.featurecount == 25
        assert len(output_layerinfo.columns) == 1
        assert output_layerinfo.name == "banana"
        assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

        # Now check the contents of the result file
        input_gdf = gfo.read_file(input_path)
        output_gdf = gfo.read_file(output_path)
        assert input_gdf.crs == output_gdf.crs
        assert len(output_gdf) == output_layerinfo.featurecount
        assert output_gdf["geometry"][0] is not None

    # Test dissolve polygons with tiles_path
    # --------------------------------------
    output_path = (
        output_basepath.parent
        / f"{output_basepath.stem}_tilespath{output_basepath.suffix}"
    )
    tiles_path = output_basepath.parent / "tiles.gpkg"
    tiles_gdf = grid_util.create_grid2(
        input_layerinfo.total_bounds, nb_squarish_tiles=4, crs=31370
    )
    gfo.to_file(tiles_gdf, tiles_path)
    gfo.dissolve(
        input_path=input_path,
        output_path=output_path,
        tiles_path=tiles_path,
        explodecollections=False,
        nb_parallel=2,
        batchsize=batchsize,
        force=True,
    )

    # Now check if the result file is correctly created
    assert output_path.exists()
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 4
    if output_basepath.suffix == ".shp":
        # Shapefile always has an FID field
        # but only if there is no other column???
        # TODO: think about whether this should also be the case for geopackage???
        assert len(output_layerinfo.columns) == 1
    else:
        assert len(output_layerinfo.columns) == 1
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

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


@pytest.mark.parametrize("suffix", DEFAULT_SUFFIXES)
def test_dissolve_polygons_aggcolumns_columns(tmp_path, suffix):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)
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
            {"column": "lblhfdtlt", "agg": "max", "as": "lbl_max"},
            {"column": "GEWASGROEP", "agg": "count", "as": "gwsgrp_cnt"},
            {"column": "lblhfdtlt", "agg": "count", "as": "lbl_count"},
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
        ]
    }
    groupby_columns = ["GEWASGROEP"]
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

    # Check agg_columns results
    grasland_idx = output_gdf[output_gdf["GEWASGROEP"] == "Grasland"].index.to_list()[0]
    assert output_gdf["lbl_max"][grasland_idx] == "Grasland"
    assert output_gdf["gwsgrp_cnt"][grasland_idx] == 30
    assert output_gdf["lbl_count"][grasland_idx] == 30
    print(f"output_gdf.lbl_concat_distinct: {output_gdf['lbl_conc_d'][grasland_idx]}")
    assert output_gdf["lbl_cnt_d"][grasland_idx] == 1
    assert output_gdf["lbl_conc"][grasland_idx].startswith("Grasland,Grasland,")
    assert output_gdf["lbl_conc_s"][grasland_idx].startswith("Grasland;Grasland;")
    assert output_gdf["lbl_conc_d"][grasland_idx] == "Grasland"
    assert output_gdf["tlt_mea"][grasland_idx] == 60  # type: ignore
    assert int(output_gdf["tlt_min"][grasland_idx]) == 60  # type: ignore
    assert output_gdf["tlt_sum"][grasland_idx] == 1800  # type: ignore

    groenten_idx = output_gdf[
        output_gdf["GEWASGROEP"] == "Groenten, kruiden en sierplanten"
    ].index.to_list()[0]
    assert output_gdf["lbl_count"][groenten_idx] == 5
    print(
        "groenten.lblhfdtlt_concat_distinct: "
        "f{output_gdf['lbl_conc_d'][groenten_idx]}"
    )
    assert output_gdf["lbl_cnt_d"][groenten_idx] == 4
    fid_concat_result = sorted(output_gdf["fid_concat"][groenten_idx].split(","))
    if gfo.GeofileType(input_path).is_fid_zerobased:
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
        groupby_columns=["GEWASGROEP"],
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
    assert len(grasland_json) == 30
    grasland_json_firstrow = json.loads(str(grasland_json[0]))
    if agg_columns["json"] is None:
        # fid_orig column is added in json, but index column disappeared ???
        assert len(grasland_json_firstrow) == len(input_layerinfo.columns)
    else:
        # fid_orig column is added in json
        assert len(grasland_json_firstrow) == len(agg_columns["json"]) + 1


@pytest.mark.parametrize(
    "suffix, epsg, testfile",
    [
        (".gpkg", 31370, "polygon-parcel"),
        (".gpkg", 31370, "linestring-row-trees"),
        (".gpkg", 4326, "polygon-parcel"),
        (".shp", 31370, "polygon-parcel"),
        (".shp", 4326, "polygon-parcel"),
    ],
)
def test_simplify_vw(tmp_path, suffix, epsg, testfile):
    # Skip test if simplification is not available
    _ = pytest.importorskip("simplification")

    # Init
    input_path = test_helper.get_testfile(testfile, suffix=suffix, epsg=epsg)
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    assert input_layerinfo.crs is not None
    if input_layerinfo.crs.is_projected:
        tolerance = 5
    else:
        # 1 degree = 111 km or 111000 m
        tolerance = 5 / 111000

    # Test vw (visvalingam-whyatt) algorithm
    output_path = tmp_path / f"{input_path.stem}-output_vw{suffix}"
    gfo.simplify(
        input_path=input_path,
        output_path=output_path,
        tolerance=tolerance,
        algorithm=geometry_util.SimplifyAlgorithm.VISVALINGAM_WHYATT,
        batchsize=batchsize,
    )

    # Check if the file is correctly created
    assert output_path.exists()
    assert gfo.has_spatial_index(output_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert input_layerinfo.featurecount == output_layerinfo.featurecount
    assert len(input_layerinfo.columns) == len(output_layerinfo.columns)
    assert output_layerinfo.geometrytype == input_layerinfo.geometrytype

    # Check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == output_layerinfo.featurecount
    assert output_gdf["geometry"][0] is not None
    # TODO: a more in-depth check would be better


@pytest.mark.parametrize(
    "suffix, epsg, testfile",
    [
        (".gpkg", 31370, "polygon-parcel"),
        (".gpkg", 31370, "linestring-row-trees"),
        (".gpkg", 4326, "polygon-parcel"),
        (".shp", 31370, "polygon-parcel"),
        (".shp", 4326, "polygon-parcel"),
    ],
)
def test_simplify_lang(tmp_path, suffix, epsg, testfile):
    input_path = test_helper.get_testfile(testfile, suffix=suffix, epsg=epsg)
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    assert input_layerinfo.crs is not None
    if input_layerinfo.crs.is_projected:
        tolerance = 5
    else:
        # 1 degree = 111 km or 111000 m
        tolerance = 5 / 111000
    # Test lang algorithm
    output_path = tmp_path / f"{input_path.stem}-output_lang{suffix}"
    gfo.simplify(
        input_path=input_path,
        output_path=output_path,
        tolerance=tolerance,
        algorithm=geometry_util.SimplifyAlgorithm.LANG,
        lookahead=8,
        batchsize=batchsize,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    assert gfo.has_spatial_index(output_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert input_layerinfo.featurecount == output_layerinfo.featurecount
    assert len(input_layerinfo.columns) == len(output_layerinfo.columns)
    assert output_layerinfo.geometrytype == input_layerinfo.geometrytype

    # Check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == output_layerinfo.featurecount
    assert output_gdf["geometry"][0] is not None
    # TODO: some more in-depth validations would be better
