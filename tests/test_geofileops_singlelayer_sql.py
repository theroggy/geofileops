# -*- coding: utf-8 -*-
"""
Tests for operations that are executed using a sql statement on one layer.
"""

import math

import geopandas as gpd
import geopandas._compat as gpd_compat
import pytest

if gpd_compat.USE_PYGEOS:
    import pygeos as shapely2_or_pygeos
else:
    import shapely as shapely2_or_pygeos
from shapely.geometry import MultiPolygon, Polygon

import geofileops as gfo
from geofileops import GeometryType
from geofileops.util import _geoops_sql as geoops_sql
from tests import test_helper
from tests.test_helper import EPSGS, SUFFIXES
from tests.test_helper import assert_geodataframe_equal


@pytest.mark.parametrize("gridsize", [0.0, 0.1])
def test_delete_duplicate_geometries(tmp_path, gridsize):
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
    expected_gdf = test_gdf.iloc[[0, 2, 4]].reset_index(drop=True)
    suffix = ".gpkg"
    input_path = tmp_path / f"input_test_data{suffix}"
    gfo.to_file(test_gdf, input_path)
    input_info = gfo.get_layerinfo(input_path)

    # Run test
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    print(f"Run test for suffix {suffix}")
    # delete_duplicate_geometries isn't multiprocess, so no batchsize needed
    gfo.delete_duplicate_geometries(
        input_path=input_path, output_path=output_path, gridsize=gridsize
    )

    # Check result, 2 duplicates should be removed
    result_info = gfo.get_layerinfo(output_path)
    assert result_info.featurecount == input_info.featurecount - 2
    result_gdf = gfo.read_file(output_path)
    if gridsize != 0.0:
        expected_gdf.geometry = shapely2_or_pygeos.set_precision(
            expected_gdf.geometry.array.data, grid_size=gridsize
        )
    assert_geodataframe_equal(result_gdf, expected_gdf)


def test_dissolve_singlethread_output_exists(tmp_path):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel")
    output_path = tmp_path / f"{input_path.stem}-output{input_path.suffix}"
    output_path.touch()

    # Run test without force
    geoops_sql.dissolve_singlethread(
        input_path=input_path,
        output_path=output_path,
    )
    assert output_path.exists()
    assert output_path.stat().st_size == 0

    # Run test with force
    geoops_sql.dissolve_singlethread(
        input_path=input_path,
        output_path=output_path,
        force=True,
    )
    assert output_path.exists()
    assert output_path.stat().st_size != 0


@pytest.mark.parametrize("suffix", SUFFIXES)
@pytest.mark.parametrize("epsg", EPSGS)
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
    gfo.isvalid(
        input_path=input_path, batchsize=batchsize, validate_attribute_data=True
    )

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


