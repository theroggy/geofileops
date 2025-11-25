"""
Tests for operations that are executed using a sql statement on one layer.
"""

import logging
import math
from importlib import import_module
from typing import Any

import geopandas as gpd
import pytest
import shapely
from shapely import MultiPolygon, Polygon

from geofileops import GeometryType, fileops, geoops
from geofileops._compat import GDAL_GTE_39, GDAL_GTE_311
from geofileops.util import _general_util, _geofileinfo, _geoops_sql
from geofileops.util._geofileinfo import GeofileInfo
from geofileops.util._geopath_util import GeoPath
from tests import test_helper
from tests.test_helper import (
    EPSGS,
    GRIDSIZE_DEFAULT,
    SUFFIXES_GEOOPS,
    SUFFIXES_GEOOPS_EXT,
    TESTFILES,
    WHERE_AREA_GT_400,
    assert_geodataframe_equal,
)

# Init gfo module
current_geoops_module = "unknown"
GEOOPS_MODULES = [
    "geofileops.geoops",
    "geofileops.util._geoops_gpd",
    "geofileops.util._geoops_sql",
]


def set_geoops_module(geoops_module: str):
    global current_geoops_module  # noqa: PLW0603
    if current_geoops_module == geoops_module:
        # The right module is already loaded, so don't do anything
        return
    else:
        # Load the desired module as fileops
        global geoops  # noqa: PLW0603
        geoops = import_module(geoops_module, __package__)
        current_geoops_module = geoops_module
        print(f"gfo module switched to: {current_geoops_module}")


def basic_combinations_to_test(
    geoops_modules: list[str] = GEOOPS_MODULES,
    testfiles: list[str] = TESTFILES,
    epsgs: list[int] = EPSGS,
    suffixes: list[str] = SUFFIXES_GEOOPS,
) -> list[Any]:
    """
    Return sensible combinations of parameters to be used in tests for following params:
        suffix, epsg, geoops_module, testfile, empty_input, gridsize, where_post
    """
    result = []

    # On .gpkg test:
    #   - all combinations of geoops_modules, testfiles and epsgs
    #   - fixed empty_input, suffix
    #   - dimensions="XYZ" for polygon input
    #   - custom fid_column for point input
    for epsg in epsgs:
        for geoops_module in geoops_modules:
            for testfile in testfiles:
                where_post = None
                keep_empty_geoms: bool | None = False
                dimensions = None
                gridsize = 0.01 if epsg == 31370 else GRIDSIZE_DEFAULT
                fid_column = None
                if testfile == "polygon-parcel":
                    dimensions = "XYZ"
                    keep_empty_geoms = None
                    if epsg == 31370:
                        where_post = WHERE_AREA_GT_400
                elif testfile == "point":
                    keep_empty_geoms = True
                    fid_column = "fid_custom"
                result.append(
                    (
                        ".gpkg",
                        epsg,
                        geoops_module,
                        testfile,
                        False,
                        gridsize,
                        keep_empty_geoms,
                        where_post,
                        dimensions,
                        fid_column,
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
                where_post = ""
                keep_empty_geoms = False
                gridsize = 0.01 if testfile == "polygon-parcel" else GRIDSIZE_DEFAULT
                if testfile == "polygon-parcel":
                    where_post = WHERE_AREA_GT_400
                else:
                    keep_empty_geoms = True
                dimensions = None
                fid_column = None
                result.append(
                    (
                        suffix,
                        31370,
                        geoops_module,
                        testfile,
                        False,
                        gridsize,
                        keep_empty_geoms,
                        where_post,
                        dimensions,
                        fid_column,
                    )
                )

    # Test empty_input=True on
    #   - all combinations of fileops_modules and SUFFIXES
    #   - fixed epsg, testfile and empty_input
    for geoops_module in geoops_modules:
        for suffix in suffixes:
            gridsize = 0.01 if suffix == ".gpkg" else GRIDSIZE_DEFAULT
            keep_empty_geoms = False
            where_post = None
            dimensions = None
            fid_column = None
            result.append(
                (
                    suffix,
                    31370,
                    geoops_module,
                    "polygon-parcel",
                    True,
                    gridsize,
                    keep_empty_geoms,
                    where_post,
                    dimensions,
                    fid_column,
                )
            )

    return result


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS_EXT)
@pytest.mark.parametrize("worker_type", ["threads", "processes"])
@pytest.mark.parametrize("geoops_module", GEOOPS_MODULES)
def test_buffer(tmp_path, suffix, worker_type, geoops_module):
    """Buffer minimal test."""
    if not GDAL_GTE_311 and suffix in {".gpkg.zip", ".shp.zip"}:
        # Skip test for unsupported GDAL versions
        pytest.skip(".zip support requires gdal>=3.11")

    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    input_layerinfo = fileops.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Now run test
    output_path = tmp_path / f"output{suffix}"
    set_geoops_module(geoops_module)
    with _general_util.TempEnv({"GFO_WORKER_TYPE": worker_type}):
        geoops.buffer(
            input_path=input_path,
            output_path=output_path,
            distance=1,
            nb_parallel=2,
            keep_empty_geoms=True,
            batchsize=batchsize,
        )

    # Now check if the output file is correctly created
    assert output_path.exists()
    output_layerinfo = fileops.get_layerinfo(output_path)
    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)
    assert output_layerinfo.featurecount == input_layerinfo.featurecount


