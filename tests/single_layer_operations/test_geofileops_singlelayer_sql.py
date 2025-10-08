"""
Tests for operations that are executed using a sql statement on one layer.
"""

import math

import geopandas as gpd
import pytest
from shapely.geometry import Polygon

import geofileops as gfo
from geofileops import GeometryType
from geofileops._compat import GDAL_GTE_311
from geofileops.util import _geoops_sql as geoops_sql
from geofileops.util._geopath_util import GeoPath
from tests import test_helper
from tests.test_helper import (
    EPSGS,
    SUFFIXES_GEOOPS,
    SUFFIXES_GEOOPS_EXT,
    assert_geodataframe_equal,
)


@pytest.mark.parametrize(
    "priority_column, priority_ascending",
    [(None, True), (None, False), ("priority", True), ("priority", False)],
)
def test_delete_duplicate_geoms(tmp_path, priority_column, priority_ascending):
    # Prepare test data
    test_gdf = gpd.GeoDataFrame(
        {"fid": [1, 2, 3, 4, 5], "priority": [5, 3, 3, 4, 5]},
        geometry=[
            test_helper.TestData.polygon_with_island,
            test_helper.TestData.polygon_with_island,
            test_helper.TestData.polygon_no_islands,
            test_helper.TestData.polygon_no_islands,
            test_helper.TestData.polygon_with_island2,
        ],
        crs=test_helper.TestData.crs_epsg,
    )
    if priority_column is None:
        if priority_ascending:
            expected_gdf = test_gdf.iloc[[0, 2, 4]].set_index(keys="fid")
        else:
            expected_gdf = test_gdf.iloc[[1, 3, 4]].set_index(keys="fid")
    else:  # noqa: PLR5501
        if priority_ascending:
            expected_gdf = test_gdf.iloc[[1, 2, 4]].set_index(keys="fid")
        else:
            expected_gdf = test_gdf.iloc[[0, 3, 4]].set_index(keys="fid")

    suffix = ".gpkg"
    input_path = tmp_path / f"input_test_data{suffix}"
    gfo.to_file(test_gdf, input_path)
    batchsize = math.ceil(gfo.get_layerinfo(input_path).featurecount / 2)

    # Run test
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    gfo.delete_duplicate_geometries(
        input_path=input_path,
        output_path=output_path,
        priority_column=priority_column,
        priority_ascending=priority_ascending,
        batchsize=batchsize,
    )

    # Check result
    result_gdf = gfo.read_file(output_path, fid_as_index=True)
    assert_geodataframe_equal(result_gdf, expected_gdf)


def test_delete_duplicate_geoms_notexact(tmp_path):
    """Test if the test of being duplicates is tolerant enough for small differences.

    Technically this should be the case because the comparison is done using ST_Equals.

    E.g.:
      - The order of points in a polygon can be different
      - The starting point of rings in polygons can be different
      - A polygon can countain extra points if they don't add any surfact
    """
    # Prepare test data
    test_gdf = gpd.GeoDataFrame(
        {"fid": [1, 2, 3, 4, 5]},
        geometry=[
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]),
            Polygon([(1, 0), (1, 1), (0, 1), (0, 0), (1, 0)]),
            Polygon([(1, 0), (0, 0), (0, 1), (1, 1), (1, 0)]),
            Polygon([(0, 0), (1, 0), (1, 1), (0, 1), (0, 0.5), (0, 0)]),
            Polygon([(3, 0), (3, 1), (2, 1), (2, 0), (3, 0)]),
        ],
        crs=test_helper.TestData.crs_epsg,
    )
    expected_gdf = test_gdf.iloc[[0, 4]].set_index(keys="fid")
    suffix = ".gpkg"
    input_path = tmp_path / f"input_test_data{suffix}"
    gfo.to_file(test_gdf, input_path)

    # Run test
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    gfo.delete_duplicate_geometries(input_path=input_path, output_path=output_path)

    # Check result
    result_gdf = gfo.read_file(output_path, fid_as_index=True)
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


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS_EXT)
@pytest.mark.parametrize("epsg", EPSGS)
@pytest.mark.filterwarnings(
    "ignore: The default date converter is deprecated as of Python 3.12"
)
def test_isvalid(tmp_path, suffix, epsg):
    """Test isvalid operation."""
    if not GDAL_GTE_311 and suffix in {".gpkg.zip", ".shp.zip"}:
        # Skip test for unsupported GDAL versions
        pytest.skip(".zip support requires gdal>=3.11")

    # Prepare test data
    input_tmp_path = test_helper.get_testfile(
        "polygon-invalid",
        dst_dir=tmp_path,
        suffix=suffix.replace(".zip", ""),
        epsg=epsg,
    )

    # For Geopackage, also test if fid is properly preserved
    preserve_fid = True if suffix == ".gpkg" else False
    # Delete 2nd row, so we can check properly if fid is retained for Geopackage
    # WHERE rowid = 2, because fid is not known for .shp file with sql_dialect="SQLITE"
    input_layer = gfo.get_only_layer(input_tmp_path)
    sql_stmt = f'DELETE FROM "{input_layer}" WHERE rowid = 2'
    gfo.execute_sql(input_tmp_path, sql_stmt=sql_stmt, sql_dialect="SQLITE")
    if suffix.endswith(".zip"):
        input_path = input_tmp_path.with_suffix(suffix)
        gfo.geo_sozip(input_tmp_path, input_path)
    else:
        input_path = input_tmp_path

    # Now run test
    output_path = tmp_path / f"output{suffix}"
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    gfo.isvalid(input_path=input_path, output_path=output_path, batchsize=batchsize)

    # Now check if the tmp file is correctly created
    assert output_path.exists() is True
    result_layerinfo = gfo.get_layerinfo(output_path)
    assert input_layerinfo.featurecount == result_layerinfo.featurecount
    assert len(input_layerinfo.columns) == len(result_layerinfo.columns) - 2

    output_gdf = gfo.read_file(output_path, fid_as_index=preserve_fid)
    assert output_gdf["geometry"].iloc[0] is not None
    assert output_gdf["isvalid"].iloc[0] == 0
    if preserve_fid:
        assert output_gdf.iloc[0:2].index.sort_values().tolist() == [1, 3]

    # Do operation, without specifying output path
    gfo.isvalid(
        input_path=input_path, batchsize=batchsize, validate_attribute_data=True
    )

    # Now check if the tmp file is correctly created
    output_auto_path = tmp_path / f"{GeoPath(input_path).stem}_isvalid{suffix}"
    assert output_auto_path.exists()
    result_auto_layerinfo = gfo.get_layerinfo(output_auto_path)
    assert input_layerinfo.featurecount == result_auto_layerinfo.featurecount
    assert len(input_layerinfo.columns) == len(result_auto_layerinfo.columns) - 2

    output_auto_gdf = gfo.read_file(output_auto_path)
    assert output_auto_gdf["geometry"][0] is not None
    assert output_auto_gdf["isvalid"][0] == 0


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
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


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
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