@pytest.mark.parametrize("suffix", SUFFIXES)
@pytest.mark.parametrize("input_empty", [True, False])
def test_makevalid(tmp_path, suffix, input_empty):
    # Prepare test data
    input_path = test_helper.get_testfile(
        "polygon-invalid", suffix=suffix, empty=input_empty
    )

    # If the input file is not empty, it should have invalid geoms
    if not input_empty:
        input_isvalid_path = tmp_path / f"{input_path.stem}_is-valid{suffix}"
        isvalid = gfo.isvalid(input_path=input_path, output_path=input_isvalid_path)
        assert isvalid is False, "Input file should contain invalid features"

    # Make sure the input file is not valid
    if not input_empty:
        output_isvalid_path = (
            tmp_path / f"{input_path.stem}_is-valid{input_path.suffix}"
        )
        isvalid = gfo.isvalid(input_path=input_path, output_path=output_isvalid_path)
        assert isvalid is False, "Input file should contain invalid features"

    # Do operation
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    gfo.makevalid(
        input_path=input_path,
        output_path=output_path,
        nb_parallel=2,
        force_output_geometrytype=gfo.GeometryType.MULTIPOLYGON,
        validate_attribute_data=True,
    )

    # Now check if the output file is correctly created
    assert output_path.exists()
    layerinfo_orig = gfo.get_layerinfo(input_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
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
    isvalid = gfo.isvalid(input_path=output_path, output_path=output_new_isvalid_path)
    assert isvalid is True, "Output file shouldn't contain invalid features"

    # Run makevalid with existing output file and force=False (=default)
    gfo.makevalid(input_path=input_path, output_path=output_path)


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
def test_makevalid_gridsize(tmp_path, descr: str, geometry, expected_geometry):
    # Prepare test data
    # -----------------
    input_gdf = gpd.GeoDataFrame({"descr": [descr]}, geometry=[geometry], crs=31370)
    input_path = tmp_path / "test.gpkg"
    gfo.to_file(input_gdf, input_path)
    gridsize = 1

    # Now we are ready to test
    # ------------------------
    result_path = tmp_path / "test_makevalid.gpkg"
    gfo.makevalid(
        input_path=input_path,
        output_path=result_path,
        gridsize=gridsize,
        force=True,
    )
    result_gdf = gfo.read_file(result_path)

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
    expected_error = (
        "the precision parameter is deprecated and cannot be combined with gridsize"
    )
    with pytest.raises(ValueError, match=expected_error):
        gfo.makevalid(
            input_path="abc",
            output_path="def",
            gridsize=1,
            precision=1,
        )


@pytest.mark.parametrize("suffix", SUFFIXES)
@pytest.mark.parametrize("gridsize", [0.0, 0.01])
def test_select(tmp_path, suffix, gridsize):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Now run test
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    layerinfo_input = gfo.get_layerinfo(input_path)
    sql_stmt = 'SELECT {geometrycolumn}, "oidn", "UIDN" FROM "{input_layer}"'
    # Column casing seems to behave odd: without gridsize (=subselect) results in upper
    # casing rgardless of quotes or not, with gridsize (=subselect) casing in select is
    # retained in output.
    gfo.select(
        input_path=input_path,
        output_path=output_path,
        sql_stmt=sql_stmt,
        gridsize=gridsize,
    )

    # Now check if the tmp file is correctly created
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_input.featurecount == layerinfo_output.featurecount
    columns_output_upper = [col.upper() for col in layerinfo_output.columns]
    assert "OIDN" in columns_output_upper
    assert "UIDN" in columns_output_upper
    assert len(layerinfo_output.columns) == 2
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_select_column_casing(tmp_path, suffix):
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
    assert "uidn" in layerinfo_select.columns
    assert len(layerinfo_select.columns) == len(columns)

    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None


@pytest.mark.parametrize("input_suffix", SUFFIXES)
@pytest.mark.parametrize("output_suffix", SUFFIXES)
def test_select_emptyinput(tmp_path, input_suffix, output_suffix):
    # Prepare test data
    input_path = test_helper.get_testfile(
        "polygon-parcel", suffix=input_suffix, dst_dir=tmp_path, empty=True
    )
    input_layerinfo = gfo.get_layerinfo(input_path)
    assert input_layerinfo.featurecount == 0

    # Test with simple select
    # -----------------------
    output_stem = f"{input_path.stem}-{input_suffix.replace('.', '')}-simple"
    output_path = tmp_path / f"{output_stem}{output_suffix}"
    sql_stmt = 'SELECT {geometrycolumn}, oidn, uidn FROM "{input_layer}"'

    gfo.select(input_path=input_path, output_path=output_path, sql_stmt=sql_stmt)

    # Now check if the tmp file is correctly created
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == 0
    assert "oidn" in layerinfo_output.columns
    assert "uidn" in layerinfo_output.columns
    assert len(layerinfo_output.columns) == 2
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON


@pytest.mark.parametrize(
    "input_suffix, output_suffix",
    [
        (".gpkg", ".gpkg"),
        (".gpkg", ".shp"),
        (".shp", ".gpkg"),
        (".shp", ".shp"),
    ],
)
def test_select_emptyinput_operation(tmp_path, input_suffix, output_suffix):
    """
    A select with a geometry operation (eg. buffer,...) on an empty input file should
    result in an empty output file.
    """
    # Prepare test data
    input_path = test_helper.get_testfile(
        "polygon-parcel", suffix=input_suffix, dst_dir=tmp_path, empty=True
    )

    input_layerinfo = gfo.get_layerinfo(input_path)
    assert input_layerinfo.featurecount == 0

    # Test with complex select: with geometry operation
    # -------------------------------------------------
    output_stem = f"{input_path.stem}-{input_suffix.replace('.', '')}-complex"
    output_path = tmp_path / f"{output_stem}{output_suffix}"
    sql_stmt = """
        SELECT st_buffer({geometrycolumn}, 1, 5) as {geometrycolumn}, oidn, uidn
          FROM "{input_layer}"
    """
    gfo.select(input_path=input_path, output_path=output_path, sql_stmt=sql_stmt)

    assert output_path.exists()
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 0


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_select_emptyresult(tmp_path, suffix):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Now run test
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    sql_stmt = 'SELECT {geometrycolumn}, oidn, uidn FROM "{input_layer}" WHERE 1=0'

    gfo.select(input_path=input_path, output_path=output_path, sql_stmt=sql_stmt)

    # Now check if the tmp file is correctly created
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == 0
    assert "oidn" in layerinfo_output.columns
    assert "uidn" in layerinfo_output.columns
    assert len(layerinfo_output.columns) == 2
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON


@pytest.mark.parametrize(
    "sql_stmt",
    [
        'SELECT {geometrycolumn}, "oidn", "UIDN" FROM "{input_layer}"',
    ],
)
@pytest.mark.parametrize("input_suffix", SUFFIXES)
@pytest.mark.parametrize("output_suffix", SUFFIXES)
@pytest.mark.parametrize("gridsize", [0.0])
def test_select_geom_aliases(tmp_path, input_suffix, output_suffix, sql_stmt, gridsize):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=input_suffix)

    # Now run test
    name = f"{input_path.stem}-{input_suffix.replace('.', '')}-output{output_suffix}"
    output_path = tmp_path / name
    layerinfo_input = gfo.get_layerinfo(input_path)
    gfo.select(
        input_path=input_path,
        output_path=output_path,
        sql_stmt=sql_stmt,
        gridsize=gridsize,
    )

    # Now check if the tmp file is correctly created
    assert output_path.exists()
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_input.featurecount == layerinfo_output.featurecount
    columns_output_upper = [col.upper() for col in layerinfo_output.columns]
    assert "OIDN" in columns_output_upper
    assert "UIDN" in columns_output_upper
    assert len(layerinfo_output.columns) == 2
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_select_invalid_sql(tmp_path, suffix):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Now run test
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    sql_stmt = 'SELECT {geometrycolumn}, not_existing_column FROM "{input_layer}"'

    with pytest.raises(Exception, match="Error no such column"):
        gfo.select(input_path=input_path, output_path=output_path, sql_stmt=sql_stmt)


