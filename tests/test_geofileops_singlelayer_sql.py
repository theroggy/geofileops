# -*- coding: utf-8 -*-
"""
Tests for operations that are executed using a sql statement on one layer.
"""

import math
from pathlib import Path
import sys

import geopandas as gpd
import pytest

# Add path so the local geofileops packages are found
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import geofileops as gfo
from geofileops import GeometryType
from tests import test_helper
from tests.test_helper import DEFAULT_EPSGS, DEFAULT_SUFFIXES


def test_delete_duplicate_geometries(tmp_path):
    # Prepare test data
    test_gdf = gpd.GeoDataFrame(
        geometry=[
            test_helper.TestData.polygon_with_island,
            test_helper.TestData.polygon_with_island,
            test_helper.TestData.polygon_no_islands,
            test_helper.TestData.polygon_no_islands,
            test_helper.TestData.polygon_with_island2,
        ],
        crs=test_helper.TestData.crs_epsg,
    )
    suffix = ".gpkg"
    input_path = tmp_path / f"input_test_data{suffix}"
    gfo.to_file(test_gdf, input_path)
    input_info = gfo.get_layerinfo(input_path)

    # Run test
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    print(f"Run test for suffix {suffix}")
    # delete_duplicate_geometries isn't multiprocess, so no batchsize needed
    gfo.delete_duplicate_geometries(input_path=input_path, output_path=output_path)

    # Check result, 2 duplicates should be removed
    result_info = gfo.get_layerinfo(output_path)
    assert result_info.featurecount == input_info.featurecount - 2


@pytest.mark.parametrize("suffix", DEFAULT_SUFFIXES)
@pytest.mark.parametrize("epsg", DEFAULT_EPSGS)
def test_isvalid(tmp_path, suffix, epsg):
    # Prepare test data
    input_path = test_helper.get_testfile(
        "polygon-invalid", dst_dir=tmp_path, suffix=suffix, epsg=epsg
    )

    # Now run test
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    gfo.isvalid(input_path=input_path, output_path=output_path, batchsize=batchsize)

    # Now check if the tmp file is correctly created
    assert output_path.exists() is True
    result_layerinfo = gfo.get_layerinfo(output_path)
    assert input_layerinfo.featurecount == result_layerinfo.featurecount
    assert len(input_layerinfo.columns) == len(result_layerinfo.columns) - 2

    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
    assert output_gdf["isvalid"][0] == 0

    # Do operation, without specifying output path
    gfo.isvalid(input_path=input_path, batchsize=batchsize)

    # Now check if the tmp file is correctly created
    output_auto_path = (
        output_path.parent / f"{input_path.stem}_isvalid{output_path.suffix}"
    )
    assert output_auto_path.exists()
    result_auto_layerinfo = gfo.get_layerinfo(output_auto_path)
    assert input_layerinfo.featurecount == result_auto_layerinfo.featurecount
    assert len(input_layerinfo.columns) == len(result_auto_layerinfo.columns) - 2

    output_auto_gdf = gfo.read_file(output_auto_path)
    assert output_auto_gdf["geometry"][0] is not None
    assert output_auto_gdf["isvalid"][0] == 0


@pytest.mark.parametrize("suffix", DEFAULT_SUFFIXES)
def test_makevalid(tmp_path, suffix):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-invalid", suffix=suffix)

    # Do operation
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    gfo.makevalid(input_path=input_path, output_path=output_path, nb_parallel=2)

    # Now check if the output file is correctly created
    assert output_path.exists()
    layerinfo_orig = gfo.get_layerinfo(input_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_orig.featurecount == layerinfo_output.featurecount
    assert len(layerinfo_orig.columns) == len(layerinfo_output.columns)
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None

    # Make sure the input file was not valid
    output_isvalid_path = (
        output_path.parent / f"{output_path.stem}_is-valid{output_path.suffix}"
    )
    isvalid = gfo.isvalid(input_path=input_path, output_path=output_isvalid_path)
    assert isvalid is False, "Input file should contain invalid features"

    # Check if the result file is valid
    output_new_isvalid_path = (
        output_path.parent / f"{output_path.stem}_new_is-valid{output_path.suffix}"
    )
    isvalid = gfo.isvalid(input_path=output_path, output_path=output_new_isvalid_path)
    assert isvalid is True, "Output file shouldn't contain invalid features"


@pytest.mark.parametrize("input_suffix", DEFAULT_SUFFIXES)
@pytest.mark.parametrize("output_suffix", DEFAULT_SUFFIXES)
def test_select(tmp_path, input_suffix, output_suffix):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=input_suffix)

    # Now run test
    output_path = (
        tmp_path
        / f"{input_path.stem}-{input_suffix.replace('.', '')}-output{output_suffix}"
    )
    layerinfo_input = gfo.get_layerinfo(input_path)
    sql_stmt = 'SELECT {geometrycolumn}, oidn, uidn FROM "{input_layer}"'
    gfo.select(input_path=input_path, output_path=output_path, sql_stmt=sql_stmt)

    # Now check if the tmp file is correctly created
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_input.featurecount == layerinfo_output.featurecount
    assert "OIDN" in layerinfo_output.columns
    assert "UIDN" in layerinfo_output.columns
    assert len(layerinfo_output.columns) == 2
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None


@pytest.mark.parametrize("suffix", DEFAULT_SUFFIXES)
def test_select_various_options(tmp_path, suffix):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", tmp_path, suffix)

    # Check if columns parameter works (case insensitive)
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    columns = ["OIDN", "uidn", "HFDTLT", "lblhfdtlt", "GEWASGROEP", "lengte", "OPPERVL"]
    layerinfo_input = gfo.get_layerinfo(input_path)
    sql_stmt = '''SELECT {geometrycolumn}
                        {columns_to_select_str}
                    FROM "{input_layer}"'''
    gfo.select(
        input_path=input_path,
        output_path=output_path,
        columns=columns,
        sql_stmt=sql_stmt,
    )

    # Now check if the tmp file is correctly created
    layerinfo_select = gfo.get_layerinfo(output_path)
    assert layerinfo_input.featurecount == layerinfo_select.featurecount
    assert "OIDN" in layerinfo_select.columns
    assert "UIDN" in layerinfo_select.columns
    assert len(layerinfo_select.columns) == len(columns)

    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
