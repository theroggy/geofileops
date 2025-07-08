"""Module containing utilities regarding sqlite/spatialite files."""

import datetime
import enum
import logging
import pprint
import shutil
import sqlite3
import time
import warnings
from pathlib import Path
from typing import TYPE_CHECKING, Any, Union

from pygeoops import GeometryType
from pyproj import CRS, Transformer

import geofileops as gfo
from geofileops.helpers._configoptions_helper import ConfigOptions
from geofileops.util import _geopath_util, _sqlite_userdefined
from geofileops.util._general_util import MissingRuntimeDependencyError

if TYPE_CHECKING:  # pragma: no cover
    import os

logger = logging.getLogger(__name__)


class EmptyResultError(Exception):
    """Exception raised when the SQL statement disn't return any rows.

    Attributes:
        message (str): Exception message
    """

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


def spatialite_version_info() -> dict[str, str]:
    """Returns the versions of the spatialite modules.

    Versions returned: spatialite_version, geos_version.

    Raises:
        RuntimeError: if a runtime dependency is not available.

    Returns:
        Dict[str, str]: a dict with the version of the runtime dependencies.
    """
    test_path = Path(__file__).resolve().parent / "test.gpkg"
    conn = sqlite3.connect(test_path)
    try:
        load_spatialite(conn)
        sql = "SELECT spatialite_version(), geos_version()"
        result = conn.execute(sql).fetchall()
        spatialite_version = result[0][0]
        geos_version = result[0][1]
    except MissingRuntimeDependencyError:  # pragma: no cover
        conn.rollback()
        raise
    except Exception as ex:  # pragma: no cover
        conn.rollback()
        raise RuntimeError(f"Error {ex} executing {sql}") from ex
    finally:
        conn.close()

    if not spatialite_version:  # pragma: no cover
        warnings.warn(
            "empty sqlite3 spatialite version: probably a geofileops dependency was "
            "not installed correctly: check the installation instructions in the "
            "geofileops docs.",
            stacklevel=1,
        )
    if not geos_version:  # pragma: no cover
        warnings.warn(
            "empty sqlite3 spatialite GEOS version: probably a geofileops dependency "
            "was not installed correctly: check the installation instructions in the "
            "geofileops docs.",
            stacklevel=1,
        )

    versions = {
        "spatialite_version": spatialite_version,
        "geos_version": geos_version,
    }
    return versions


class SqliteProfile(enum.Enum):
    DEFAULT = 0
    SPEED = 1