@pytest.mark.parametrize("suffix", SUFFIXES)
@pytest.mark.parametrize("gridsize", [0.0, 0.01])
def test_select_nogeom_in_input(tmp_path, suffix, gridsize):
    # Prepare test data
    input_geom_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    data_df = gfo.read_file(input_geom_path, ignore_geometry=True)
    input_path = tmp_path / f"{input_geom_path.stem}_nogeom{suffix}"
    gfo.to_file(data_df, input_path)

    # Now run test
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    sql_stmt = 'SELECT * FROM "{input_layer}"'

    # Column casing seems to behave odd: without gridsize (=subselect) results in upper
    # casing regardless of quotes or not, with gridsize (=subselect) casing in select is
    # retained in output.
    if suffix == ".shp":
        input_path = input_path.with_suffix(".dbf")
    gfo.select(
        input_path=input_path,
        output_path=output_path,
        sql_stmt=sql_stmt,
        gridsize=gridsize,
    )

    # Now check if the tmp file is correctly created
    if suffix == ".shp":
        output_path = output_path.with_suffix(".dbf")
    layerinfo_output = gfo.get_layerinfo(output_path, raise_on_nogeom=False)
    layerinfo_input = gfo.get_layerinfo(input_path, raise_on_nogeom=False)
    assert layerinfo_input.featurecount == layerinfo_output.featurecount
    columns_output_upper = [col.upper() for col in layerinfo_output.columns]
    assert "OIDN" in columns_output_upper
    assert "UIDN" in columns_output_upper
    assert len(layerinfo_output.columns) == len(layerinfo_input.columns)

    assert layerinfo_output.geometrycolumn is None
    assert layerinfo_output.geometrytype is None


