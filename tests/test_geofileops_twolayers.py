# -*- coding: utf-8 -*-
"""
Tests for operations that are executed using a sql statement on two layers.
"""

import math
from pathlib import Path
import sys

import geopandas as gpd
import pytest

# Add path so the local geofileops packages are found
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import geofileops as gfo
from geofileops import GeometryType, PrimitiveType
from geofileops.util import _geoops_sql
from tests import test_helper
from tests.test_helper import DEFAULT_SUFFIXES, DEFAULT_TESTFILES
from tests.test_helper import assert_geodataframe_equal


@pytest.mark.parametrize("testfile", DEFAULT_TESTFILES)
@pytest.mark.parametrize("suffix", DEFAULT_SUFFIXES)
def test_clip(tmp_path, testfile, suffix):
    input_path = test_helper.get_testfile(testfile, suffix=suffix)
    clip_path = test_helper.get_testfile("polygon-zone", suffix=suffix)
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    gfo.clip(
        input_path=input_path,
        clip_path=clip_path,
        output_path=output_path,
        batchsize=batchsize,
    )

    # Compare result with geopandas
    assert output_path.exists()
    output_gdf = gfo.read_file(output_path)
    input_gdf = gfo.read_file(input_path)
    clip_gdf = gfo.read_file(clip_path)
    output_gpd_gdf = gpd.clip(input_gdf, clip_gdf, keep_geom_type=True)
    assert_geodataframe_equal(
        output_gdf, output_gpd_gdf, promote_to_multi=True, sort_values=True
    )


@pytest.mark.parametrize("testfile", DEFAULT_TESTFILES)
@pytest.mark.parametrize("suffix", DEFAULT_SUFFIXES)
def test_erase(tmp_path, testfile, suffix):
    input_path = test_helper.get_testfile(testfile, suffix=suffix)
    erase_path = test_helper.get_testfile("polygon-zone", suffix=suffix)
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"

    gfo.erase(
        input_path=input_path,
        erase_path=erase_path,
        output_path=output_path,
        batchsize=batchsize,
    )

    # Compare result with geopandas
    assert output_path.exists()
    output_gdf = gfo.read_file(output_path)
    input_gdf = gfo.read_file(input_path)
    erase_gdf = gfo.read_file(erase_path)
    output_gpd_gdf = gpd.overlay(
        input_gdf, erase_gdf, how="difference", keep_geom_type=True
    )
    assert_geodataframe_equal(
        output_gdf,
        output_gpd_gdf,
        promote_to_multi=True,
        sort_values=True,
        check_less_precise=True,
        normalize=True,
    )


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


