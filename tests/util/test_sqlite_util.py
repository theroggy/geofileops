"""
Tests for functionalities in ogr_util.
"""

import logging
import sqlite3
import warnings
from pathlib import Path

import pytest
import shapely
from shapely import box

import geofileops as gfo
from geofileops import fileops
from geofileops._compat import GDAL_GTE_311
from geofileops.util import _sqlite_util as sqlite_util
from geofileops.util._geofileinfo import GeofileInfo
from tests import test_helper
from tests.test_helper import assert_geodataframe_equal


def test_add_gpkg_ogr_contents(tmp_path):
    """Add the gpkg_ogr_contents table to a GPKG file, without layer."""
    path = tmp_path / "test.gpkg"
    conn = sqlite_util.create_new_spatialdb(path)

    # There should be no gpkg_ogr_contents table in the GPKG file yet.
    tables = sqlite_util.get_tables(path)
    assert "gpkg_ogr_contents" not in tables

    # Add the gpkg_ogr_contents table to the GPKG file.
    sqlite_util.add_gpkg_ogr_contents(conn, layer=None)
    tables = sqlite_util.get_tables(path)
    assert "gpkg_ogr_contents" in tables


def test_add_gpkg_ogr_contents_layer_test_triggers(tmp_path):
    """Add the gpkg_ogr_contents table and relevant triggers and check if they work."""
    path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    layer = gfo.get_only_layer(path)

    # The layer should already be registered in an gpkg_ogr_contents table.
    ogr_contents = sqlite_util.get_gpkg_ogr_contents(path)
    assert layer in ogr_contents
    featurecount_orig = ogr_contents[layer]["feature_count"]

    # Remove the gpkg_ogr_contents table and the relevant triggers.
    sqlite_util.execute_sql(path, sql_stmt="DROP TABLE gpkg_ogr_contents;")
    sqlite_util.execute_sql(
        path, sql_stmt=f'DROP TRIGGER "trigger_insert_feature_count_{layer}";'
    )
    sqlite_util.execute_sql(
        path, sql_stmt=f'DROP TRIGGER "trigger_delete_feature_count_{layer}";'
    )

    # Run add
    sqlite_util.add_gpkg_ogr_contents(path, layer=layer)
    ogr_contents = sqlite_util.get_gpkg_ogr_contents(path)
    assert layer in ogr_contents
    assert ogr_contents[layer]["feature_count"] == featurecount_orig

    # Add a row to the layer and check if the feature count is updated
    sqlite_util.execute_sql(
        path, sql_stmt=f'INSERT INTO "{layer}"(geom) VALUES (NULL);'
    )
    ogr_contents = sqlite_util.get_gpkg_ogr_contents(path)
    assert layer in ogr_contents
    assert ogr_contents[layer]["feature_count"] == featurecount_orig + 1

    # Remove a row from the layer and check if the feature count is updated
    sqlite_util.execute_sql(
        path, sql_stmt=f'DELETE FROM "{layer}" WHERE fid = {featurecount_orig + 1};'
    )
    ogr_contents = sqlite_util.get_gpkg_ogr_contents(path)
    assert layer in ogr_contents
    assert ogr_contents[layer]["feature_count"] == featurecount_orig


def test_add_gpkg_ogr_contents_layer_force_update(tmp_path):
    """Test if the force_update parameter works as intended."""
    path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    layer = gfo.get_only_layer(path)

    # The layer should already be registered in an gpkg_ogr_contents table.
    ogr_contents = sqlite_util.get_gpkg_ogr_contents(path)
    assert layer in ogr_contents
    featurecount_orig = ogr_contents[layer]["feature_count"]

    # Update the featurecount in the gpkg_ogr_contents table with wrong data.
    featurecount_updated = featurecount_orig + 5
    sql_stmt = f"""
        UPDATE gpkg_ogr_contents
           SET feature_count = {featurecount_updated}
         WHERE lower(table_name) = '{layer.lower()}'
    """
    sqlite_util.execute_sql(path, sql_stmt=sql_stmt)

    # Run add, but with force_update=False (=the default)
    sqlite_util.add_gpkg_ogr_contents(path, layer=layer)
    ogr_contents = sqlite_util.get_gpkg_ogr_contents(path)
    assert layer in ogr_contents
    assert ogr_contents[layer]["feature_count"] == featurecount_updated

    # Run add, but with force_update=True
    sqlite_util.add_gpkg_ogr_contents(path, layer=layer, force_update=True)
    ogr_contents = sqlite_util.get_gpkg_ogr_contents(path)
    assert layer in ogr_contents
    assert ogr_contents[layer]["feature_count"] == featurecount_orig


