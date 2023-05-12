# -*- coding: utf-8 -*-
"""
Module containing utilities regarding sqlite/spatialite files.
"""

import datetime
import enum
import logging
from pathlib import Path
import sqlite3
from typing import List, Optional, Union


import geofileops as gfo
from geofileops import GeometryType
from ._general_util import MissingRuntimeDependencyError

#####################################################################
# First define/init some general variables/constants
#####################################################################

# Get a logger...
logger = logging.getLogger(__name__)


class EmptyResultError(Exception):
    """
    Exception raised when the SQL statement disn't return any rows.

    Attributes:
        message (str): Exception message
    """

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


#####################################################################
# The real work
#####################################################################


def check_runtimedependencies():
    test_path = Path(__file__).resolve().parent / "test.gpkg"
    conn = sqlite3.connect(test_path)
    load_spatialite(conn)


class SqliteProfile(enum.Enum):
    DEFAULT = 0
    SPEED = 1


def create_new_spatialdb(path: Path, crs_epsg: Optional[int] = None):
    # Connect to sqlite
    conn = sqlite3.connect(path)
    sql = None
    try:
        with conn:
            load_spatialite(conn)

            # Init file
            output_suffix_lower = path.suffix.lower()
            if output_suffix_lower == ".gpkg":
                sql = "SELECT EnableGpkgMode();"
                # sql = 'SELECT EnableGpkgAmphibiousMode();'
                conn.execute(sql)
                # Remark: this only works on the main database!
                sql = "SELECT gpkgCreateBaseTables();"
                conn.execute(sql)
                if crs_epsg is not None and crs_epsg not in [0, -1, 4326]:
                    sql = f"SELECT gpkgInsertEpsgSRID({crs_epsg})"
                    conn.execute(sql)
            elif output_suffix_lower == ".sqlite":
                sql = "SELECT InitSpatialMetaData(1);"
                conn.execute(sql)
                if crs_epsg is not None and crs_epsg not in [0, -1, 4326]:
                    sql = f"SELECT InsertEpsgSrid({crs_epsg})"
                    conn.execute(sql)
            else:
                raise Exception(f"Unsupported output format: {output_suffix_lower}")

    except Exception as ex:
        raise Exception(f"Error creating spatial db {path}") from ex
    finally:
        conn.close()


def get_columns(
    sql_stmt: str,
    input1_path: Path,
    input2_path: Optional[Path] = None,
    use_spatialite: bool = True,
) -> List[str]:
    input1_databasename = "main"
    conn = sqlite3.connect(str(input1_path), uri=True)
    sql = None
    try:
        if use_spatialite is True:
            load_spatialite(conn)
            if input1_path.suffix.lower() == ".gpkg":
                sql = "SELECT EnableGpkgMode();"
                conn.execute(sql)

        # If input2 isn't the same database input1, attach to it
        input2_databasename = None
        if input2_path is not None:
            if input2_path == input1_path:
                input2_databasename = input1_databasename
            else:
                input2_databasename = "input2"
                sql = f"ATTACH DATABASE ? AS {input2_databasename}"
                # dbSpec = (f"file:{input2_path.resolve().as_posix()}?mode=ro",)
                dbSpec = (str(input2_path),)
                conn.execute(sql, dbSpec)
        # Prepare sql statement
        sql = sql_stmt.format(
            input1_databasename=input1_databasename,
            input2_databasename=input2_databasename,
        )

        # Execute sql to be able to get the column names
        cur = conn.cursor()
        cur.execute(sql)
        columns = [desc[0] for desc in cur.description]
        conn.rollback()
    except Exception as ex:
        conn.rollback()
        raise Exception(f"Error {ex} executing {sql}") from ex
    finally:
        conn.close()

    return columns