@pytest.mark.parametrize("suffix", DEFAULT_SUFFIXES)
def test_export_by_location(tmp_path, suffix):
    input_to_select_from_path = test_helper.get_testfile(
        "polygon-parcel", suffix=suffix
    )
    input_to_compare_with_path = test_helper.get_testfile("polygon-zone", suffix=suffix)
    output_path = tmp_path / f"{input_to_select_from_path.stem}-output{suffix}"
    input_layerinfo = gfo.get_layerinfo(input_to_select_from_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Test
    gfo.export_by_location(
        input_to_select_from_path=input_to_select_from_path,
        input_to_compare_with_path=input_to_compare_with_path,
        output_path=output_path,
        batchsize=batchsize,
    )

    # Check if the output file is correctly created
    assert output_path.exists()
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 26
    assert len(output_layerinfo.columns) == len(input_layerinfo.columns) + 1
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Check the contents of the result file
    # TODO: this test should be more elaborate...
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None


@pytest.mark.parametrize("testfile", ["polygon-parcel"])
@pytest.mark.parametrize("suffix", DEFAULT_SUFFIXES)
def test_export_by_distance(tmp_path, testfile, suffix):
    input_to_select_from_path = test_helper.get_testfile(testfile, suffix=suffix)
    input_to_compare_with_path = test_helper.get_testfile("polygon-zone", suffix=suffix)
    input_layerinfo = gfo.get_layerinfo(input_to_select_from_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    output_path = tmp_path / f"{input_to_select_from_path.stem}-output{suffix}"

    # Test
    gfo.export_by_distance(
        input_to_select_from_path=input_to_select_from_path,
        input_to_compare_with_path=input_to_compare_with_path,
        max_distance=10,
        output_path=output_path,
        batchsize=batchsize,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    output_layerinfo = gfo.get_layerinfo(input_to_select_from_path)
    assert input_layerinfo.featurecount == output_layerinfo.featurecount
    assert len(input_layerinfo.columns) == len(output_layerinfo.columns)
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Check the contents of the result file
    # TODO: this test should be more elaborate...
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None


@pytest.mark.parametrize("testfile", ["polygon-parcel"])
@pytest.mark.parametrize(
    "suffix, epsg", [(".gpkg", 31370), (".gpkg", 4326), (".shp", 31370)]
)
def test_intersection(tmp_path, testfile, suffix, epsg):
    input1_path = test_helper.get_testfile(testfile, suffix=suffix, epsg=epsg)
    input2_path = test_helper.get_testfile("polygon-zone", suffix=suffix, epsg=epsg)
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)

    # Now run test
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

    # Check if the tmp file is correctly created
    assert output_path.exists()
    input2_layerinfo = gfo.get_layerinfo(input2_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 29
    assert len(output_layerinfo.columns) == (
        len(input1_layerinfo.columns) + len(input2_layerinfo.columns)
    )
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None

    input1_gdf = gfo.read_file(input1_path)
    input2_gdf = gfo.read_file(input2_path)
    overlay_operation = "intersection"
    output_gpd_gdf = input1_gdf.overlay(
        input2_gdf, how=overlay_operation, keep_geom_type=True
    )
    renames = {
        name_gpd: name_gfo
        for name_gpd, name_gfo in zip(output_gpd_gdf.columns, output_gdf.columns)
    }
    output_gpd_gdf = output_gpd_gdf.rename(columns=renames)
    assert_geodataframe_equal(output_gdf, output_gpd_gdf, sort_values=True)


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
        filter = _geoops_sql._prepare_spatial_relations_filter(query)
        assert filter is not None and filter != ""

    # Test extra queries that should work
    ok_queries = [
        "intersects is False",
        "(intersects is False and within is True) and crosses is False"
        "(((T******** is False)))",
    ]
    for query in ok_queries:
        filter = _geoops_sql._prepare_spatial_relations_filter(query)
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
            _ = _geoops_sql._prepare_spatial_relations_filter(query)
            error = False
        except Exception:
            error = True
        assert error is True, error_reason


@pytest.mark.parametrize(
    "suffix, epsg, spatial_relations_query, discard_nonmatching, "
    "min_area_intersect, expected_featurecount",
    [
        (".gpkg", 31370, "intersects is False", False, None, 46),
        (".gpkg", 31370, "intersects is False", True, None, 0),
        (".gpkg", 31370, "intersects is True", False, 1000, 48),
        (".gpkg", 31370, "intersects is True", False, None, 49),
        (".gpkg", 31370, "intersects is True", True, 1000, 25),
        (".gpkg", 31370, "intersects is True", True, None, 29),
        (".gpkg", 31370, "T******** is True or *T******* is True", True, None, 29),
        (".gpkg", 4326, "intersects is True", False, None, 49),
        (".shp", 31370, "intersects is True", False, None, 49),
    ],
)
def test_join_by_location(
    tmp_path,
    suffix: str,
    spatial_relations_query: str,
    epsg: int,
    discard_nonmatching: bool,
    min_area_intersect: float,
    expected_featurecount: int,
):
    input1_path = test_helper.get_testfile("polygon-parcel", suffix=suffix, epsg=epsg)
    input2_path = test_helper.get_testfile("polygon-zone", suffix=suffix, epsg=epsg)
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)
    output_path = (
        tmp_path
        / f"{input1_path.stem}_{discard_nonmatching}_{min_area_intersect}{suffix}"
    )
    gfo.join_by_location(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        spatial_relations_query=spatial_relations_query,
        discard_nonmatching=discard_nonmatching,
        min_area_intersect=min_area_intersect,
        batchsize=batchsize,
        force=True,
    )

    # If no result expected, the output files shouldn't exist
    if expected_featurecount == 0:
        assert output_path.exists() is False
        return

    # Check if the output file is correctly created
    assert output_path.exists() is True
    input2_layerinfo = gfo.get_layerinfo(input2_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == expected_featurecount
    assert len(output_layerinfo.columns) == (
        len(input1_layerinfo.columns) + len(input2_layerinfo.columns) + 1
    )
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Check the contents of the result file
    # TODO: this test should be more elaborate...
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None


@pytest.mark.parametrize(
    "suffix, epsg", [(".gpkg", 31370), (".gpkg", 4384), (".shp", 31370)]
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
    gfo.join_nearest(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        nb_nearest=nb_nearest,
        batchsize=batchsize,
        force=True,
    )

    # Check if the output file is correctly created
    assert output_path.exists()
    input2_layerinfo = gfo.get_layerinfo(input2_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == nb_nearest * input1_layerinfo.featurecount
    assert len(output_layerinfo.columns) == (
        len(input1_layerinfo.columns) + len(input2_layerinfo.columns) + 2
    )
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Check the contents of the result file
    # TODO: this test should be more elaborate...
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None


@pytest.mark.parametrize(
    "suffix, epsg, overlay_operation, discard_nonmatching, expected_featurecount",
    [
        (".gpkg", 31370, "difference", False, 46),
        (".gpkg", 31370, "identity", True, 0),
        (".gpkg", 31370, "intersection", False, 48),
        (".gpkg", 31370, "symmetric_difference", False, 49),
        (".gpkg", 31370, "union", True, 25),
        (".gpkg", 4326, "intersection", False, 49),
        (".shp", 31370, "intersection", False, 49),
    ],
)
def test_overlay(
    tmp_path,
    suffix: str,
    epsg: int,
    overlay_operation: str,
    discard_nonmatching: bool,
    expected_featurecount: int,
):
    input1_path = test_helper.get_testfile("polygon-parcel", suffix=suffix, epsg=epsg)
    input2_path = test_helper.get_testfile("polygon-zone", suffix=suffix, epsg=epsg)
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)

    # Test
    """
    output_path = tmp_dir / f"{input1_path.stem}_{overlay_operation}_{input2_path.stem}_{discard_nonmatching}{suffix}"
    gfo.overlay(
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=output_path,
            spatial_relations_query=spatial_relations_query,
            discard_nonmatching=discard_nonmatching,
            min_area_intersect=min_area_intersect,
            batchsize=batchsize,
            force=True)

    # If no result expected, the output files shouldn't exist
    if expected_featurecount == 0:
        assert output_path.exists() is False
        return

    # Check if the output file is correctly created
    assert output_path.exists() is True
    layerinfo_input1 = gfo.get_layerinfo(input1_path)
    layerinfo_input2 = gfo.get_layerinfo(input2_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == expected_featurecount
    assert len(layerinfo_output.columns) == (
            len(layerinfo_input1.columns) + len(layerinfo_input2.columns) + 1)
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None
    """
    input1_gdf = gfo.read_file(input1_path)
    input2_gdf = gfo.read_file(input2_path)

    result_gdf = input1_gdf.overlay(
        input2_gdf, how=overlay_operation, keep_geom_type=True
    )
    output_gpd_path = (
        tmp_path
        / f"{input1_path.stem}_{overlay_operation}-gpd_{input2_path.stem}_{discard_nonmatching}{suffix}"
    )
    gfo.to_file(result_gdf, output_gpd_path)


@pytest.mark.parametrize(
    "suffix, epsg", [(".gpkg", 31370), (".gpkg", 4326), (".shp", 31370)]
)
def test_select_two_layers(tmp_path, suffix, epsg):
    # Prepare test data
    input1_path = test_helper.get_testfile("polygon-parcel", suffix=suffix, epsg=epsg)
    input2_path = test_helper.get_testfile("polygon-zone", suffix=suffix, epsg=epsg)
    output_path = tmp_path / f"{input1_path.stem}-output{suffix}"

    # Prepare query to execute. At the moment this is just the query for the
    # intersection() operation.
    input1_layer_info = gfo.get_layerinfo(input1_path)
    input2_layer_info = gfo.get_layerinfo(input2_path)
    primitivetype_to_extract = PrimitiveType(
        min(
            input1_layer_info.geometrytype.to_primitivetype.value,
            input2_layer_info.geometrytype.to_primitivetype.value,
        )
    )
    sql_stmt = f"""
            SELECT ST_CollectionExtract(
                    ST_Intersection(
                            layer1.{{input1_geometrycolumn}},
                            layer2.{{input2_geometrycolumn}}),
                    {primitivetype_to_extract.value}) as geom
                    {{layer1_columns_prefix_alias_str}}
                    {{layer2_columns_prefix_alias_str}}
                    ,CASE
                        WHEN layer2.naam = 'zone1' THEN 'in_zone1'
                        ELSE 'niet_in_zone1'
                        END AS category
                FROM {{input1_databasename}}."{{input1_layer}}" layer1
                JOIN {{input1_databasename}}."rtree_{{input1_layer}}_{{input1_geometrycolumn}}" layer1tree
                     ON layer1.fid = layer1tree.id
                JOIN {{input2_databasename}}."{{input2_layer}}" layer2
                JOIN {{input2_databasename}}."rtree_{{input2_layer}}_{{input2_geometrycolumn}}" layer2tree
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
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        sql_stmt=sql_stmt,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    input2_layerinfo = gfo.get_layerinfo(input2_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 29
    assert len(output_layerinfo.columns) == (
        len(input1_layerinfo.columns) + len(input2_layerinfo.columns) + 1
    )
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None


@pytest.mark.parametrize(
    "suffix, epsg", [(".gpkg", 31370), (".gpkg", 4326), (".shp", 31370)]
)
def test_split(tmp_path, suffix, epsg):
    # Prepare test data
    input1_path = test_helper.get_testfile("polygon-parcel", suffix=suffix, epsg=epsg)
    input2_path = test_helper.get_testfile("polygon-zone", suffix=suffix, epsg=epsg)
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)
    output_path = tmp_path / f"{input1_path.stem}-output{suffix}"

    # Test
    gfo.split(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        batchsize=batchsize,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    input2_layerinfo = gfo.get_layerinfo(input2_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 66
    assert (len(input1_layerinfo.columns) + len(input2_layerinfo.columns)) == len(
        output_layerinfo.columns
    )
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Check the contents of the result file
    # TODO: this test should be more elaborate...
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
    input1_gdf = gfo.read_file(input1_path)
    input2_gdf = gfo.read_file(input2_path)
    output_gpd_gdf = input1_gdf.overlay(input2_gdf, how="identity", keep_geom_type=True)
    renames = {
        name_gpd: name_gfo
        for name_gpd, name_gfo in zip(output_gpd_gdf.columns, output_gdf.columns)
    }
    output_gpd_gdf = output_gpd_gdf.rename(columns=renames)
    # OIDN is float vs int? -> check_column_type=False
    assert_geodataframe_equal(
        output_gdf,
        output_gpd_gdf,
        promote_to_multi=True,
        sort_values=True,
        check_less_precise=True,
        normalize=True,
        check_dtype=False,
    )


@pytest.mark.parametrize(
    "suffix, epsg", [(".gpkg", 31370), (".gpkg", 4326), (".shp", 31370)]
)
def test_symmetric_difference(tmp_path, suffix, epsg):
    input1_path = test_helper.get_testfile("polygon-zone", suffix=suffix, epsg=epsg)
    input2_path = test_helper.get_testfile("polygon-parcel", suffix=suffix, epsg=epsg)
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)

    # Test
    output_path = tmp_path / f"{input1_path.stem}_symmdiff_{input2_path.stem}{suffix}"
    gfo.symmetric_difference(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        batchsize=batchsize,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
    input1_gdf = gfo.read_file(input1_path)
    input2_gdf = gfo.read_file(input2_path)
    output_gpd_gdf = input1_gdf.overlay(
        input2_gdf, how="symmetric_difference", keep_geom_type=True
    )
    renames = {
        name_gpd: name_gfo
        for name_gpd, name_gfo in zip(output_gpd_gdf.columns, output_gdf.columns)
    }
    output_gpd_gdf = output_gpd_gdf.rename(columns=renames)
    assert_geodataframe_equal(
        output_gdf,
        output_gpd_gdf,
        promote_to_multi=True,
        sort_values=True,
        check_column_type=False,
        check_dtype=False,
        check_less_precise=True,
        normalize=True,
    )


@pytest.mark.parametrize(
    "suffix, epsg", [(".gpkg", 31370), (".gpkg", 4326), (".shp", 31370)]
)
def test_union(tmp_path, suffix, epsg):
    input1_path = test_helper.get_testfile("polygon-parcel", suffix=suffix, epsg=epsg)
    input2_path = test_helper.get_testfile("polygon-zone", suffix=suffix, epsg=epsg)
    input1_layerinfo = gfo.get_layerinfo(input1_path)
    batchsize = math.ceil(input1_layerinfo.featurecount / 2)

    # Test
    output_path = tmp_path / f"{input1_path.stem}_union_{input2_path.stem}{suffix}"
    gfo.union(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        batchsize=batchsize,
    )

    # Check if the tmp file is correctly created
    assert output_path.exists()
    input2_layerinfo = gfo.get_layerinfo(input2_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 71
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
    renames = {
        name_gpd: name_gfo
        for name_gpd, name_gfo in zip(output_gpd_gdf.columns, output_gdf.columns)
    }
    output_gpd_gdf = output_gpd_gdf.rename(columns=renames)
    assert_geodataframe_equal(
        output_gdf,
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
    renames = {
        name_gpd: name_gfo
        for name_gpd, name_gfo in zip(output_gpd_gdf.columns, output_gdf.columns)
    }
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
    renames = {
        name_gpd: name_gfo
        for name_gpd, name_gfo in zip(output_gpd_gdf.columns, output_gdf.columns)
    }
    output_gpd_gdf = output_gpd_gdf.rename(columns=renames)
    assert_geodataframe_equal(
        output_gdf,
        output_gpd_gdf,
        promote_to_multi=True,
        sort_values=True,
        check_less_precise=True,
        normalize=True,
    )
