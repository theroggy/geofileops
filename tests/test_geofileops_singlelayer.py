"""
Tests for operations that are executed using a sql statement on one layer.
"""

from importlib import import_module
import logging
import math
from typing import List

import geopandas as gpd
import pytest
from shapely import MultiPolygon, Polygon

from geofileops import geoops
from geofileops import fileops
from geofileops import GeometryType
from geofileops.util import _geoops_sql
from geofileops.util import _io_util as io_util
from tests import test_helper
from tests.test_helper import (
    EPSGS,
    GRIDSIZE_DEFAULT,
    SUFFIXES,
    TESTFILES,
    WHERE_AREA_GT_400,
)
from tests.test_helper import assert_geodataframe_equal

# Init gfo module
current_geoops_module = "unknown"
GEOOPS_MODULES = ["geofileops.geoops", "geofileops.util._geoops_gpd"]


def set_geoops_module(geoops_module: str):
    global current_geoops_module
    if current_geoops_module == geoops_module:
        # The right module is already loaded, so don't do anything
        return
    else:
        # Load the desired module as fileops
        global geoops
        geoops = import_module(geoops_module, __package__)
        current_geoops_module = geoops_module
        print(f"gfo module switched to: {current_geoops_module}")


def basic_combinations_to_test(
    geoops_modules: List[str] = GEOOPS_MODULES,
    testfiles: List[str] = TESTFILES,
    epsgs: List[int] = EPSGS,
    suffixes: List[str] = SUFFIXES,
) -> list:
    """
    Return sensible combinations of parameters to be used in tests for following params:
        suffix, epsg, geoops_module, testfile, empty_input, gridsize, where
    """
    result = []

    # On .gpkg test:
    #   - all combinations of geoops_modules, testfiles and epsgs
    #   - fixed empty_input, suffix
    for epsg in epsgs:
        for geoops_module in geoops_modules:
            for testfile in testfiles:
                where = None
                keep_empty_geoms = None
                gridsize = 0.001 if epsg == 31370 else GRIDSIZE_DEFAULT
                if testfile == "polygon-parcel":
                    keep_empty_geoms = False
                    if epsg == 31370:
                        where = WHERE_AREA_GT_400
                elif testfile == "point":
                    keep_empty_geoms = True
                result.append(
                    (
                        ".gpkg",
                        epsg,
                        geoops_module,
                        testfile,
                        False,
                        gridsize,
                        keep_empty_geoms,
                        where,
                    )
                )

    # On other suffixes test:
    #   - all combinations of geoops_modules, testfiles
    #   - fixed epsg and empty_input
    other_suffixes = list(suffixes)
    other_suffixes.remove(".gpkg")
    for suffix in other_suffixes:
        for geoops_module in geoops_modules:
            for testfile in testfiles:
                where = ""
                keep_empty_geoms = False
                gridsize = 0.001 if testfile == "polygon-parcel" else GRIDSIZE_DEFAULT
                if testfile == "polygon-parcel":
                    where = WHERE_AREA_GT_400
                else:
                    keep_empty_geoms = True
                result.append(
                    (
                        suffix,
                        31370,
                        geoops_module,
                        testfile,
                        False,
                        gridsize,
                        keep_empty_geoms,
                        where,
                    )
                )

    # Test empty_input=True on
    #   - all combinations of fileops_modules and SUFFIXES
    #   - fixed epsg, testfile and empty_input
    for geoops_module in geoops_modules:
        for suffix in suffixes:
            gridsize = 0.001 if suffix == ".gpkg" else GRIDSIZE_DEFAULT
            keep_empty_geoms = False
            where = None
            result.append(
                (
                    suffix,
                    31370,
                    geoops_module,
                    "polygon-parcel",
                    True,
                    gridsize,
                    keep_empty_geoms,
                    where,
                )
            )

    return result