def create_table_as_sql(
    input1_path: Path,
    input1_layer: str,
    input2_path: Path,
    output_path: Path,
    sql_stmt: str,
    output_layer: str,
    output_geometrytype: Optional[GeometryType],
    append: bool = False,
    update: bool = False,
    create_spatial_index: bool = True,
    empty_output_ok: bool = True,
    column_datatypes: Optional[dict] = None,
    profile: SqliteProfile = SqliteProfile.DEFAULT,
):
    """
    Execute sql statement and save the result in the output file.
    Args:
        input1_path (Path): the path to the 1st input file.
        input1_layer (str): the layer/table to select from in het 1st input file
        input2_path (Path): the path to the 2nd input file.
        output_path (Path): the path where the output file needs to be created/appended.
        sql_stmt (str): SELECT statement to run on the input files.
        output_layer (str): layer/table name to use.
        output_geometrytype (Optional[GeometryType]): geometry type of the output.
        append (bool, optional): True to append to an existing file. Defaults to False.
        update (bool, optional): True to append to an existing layer. Defaults to False.
        create_spatial_index (bool, optional): True to create a spatial index on the
            output layer. Defaults to True.
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
    output_suffix_lower = output_path.suffix.lower()
    if output_suffix_lower != input1_path.suffix.lower():
        raise ValueError("output_path and both input paths must have the same suffix!")
    if input2_path is not None and output_suffix_lower != input2_path.suffix.lower():
        raise ValueError("output_path and both input paths must have the same suffix!")

    # Use crs epsg from input1_layer, if it has one
    input1_layerinfo = gfo.get_layerinfo(input1_path, input1_layer)
    crs_epsg = -1
    if input1_layerinfo.crs is not None and input1_layerinfo.crs.to_epsg() is not None:
        crs_epsg = input1_layerinfo.crs.to_epsg()

    # If output file doesn't exist yet, create and init it
    if not output_path.exists():
        create_new_spatialdb(path=output_path, crs_epsg=crs_epsg)

    sql = None
    conn = sqlite3.connect(output_path, detect_types=sqlite3.PARSE_DECLTYPES)
    try:
        with conn:

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
            load_spatialite(conn)

            if output_suffix_lower == ".gpkg":
                sql = "SELECT EnableGpkgMode();"
                conn.execute(sql)

            # Set nb KB of cache
            sql = "PRAGMA cache_size=-128000;"
            conn.execute(sql)
            # Set temp storage to MEMORY
            sql = "PRAGMA temp_store=2;"
            conn.execute(sql)

            # If attach to input1
            input1_databasename = "input1"
            sql = f"ATTACH DATABASE ? AS {input1_databasename}"
            dbSpec = (str(input1_path),)
            conn.execute(sql, dbSpec)

            # If input2 isn't the same database input1, attach to it
            if input2_path is not None:
                if input2_path == input1_path:
                    input2_databasename = input1_databasename
                else:
                    input2_databasename = "input2"
                    sql = f"ATTACH DATABASE ? AS {input2_databasename}"
                    dbSpec = (str(input2_path),)
                    conn.execute(sql, dbSpec)

            # Use the sqlite profile specified
            if profile is SqliteProfile.SPEED:
                # Use memory mapped IO: much faster for calculations
                # (max 30GB)
                conn.execute("PRAGMA mmap_size=30000000000;")

                # These options don't really make a difference on windows, but
                # it doesn't hurt and maybe on other platforms...
                for databasename in [
                    output_databasename,
                    input1_databasename,
                    input2_databasename,
                ]:
                    conn.execute(f"PRAGMA {databasename}.journal_mode=OFF;")

                    # These pragma's increase speed
                    conn.execute(f"PRAGMA {databasename}.locking_mode=EXCLUSIVE;")
                    conn.execute(f"PRAGMA {databasename}.synchronous=OFF;")

            # Prepare sql statement
            sql_stmt = sql_stmt.format(
                input1_databasename=input1_databasename,
                input2_databasename=input2_databasename,
            )

            # Determine columns/datatypes to create the table
            # Create temp table to get the column names + general data types
            # + fetch one row to use it to determine geometrytype.
            sql = f"""
                CREATE TEMPORARY TABLE tmp AS
                  SELECT *
                    FROM (
                      {sql_stmt}
                    )
                  LIMIT 1;
            """
            conn.execute(sql)
            sql = "PRAGMA TABLE_INFO(tmp)"
            cur = conn.execute(sql)
            tmpcolumns = cur.fetchall()

            # Fetch one row to try to get more detailed data types if needed
            sql = "SELECT * FROM tmp"
            tmpdata = conn.execute(sql).fetchone()
            if tmpdata is not None and len(tmpdata) == 0:
                tmpdata = None
            if not empty_output_ok and tmpdata is None:
                # If no row was returned, stop
                raise EmptyResultError(f"Query didn't return any rows: {sql_stmt}")

            # Loop over all columns to determine the data type
            column_types = {}
            for column_index, column in enumerate(tmpcolumns):
                columnname = column[1]
                columntype = column[2]

                if column_datatypes is not None and columnname in column_datatypes:
                    column_types[columnname] = column_datatypes[columnname]
                elif columnname == "geom":
                    # PRAGMA TABLE_INFO gives None as column type for a
                    # geometry column. So if output_geometrytype not specified,
                    # Use ST_GeometryType to get the type
                    # based on the data + apply to_multitype to be sure
                    if output_geometrytype is None:
                        sql = f"SELECT ST_GeometryType({columnname}) FROM tmp;"
                        result = conn.execute(sql).fetchall()
                        if len(result) > 0:
                            output_geometrytype = GeometryType[
                                result[0][0]
                            ].to_multitype
                        else:
                            output_geometrytype = GeometryType["GEOMETRY"]
                    column_types[columnname] = output_geometrytype.name
                else:
                    # If PRAGMA TABLE_INFO doesn't specify the datatype, determine based
                    # on data.
                    if columntype is None or columntype == "":
                        sql = f"SELECT typeof({columnname}) FROM tmp;"
                        result = conn.execute(sql).fetchall()
                        if len(result) > 0 and result[0][0] is not None:
                            column_types[columnname] = result[0][0]
                        else:
                            # If unknown, take the most general types
                            column_types[columnname] = "NUMERIC"
                    elif columntype == "NUM":
                        # PRAGMA TABLE_INFO sometimes returns 'NUM', but apparently this
                        # cannot be used in "CREATE TABLE".
                        if tmpdata is not None and isinstance(
                            tmpdata[column_index], datetime.date
                        ):
                            column_types[columnname] = "DATE"
                        elif tmpdata is not None and isinstance(
                            tmpdata[column_index], datetime.datetime
                        ):
                            column_types[columnname] = "DATETIME"
                        else:
                            sql = f'SELECT datetime("{columnname}") FROM tmp;'
                            result = conn.execute(sql).fetchall()
                            if len(result) > 0 and result[0][0] is not None:
                                column_types[columnname] = "DATETIME"
                            else:
                                column_types[columnname] = "NUMERIC"
                    else:
                        column_types[columnname] = columntype

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
            assert output_geometrytype is not None
            if output_suffix_lower == ".gpkg":
                # ~ mimic behaviour of gpkgAddGeometryColumn()
                sql = f"""
                    INSERT INTO {output_databasename}.gpkg_contents (
                        table_name, data_type, identifier, description, last_change,
                        min_x, min_y, max_x, max_y, srs_id)
                    VALUES ('{output_layer}', 'features', NULL, '', DATETIME(),
                        NULL, NULL, NULL, NULL, {to_string_for_sql(crs_epsg)});
                """
                conn.execute(sql)
                sql = f"""
                    INSERT INTO {output_databasename}.gpkg_geometry_columns (
                        table_name, column_name, geometry_type_name, srs_id, z, m)
                    VALUES ('{output_layer}', 'geom', '{output_geometrytype.name}',
                        {to_string_for_sql(crs_epsg)}, 0, 0);
                """
                conn.execute(sql)

                # Now add geom triggers
                # Remark: this only works on the main database!
                sql = f"SELECT gpkgAddGeometryTriggers('{output_layer}', 'geom');"
                conn.execute(sql)
            elif output_suffix_lower == ".sqlite":
                # Create metadata for the geometry column
                sql = f"""
                    SELECT RecoverGeometryColumn(
                        '{output_layer}', 'geom',
                        {to_string_for_sql(crs_epsg)}, '{output_geometrytype.name}');
                """
                conn.execute(sql)

            # Insert data using the sql statement specified
            try:
                columns_for_insert = [f'"{column[1]}"' for column in tmpcolumns]
                sql = (
                    f'INSERT INTO {output_databasename}."{output_layer}" '
                    f'({", ".join(columns_for_insert)})\n{sql_stmt}'
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

            # Create spatial index if needed
            if create_spatial_index is True:
                sql = f"SELECT UpdateLayerStatistics('{output_layer}', 'geom');"
                conn.execute(sql)
                if output_suffix_lower == ".gpkg":
                    # Create the necessary empty index, triggers,...
                    sql = f"SELECT gpkgAddSpatialIndex('{output_layer}', 'geom');"
                    conn.execute(sql)
                    # Now fill the index
                    sql = f"""
                        INSERT INTO "rtree_{output_layer}_geom"
                          SELECT fid
                                ,ST_MinX(geom)
                                ,ST_MaxX(geom)
                                ,ST_MinY(geom)
                                ,ST_MaxY(geom)
                            FROM "{output_layer}"
                           WHERE geom IS NOT NULL
                             AND NOT ST_IsEmpty(geom)
                    """
                    conn.execute(sql)
                elif output_suffix_lower == ".sqlite":
                    sql = f"SELECT CreateSpatialIndex('{output_layer}', 'geom');"
                    conn.execute(sql)
            conn.commit()

    except EmptyResultError:
        logger.info(f"Query didn't return any rows: {sql_stmt}")
        conn.close()
        conn = None
        if output_path.exists():
            output_path.unlink()
    except Exception as ex:
        raise Exception(f"Error {ex} executing {sql}") from ex
    finally:
        if conn is not None:
            conn.close()


def execute_sql(
    path: Path, sql_stmt: Union[str, List[str]], use_spatialite: bool = True
):
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
        conn.execute("PRAGMA journal_mode = WAL")
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
        raise Exception(f"Error executing {sql}") from ex
    finally:
        conn.close()


def test_data_integrity(path: Path, use_spatialite: bool = True):
    # Get list of layers in database
    layers = gfo.listlayers(path=path)

    # Connect to database file
    conn = sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
    sql = None

    try:
        if use_spatialite is True:
            load_spatialite(conn)
        if path.suffix.lower() == ".gpkg":
            sql = "SELECT EnableGpkgMode();"
            conn.execute(sql)

        # Set nb KB of cache
        sql = "PRAGMA cache_size=-50000;"
        conn.execute(sql)
        # Use memory mapped IO = much faster (max 30GB)
        conn.execute("PRAGMA mmap_size=30000000000;")

        # Loop over all layers to check if all data is readable
        for layer in layers:
            sql = f'SELECT * FROM "{layer}"'
            cursor = conn.execute(sql)

            # Fetch the data in chunks to evade excessive memory usage
            while True:
                result = cursor.fetchmany(10000)
                if not result:
                    # All data was fetched from layer
                    break

    except Exception as ex:
        raise Exception(f"Error executing {sql}") from ex
    finally:
        conn.close()


def load_spatialite(conn):
    """
    Load mod_spatialite for an existing sqlite connection.

    Args:
        conn ([type]): Sqlite connection
    """
    conn.enable_load_extension(True)
    try:
        conn.load_extension("mod_spatialite")
    except Exception as ex:
        raise MissingRuntimeDependencyError(
            "Error trying to load mod_spatialite."
        ) from ex