@pytest.mark.parametrize("use_spatialite", [True, False])
def test_connect(use_spatialite):
    """Test the connect function."""
    test_path = test_helper.get_testfile("polygon-parcel")

    conn = sqlite_util.connect(test_path, use_spatialite=use_spatialite)

    # Check connection
    try:
        assert isinstance(conn, sqlite3.Connection)
        if use_spatialite:
            # Verify if spatialite extension is loaded by checking versions
            sql = "SELECT spatialite_version(), geos_version()"
            spatialite_version, geos_version = conn.execute(sql).fetchone()

            assert spatialite_version is not None
            assert geos_version is not None
        else:
            # Verify that spatialite is not loaded by checking that the
            # spatialite_version function does not exist.
            sql = "SELECT spatialite_version();"
            with pytest.raises(sqlite3.OperationalError, match="no such function"):
                conn.execute(sql).fetchone()

    finally:
        conn.close()


def test_connect_invalid(tmp_path):
    """Test error handling in the connect function."""
    not_existing_path = tmp_path / "not_existing_file.gpkg"
    with pytest.raises(FileNotFoundError, match="Database file not found"):
        sqlite_util.connect(not_existing_path)


@pytest.mark.parametrize(
    "layer1_empty, layer2_empty",
    [(True, True), (True, False), (False, True), (False, False)],
)
def test_copy_table(tmp_path, layer1_empty, layer2_empty):
    """Test the copy_table function.

    Test with combinations of empty and non-empty input layers to make sure the
    total_bounds are handled correctly.
    """
    if not GDAL_GTE_311 and (
        (layer1_empty and not layer2_empty) or (not layer1_empty and layer2_empty)
    ):
        pytest.skip(
            "GDAL versions < 3.11 have issues with calculating total_bounds when "
            "one of the layers is empty."
        )

    layer1_path = test_helper.get_testfile(
        "polygon-parcel", geom_name="geometry", dst_dir=tmp_path, empty=layer1_empty
    )
    layer2_path = test_helper.get_testfile(
        "polygon-zone", geom_name="geometry", dst_dir=tmp_path, empty=layer2_empty
    )
    gfo.drop_column(layer2_path, column_name="naam")
    layer1_info = gfo.get_layerinfo(layer1_path)
    layer2_info = gfo.get_layerinfo(layer2_path)

    # Append layer2 to layer1
    sqlite_util.copy_table(
        input_path=layer2_path,
        output_path=layer1_path,
        input_table=layer2_info.name,
        output_table=layer1_info.name,
    )

    # Check if the rows were appended
    result_info = gfo.get_layerinfo(layer1_path)
    assert (
        result_info.featurecount == layer1_info.featurecount + layer2_info.featurecount
    )

    # Check total bounds
    # total_bounds with all zero values are ignored
    exp_bounds_list = [
        bounds
        for bounds in [layer1_info.total_bounds, layer2_info.total_bounds]
        if not all(value == 0 for value in bounds)
    ]
    exp_total_bounds = (
        shapely.MultiPolygon([box(*bounds) for bounds in exp_bounds_list]).bounds
        if len(exp_bounds_list) > 0
        else (0, 0, 0, 0)
    )
    for idx, value in enumerate(result_info.total_bounds):
        assert round(value) == round(exp_total_bounds[idx])


def test_copy_table_columns(tmp_path):
    """Test the copy_table function, but only copy some columns.

    The columns that are not copied will be NULL in the output file.
    """
    input_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    layer = gfo.get_only_layer(input_path)
    info = gfo.get_layerinfo(input_path, layer)
    output_path = tmp_path / "output.gpkg"
    gfo.copy(input_path, output_path)

    # Append the layer to itself, but only copy the 'geom' and 'OIDN' columns.
    sqlite_util.copy_table(
        input_path=input_path,
        output_path=output_path,
        input_table=layer,
        output_table=layer,
        columns=["geom", "OIDN"],
    )

    # Check if the rows were appended
    result = gfo.read_file(output_path)
    assert info.featurecount * 2 == len(result)
    # For all appended rows, the columns that were not copied should be NULL
    for column in result.columns:
        if column in ("geometry", "OIDN"):
            warnings.filterwarnings("ignore", "GeoSeries.notna", UserWarning)
            assert result[column].iloc[info.featurecount :].notnull().all()
        else:
            assert result[column].iloc[info.featurecount :].isnull().all()