def add_gpkg_ogr_contents(database: Any, layer: str | None, force_update: bool = False):
    """Add a layer to the gpkg_ogr_contents table in a geopackage.

    If the table doesn't exist yet, it will be created.

    Args:
        database (Any): the database to add the gpkg_ogr_contents to. This can be a path
            to a file or an sqlite3.Connection object. If it is a connection, it won't
            be closed when returning.
        layer (str): the name of the layer to add to the gpkg_ogr_contents table.
            If None, only the table will be created.
        force_update (bool, optional): True to update the data if the layer already
            exists. Defaults to False.

    Raises:
        RuntimeError: an error occured while creating the table.

    Returns:
        None
    """
    if isinstance(database, sqlite3.Connection):
        # If a connection is passed, use it
        conn = database
    else:
        conn = sqlite3.connect(database)

    sql = None
    try:
        # Create gpkg_ogr_contents table if it doesn't exist yet
        sql = """
            CREATE TABLE IF NOT EXISTS gpkg_ogr_contents(
                table_name TEXT NOT NULL PRIMARY KEY,
                feature_count INTEGER DEFAULT 0
            );
        """
        conn.execute(sql)

        if layer is None:
            conn.commit()
            return

        # Create triggers to keep the feature count up to date
        sql = f"""
            CREATE TRIGGER IF NOT EXISTS "trigger_insert_feature_count_{layer}"
                AFTER INSERT ON "{layer}"
            BEGIN
                UPDATE gpkg_ogr_contents
                    SET feature_count = feature_count + 1
                WHERE lower(table_name) = lower('{layer}');
            END;
        """
        conn.execute(sql)
        sql = f"""
            CREATE TRIGGER IF NOT EXISTS "trigger_delete_feature_count_{layer}"
                AFTER DELETE ON "{layer}"
            BEGIN
                UPDATE gpkg_ogr_contents
                    SET feature_count = feature_count - 1
                WHERE lower(table_name) = lower('{layer}');
            END;
        """
        conn.execute(sql)

        # Check if the layer already exists in the gpkg_ogr_contents table
        sql = f"""
            SELECT * FROM gpkg_ogr_contents
             WHERE lower(table_name) = '{layer.lower()}';
        """
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql)
        contents = cursor.fetchall()
        if len(contents) > 0:
            # Layer already exists, check if we need to update it
            if force_update:
                sql = f"""
                    UPDATE gpkg_ogr_contents
                       SET feature_count = (SELECT COUNT(*) FROM "{layer}")
                     WHERE lower(table_name) = '{layer.lower()}';
                """
                conn.execute(sql)
            else:
                # Layer already exists and we don't want to update it, so skip it
                return
        else:
            # Layer doesn't exist yet, so add it to the gpkg_ogr_contents table
            sql = f"""
                INSERT INTO gpkg_ogr_contents (table_name, feature_count)
                  VALUES ('{layer}', (SELECT COUNT(*) FROM "{layer}"));
            """
            conn.execute(sql)

        conn.commit()

    except Exception as ex:  # pragma: no cover
        conn.rollback()
        raise RuntimeError(f"Error executing {sql}") from ex
    finally:
        # If no existing connection was passed, close the connection
        if not isinstance(database, sqlite3.Connection):
            conn.close()


def create_new_spatialdb(
    path: Union[str, "os.PathLike[Any]"],
    crs_epsg: int | None = None,
    filetype: str | None = None,
) -> sqlite3.Connection:
    """Create a new spatialite database file.

    Notes:
        - the bounds filled out in the gpkg_contents table will be the bounds of the crs

    Args:
        path (PathLike): the path the create the database file.
        crs_epsg (int, optional): crs to add to the crs reference layer.
            Defaults to None.
        filetype (str, optional): filetype of the spatial database to create. If
            specified, takes precendence over the suffix of the path. Possible values
            are "gpkg" and "sqlite". Defaults to None.

    Raises:
        ValueError: an invalid parameter value is passed.
        RuntimeError: an error occured while creating the database.

    Returns:
        sqlite3.Connection: the connection to the created database.
    """
    # Check input parameters
    if filetype is not None:
        filetype = filetype.lower()
    else:
        suffix = Path(path).suffix.lower()
        if suffix == ".gpkg":
            filetype = "gpkg"
        elif suffix == ".sqlite":
            filetype = "sqlite"
        else:
            raise ValueError(
                f"Unsupported {suffix=} for {path=}, change suffix or specify filetype"
            )

    if crs_epsg is not None and not isinstance(crs_epsg, int):
        raise ValueError(f"Invalid {crs_epsg=}")

    # Connecting to non existing database file will create it...
    conn = sqlite3.connect(path)
    sql = None
    try:
        load_spatialite(conn)

        # Starting transaction manually for good performance, mainly needed on Windows.
        sql = "BEGIN TRANSACTION;"
        conn.execute(sql)

        if filetype == "gpkg":
            sql = "SELECT EnableGpkgMode();"
            conn.execute(sql)

            # Remark: this only works on the main database!
            sql = "SELECT gpkgCreateBaseTables();"
            conn.execute(sql)

            if crs_epsg is not None and crs_epsg not in [0, -1, 4326]:
                sql = f"SELECT gpkgInsertEpsgSRID({crs_epsg});"
                conn.execute(sql)

            # The GPKG created till now is of version 1.0. Apply some upgrades to
            # make it 1.4.

            # Upgrade GPKG from version 1.0 to 1.4.
            # Most changes are related to rtree index triggers, but they
            # are not applicable here as this is an empty database at this point.
            # The 1.3 changes are needed: remove following metadata triggers as they
            # gave issues in some circumstances.
            # https://github.com/opengeospatial/geopackage/pull/240
            triggers_to_remove = [
                "gpkg_metadata_md_scope_insert",
                "gpkg_metadata_md_scope_update",
                "gpkg_metadata_reference_reference_scope_insert",
                "gpkg_metadata_reference_reference_scope_update",
                "gpkg_metadata_reference_column_name_insert",
                "gpkg_metadata_reference_column_name_update",
                "gpkg_metadata_reference_row_id_value_insert",
                "gpkg_metadata_reference_row_id_value_update",
                "gpkg_metadata_reference_timestamp_insert",
                "gpkg_metadata_reference_timestamp_update",
            ]
            for trigger in triggers_to_remove:
                sql = f"DROP TRIGGER IF EXISTS {trigger};"
                conn.execute(sql)

            # Set GPKG version to 1.4
            sql = "PRAGMA application_id=1196444487;"
            conn.execute(sql)
            sql = "PRAGMA user_version=10400;"
            conn.execute(sql)

        elif filetype == "sqlite":
            sql = "SELECT InitSpatialMetaData(1);"
            conn.execute(sql)
            if crs_epsg is not None and crs_epsg not in [0, -1, 4326]:
                sql = f"SELECT InsertEpsgSrid({crs_epsg});"
                conn.execute(sql)

        else:
            raise ValueError(f"Unsupported {filetype=}")

        conn.commit()

    except ValueError:
        conn.close()
        raise
    except Exception as ex:  # pragma: no cover
        conn.close()
        raise RuntimeError(f"Error creating spatial db {path} executing {sql}") from ex

    return conn