@pytest.mark.parametrize(
    "suffix, epsg, geoops_module, testfile, empty_input, gridsize, keep_empty_geoms, "
    "where_post, dimensions, fid_column",
    basic_combinations_to_test(),
)
def test_buffer_basic(
    tmp_path,
    suffix,
    epsg,
    geoops_module,
    testfile,
    empty_input,
    gridsize,
    keep_empty_geoms,
    where_post,
    dimensions,
    fid_column,
):
    """Buffer basics are available both in the gpd and sql implementations."""
    if (
        not GDAL_GTE_39
        and dimensions == "XYZ"
        and suffix == ".gpkg"
        and geoops_module != "_geoops_gpd"
    ):
        pytest.xfail(
            "GDAL < 3.9 (at least) writes 3D geometries even though "
            "force_geometrytype='MULTIPOLYGON' for buffer operation."
        )
    # Prepare test data
    input_path = test_helper.get_testfile(
        testfile,
        suffix=suffix,
        epsg=epsg,
        empty=empty_input,
        dimensions=dimensions,
        fid_column=fid_column,
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
    # Default value for keep_empty_geoms is False
    keep_empty_geoms_prepped = False if keep_empty_geoms is None else keep_empty_geoms
    expected_gdf = test_helper.prepare_expected_result(
        expected_gdf,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms_prepped,
        where_post=where_post,
    )

    # Test positive buffer
    kwargs = {}
    if keep_empty_geoms is not None:
        kwargs["keep_empty_geoms"] = keep_empty_geoms
    geoops.buffer(
        input_path=input_path,
        output_path=output_path,
        distance=distance,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms,
        where_post=where_post,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Now check if the output file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert fileops.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = fileops.get_layerinfo(output_path)
    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)

    if empty_input:
        return

    # More detailed check
    output_gdf = fileops.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
    # Check less precise for geographic CRS (WGS84)
    check_less_precise = not input_layerinfo.crs.is_projected
    assert_geodataframe_equal(
        output_gdf,
        expected_gdf,
        normalize=True,
        promote_to_multi=True,
        check_less_precise=check_less_precise,
        sort_values=True,
    )


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize("testfile", ["polygon-parcel"])
@pytest.mark.parametrize("geoops_module", GEOOPS_MODULES)
@pytest.mark.parametrize(
    "columns, exp_columns",
    [(["LblHfdTlt", "fid"], ["LblHfdTlt", "fid_1"]), ("LblHfdTlt", ["LblHfdTlt"])],
)
def test_buffer_columns_fid(
    tmp_path, suffix, geoops_module, testfile, columns, exp_columns
):
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
        columns=columns,
        explodecollections=True,
        keep_empty_geoms=False,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Read input file and extract some info
    input_gdf = fileops.read_file(input_path, fid_as_index=True)
    if _geofileinfo.get_geofileinfo(input_path).is_fid_zerobased:
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
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert fileops.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = fileops.get_layerinfo(output_path)
    output_gdf = fileops.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
    assert list(output_layerinfo.columns) == exp_columns
    if "fid" in columns:
        assert len(output_gdf[output_gdf.fid_1 == multi_fid]) == 2


@pytest.mark.parametrize("geoops_module", GEOOPS_MODULES)
def test_buffer_force(tmp_path, geoops_module):
    suffix = ".gpkg"
    input_path = test_helper.get_testfile("polygon-parcel")
    input_layerinfo = fileops.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    distance = 1
    set_geoops_module(geoops_module)

    # Run buffer
    output_path = tmp_path / f"{GeoPath(input_path).stem}-output{suffix}"
    assert not output_path.exists()

    # Use "processes" worker type to test this as well
    with _general_util.TempEnv({"GFO_WORKER_TYPE": "processes"}):
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
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert fileops.has_spatial_index(output_path) is exp_spatial_index
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
    "exp_error, exp_ex, input_path, output_path",
    [
        (
            "buffer: output_path must not equal input_path",
            ValueError,
            "not_existing_path.gpkg",
            "not_existing_path.gpkg",
        ),
        (
            "buffer: input_path not found:",
            FileNotFoundError,
            "not_existing_path",
            "output.gpkg",
        ),
    ],
)
@pytest.mark.parametrize("geoops_module", GEOOPS_MODULES)
def test_buffer_invalid_params(
    tmp_path, input_path, output_path, exp_ex, exp_error, geoops_module
):
    """Invalid params for single layer operations."""
    # Internal functions are directly called, so need to be Path objects
    if isinstance(output_path, str):
        output_path = tmp_path / output_path
    if isinstance(input_path, str):
        input_path = tmp_path / input_path

    # Now run test
    set_geoops_module(geoops_module)
    with pytest.raises(exp_ex, match=exp_error):
        geoops.buffer(input_path=input_path, output_path=output_path, distance=1)