def test_copy_table_error(tmp_path):
    """Test error handling in the copy_table function."""
    test_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    layer = gfo.get_only_layer(test_path)

    with pytest.raises(ValueError, match="Input and output paths cannot be the same"):
        sqlite_util.copy_table(
            input_path=test_path,
            output_path=test_path,
            input_table=layer,
            output_table=layer,
        )

    # Both input and output files should exist
    not_existing_path = tmp_path / "not_existing_file.gpkg"
    with pytest.raises(FileNotFoundError, match="Input file not found"):
        sqlite_util.copy_table(
            input_path=not_existing_path,
            output_path=test_path,
            input_table=layer,
            output_table=layer,
        )
    with pytest.raises(FileNotFoundError, match="Output file not found"):
        sqlite_util.copy_table(
            input_path=test_path,
            output_path=not_existing_path,
            input_table=layer,
            output_table=layer,
        )


@pytest.mark.parametrize(
    "filename, filetype, crs_epsg",
    [
        (":memory:", "GpKg", None),
        (":memory:", "SqlitE", None),
        ("test.sqlite", None, 31370),
        ("test.gpkg", None, 31370),
    ],
)
def test_create_new_spatialdb(tmp_path, filename, filetype, crs_epsg):
    if filename == ":memory:":
        output = filename
    else:
        output = tmp_path / filename

    conn = sqlite_util.create_new_spatialdb(
        output, crs_epsg=crs_epsg, filetype=filetype
    )
    conn.close()

    if filename != ":memory:":
        assert output.exists()


@pytest.mark.parametrize(
    "filename, filetype, crs_epsg, expected_error",
    [
        (":memory:", None, None, "Unsupported suffix"),
        ("test.unknown", None, None, "Unsupported suffix"),
        ("no_suffix", None, None, "Unsupported suffix"),
        ("file", "unknown", None, "Unsupported filetype"),
        (":memory:", "gpkg", "abc", "Invalid crs_epsg"),
    ],
)
def test_create_new_spatialdb_error(
    tmp_path, filename, filetype, crs_epsg, expected_error
):
    if filename == ":memory:":
        output = filename
    else:
        output = tmp_path / filename

    with pytest.raises(Exception, match=expected_error):
        sqlite_util.create_new_spatialdb(output, crs_epsg=crs_epsg, filetype=filetype)