def get_columns(
    sql_stmt: str,
    input_databases: dict[str, Path],
    empty_output_ok: bool = True,
    use_spatialite: bool = True,
    output_geometrytype: GeometryType | None = None,
) -> dict[str, str]:
    # Init
    start = time.perf_counter()
    tmp_dir = None

    def get_filetype(path: Path) -> str:
        if _geopath_util.suffixes(path).lower() in (".gpkg", ".gpkg.zip"):
            return "gpkg"
        return path.suffix.lstrip(".")

    # Connect to/create sqlite main database
    if "main" in input_databases:
        # If an input database is main, use it as the main database
        main_db_path = input_databases["main"]
        filetype = get_filetype(main_db_path)
        conn = sqlite3.connect(main_db_path, detect_types=sqlite3.PARSE_DECLTYPES)
        new_db = False
    else:
        # Create temp output db to be sure the output DB is writable, even though we
        # only create a temporary table.
        filetype = get_filetype(next(iter(input_databases.values())))
        conn = create_new_spatialdb(":memory:", filetype=filetype)
        new_db = True

    sql = None
    try:
        if not new_db:
            # If an existing database is opened, we still need to load spatialite
            load_spatialite(conn)

        if filetype == "gpkg":
            sql = "SELECT EnableGpkgMode();"
            conn.execute(sql)

        # Attach to all input databases
        for dbname, path in input_databases.items():
            # main is already opened, so skip it
            if dbname == "main":
                continue

            sql = f"ATTACH DATABASE ? AS {dbname}"
            dbSpec = (str(path),)
            conn.execute(sql, dbSpec)

        # Set some default performance options
        database_names = ["main"] + list(input_databases.keys())
        set_performance_options(conn, SqliteProfile.SPEED, database_names)

        # Start transaction manually needed for performance
        sql = "BEGIN TRANSACTION;"
        conn.execute(sql)

        # Prepare sql statement for execute
        sql_stmt_prepared = sql_stmt.format(batch_filter="")

        # Log explain plan if debug logging enabled.
        if logger.isEnabledFor(logging.DEBUG):
            sql = f"""
                EXPLAIN QUERY PLAN
                SELECT * FROM (
                  {sql_stmt_prepared}
                );
            """
            cur = conn.execute(sql)
            plan = cur.fetchall()
            cur.close()
            logger.debug(pprint.pformat(plan))

        # Create temp table to get the column names + general data types
        # + fetch one row to use it to determine geometrytype.
        # Remark: specify redundant OFFSET 0 to keep sqlite from flattings the subquery.
        sql = f"""
            CREATE TEMPORARY TABLE tmp AS
            SELECT *
              FROM (
                {sql_stmt_prepared}
              )
             LIMIT 1 OFFSET 0;
        """
        conn.execute(sql)
        conn.commit()

        sql = "PRAGMA TABLE_INFO(tmp)"
        cur = conn.execute(sql)
        tmpcolumns = cur.fetchall()
        cur.close()

        # Fetch one row to try to get more detailed data types if needed
        sql = "SELECT * FROM tmp"
        tmpdata = conn.execute(sql).fetchone()
        if tmpdata is not None and len(tmpdata) == 0:
            tmpdata = None
        if not empty_output_ok and tmpdata is None:
            # If no row was returned, stop
            raise EmptyResultError(f"Query didn't return any rows: {sql_stmt}")

        # Loop over all columns to determine the data type
        columns = {}
        for column_index, column in enumerate(tmpcolumns):
            columnname = column[1]
            columntype = column[2]

            if columnname == "geom":
                # PRAGMA TABLE_INFO gives None as column type for a
                # geometry column. So if output_geometrytype not specified,
                # Use ST_GeometryType to get the type
                # based on the data + apply to_multitype to be sure
                if output_geometrytype is None:
                    sql = f'SELECT ST_GeometryType("{columnname}") FROM tmp;'
                    result = conn.execute(sql).fetchall()
                    if len(result) > 0 and result[0][0] is not None:
                        output_geometrytype = GeometryType[result[0][0]].to_multitype
                    else:
                        output_geometrytype = GeometryType["GEOMETRY"]
                columns[columnname] = output_geometrytype.name
            elif columntype == "INT":
                columns[columnname] = "INTEGER"
            elif columntype is None or columntype == "":
                sql = f'SELECT typeof("{columnname}") FROM tmp;'
                result = conn.execute(sql).fetchall()
                if len(result) > 0 and result[0][0] is not None:
                    columns[columnname] = result[0][0]
                else:
                    # If unknown, take the most general types
                    columns[columnname] = "NUMERIC"
            elif columntype == "NUM":
                # PRAGMA TABLE_INFO sometimes returns 'NUM', but apparently this
                # cannot be used in "CREATE TABLE".
                if tmpdata is None:
                    columns[columnname] = "NUMERIC"
                elif isinstance(tmpdata[column_index], datetime.date):
                    columns[columnname] = "DATE"
                elif isinstance(tmpdata[column_index], datetime.datetime):
                    columns[columnname] = "DATETIME"
                elif isinstance(tmpdata[column_index], str):
                    sql = f'SELECT datetime("{columnname}") FROM tmp;'
                    result = conn.execute(sql).fetchall()
                    if len(result) > 0 and result[0][0] is not None:
                        columns[columnname] = "DATETIME"
                    else:
                        columns[columnname] = "NUMERIC"
                else:
                    columns[columnname] = "NUMERIC"
            else:
                columns[columnname] = columntype

    except Exception as ex:  # pragma: no cover
        conn.rollback()
        raise RuntimeError(f"Error {ex} executing {sql}") from ex
    finally:
        conn.close()
        if ConfigOptions.remove_temp_files:
            if tmp_dir is not None:
                shutil.rmtree(tmp_dir, ignore_errors=True)

    time_taken = time.perf_counter() - start
    if time_taken > 5:  # pragma: no cover
        logger.info(f"get_columns ready, took {time_taken:.2f} seconds")

    return columns