@pytest.mark.parametrize("suffix", [".gpkg", ".gpkg.zip"])
@pytest.mark.parametrize("geoops_module", GEOOPS_MODULES)
def test_buffer_layer_special_cases(tmp_path, suffix, geoops_module):
    """Test buffer on input file with multiple layers + a custom output layer.

    Only tested on .gpkg and .gpkg.zip as these support multiple layers/custom layer
    names.
    """
    if not GDAL_GTE_311 and suffix in {".gpkg.zip"}:
        # Skip test for unsupported GDAL versions
        pytest.skip(".zip support requires gdal>=3.11")

    # Prepare test data
    input_path = test_helper.get_testfile("polygon-twolayers", suffix=suffix)
    input_layerinfo = fileops.get_layerinfo(input_path, layer="parcels")
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    output_layer = "buffered_parcels"

    # Now run test
    output_path = tmp_path / f"output{suffix}"
    set_geoops_module(geoops_module)
    geoops.buffer(
        input_path=input_path,
        output_path=output_path,
        input_layer="parcels",
        output_layer=output_layer,
        distance=1,
        nb_parallel=2,
        keep_empty_geoms=True,
        batchsize=batchsize,
    )

    # Now check if the output file is correctly created
    assert output_path.exists()
    output_layerinfo = fileops.get_layerinfo(output_path)
    assert output_layerinfo.name == output_layer
    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)
    assert output_layerinfo.featurecount == input_layerinfo.featurecount