@pytest.mark.parametrize("create_spatial_index", [(True), (False)])
@pytest.mark.parametrize("create_ogr_contents", [(True), (False)])
@pytest.mark.parametrize("output_epsg", [-1, 31370])
@pytest.mark.filterwarnings(
    "ignore:.*Using create_spatial_index=True for a GPKG file is not recommended .*"
)
def test_create_table_as_sql(
    tmp_path, create_spatial_index, create_ogr_contents, output_epsg
):
    output_path = tmp_path / "output.gpkg"
    input1_path = test_helper.get_testfile(testfile="polygon-parcel", dst_dir=tmp_path)
    input2_path = test_helper.get_testfile(testfile="polygon-zone", dst_dir=tmp_path)

    sql_stmt = """
            SELECT CastToMulti(ST_CollectionExtract(
                       ST_Intersection(layer1.geom, layer2.geometry), 3)) as geom
                  ,ST_area(layer1.geom) AS area_intersect
                  ,layer1.HFDTLT
                  ,layer2.naam
              FROM {input1_databasename}."parcels" layer1
              JOIN {input1_databasename}."rtree_parcels_geom" layer1tree
                ON layer1.fid = layer1tree.id
              JOIN {input2_databasename}."zones" layer2
              JOIN {input2_databasename}."rtree_zones_geometry" layer2tree
                ON layer2.fid = layer2tree.id
             WHERE 1=1
               AND layer1.rowid > 0 AND layer1.rowid < 10
               AND layer1tree.minx <= layer2tree.maxx
               AND layer1tree.maxx >= layer2tree.minx
               AND layer1tree.miny <= layer2tree.maxy
               AND layer1tree.maxy >= layer2tree.miny
               AND ST_Intersects(layer1.geom, layer2.geometry) = 1
               AND ST_Touches(layer1.geom, layer2.geometry) = 0
            """
    sql_stmt = sql_stmt.format(
        input1_databasename="input1_db", input2_databasename="input2_db"
    )

    sqlite_util.create_table_as_sql(
        input_databases={"input1_db": input1_path, "input2_db": input2_path},
        output_path=output_path,
        output_layer=output_path.stem,
        output_geometrytype=gfo.GeometryType.MULTIPOLYGON,
        output_crs=output_epsg,
        sql_stmt=sql_stmt,
        profile=sqlite_util.SqliteProfile.SPEED,
        create_spatial_index=create_spatial_index,
        create_ogr_contents=create_ogr_contents,
    )

    assert output_path.exists()
    assert gfo.has_spatial_index(output_path) is create_spatial_index
    output_info = gfo.get_layerinfo(output_path)
    assert output_info.featurecount == 7

    # Check if the "gpkg_ogr_contents" table is present in the output gpkg if needed.
    tables = sqlite_util.get_tables(output_path)
    if create_ogr_contents:
        assert "gpkg_ogr_contents" in tables
        gpkg_ogr_contents = sqlite_util.get_gpkg_ogr_contents(output_path)
        assert gpkg_ogr_contents["output"]["feature_count"] is not None
    else:
        assert "gpkg_ogr_contents" not in tables

    # The bounds of the layer should typically be filled out. It won't be filled out
    # if the output_epsg is -1 and no spatial index is created.
    if create_spatial_index or output_epsg != -1:
        gpkg_contents = sqlite_util.get_gpkg_contents(output_path)
        assert gpkg_contents["output"]["min_x"] is not None
        assert gpkg_contents["output"]["min_y"] is not None
        assert gpkg_contents["output"]["max_x"] is not None
        assert gpkg_contents["output"]["max_y"] is not None

    # The gpkg created by spatialite by default include some triggers that have errors
    # and were removed from the gpkg spec but not removed in spatialite.
    # These operations give errors if the triggers are still there.
    gfo.drop_column(output_path, column_name="naam")
    gfo.rename_layer(output_path, layer=output_path.stem, new_layer="test_layername")


@pytest.mark.parametrize(
    "kwargs, expected_error",
    [
        ({"append": True}, "append=True nor update=True are implemented."),
        ({"update": True}, "append=True nor update=True are implemented."),
        (
            {
                "input_databases": {
                    "input1": Path("input1.sqlite"),
                    "input2": Path("input2.gpkg"),
                }
            },
            "output_path and all input paths must have the same suffix!",
        ),
        (
            {
                "input_databases": {
                    "input1": Path("input1.gpkg"),
                    "input2": Path("input2.sqlite"),
                }
            },
            "output_path and all input paths must have the same suffix!",
        ),
        (
            {"output_path": Path("output.sqlite")},
            "output_path and all input paths must have the same suffix!",
        ),
    ],
)
def test_create_table_as_sql_invalidparams(kwargs, expected_error):
    # Set default values for kwargs that are not specified:
    if "input_databases" not in kwargs:
        kwargs["input_databases"] = {
            "input1_db": Path("input1.gpkg"),
            "input2_db": Path("input2.gpkg"),
        }
    if "output_path" not in kwargs:
        kwargs["output_path"] = Path("output.gpkg")
    if "output_layer" not in kwargs:
        kwargs["output_layer"] = "output_layer"
    if "sql_stmt" not in kwargs:
        kwargs["sql_stmt"] = "SELECTje"
    if "output_geometrytype" not in kwargs:
        kwargs["output_geometrytype"] = None
    if "output_crs" not in kwargs:
        kwargs["output_crs"] = -1

    with pytest.raises(ValueError, match=expected_error):
        sqlite_util.create_table_as_sql(**kwargs)