def create_table_as_sql(
    input_databases: dict[str, Path],
    output_path: Path,
    sql_stmt: str,
    output_layer: str,
    output_geometrytype: GeometryType | None,
    output_crs: int,
    append: bool = False,
    update: bool = False,
    create_spatial_index: bool = False,
    create_ogr_contents: bool = False,
    empty_output_ok: bool = True,
    column_datatypes: dict | None = None,
    profile: SqliteProfile = SqliteProfile.DEFAULT,
):
    """Execute sql statement and save the result in the output file.

    Args:
        input_databases (dict): dict with the database name(s) and path(s) to the input
            database(s).
        output_path (Path): the path where the output file needs to be created/appended.
        sql_stmt (str): SELECT statement to run on the input files.
        output_layer (str): layer/table name to use.
        output_geometrytype (Optional[GeometryType]): geometry type of the output.
        output_crs (int): epsg code of crs of the output file.
        append (bool, optional): True to append to an existing file. Defaults to False.
        update (bool, optional): True to append to an existing layer. Defaults to False.
        create_spatial_index (bool, optional): True to create a spatial index on the
            output layer. Defaults to False.
        create_ogr_contents (bool, optional): True to create the gpkg_ogr_contents table
            in the output file and fill it up. Defaults to False.
        empty_output_ok (bool, optional): If the sql_stmt doesn't return any rows and
            True, create an empty output file. If False, throw EmptyResultError.
            Defaults to True.
        column_datatypes (dict, optional): Can be used to specify the data types of
            columns in the form of {"columnname": "datatype"}. If the data type of
            (some) columns is not specified, it it automatically determined as good as
            possible. Defaults to None.
        profile (SqliteProfile, optional): the set of PRAGMA's to use when creating the
            table. SqliteProfile.DEFAULT will use default setting. SqliteProfile.SPEED
            uses settings optimized for speed, but will be less save regarding
            transaction safety,...
            Defaults to SqliteProfile.DEFAULT.

    Raises:
        ValueError: invalid (combinations of) parameters passed.
        EmptyResultError: the sql_stmt didn't return any rows.
    """
    # Check input parameters
    if append is True or update is True:
        raise ValueError("append=True nor update=True are implemented.")

    # All input files and the output file must have the same suffix.
    output_suffix_lower = output_path.suffix.lower()
    for path in input_databases.values():
        if output_suffix_lower != path.suffix.lower():
            raise ValueError(
                "output_path and all input paths must have the same suffix!"
            )

    # Determine columns/datatypes to create the table if not specified
    column_types = column_datatypes
    if column_types is None:
        column_types = get_columns(
            sql_stmt=sql_stmt,
            input_databases=input_databases,
            empty_output_ok=empty_output_ok,
            use_spatialite=True,
            output_geometrytype=output_geometrytype,
        )

    if not output_path.exists():
        # Output file doesn't exist yet: create and init it
        conn = create_new_spatialdb(path=output_path, crs_epsg=output_crs)
        new_db = True
    else:
        # Output file exists: open it
        conn = sqlite3.connect(
            output_path, detect_types=sqlite3.PARSE_DECLTYPES, uri=True
        )
        new_db = False

    sql = None
    try:

        def to_string_for_sql(input) -> str:
            if input is None:
                return "NULL"
            else:
                return str(input)

        # Connect to output database file so it is main, otherwise the
        # gpkg... functions don't work
        # Remark: sql statements using knn only work if they are main, so they
        # are executed with ogr, as the output needs to be main as well :-(.
        output_databasename = "main"
        if not new_db:
            # If an existing database is opened, we still need to load spatialite
            load_spatialite(conn)

        if output_suffix_lower == ".gpkg":
            sql = "SELECT EnableGpkgMode();"
            conn.execute(sql)

        # Attach to all input databases
        for dbname, path in input_databases.items():
            sql = f"ATTACH DATABASE ? AS {dbname}"
            dbSpec = (str(path),)
            conn.execute(sql, dbSpec)

        # Set some default performance options
        database_names = [output_databasename] + list(input_databases.keys())
        set_performance_options(conn, profile, database_names)

        # Start transaction manually needed for performance
        sql = "BEGIN TRANSACTION;"
        conn.execute(sql)

        # If geometry type was not specified, look for it in column_types
        if output_geometrytype is None and "geom" in column_types:
            output_geometrytype = GeometryType(column_types["geom"])

        # Now we can create the table
        # Create output table using the gpkgAddGeometryColumn() function
        # Problem: the spatialite function gpkgAddGeometryColumn() doesn't support
        # layer names with special characters (eg. '-')...
        # Solution: mimic the behaviour of gpkgAddGeometryColumn manually.
        # Create table without geom column
        """
        columns_for_create = [
            f'"{columnname}" {column_types[columnname]}\n' for columnname
            in column_types if columnname != 'geom'
        ]
        sql = (
            f'CREATE TABLE {output_databasename}."{output_layer}" '
            f'({", ".join(columns_for_create)})'
        )
        conn.execute(sql)
        # Add geom column with gpkgAddGeometryColumn()
        # Remark: output_geometrytype.name should be detemined from data if needed,
        # see above...
        sql = (
            f"SELECT gpkgAddGeometryColumn("
            f"    '{output_layer}', 'geom', '{output_geometrytype.name}', 0, 0, "
            f"    {to_string_for_sql(crs_epsg)});"
        conn.execute(sql)
        """
        columns_for_create = [
            f'"{columnname}" {column_types[columnname]}\n'
            for columnname in column_types
            if columnname.lower() != "fid"
        ]
        sql = f"""
            CREATE TABLE {output_databasename}."{output_layer}" (
                fid INTEGER PRIMARY KEY AUTOINCREMENT NOT NULL,
                {", ".join(columns_for_create)}
            )
        """
        conn.execute(sql)

        # Add metadata
        if output_suffix_lower == ".gpkg":
            data_type = "features" if "geom" in column_types else "attributes"

            # Fill out the bounds of the layer using the bounds of the crs if possible
            try:
                crs = CRS.from_user_input(output_crs)
                if crs is not None and crs.area_of_use is not None:
                    transformer = Transformer.from_crs(
                        crs.geodetic_crs, crs, always_xy=True
                    )
                    bounds = transformer.transform_bounds(*crs.area_of_use.bounds)
                    min_x, min_y, max_x, max_y = (
                        to_string_for_sql(coord) for coord in bounds
                    )
                else:
                    min_x = min_y = max_x = max_y = "NULL"

            except Exception:
                min_x = min_y = max_x = max_y = "NULL"

            # ~ mimic behaviour of gpkgAddGeometryColumn()
            sql = f"""
                INSERT INTO {output_databasename}.gpkg_contents (
                  table_name, data_type, identifier, description, last_change,
                  min_x, min_y, max_x, max_y, srs_id)
                VALUES ('{output_layer}', '{data_type}', NULL, '', DATETIME(),
                  {min_x}, {min_y}, {max_x}, {max_y}, {to_string_for_sql(output_crs)});
            """
            conn.execute(sql)

            # If there is a geometry column, register it
            if "geom" in column_types:
                assert output_geometrytype is not None
                sql = f"""
                    INSERT INTO {output_databasename}.gpkg_geometry_columns (
                        table_name, column_name, geometry_type_name, srs_id, z, m)
                    VALUES ('{output_layer}', 'geom', '{output_geometrytype.name}',
                        {to_string_for_sql(output_crs)}, 0, 0);
                """
                conn.execute(sql)

                # Geometry triggers were removed from the GPKG specs in 1.2!
                # Remark: this only works on the main database!
                # sql = f"SELECT gpkgAddGeometryTriggers('{output_layer}', 'geom');"
                # conn.execute(sql)

        elif output_suffix_lower == ".sqlite":
            # Create geom metadata if there is one
            if "geom" in column_types:
                assert output_geometrytype is not None
                sql = f"""
                    SELECT RecoverGeometryColumn(
                        '{output_layer}', 'geom',
                        {to_string_for_sql(output_crs)}, '{output_geometrytype.name}');
                """
                conn.execute(sql)

        # Insert data using the sql statement specified
        try:
            columns_for_insert = [f'"{column}"' for column in column_types]
            sql = (
                f'INSERT INTO {output_databasename}."{output_layer}" '
                f"({', '.join(columns_for_insert)})\n{sql_stmt}"
            )
            conn.execute(sql)

        except Exception as ex:
            ex_message = str(ex).lower()
            if ex_message.startswith(
                "unique constraint failed:"
            ) and ex_message.endswith(".fid"):
                ex.args = (
                    f"{ex}: avoid this by not selecting or aliasing fid "
                    '("select * will select fid!)',
                )
            raise

        # Fill out the feature count in the gpkg_ogr_contents table + create triggers
        if create_ogr_contents and output_suffix_lower == ".gpkg":
            add_gpkg_ogr_contents(database=conn, layer=output_layer, force_update=True)

        # Create spatial index if needed
        if create_spatial_index and "geom" in column_types:
            sql = f"SELECT UpdateLayerStatistics('{output_layer}', 'geom');"
            conn.execute(sql)
            if output_suffix_lower == ".gpkg":
                warnings.warn(
                    "Using create_spatial_index=True for a GPKG file is not "
                    "recommended as it is slow and creates outdated triggers; "
                    "better use gfo.create_spatial_index() afterwards.",
                    stacklevel=2,
                )
                # Create the necessary empty index, triggers,...
                sql = f"SELECT gpkgAddSpatialIndex('{output_layer}', 'geom');"
                conn.execute(sql)
                # Now fill the index
                sql = f"""
                    INSERT INTO "rtree_{output_layer}_geom"
                      SELECT fid
                            ,ST_MinX(geom), ST_MaxX(geom), ST_MinY(geom), ST_MaxY(geom)
                        FROM "{output_layer}"
                       WHERE geom IS NOT NULL
                         AND ST_IsEmpty(geom) = 0
                """
                conn.execute(sql)
            elif output_suffix_lower == ".sqlite":
                sql = f"SELECT CreateSpatialIndex('{output_layer}', 'geom');"
                conn.execute(sql)

        conn.commit()

    except EmptyResultError:
        logger.info(f"Query didn't return any rows: {sql_stmt}")
        conn.close()
        if output_path.exists():
            output_path.unlink()
    except Exception as ex:  # pragma: no cover
        raise RuntimeError(f"Error {ex} executing {sql}") from ex
    finally:
        if conn is not None:
            conn.close()


