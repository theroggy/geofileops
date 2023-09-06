"""
Tests for operations using GeoPandas.
"""

import pytest

import geofileops as gfo
from geofileops import GeometryType
from tests import test_helper
from tests.test_helper import SUFFIXES


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_clip_by_geometry(tmp_path, suffix):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # For Geopackage, also test if fid is properly preserved
    preserve_fid = True if suffix == ".gpkg" else False

    # Do operation
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    clip_wkt = (
        "Polygon ((156072 196691, 156036 196836, 156326 196927, 156368 196750, "
        "156072 196691))"
    )
    gfo.clip_by_geometry(
        input_path=input_path, output_path=output_path, clip_geometry=clip_wkt
    )

    # Now check if the output file is correctly created
    assert output_path.exists()
    assert gfo.has_spatial_index(output_path)
    layerinfo_orig = gfo.get_layerinfo(input_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == 22
    assert len(layerinfo_orig.columns) == len(layerinfo_output.columns)
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path, fid_as_index=preserve_fid)
    assert output_gdf["geometry"].iloc[0] is not None

    # Check if the fid was properly retained if relevant
    if preserve_fid:
        assert output_gdf.iloc[0:2].index.sort_values().tolist() == [1, 10]


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_export_by_bounds(tmp_path, suffix):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # For Geopackage, also test if fid is properly preserved
    preserve_fid = True if suffix == ".gpkg" else False

    # Do operation
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    filter = (156036, 196691, 156368, 196927)
    gfo.export_by_bounds(input_path=input_path, output_path=output_path, bounds=filter)

    # Now check if the output file is correctly created
    assert output_path.exists()
    assert gfo.has_spatial_index(output_path)
    layerinfo_orig = gfo.get_layerinfo(input_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == 25
    assert len(layerinfo_orig.columns) == len(layerinfo_output.columns)
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path, fid_as_index=preserve_fid)
    assert output_gdf["geometry"].iloc[0] is not None

    # Check if the fid was properly retained if relevant
    if preserve_fid:
        assert output_gdf.iloc[0:2].index.sort_values().tolist() == [1, 8]


def test_warp(tmp_path):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel")
    input_gdf = gfo.read_file(input_path)
    input_bounds = input_gdf.total_bounds
    warped_min = 0
    warped_max = 10000
    gcps = [
        (input_bounds[0], input_bounds[1], warped_min, warped_min, None),
        (input_bounds[0], input_bounds[3], warped_min, warped_max, None),
        (input_bounds[2], input_bounds[3], warped_max, warped_max, None),
        (input_bounds[2], input_bounds[1], warped_max, warped_min, None),
    ]

    # Test first with existing output path and force=False
    output_path = tmp_path / f"{input_path.stem}-output.gpkg"
    output_path.touch()
    gfo.warp(
        input_path=input_path,
        output_path=output_path,
        gcps=gcps,
        algorithm="tps",
    )
    assert output_path.exists()
    assert output_path.stat().st_size == 0

    # Test force=True
    gfo.warp(
        input_path=input_path,
        output_path=output_path,
        gcps=gcps,
        algorithm="tps",
        force=True,
    )

    # Now check if the output file is correctly created
    assert output_path.exists()
    assert gfo.has_spatial_index(output_path)
    layerinfo_orig = gfo.get_layerinfo(input_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == layerinfo_orig.featurecount
    assert len(layerinfo_orig.columns) == len(layerinfo_output.columns)
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
    output_bounds = output_gdf.total_bounds
    assert output_bounds[0] >= warped_min
    assert output_bounds[1] >= warped_min
    assert output_bounds[2] <= warped_max
    assert output_bounds[3] <= warped_max