@pytest.mark.parametrize("input_suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize("output_suffix", SUFFIXES_GEOOPS)
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


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
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


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
def test_select_equal_columns(tmp_path, suffix):
    """Select that selects two columns with identical names."""
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Now run test
    output_path = tmp_path / f"{GeoPath(input_path).stem}-output{suffix}"
    sql_stmt = 'SELECT {geometrycolumn}, oidn, uidn AS oidn FROM "{input_layer}"'

    gfo.select(input_path=input_path, output_path=output_path, sql_stmt=sql_stmt)

    # Now check if the tmp file is correctly created
    layerinfo_input = gfo.get_layerinfo(input_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_input.featurecount == layerinfo_output.featurecount
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

    assert len(layerinfo_output.columns) == 2
    columns_output_upper = [col.upper() for col in layerinfo_output.columns]
    assert "OIDN" in columns_output_upper
    if suffix in (".gpkg", ".gpkg.zip"):
        assert "OIDN:1" in columns_output_upper
    elif suffix in (".shp", ".shp.zip"):
        assert "OIDN_1" in columns_output_upper
    else:
        raise ValueError(f"Test doesn't support {suffix=}")

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None


@pytest.mark.parametrize(
    "sql_stmt",
    [
        'SELECT {geometrycolumn}, "oidn", "UIDN" FROM "{input_layer}"',
    ],
)
@pytest.mark.parametrize("input_suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize("output_suffix", SUFFIXES_GEOOPS)
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


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
def test_select_invalid_sql(tmp_path, suffix):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Now run test
    output_path = tmp_path / f"{GeoPath(input_path).stem}-output{suffix}"
    sql_stmt = 'SELECT {geometrycolumn}, not_existing_column FROM "{input_layer}"'

    with pytest.raises(Exception, match="Error no such column"):
        gfo.select(input_path=input_path, output_path=output_path, sql_stmt=sql_stmt)

    assert not output_path.exists()


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize("gridsize", [0.0, 0.01])
def test_select_nogeom_in_input(tmp_path, suffix, gridsize):
    # Prepare test data
    input_geom_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    data_df = gfo.read_file(input_geom_path, ignore_geometry=True)
    input_path = tmp_path / f"{GeoPath(input_geom_path).stem}_nogeom{suffix}"
    gfo.to_file(data_df, input_path)

    # Now run test
    output_path = tmp_path / f"{GeoPath(input_path).stem}-output{suffix}"
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


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
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


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
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


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize("explodecollections", [True, False])
def test_select_star(tmp_path, suffix, explodecollections):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Now run test
    name = f"{GeoPath(input_path).stem}-output{suffix}"
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