@pytest.mark.parametrize(
    "suffix, epsg, geoops_module, testfile, empty_input, gridsize, keep_empty_geoms, "
    "where",
    basic_combinations_to_test(),
)
def test_buffer(
    tmp_path,
    suffix,
    epsg,
    geoops_module,
    testfile,
    empty_input,
    gridsize,
    keep_empty_geoms,
    where,
):
    """Buffer basics are available both in the gpd and sql implementations."""
    # Prepare test data
    input_path = test_helper.get_testfile(
        testfile, suffix=suffix, epsg=epsg, empty=empty_input
    )

    # Now run test
    output_path = tmp_path / f"{input_path.stem}-{geoops_module}{suffix}"
    set_geoops_module(geoops_module)
    input_layerinfo = fileops.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    assert input_layerinfo.crs is not None
    distance = 1
    if input_layerinfo.crs.is_projected is False:
        # 1 degree = 111 km or 111000 m
        distance /= 111000

    # Prepare expected result
    expected_gdf = fileops.read_file(input_path)
    expected_gdf.geometry = expected_gdf.geometry.buffer(distance, resolution=5)
    expected_gdf = test_helper.prepare_expected_result(
        expected_gdf, gridsize=gridsize, keep_empty_geoms=keep_empty_geoms, where=where
    )

    # Test positive buffer
    geoops.buffer(
        input_path=input_path,
        output_path=output_path,
        distance=distance,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms,
        where=where,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Now check if the output file is correctly created
    assert output_path.exists()
    assert fileops.has_spatial_index(output_path)
    output_layerinfo = fileops.get_layerinfo(output_path)
    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)

    if empty_input:
        return

    # More detailed check
    output_gdf = fileops.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
    check_less_precise = True if input_layerinfo.crs.is_projected is False else False
    assert_geodataframe_equal(
        output_gdf,
        expected_gdf,
        promote_to_multi=True,
        check_less_precise=check_less_precise,
        sort_values=True,
    )