@pytest.mark.parametrize(
    "suffix, epsg, geoops_module, testfile, empty_input, gridsize, keep_empty_geoms, "
    "where_post, dimensions, fid_column",
    basic_combinations_to_test(epsgs=[31370]),
)
def test_buffer_negative(
    tmp_path,
    suffix,
    epsg,  # noqa: ARG001
    geoops_module,
    testfile,
    empty_input,  # noqa: ARG001
    gridsize,
    keep_empty_geoms,
    where_post,
    dimensions,  # noqa: ARG001
    fid_column,
):
    """Buffer basics are available both in the gpd and sql implementations."""
    input_path = test_helper.get_testfile(
        testfile, suffix=suffix, fid_column=fid_column
    )

    # Now run test
    output_path = tmp_path / f"{GeoPath(input_path).stem}-{geoops_module}{suffix}"
    set_geoops_module(geoops_module)
    input_layerinfo = fileops.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    keep_empty_geoms_prepped = False if keep_empty_geoms is None else keep_empty_geoms

    # Test negative buffer
    distance = -10
    kwargs = {}
    if keep_empty_geoms is not None:
        kwargs["keep_empty_geoms"] = keep_empty_geoms
    output_path = tmp_path / f"{GeoPath(output_path).stem}_m10m{suffix}"
    geoops.buffer(
        input_path=input_path,
        output_path=output_path,
        distance=distance,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=2,
        batchsize=batchsize,
        **kwargs,
    )

    # Now check if the output file is correctly created
    assert output_path.exists()

    output_layerinfo = fileops.get_layerinfo(output_path)
    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)

    if input_layerinfo.geometrytype in [
        GeometryType.MULTIPOINT,
        GeometryType.MULTILINESTRING,
    ]:
        # A Negative buffer of points or linestrings gives NULL geometries
        if keep_empty_geoms_prepped:
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
            keep_empty_geoms=keep_empty_geoms_prepped,
            where_post=where_post,
        )
        assert_geodataframe_equal(output_gdf, expected_gdf, sort_values=True)


@pytest.mark.parametrize("geoops_module", GEOOPS_MODULES)
def test_buffer_negative_explode(tmp_path, geoops_module):
    """Buffer basics are available both in the gpd and sql implementations."""
    suffix = ".gpkg"
    input_path = test_helper.get_testfile("polygon-parcel")

    # Now run test
    output_path = tmp_path / f"{GeoPath(input_path).stem}-output{suffix}"
    set_geoops_module(geoops_module)
    input_layerinfo = fileops.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Test negative buffer with explodecollections
    output_path = (
        output_path.parent / f"{GeoPath(output_path).stem}_m10m_explode{suffix}"
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
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert fileops.has_spatial_index(output_path) is exp_spatial_index
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
@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize(
    "keep_empty_geoms, where_post", [(False, None), (False, WHERE_AREA_GT_400)]
)
@pytest.mark.parametrize("explodecollections", [True, False])
def test_buffer_negative_where_explode(
    tmp_path, suffix, geoops_module, keep_empty_geoms, where_post, explodecollections
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
        where_post=where_post,
        explodecollections=explodecollections,
    )

    # Run test
    geoops.buffer(
        input_path=input_path,
        output_path=output_path,
        distance=distance,
        explodecollections=explodecollections,
        keep_empty_geoms=keep_empty_geoms,
        where_post=where_post,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Check result
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert fileops.has_spatial_index(output_path) is exp_spatial_index
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
def test_buffer_preserve_fid_gpkg(tmp_path, geoops_module):
    """
    Buffer test to check if fid is properly preserved.

    Only relevant for e.g. Geopackage as it saves the fid as a value. For e.g.
    shapefiles the fid is not retained, but always a sequence from 0 in the file.
    """
    # Prepare test data: remove 2 fid's from file to check if the fid's are preserved
    input_full_path = test_helper.get_testfile("polygon-parcel")
    input_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    input_layer = fileops.get_only_layer(input_path)
    sql_stmt = f'DELETE FROM "{input_layer}" WHERE fid IN (5, 6)'
    fileops.execute_sql(input_path, sql_stmt=sql_stmt)

    # Now run test
    output_path = tmp_path / f"{input_path.stem}-{geoops_module}.gpkg"
    set_geoops_module(geoops_module)
    input_layerinfo = fileops.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Test positive buffer
    geoops.buffer(
        input_path=input_path,
        output_path=output_path,
        distance=1,
        keep_empty_geoms=False,
        nb_parallel=2,
        batchsize=batchsize,
    )

    # Prepare expected result to compare with
    expected_gdf = fileops.read_file(input_full_path, fid_as_index=True)
    expected_gdf = expected_gdf[~expected_gdf.index.isin([5, 6])]
    expected_gdf = expected_gdf[~expected_gdf.geometry.is_empty]

    # Check if the output file with the expected result
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert fileops.has_spatial_index(output_path) is exp_spatial_index
    output_gdf = fileops.read_file(output_path, fid_as_index=True)
    assert len(output_gdf) == len(expected_gdf)
    assert output_gdf["geometry"].iloc[0] is not None
    assert (
        output_gdf.index.sort_values().tolist()
        == expected_gdf.index.sort_values().tolist()
    )


@pytest.mark.parametrize("geoops_module", GEOOPS_MODULES)
def test_buffer_shp_to_gpkg(
    tmp_path,
    geoops_module,
):
    """
    Buffer from shapefile to gpkg.

    Test added because this gave a unique constraint error on fid's, because for each
    partial file the fid started again with 0.
    """
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=".shp")

    # Now run test
    output_path = tmp_path / f"{input_path.stem}-{geoops_module}.gpkg"
    set_geoops_module(geoops_module)
    input_layerinfo = fileops.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    distance = 1
    keep_empty_geoms = False

    # Prepare expected result
    expected_gdf = fileops.read_file(input_path)
    expected_gdf.geometry = expected_gdf.geometry.buffer(distance, resolution=5)
    expected_gdf = test_helper.prepare_expected_result(
        expected_gdf, keep_empty_geoms=keep_empty_geoms
    )

    # Test positive buffer
    geoops.buffer(
        input_path=input_path,
        output_path=output_path,
        distance=distance,
        nb_parallel=2,
        batchsize=batchsize,
        keep_empty_geoms=keep_empty_geoms,
    )

    # Now check if the output file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert fileops.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = fileops.get_layerinfo(output_path)
    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)

    # More detailed check
    output_gdf = fileops.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
    assert_geodataframe_equal(
        output_gdf,
        expected_gdf,
        promote_to_multi=True,
        sort_values=True,
    )