def test_execute_sql(tmp_path):
    test_path = test_helper.get_testfile(testfile="polygon-parcel", dst_dir=tmp_path)
    exp_spatial_index = GeofileInfo(test_path).default_spatial_index
    assert gfo.has_spatial_index(test_path) is exp_spatial_index
    info_input = gfo.get_layerinfo(test_path)
    nb_deleted = 0

    # Execute one statement
    sql_stmt = "DELETE FROM parcels WHERE rowid = (SELECT MIN(rowid) FROM parcels)"
    sqlite_util.execute_sql(test_path, sql_stmt=sql_stmt)
    nb_deleted += 1
    info = gfo.get_layerinfo(test_path)
    assert info.featurecount == info_input.featurecount - nb_deleted

    # Execute a list of statements
    sqlite_util.execute_sql(test_path, sql_stmt=[sql_stmt, sql_stmt])
    nb_deleted += 2
    info = gfo.get_layerinfo(test_path)
    assert info.featurecount == info_input.featurecount - nb_deleted


def test_execute_sql_invalid(tmp_path):
    test_path = test_helper.get_testfile(testfile="polygon-parcel", dst_dir=tmp_path)

    with pytest.raises(RuntimeError, match="Error executing"):
        sqlite_util.execute_sql(test_path, sql_stmt="INVALID SQL STATEMENT")


@pytest.mark.parametrize(
    "db1_name, db2_name", [("input1_db", "input2_db"), ("main", "input2_db")]
)
def test_get_columns(db1_name, db2_name):
    # Prepare test data
    input1_path = test_helper.get_testfile("polygon-parcel")
    input2_path = test_helper.get_testfile("polygon-zone")

    input1_info = gfo.get_layerinfo(input1_path)
    input2_info = gfo.get_layerinfo(input2_path)
    # Also include an identical column name aliasing a constant, is special case that
    # was a bug (https://github.com/geofileops/geofileops/pull/477).
    sql_stmt = f"""
        SELECT layer1.OIDN, layer1.UIDN, layer1.datum, layer2.naam, 'test' AS naam
          FROM {db1_name}."{input1_info.name}" layer1
          CROSS JOIN {db2_name}."{input2_info.name}" layer2
         WHERE 1=1
    """

    # Set logging level to DEBUG so the explain plan logging code path is touched.
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Run test
    columns = sqlite_util.get_columns(
        sql_stmt=sql_stmt,
        input_databases={db1_name: input1_path, db2_name: input2_path},
    )

    assert len(columns) == 5


def test_get_column_types():
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel")
    input_info = gfo.get_layerinfo(input_path)

    # Run test
    column_types = sqlite_util.get_column_types(
        database=input_path, table=input_info.name
    )

    # Check results
    assert len(column_types) == len(input_info.columns) + 2
    assert column_types["fid"] == "INTEGER"
    assert column_types["geom"] == "MULTIPOLYGON"
    assert column_types["OIDN"] == "INTEGER"
    assert column_types["HFDTLT"] == "TEXT(20)"
    assert column_types["DATUM"] == "DATETIME"


def test_create_table_as_sql_single_input(tmp_path):
    input_path = test_helper.get_testfile(testfile="polygon-parcel", dst_dir=tmp_path)
    output_path = tmp_path / "output.gpkg"
    distance = 10
    resolution = 5

    # Prepare expected result
    expected_gdf = fileops.read_file(input_path, columns=["HFDTLT"])
    expected_gdf.geometry = expected_gdf.geometry.buffer(
        distance, resolution=resolution
    )

    sql_stmt = f"""
        SELECT ST_buffer(layer.geom, {distance}, {resolution}) as geom
              ,layer.HFDTLT
          FROM "parcels" layer
    """
    sqlite_util.create_table_as_sql(
        input_databases={"input": input_path},
        output_path=output_path,
        output_layer=None,
        output_geometrytype=None,
        output_crs=31370,
        sql_stmt=sql_stmt,
    )

    assert output_path.exists()
    output_gdf = fileops.read_file(output_path)

    # EMPTY geometry becomes NULL/None...
    expected_gdf.loc[expected_gdf.geometry.is_empty, "geometry"] = None
    assert_geodataframe_equal(output_gdf, expected_gdf)