def execute_sql(path: Path, sql_stmt: str | list[str], use_spatialite: bool = True):
    # Connect to database file
    conn = sqlite3.connect(path)
    sql = None

    try:
        if use_spatialite is True:
            load_spatialite(conn)
            if path.suffix.lower() == ".gpkg":
                sql = "SELECT EnableGpkgMode();"
                conn.execute(sql)

        """
        # Set nb KB of cache
        sql = "PRAGMA cache_size=-50000;"
        conn.execute(sql)
        sql = "PRAGMA temp_store=MEMORY;"
        conn.execute(sql)
        """
        if isinstance(sql_stmt, str):
            sql = sql_stmt
            conn.execute(sql)
        else:
            for sql in sql_stmt:
                conn.execute(sql)
        conn.commit()

    except Exception as ex:
        conn.rollback()
        raise RuntimeError(f"Error executing {sql}") from ex
    finally:
        conn.close()


def get_gpkg_contents(path: Path) -> dict[str, dict]:
    """Get the contents of the gpkg_contents table of a geopackage.

    Args:
        path (Path): file path to the geopackage.

    Returns:
        dict[str, Any]: the contents of the geopackage.
    """
    conn = sqlite3.connect(path)
    sql = None
    try:
        sql = "SELECT * FROM gpkg_contents;"
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql)
        contents = cursor.fetchall()
        contents_dict = {row["table_name"]: dict(row) for row in contents}
    except Exception as ex:  # pragma: no cover
        raise RuntimeError(f"Error executing {sql}") from ex
    finally:
        conn.close()

    return contents_dict