@pytest.mark.parametrize("suffix", SUFFIXES)
@pytest.mark.parametrize("testfile", ["polygon-parcel"])
@pytest.mark.parametrize("geoops_module", GEOOPS_MODULES)
def test_buffer_columns_fid(tmp_path, suffix, geoops_module, testfile):
    """Buffer basics are available both in the gpd and sql implementations."""
    # Prepare test data
    input_path = test_helper.get_testfile(testfile, suffix=suffix)

    # Now run test
    output_path = tmp_path / f"{input_path.stem}-{geoops_module}{suffix}"
    set_geoops_module(geoops_module)
    input_layerinfo = fileops.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Test positive buffer
    geoops.buffer(
        input_path=input_path,
        output_path=output_path,
        distance=1,
        columns=["LblHfdTlt", "fid"],
        explodecollections=True,
        keep_empty_geoms=False,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Read input file and extract some info
    input_gdf = fileops.read_file(input_path, fid_as_index=True)
    if fileops.GeofileType(input_path).is_fid_zerobased:
        assert input_gdf.index[0] == 0
    else:
        assert input_gdf.index[0] == 1
    input_multi_gdf = input_gdf[
        input_gdf.geometry.buffer(0).geom_type == "MultiPolygon"
    ]
    assert len(input_multi_gdf) == 2
    multi_fid = input_multi_gdf.index[0]

    # Now check if the output file is correctly created
    assert output_path.exists()
    assert fileops.has_spatial_index(output_path)
    output_layerinfo = fileops.get_layerinfo(output_path)
    output_gdf = fileops.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
    assert list(output_layerinfo.columns) == ["LblHfdTlt", "fid_1"]
    assert len(output_gdf[output_gdf.fid_1 == multi_fid]) == 2


@pytest.mark.parametrize("geoops_module", GEOOPS_MODULES)
def test_buffer_force(tmp_path, geoops_module):
    input_path = test_helper.get_testfile("polygon-parcel")
    input_layerinfo = fileops.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    distance = 1
    set_geoops_module(geoops_module)

    # Run buffer
    output_path = tmp_path / f"{input_path.stem}-output{input_path.suffix}"
    assert output_path.exists() is False

    geoops.buffer(
        input_path=input_path,
        output_path=output_path,
        distance=distance,
        keep_empty_geoms=False,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Test buffer to existing output path
    assert output_path.exists()
    assert fileops.has_spatial_index(output_path)
    mtime_orig = output_path.stat().st_mtime
    geoops.buffer(
        input_path=input_path,
        output_path=output_path,
        distance=distance,
        keep_empty_geoms=False,
        nb_parallel=2,
        batchsize=batchsize,
    )
    assert output_path.stat().st_mtime == mtime_orig

    # With force=True
    geoops.buffer(
        input_path=input_path,
        output_path=output_path,
        distance=distance,
        keep_empty_geoms=False,
        nb_parallel=2,
        batchsize=batchsize,
        force=True,
    )
    assert output_path.stat().st_mtime != mtime_orig


@pytest.mark.parametrize(
    "expected_error, input_path, output_path",
    [
        (
            "buffer: output_path must not equal input_path",
            test_helper.get_testfile("polygon-parcel"),
            test_helper.get_testfile("polygon-parcel"),
        ),
        (
            "buffer: input_path doesn't exist:",
            "not_existing_path",
            "output.gpkg",
        ),
    ],
)
@pytest.mark.parametrize("geoops_module", GEOOPS_MODULES)
def test_buffer_invalid_params(
    tmp_path, input_path, output_path, expected_error, geoops_module
):
    """
    Invalid params for single layer operations.
    """
    # Internal functions are directly called, so need to be Path objects
    if isinstance(output_path, str):
        output_path = tmp_path / output_path
    if isinstance(input_path, str):
        input_path = tmp_path / input_path

    # Now run test
    set_geoops_module(geoops_module)
    with pytest.raises(ValueError, match=expected_error):
        geoops.buffer(input_path=input_path, output_path=output_path, distance=1)


@pytest.mark.parametrize(
    "suffix, epsg, geoops_module, testfile, empty_input, gridsize, keep_empty_geoms, "
    "where",
    basic_combinations_to_test(epsgs=[31370]),
)
def test_buffer_negative(
    tmp_path,
    suffix,
    epsg,
    geoops_module,
    testfile,
    empty_input,
    gridsize,
    keep_empty_geoms,
    where,
):
    """Buffer basics are available both in the gpd and sql implementations."""
    input_path = test_helper.get_testfile(testfile, suffix=suffix)

    # Now run test
    output_path = tmp_path / f"{input_path.stem}-{geoops_module}{suffix}"
    set_geoops_module(geoops_module)
    input_layerinfo = fileops.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Test negative buffer
    distance = -10
    output_path = output_path.parent / f"{output_path.stem}_m10m{output_path.suffix}"
    geoops.buffer(
        input_path=input_path,
        output_path=output_path,
        distance=distance,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms,
        where=where,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Now check if the output file is correctly created
    assert output_path.exists()
    assert fileops.has_spatial_index(output_path)
    output_layerinfo = fileops.get_layerinfo(output_path)
    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)

    if input_layerinfo.geometrytype in [
        GeometryType.MULTIPOINT,
        GeometryType.MULTILINESTRING,
    ]:
        # A Negative buffer of points or linestrings gives NULL geometries
        if keep_empty_geoms:
            # If no filtering on NULL geoms, all rows are still present
            assert output_layerinfo.featurecount == input_layerinfo.featurecount
            if suffix != ".shp":
                # The None geoms aren't properly detected as geometry in shp, so becomes
                # an extra attribute column...
                # assert len(output_layerinfo.columns) == len(input_layerinfo.columns)
                pass
        else:
            # Everything is filtered away...
            assert output_layerinfo.featurecount == 0

    else:
        # A Negative buffer of polygons gives a result for large polygons.
        # 7 polygons disappear because of the negative buffer
        assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

        # Read result for some more detailed checks
        output_gdf = fileops.read_file(output_path)

        # Prepare expected result
        expected_gdf = fileops.read_file(input_path)
        expected_gdf.geometry = expected_gdf.geometry.buffer(distance, resolution=5)
        expected_gdf = test_helper.prepare_expected_result(
            expected_gdf,
            gridsize=gridsize,
            keep_empty_geoms=keep_empty_geoms,
            where=where,
        )
        assert_geodataframe_equal(output_gdf, expected_gdf, sort_values=True)


@pytest.mark.parametrize("geoops_module", GEOOPS_MODULES)
def test_buffer_negative_explode(tmp_path, geoops_module):
    """Buffer basics are available both in the gpd and sql implementations."""
    input_path = test_helper.get_testfile("polygon-parcel")

    # Now run test
    output_path = tmp_path / f"{input_path.stem}-output{input_path.suffix}"
    set_geoops_module(geoops_module)
    input_layerinfo = fileops.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Test negative buffer with explodecollections
    output_path = (
        output_path.parent / f"{output_path.stem}_m10m_explode{output_path.suffix}"
    )
    distance = -10
    keep_empty_geoms = False
    geoops.buffer(
        input_path=input_path,
        output_path=output_path,
        distance=distance,
        explodecollections=True,
        keep_empty_geoms=keep_empty_geoms,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Now check if the output file is correctly created
    assert output_path.exists()
    assert fileops.has_spatial_index(output_path)
    layerinfo_output = fileops.get_layerinfo(output_path)
    assert len(layerinfo_output.columns) == len(input_layerinfo.columns)
    assert layerinfo_output.geometrytype == GeometryType.POLYGON

    output_gdf = fileops.read_file(output_path)

    expected_gdf = fileops.read_file(input_path)
    expected_gdf.geometry = expected_gdf.geometry.buffer(distance, resolution=5)
    expected_gdf = test_helper.prepare_expected_result(
        expected_gdf, explodecollections=True, keep_empty_geoms=keep_empty_geoms
    )
    assert_geodataframe_equal(
        output_gdf,
        expected_gdf,
        promote_to_multi=True,
        sort_values=True,
        check_crs=False,
    )


@pytest.mark.parametrize("geoops_module", GEOOPS_MODULES)
@pytest.mark.parametrize("suffix", SUFFIXES)
@pytest.mark.parametrize(
    "keep_empty_geoms, where", [(False, None), (False, WHERE_AREA_GT_400)]
)
@pytest.mark.parametrize("explodecollections", [True, False])
def test_buffer_negative_where_explode(
    tmp_path, suffix, geoops_module, keep_empty_geoms, where, explodecollections
):
    """Buffer basics are available both in the gpd and sql implementations."""
    # Prepare test data/environment
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    set_geoops_module(geoops_module)
    output_path = tmp_path / f"{input_path.stem}-{geoops_module}{suffix}"
    input_layerinfo = fileops.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    distance = -10

    expected_gdf = fileops.read_file(input_path)
    expected_gdf.geometry = expected_gdf.geometry.buffer(distance, resolution=5)
    expected_gdf = test_helper.prepare_expected_result(
        expected_gdf,
        keep_empty_geoms=keep_empty_geoms,
        where=where,
        explodecollections=explodecollections,
    )

    # Run test
    geoops.buffer(
        input_path=input_path,
        output_path=output_path,
        distance=distance,
        explodecollections=explodecollections,
        keep_empty_geoms=keep_empty_geoms,
        where=where,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Check result
    assert output_path.exists()
    assert fileops.has_spatial_index(output_path)
    output_layerinfo = fileops.get_layerinfo(output_path)
    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)

    output_gdf = fileops.read_file(output_path)
    assert output_gdf["geometry"][0] is not None

    assert_geodataframe_equal(
        output_gdf,
        expected_gdf,
        promote_to_multi=True,
        sort_values=True,
    )


@pytest.mark.parametrize("geoops_module", GEOOPS_MODULES)
@pytest.mark.parametrize("suffix", SUFFIXES)
@pytest.mark.parametrize(
    "empty_input, gridsize, keep_empty_geoms, where",
    [(True, 0.0, True, None), (False, 0.001, None, WHERE_AREA_GT_400)],
)
def test_convexhull(
    tmp_path, geoops_module, suffix, empty_input, gridsize, keep_empty_geoms, where
):
    # Prepare test data
    logging.basicConfig(level=logging.DEBUG)
    input_path = test_helper.get_testfile(
        "polygon-parcel", suffix=suffix, empty=empty_input
    )
    set_geoops_module(geoops_module)
    input_layerinfo = fileops.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Also check if columns parameter works (case insensitive)
    columns = ["OIDN", "uidn", "HFDTLT", "lblhfdtlt", "GEWASGROEP", "lengte", "OPPERVL"]

    # Prepare expected result
    expected_gdf = fileops.read_file(input_path)
    expected_gdf.geometry = expected_gdf.geometry.convex_hull
    expected_gdf = test_helper.prepare_expected_result(
        expected_gdf,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms,
        where=where,
        columns=columns,
    )

    # Run test
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    geoops.convexhull(
        input_path=input_path,
        columns=columns,
        output_path=output_path,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms,
        where=where,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Now check if the output file is correctly created
    assert output_path.exists()
    assert fileops.has_spatial_index(output_path)
    layerinfo_output = fileops.get_layerinfo(output_path)
    assert "OIDN" in layerinfo_output.columns
    assert "uidn" in layerinfo_output.columns
    assert len(layerinfo_output.columns) == len(columns)
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

    # If input was empty, we are already OK
    if empty_input:
        return

    # More detailed check
    output_gdf = fileops.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
    assert_geodataframe_equal(output_gdf, expected_gdf, sort_values=True)


@pytest.mark.parametrize("suffix", SUFFIXES)
@pytest.mark.parametrize("input_empty", [True, False])
@pytest.mark.parametrize(
    "geoops_module", ["geofileops.geoops", "geofileops.util._geoops_sql"]
)
def test_makevalid(tmp_path, suffix, input_empty, geoops_module):
    # Prepare test data
    input_path = test_helper.get_testfile(
        "polygon-invalid", suffix=suffix, empty=input_empty
    )
    set_geoops_module(geoops_module)

    # If the input file is not empty, it should have invalid geoms
    if not input_empty:
        input_isvalid_path = tmp_path / f"{input_path.stem}_is-valid{suffix}"
        isvalid = _geoops_sql.isvalid(
            input_path=input_path, output_path=input_isvalid_path
        )
        assert isvalid is False, "Input file should contain invalid features"

    # Make sure the input file is not valid
    if not input_empty:
        output_isvalid_path = (
            tmp_path / f"{input_path.stem}_is-valid{input_path.suffix}"
        )
        isvalid = _geoops_sql.isvalid(
            input_path=input_path, output_path=output_isvalid_path
        )
        assert isvalid is False, "Input file should contain invalid features"

    # Do operation
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    geoops.makevalid(
        input_path=input_path,
        output_path=output_path,
        nb_parallel=2,
        force_output_geometrytype=fileops.GeometryType.MULTIPOLYGON,
        validate_attribute_data=True,
    )

    # Now check if the output file is correctly created
    assert output_path.exists()
    layerinfo_orig = fileops.get_layerinfo(input_path)
    layerinfo_output = fileops.get_layerinfo(output_path)
    assert len(layerinfo_orig.columns) == len(layerinfo_output.columns)
    assert layerinfo_output.geometrytype in [
        GeometryType.POLYGON,
        GeometryType.MULTIPOLYGON,
    ]

    if not input_empty:
        assert layerinfo_orig.featurecount == layerinfo_output.featurecount

    # Check if the result file is valid
    output_new_isvalid_path = (
        tmp_path / f"{output_path.stem}_new_is-valid{output_path.suffix}"
    )
    isvalid = _geoops_sql.isvalid(
        input_path=output_path, output_path=output_new_isvalid_path
    )
    assert isvalid is True, "Output file shouldn't contain invalid features"

    # Run makevalid with existing output file and force=False (=default)
    geoops.makevalid(input_path=input_path, output_path=output_path)


@pytest.mark.parametrize(
    "descr, geometry, expected_geometry",
    [
        ("sliver", Polygon([(0, 0), (10, 0), (10, 0.5), (0, 0)]), Polygon()),
        (
            "poly + sliver",
            MultiPolygon(
                [
                    Polygon([(0, 5), (5, 5), (5, 10), (0, 10), (0, 5)]),
                    Polygon([(0, 0), (10, 0), (10, 0.5), (0, 0)]),
                ]
            ),
            Polygon([(0, 5), (5, 5), (5, 10), (0, 10), (0, 5)]),
        ),
    ],
)
@pytest.mark.parametrize(
    "geoops_module", ["geofileops.geoops", "geofileops.util._geoops_sql"]
)
def test_makevalid_gridsize(
    tmp_path, descr: str, geometry, geoops_module, expected_geometry
):
    # Prepare test data
    # -----------------
    set_geoops_module(geoops_module)
    input_gdf = gpd.GeoDataFrame({"descr": [descr]}, geometry=[geometry], crs=31370)
    input_path = tmp_path / "test.gpkg"
    fileops.to_file(input_gdf, input_path)
    gridsize = 1

    # Now we are ready to test
    # ------------------------
    result_path = tmp_path / "test_makevalid.gpkg"
    geoops.makevalid(
        input_path=input_path,
        output_path=result_path,
        gridsize=gridsize,
        keep_empty_geoms=False,
        force=True,
    )
    result_gdf = fileops.read_file(result_path)

    # Compare with expected result
    expected_gdf = gpd.GeoDataFrame(
        {"descr": [descr]}, geometry=[expected_geometry], crs=31370
    )
    expected_gdf = expected_gdf[~expected_gdf.geometry.is_empty]
    if len(expected_gdf) == 0:
        assert len(result_gdf) == 0
    else:
        assert_geodataframe_equal(result_gdf, expected_gdf)


def test_makevalid_invalidparams():
    # Only test on geoops, as the invalid params only exist there.
    set_geoops_module("geofileops.geoops")
    expected_error = (
        "the precision parameter is deprecated and cannot be combined with gridsize"
    )
    with pytest.raises(ValueError, match=expected_error):
        geoops.makevalid(
            input_path="abc",
            output_path="def",
            gridsize=1,
            precision=1,
        )


@pytest.mark.parametrize(
    "suffix, epsg, geoops_module, testfile, empty_input, gridsize, keep_empty_geoms, "
    "where",
    basic_combinations_to_test(testfiles=["polygon-parcel", "linestring-row-trees"]),
)
def test_simplify(
    tmp_path,
    suffix,
    epsg,
    geoops_module,
    testfile,
    empty_input,
    gridsize,
    keep_empty_geoms,
    where,
):
    # Prepare test data
    tmp_dir = tmp_path / f"{geoops_module}_{epsg}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    input_path = test_helper.get_testfile(
        testfile, dst_dir=tmp_dir, suffix=suffix, epsg=epsg, empty=empty_input
    )
    output_path = tmp_dir / f"{input_path.stem}-output{suffix}"
    set_geoops_module(geoops_module)
    input_layerinfo = fileops.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    assert input_layerinfo.crs is not None
    if input_layerinfo.crs.is_projected:
        tolerance = 5
    else:
        # 1 degree = 111 km or 111000 m
        tolerance = 5 / 111000

    # Prepare expected result
    expected_gdf = fileops.read_file(input_path)
    expected_gdf.geometry = expected_gdf.geometry.simplify(tolerance)
    expected_gdf = test_helper.prepare_expected_result(
        expected_gdf,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms,
        where=where,
    )

    # Test default algorithm (rdp)
    output_path = io_util.with_stem(input_path, output_path)
    geoops.simplify(
        input_path=input_path,
        output_path=output_path,
        tolerance=tolerance,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms,
        where=where,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Now check if the tmp file is correctly created
    assert output_path.exists()
    assert fileops.has_spatial_index(output_path)
    output_layerinfo = fileops.get_layerinfo(output_path)
    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)

    # If input was empty, we are already OK
    if empty_input:
        return

    # More detailed checks
    output_gdf = fileops.read_file(output_path)
    assert_geodataframe_equal(
        output_gdf, expected_gdf, sort_values=True, normalize=True
    )


@pytest.mark.parametrize(
    "algorithm",
    [
        "lang",
        "lang+",
        "rdp",
        "vw",
        geoops.SimplifyAlgorithm.LANG,
        geoops.SimplifyAlgorithm.LANGP,
        geoops.SimplifyAlgorithm.RAMER_DOUGLAS_PEUCKER,
        geoops.SimplifyAlgorithm.VISVALINGAM_WHYATT,
    ],
)
def test_simplify_algorithms(tmp_path, algorithm):
    """
    Rude check on supported algorithms.
    """
    input_path = test_helper.get_testfile("polygon-parcel")
    output_path = tmp_path / f"{input_path.stem}_output.gpkg"

    # Test specifically with geoops
    set_geoops_module("geofileops.geoops")
    geoops.simplify(
        input_path=input_path,
        output_path=output_path,
        tolerance=1,
        algorithm=algorithm,
        nb_parallel=2,
    )

    assert output_path.exists()