def test_get_gpkg_content():
    input_path = test_helper.get_testfile(testfile="polygon-parcel")

    layer = gfo.get_only_layer(input_path)
    layer_info = gfo.get_layerinfo(input_path, layer)

    content_info = sqlite_util.get_gpkg_content(input_path, layer)
    assert content_info["table_name"] == layer
    assert content_info["data_type"] == "features"
    assert content_info["srs_id"] == layer_info.crs.to_epsg()
    assert round(content_info["min_x"]) == round(layer_info.total_bounds[0])
    assert round(content_info["min_y"]) == round(layer_info.total_bounds[1])
    assert round(content_info["max_x"]) == round(layer_info.total_bounds[2])
    assert round(content_info["max_y"]) == round(layer_info.total_bounds[3])
    for idx, value in enumerate(content_info["total_bounds"]):
        assert round(value) == round(layer_info.total_bounds[idx])


@pytest.mark.parametrize("database_connection", [True, False])
def test_get_gpkg_contents(database_connection):
    """Test getting gpkg_contents with both a path and a connection."""
    input_path = test_helper.get_testfile(testfile="polygon-parcel")
    database = sqlite_util.connect(input_path) if database_connection else input_path

    gpkg_contents = sqlite_util.get_gpkg_contents(database=database)

    if database_connection:
        database.close()
        database = None

    # Check results
    layer = gfo.get_only_layer(input_path)
    layer_info = gfo.get_layerinfo(input_path, layer)

    assert layer in gpkg_contents
    content_info = gpkg_contents[layer]
    assert content_info["table_name"] == layer
    assert content_info["data_type"] == "features"
    assert content_info["srs_id"] == layer_info.crs.to_epsg()
    assert round(content_info["min_x"]) == round(layer_info.total_bounds[0])
    assert round(content_info["min_y"]) == round(layer_info.total_bounds[1])
    assert round(content_info["max_x"]) == round(layer_info.total_bounds[2])
    assert round(content_info["max_y"]) == round(layer_info.total_bounds[3])


@pytest.mark.parametrize("database_connection", [True, False])
def test_get_gpkg_geometry_column_info(database_connection):
    """Test getting gpkg_geometry_columns with both a path and a connection."""
    input_path = test_helper.get_testfile(testfile="polygon-parcel")
    layer = gfo.get_only_layer(input_path)
    database = sqlite_util.connect(input_path) if database_connection else input_path

    geometry_column_info = sqlite_util.get_gpkg_geometry_column_info(
        database=database, table_name=layer
    )

    if database_connection:
        database.close()
        database = None

    # Check result
    layer_info = gfo.get_layerinfo(input_path)
    assert layer_info.geometrycolumn == geometry_column_info["column_name"]


@pytest.mark.parametrize("empty", [True, False])
def test_get_gpkg_total_bounds(empty):
    input_path = test_helper.get_testfile(testfile="polygon-parcel", empty=empty)

    layer = gfo.get_only_layer(input_path)
    layer_info = gfo.get_layerinfo(input_path, layer)

    total_bounds = sqlite_util.get_gpkg_total_bounds(input_path, layer)
    if empty:
        assert total_bounds is None
    else:
        for idx, value in enumerate(total_bounds):
            assert round(value) == round(layer_info.total_bounds[idx])


def test_load_spatialite():
    test_path = test_helper.get_testfile("polygon-parcel")
    conn = sqlite3.connect(test_path)

    sqlite_util.load_spatialite(conn, enable_gpkg_mode=True)

    # Verify if spatialite extension is loaded by checking versions
    sql = "SELECT spatialite_version(), geos_version()"
    spatialite_version, geos_version = conn.execute(sql).fetchone()

    assert spatialite_version is not None
    assert geos_version is not None

    # Verify if GPKG mode is enabled
    sql = "SELECT GetGpkgMode();"
    gpkg_mode = conn.execute(sql).fetchone()[0]

    assert gpkg_mode == 1


def test_load_spatialite_gpkgmode_failed():
    """Test error if enabling GPKG mode fails.

    Enabling GPKG mode will fail here because the test file is not a valid GPKG file.
    """
    test_path = test_helper.get_testfile("polygon-parcel", suffix=".sqlite")
    conn = sqlite3.connect(test_path)

    with pytest.raises(
        RuntimeError, match="Failed to enable GPKG mode in mod_spatialite"
    ):
        sqlite_util.load_spatialite(conn, enable_gpkg_mode=True)