def get_gpkg_ogr_contents(path: Path) -> dict[str, dict]:
    """Get the contents of the gpkg_ogr_contents table of a geopackage.

    Args:
        path (Path): file path to the geopackage.

    Returns:
        dict[str, Any]: the contents of the geopackage.
    """
    conn = sqlite3.connect(path)
    sql = None
    try:
        sql = "SELECT * FROM gpkg_ogr_contents;"
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(sql)
        contents = cursor.fetchall()
        contents_dict = {row["table_name"]: dict(row) for row in contents}
    except Exception as ex:  # pragma: no cover
        raise RuntimeError(f"Error executing {sql}") from ex
    finally:
        conn.close()

    return contents_dict


def get_tables(path: Path) -> list[str]:
    """List all tables in the database.

    Args:
        path (Path): file path to the database.

    Returns:
        list[str]: the list of all tables in the database.
    """
    conn = sqlite3.connect(path)
    sql = None
    try:
        sql = "SELECT name FROM sqlite_master WHERE type='table';"
        cursor = conn.execute(sql)
        tables = [row[0] for row in cursor.fetchall()]
    except Exception as ex:  # pragma: no cover
        raise RuntimeError(f"Error executing {sql}") from ex
    finally:
        conn.close()

    return tables


def test_data_integrity(path: Path, use_spatialite: bool = True):
    # Get list of layers in database
    layers = gfo.listlayers(path=path)

    # Connect to database file
    conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    sql = None

    try:
        if use_spatialite:
            load_spatialite(conn)
        if path.suffix.lower() == ".gpkg":
            sql = "SELECT EnableGpkgMode();"
            conn.execute(sql)

        # Set some basic default performance options
        set_performance_options(conn)

        # Loop over all layers to check if all data is readable
        for layer in layers:
            sql = f'SELECT * FROM "{layer}"'
            cursor = conn.execute(sql)

            # Fetch the data in chunks to avoid excessive memory usage
            while True:
                result = cursor.fetchmany(10000)
                if not result:
                    # All data was fetched from layer
                    break

    except Exception as ex:  # pragma: no cover
        raise RuntimeError(f"Error executing {sql}") from ex
    finally:
        conn.close()