@pytest.mark.parametrize("suffix", SUFFIXES)
@pytest.mark.parametrize("gridsize", [0.0, 0.01])
def test_select_nogeom_selected(tmp_path, suffix, gridsize):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Now run test
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    layerinfo_input = gfo.get_layerinfo(input_path)
    sql_stmt = 'SELECT "oidn", "UIDN" FROM "{input_layer}"'

    # Column casing seems to behave odd: without gridsize (=subselect) results in upper
    # casing rgardless of quotes or not, with gridsize (=subselect) casing in select is
    # retained in output.
    gfo.select(
        input_path=input_path,
        output_path=output_path,
        sql_stmt=sql_stmt,
        gridsize=gridsize,
    )

    # Now check if the tmp file is correctly created
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_input.featurecount == layerinfo_output.featurecount
    columns_output_upper = [col.upper() for col in layerinfo_output.columns]
    assert "OIDN" in columns_output_upper
    assert "UIDN" in columns_output_upper
    assert len(layerinfo_output.columns) == 2
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)

    # A geometry column is present even though it isn't selected, but values are None
    assert output_gdf["geometry"][0] is None


def test_select_output_exists(tmp_path):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel")
    output_path = tmp_path / f"{input_path.stem}-output{input_path.suffix}"
    output_path.touch()
    sql_stmt = 'SELECT {geometrycolumn}, oidn, uidn FROM "{input_layer}"'

    # Now run test
    gfo.select(input_path=input_path, output_path=output_path, sql_stmt=sql_stmt)
    assert output_path.stat().st_size == 0


@pytest.mark.parametrize("suffix", SUFFIXES)
@pytest.mark.parametrize(
    "nb_parallel, has_batch_filter, exp_raise",
    [(1, False, False), (2, True, False), (2, False, True)],
)
def test_select_batch_filter(
    tmp_path, suffix, nb_parallel, has_batch_filter, exp_raise
):
    """
    Test if batch_filter checks are OK.
    """
    input_path = test_helper.get_testfile("polygon-parcel", tmp_path, suffix)
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    sql_stmt = """
        SELECT {geometrycolumn}
              {columns_to_select_str}
          FROM "{input_layer}" layer
         WHERE 1=1
    """
    if has_batch_filter:
        sql_stmt += "{batch_filter}"

    if exp_raise:
        with pytest.raises(
            ValueError,
            match="Number batches > 1 requires a batch_filter placeholder in ",
        ):
            gfo.select(input_path, output_path, sql_stmt, nb_parallel=nb_parallel)
    else:
        gfo.select(input_path, output_path, sql_stmt, nb_parallel=nb_parallel)


@pytest.mark.parametrize("suffix", SUFFIXES)
@pytest.mark.parametrize("explodecollections", [True, False])
def test_select_star(tmp_path, suffix, explodecollections):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Now run test
    name = f"{input_path.stem}-output{suffix}"
    output_path = tmp_path / name
    input_layerinfo = gfo.get_layerinfo(input_path)
    sql_stmt = 'SELECT * FROM "{input_layer}"'
    gfo.select(
        input_path=input_path,
        output_path=output_path,
        sql_stmt=sql_stmt,
        explodecollections=explodecollections,
    )

    # Now check if the tmp file is correctly created
    output_layerinfo = gfo.get_layerinfo(output_path)
    if explodecollections:
        assert output_layerinfo.featurecount == input_layerinfo.featurecount + 2
    else:
        assert output_layerinfo.featurecount == input_layerinfo.featurecount
    columns_output_upper = [col.upper() for col in output_layerinfo.columns]
    assert "OIDN" in columns_output_upper
    assert "UIDN" in columns_output_upper
    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
