# -*- coding: utf-8 -*-
"""
Module containing utilities regarding sqlite/spatialite files.
"""

import datetime
import enum
import logging
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Dict, List, Optional, Union

import pygeoops
import shapely
from shapely.geometry.base import BaseMultipartGeometry

import geofileops as gfo
from geofileops import GeometryType
from geofileops.util._general_util import MissingRuntimeDependencyError

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
    empty_output_ok: bool = True,
    use_spatialite: bool = True,
    output_geometrytype: Optional[GeometryType] = None,
) -> Dict[str, str]:
    # Create temp output db to be sure the output DB is writable, even though we only
    # create a temporary table.
    tmp_dir = Path(tempfile.mkdtemp(prefix="geofileops/get_columns_"))
    tmp_path = tmp_dir / f"temp{input1_path.suffix}"
    create_new_spatialdb(path=tmp_path)

    sql = None
    conn = sqlite3.connect(tmp_path, detect_types=sqlite3.PARSE_DECLTYPES)
    try:
        # Load spatialite if asked for
        if use_spatialite:
            load_spatialite(conn)
            if tmp_path.suffix.lower() == ".gpkg":
                sql = "SELECT EnableGpkgMode();"
                conn.execute(sql)

        # Attach to input1
        input1_databasename = "input1"
        sql = f"ATTACH DATABASE ? AS {input1_databasename}"
        dbSpec = (str(input1_path),)
        conn.execute(sql, dbSpec)

        # If input2 isn't the same database input1, attach to it
        input2_databasename = None
        if input2_path is not None:
            if input2_path == input1_path:
                input2_databasename = input1_databasename
            else:
                input2_databasename = "input2"
                sql = f"ATTACH DATABASE ? AS {input2_databasename}"
                dbSpec = (str(input2_path),)
                conn.execute(sql, dbSpec)

        # Prepare sql statement for execute
        sql = sql_stmt.format(
            input1_databasename=input1_databasename,
            input2_databasename=input2_databasename,
            batch_filter="",
        )

        # Create temp table to get the column names + general data types
        # + fetch one row to use it to determine geometrytype.
        # Remark: specify redundant OFFSET 0 to keep sqlite from flattings the subquery.
        sql = f"""
            CREATE TEMPORARY TABLE tmp AS
            SELECT *
                FROM (
                {sql}
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
                    sql = f"SELECT ST_GeometryType({columnname}) FROM tmp;"
                    result = conn.execute(sql).fetchall()
                    if len(result) > 0 and result[0][0] is not None:
                        output_geometrytype = GeometryType[result[0][0]].to_multitype
                    else:
                        output_geometrytype = GeometryType["GEOMETRY"]
                columns[columnname] = output_geometrytype.name
            else:
                # If PRAGMA TABLE_INFO doesn't specify the datatype, determine based
                # on data.
                if columntype is None or columntype == "":
                    sql = f"SELECT typeof({columnname}) FROM tmp;"
                    result = conn.execute(sql).fetchall()
                    if len(result) > 0 and result[0][0] is not None:
                        columns[columnname] = result[0][0]
                    else:
                        # If unknown, take the most general types
                        columns[columnname] = "NUMERIC"
                elif columntype == "NUM":
                    # PRAGMA TABLE_INFO sometimes returns 'NUM', but apparently this
                    # cannot be used in "CREATE TABLE".
                    if tmpdata is not None and isinstance(
                        tmpdata[column_index], datetime.date
                    ):
                        columns[columnname] = "DATE"
                    elif tmpdata is not None and isinstance(
                        tmpdata[column_index], datetime.datetime
                    ):
                        columns[columnname] = "DATETIME"
                    else:
                        sql = f'SELECT datetime("{columnname}") FROM tmp;'
                        result = conn.execute(sql).fetchall()
                        if len(result) > 0 and result[0][0] is not None:
                            columns[columnname] = "DATETIME"
                        else:
                            columns[columnname] = "NUMERIC"
                else:
                    columns[columnname] = columntype

    except Exception as ex:
        conn.rollback()
        raise RuntimeError(f"Error {ex} executing {sql}") from ex
    finally:
        conn.close()
        shutil.rmtree(tmp_dir, ignore_errors=True)

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
    conn = sqlite3.connect(output_path, detect_types=sqlite3.PARSE_DECLTYPES, uri=True)
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
            # input1_uri = f"file:{input1_path}?immutable=1"
            # dbSpec = (str(input1_uri),)
            conn.execute(sql, dbSpec)

            # If input2 isn't the same database input1, attach to it
            input2_databasename = None
            if input2_path is not None:
                if input2_path == input1_path:
                    input2_databasename = input1_databasename
                else:
                    input2_databasename = "input2"
                    sql = f"ATTACH DATABASE ? AS {input2_databasename}"
                    dbSpec = (str(input2_path),)
                    # input2_uri = f"file:{input1_path}?immutable=1"
                    # dbSpec = (str(input2_uri),)
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

            # Determine columns/datatypes to create the table if not specified
            column_types = column_datatypes
            if column_types is None:
                column_types = get_columns(
                    sql_stmt=sql_stmt,
                    input1_path=input1_path,
                    input2_path=input2_path,
                    empty_output_ok=empty_output_ok,
                    use_spatialite=True,
                    output_geometrytype=output_geometrytype,
                )

            # If geometry type was not specified, look for it in column_types
            if output_geometrytype is None:
                if "geom" in column_types:
                    output_geometrytype = GeometryType(column_types["geom"])
                else:
                    raise ValueError(
                        "output_geometrytype not specified + determination from "
                        "sql_stmt failed"
                    )

            # Prepare sql statement
            sql_stmt = sql_stmt.format(
                input1_databasename=input1_databasename,
                input2_databasename=input2_databasename,
            )

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
                columns_for_insert = [f'"{column}"' for column in column_types]
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
        if output_path.exists():
            output_path.unlink()
    except Exception as ex:
        raise RuntimeError(f"Error {ex} executing {sql}") from ex
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

    # Register custom function
    conn.create_function(
        "st_difference_collection", 3, st_difference_collection, deterministic=True
    )

    # Register custom aggregate function
    # conn.create_aggregate("st_difference_agg", 2, DifferenceAgg)


def st_difference_collection(geom1: bytes, geom2: bytes, keep_geom_type: int = 0):
    # Check/prepare input
    if geom1 is None:
        return None
    if geom2 is None:
        return geom1

    geom = shapely.from_wkb(geom1)
    geoms_to_subtract = shapely.from_wkb(geom2)
    keep_geom_type = False if keep_geom_type == 0 else True

    try:
        if not isinstance(geoms_to_subtract, BaseMultipartGeometry):
            result = pygeoops.difference_all_tiled(
                geom, geoms_to_subtract, keep_geom_type=keep_geom_type
            )
        else:
            result = pygeoops.difference_all_tiled(
                geom,
                shapely.get_parts(geoms_to_subtract),
                keep_geom_type=keep_geom_type,
            )

        # If an empty result, return None
        if result is None or result.is_empty:
            return None

        return shapely.to_wkb(result)
    except Exception as ex:
        # ex.with_traceback()
        print(ex)


"""
class DifferenceAgg:
    def __init__(self):
        self.init_todo = True
        self.tmpdiff = None
        self.is_split = False
        self.geom_mbrp = None
        self.geom_dimension = None
        self.num_coords_max = 5000

    def step(self, geom, geoms_to_subtract):
        try:
            # Init on first call
            if self.init_todo:
                self.init_todo = True
                if geom is None:
                    self.tmpdiff = shapely.Geometry()
                geom = shapely.from_wkb(geom)
                self.geom_mbrp = shapely.box(*geom.bounds)
                self.geom_dimension = shapely.get_dimensions(geom)
                self.tmpdiff, self.is_split = difference._split_if_needed(
                    geom, self.num_coords_max
                )
            elif shapely.is_empty(self.tmpdiff).all():
                return

            # Apply difference
            geom_to_subtract = shapely.from_wkb(geoms_to_subtract)
            self.tmpdiff = difference._difference_intersecting(
                self.tmpdiff, geom_to_subtract, output_dimensions=self.geom_dimension
            )
            self.tmpdiff = self.tmpdiff[~shapely.is_empty(self.tmpdiff)]

        except Exception as ex:
            # ex.with_traceback()
            print(ex)

    def finalize(self):
        try:
            if self.tmpdiff is None or shapely.is_empty(self.tmpdiff).all():
                return None
            elif self.is_split:
                return shapely.to_wkb(shapely.unary_union(self.tmpdiff))
            else:
                return shapely.to_wkb(self.tmpdiff[0])
        except Exception as ex:
            raise ex
"""