def set_performance_options(
    conn: sqlite3.Connection,
    profile: SqliteProfile | None = None,
    database_names: list[str] = [],
):
    try:
        # Set cache size to 128 MB (in kibibytes)
        sql = "PRAGMA cache_size=-128000;"
        conn.execute(sql)
        # Set temp storage to MEMORY
        sql = "PRAGMA temp_store=2;"
        conn.execute(sql)
        # Set soft heap limit to 1 GB (in bytes)
        sql = f"PRAGMA soft_heap_limit={1024 * 1024 * 1024};"
        conn.execute(sql)

        # Use the sqlite profile specified
        if profile is not None and profile == SqliteProfile.SPEED:
            # Use memory mapped IO: much faster for calculations
            # (max 30GB)
            sql = "PRAGMA mmap_size=30000000000;"
            conn.execute(sql)

            # These options don't really make a difference on windows, but
            # it doesn't hurt and maybe on other platforms...
            for databasename in database_names:
                sql = f"PRAGMA {databasename}.journal_mode=OFF;"
                conn.execute(sql)

                # These pragma's increase speed
                sql = f"PRAGMA {databasename}.locking_mode=EXCLUSIVE;"
                conn.execute(sql)
                sql = f"PRAGMA {databasename}.synchronous=OFF;"
                conn.execute(sql)

    except Exception as ex:  # pragma: no cover
        raise RuntimeError(f"Error executing {sql}: {ex}") from ex


def load_spatialite(conn):
    """Load mod_spatialite for an existing sqlite connection.

    Args:
        conn ([type]): Sqlite connection
    """
    conn.enable_load_extension(True)
    try:
        conn.load_extension("mod_spatialite")
    except Exception as ex:  # pragma: no cover
        raise MissingRuntimeDependencyError(
            "Error trying to load mod_spatialite."
        ) from ex

    # Register custom functions
    # conn.create_function(
    #     "GFO_Difference_Collection",
    #     -1,
    #     sqlite_userdefined.gfo_difference_collection,
    #     deterministic=True,
    # )

    conn.create_function(
        "GFO_ReducePrecision",
        -1,
        _sqlite_userdefined.gfo_reduceprecision,
        deterministic=True,
    )

    # conn.create_function(
    #     "GFO_Split", -1, sqlite_userdefined.gfo_split, deterministic=True
    # )

    # conn.create_function(
    #     "GFO_Subdivide", -1, sqlite_userdefined.gfo_subdivide, deterministic=True
    # )

    # Register custom aggregate function
    # conn.create_aggregate("GFO_Difference_Agg", 3, userdefined.DifferenceAgg)