@pytest.mark.parametrize("geoops_module", GEOOPS_MODULES)
@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize(
    "empty_input, gridsize, keep_empty_geoms, where_post",
    [(True, 0.0, True, None), (False, 0.01, None, WHERE_AREA_GT_400)],
)
def test_convexhull(
    tmp_path, geoops_module, suffix, empty_input, gridsize, keep_empty_geoms, where_post
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
    keep_empty_geoms_prepped = False if keep_empty_geoms is None else keep_empty_geoms
    expected_gdf = test_helper.prepare_expected_result(
        expected_gdf,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms_prepped,
        where_post=where_post,
        columns=columns,
    )

    # Run test
    kwargs = {}
    if keep_empty_geoms is not None:
        kwargs["keep_empty_geoms"] = keep_empty_geoms
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    geoops.convexhull(
        input_path=input_path,
        columns=columns,
        output_path=output_path,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=2,
        batchsize=batchsize,
        **kwargs,
    )

    # Now check if the output file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert fileops.has_spatial_index(output_path) is exp_spatial_index
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


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize("input_empty", [True, False])
@pytest.mark.parametrize("geoops_module", GEOOPS_MODULES)
@pytest.mark.filterwarnings(
    "ignore: The default date converter is deprecated as of Python 3.12"
)
def test_makevalid(tmp_path, suffix, input_empty, geoops_module):
    # Prepare test data
    input_path = test_helper.get_testfile(
        "polygon-invalid", suffix=suffix, empty=input_empty
    )
    set_geoops_module(geoops_module)

    # If the input file is not empty, it should have invalid geoms
    if not input_empty:
        output_isvalid_path = tmp_path / f"{GeoPath(input_path).stem}_is-valid{suffix}"
        isvalid = _geoops_sql.isvalid(
            input_path=input_path, output_path=output_isvalid_path
        )
        assert isvalid is False, "Input file should contain invalid features"

    # Add some extra kwargs
    kwargs = {}
    if geoops_module == "geofileops.geoops":
        kwargs["validate_attribute_data"] = True

    # Do operation
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    geoops.makevalid(
        input_path=input_path,
        output_path=output_path,
        nb_parallel=2,
        force_output_geometrytype=fileops.GeometryType.MULTIPOLYGON,
        **kwargs,
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
        tmp_path / f"{GeoPath(output_path).stem}_new_is-valid{suffix}"
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
        ("sliver", Polygon([(0, 0), (5, 0), (10, 0), (15, 0)]), Polygon()),
        (
            "poly + line",
            MultiPolygon(
                [
                    Polygon([(0, 5), (5, 5), (5, 10), (0, 10), (0, 5)]),
                    Polygon([(0, 0), (5, 0), (10, 0), (15, 0)]),
                ]
            ),
            Polygon([(0, 5), (5, 5), (5, 10), (0, 10), (0, 5)]),
        ),
    ],
)
@pytest.mark.parametrize("geoops_module", GEOOPS_MODULES)
def test_makevalid_collapsing_part(
    tmp_path, descr: str, geometry, geoops_module, expected_geometry
):
    # Prepare test data
    set_geoops_module(geoops_module)
    input_gdf = gpd.GeoDataFrame({"descr": [descr]}, geometry=[geometry], crs=31370)
    input_path = tmp_path / "test.gpkg"
    fileops.to_file(input_gdf, input_path)

    # Now we are ready to test
    result_path = tmp_path / "test_makevalid_collapsing_part.gpkg"
    geoops.makevalid(
        input_path=input_path,
        output_path=result_path,
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


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize("explodecollections", [True, False])
@pytest.mark.parametrize("geoops_module", GEOOPS_MODULES)
def test_makevalid_exploded_input(tmp_path, suffix, geoops_module, explodecollections):
    """
    Test that even if single polygon input, output is multipolygon.

    Unless explodecollections of the output is True. Is necessary because makevalid can
    create multipolygons, and then the output becomes GEOMETRY.
    """
    # Prepare test data
    input_path = test_helper.get_testfile(
        "polygon-invalid", suffix=suffix, explodecollections=True
    )
    set_geoops_module(geoops_module)

    # Do operation
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    geoops.makevalid(
        input_path=input_path,
        output_path=output_path,
        explodecollections=explodecollections,
        nb_parallel=2,
    )

    # Now check if the output file is correctly created
    assert output_path.exists()
    layerinfo_orig = fileops.get_layerinfo(input_path)
    layerinfo_output = fileops.get_layerinfo(output_path)
    assert len(layerinfo_orig.columns) == len(layerinfo_output.columns)
    assert layerinfo_output.geometrytype in {
        GeometryType.POLYGON,
        GeometryType.MULTIPOLYGON,
    }


@pytest.mark.parametrize("geoops_module", GEOOPS_MODULES)
@pytest.mark.parametrize("gridsize", [0.0, 0.01])
@pytest.mark.parametrize("keep_empty_geoms", [None, True])
def test_makevalid_gridsize(tmp_path, geoops_module, gridsize, keep_empty_geoms):
    """
    Apply gridsize on the default test file to make it removes sliver polygon.
    """
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel")
    input_info = fileops.get_layerinfo(input_path)

    expected_featurecount = input_info.featurecount
    # If NULL/EMPTY geoms should not be kept, the expected featurecount is lower.
    # (keep_empty_geoms=False is the default)
    if not keep_empty_geoms or keep_empty_geoms is None:
        expected_featurecount -= 1
        # With gridsize specified, a sliver polygon is removed as well
        if gridsize > 0.0:
            expected_featurecount -= 1

    set_geoops_module(geoops_module)

    # Do operation
    kwargs = {}
    if keep_empty_geoms is not None:
        kwargs["keep_empty_geoms"] = keep_empty_geoms
    output_path = tmp_path / f"{input_path.stem}-output-{gridsize}.gpkg"
    geoops.makevalid(
        input_path=input_path,
        output_path=output_path,
        gridsize=gridsize,
        nb_parallel=2,
        **kwargs,
    )

    output_info = fileops.get_layerinfo(output_path)
    assert output_info.featurecount == expected_featurecount


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
@pytest.mark.parametrize("geoops_module", GEOOPS_MODULES)
def test_makevalid_gridsize_extra(
    tmp_path, descr: str, geometry, geoops_module, expected_geometry
):
    # Prepare test data
    set_geoops_module(geoops_module)
    input_gdf = gpd.GeoDataFrame({"descr": [descr]}, geometry=[geometry], crs=31370)
    input_path = tmp_path / "test.gpkg"
    fileops.to_file(input_gdf, input_path)
    gridsize = 1

    # Now we are ready to test
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


@pytest.mark.parametrize("geoops_module", GEOOPS_MODULES)
def test_makevalid_gridsize_topoerror(tmp_path, geoops_module):
    """
    Test on a specific valid polygon that gives a topologyerror when gridsize is set.
    """
    # The only currently known test case only works with geos 3.12. sql implementation
    # doesn't handle this case properly.
    if (
        shapely.geos_version != (3, 12, 0)
        or geoops_module == "geofileops.util._geoops_sql"
    ):
        pytest.skip()

    # Prepare test data
    poly_gridsize_error = shapely.from_wkt(
        "Polygon ((26352.5 175096.6, 26352.6 175096.6, 26352.6 175096.7, "
        "26352.5 175096.7, 26352.5 175096.6),(26352.528000000002 175096.676, "
        "26352.528369565214 175096.67489130437, 26352.528140495866 175096.67619834712, "
        "26352.52785714286 175096.67714285714, 26352.53 175096.66, "
        "26352.528000000002 175096.676))"
    )
    poly_ok = shapely.from_wkt(
        "Polygon ((26352.5 175096.7, 26352.66895 175096.76895, 26352.6 175096.6, "
        "26352.5 175096.6, 26352.5 175096.7))"
    )
    test_data = {
        "descr": ["gridsize_error", "ok"],
        "geometry": [poly_gridsize_error, poly_ok],
    }
    test_gdf = gpd.GeoDataFrame(test_data, crs=31370)
    input_path = tmp_path / "input.gpkg"
    fileops.to_file(test_gdf, input_path)

    gridsize = 0.01

    # Prepare expected result
    expected_data = {
        "descr": ["gridsize_error", "ok"],
        "geometry": [
            poly_gridsize_error,
            shapely.set_precision(poly_ok, grid_size=gridsize),
        ],
    }
    assert test_data["geometry"][1] != expected_data["geometry"][1]
    expected_gdf = gpd.GeoDataFrame(expected_data, crs=31370)

    # Now run test
    set_geoops_module(geoops_module)
    output_path = tmp_path / "output.gpkg"
    geoops.makevalid(input_path=input_path, output_path=output_path, gridsize=gridsize)

    # Check result
    output_gdf = fileops.read_file(output_path)
    assert_geodataframe_equal(
        output_gdf, expected_gdf, promote_to_multi=True, normalize=True
    )


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
    "where_post, dimensions, fid_column",
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
    where_post,
    dimensions,  # noqa: ARG001
    fid_column,
):
    # Prepare test data
    tmp_dir = tmp_path / f"{geoops_module}_{epsg}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    input_path = test_helper.get_testfile(
        testfile,
        dst_dir=tmp_dir,
        suffix=suffix,
        epsg=epsg,
        empty=empty_input,
        fid_column=fid_column,
    )
    output_path = tmp_dir / f"{input_path.stem}-output{suffix}"
    set_geoops_module(geoops_module)
    input_layerinfo = fileops.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    assert input_layerinfo.crs is not None
    # 1 degree = 111 km or 111000 m
    tolerance = 5 if input_layerinfo.crs.is_projected else 5 / 111000
    keep_empty_geoms_prepped = False if keep_empty_geoms is None else keep_empty_geoms

    # Prepare expected result
    expected_gdf = fileops.read_file(input_path)
    expected_gdf.geometry = expected_gdf.geometry.simplify(tolerance)
    expected_gdf = test_helper.prepare_expected_result(
        expected_gdf,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms_prepped,
        where_post=where_post,
    )

    # Test default algorithm (rdp)
    kwargs = {}
    if keep_empty_geoms is not None:
        kwargs["keep_empty_geoms"] = keep_empty_geoms
    output_path = GeoPath(input_path).with_stem(
        f"{GeoPath(output_path).stem}_{keep_empty_geoms}"
    )
    geoops.simplify(
        input_path=input_path,
        output_path=output_path,
        tolerance=tolerance,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=2,
        batchsize=batchsize,
        **kwargs,
    )

    # Now check if the tmp file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert fileops.has_spatial_index(output_path) is exp_spatial_index
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
