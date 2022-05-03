# -*- coding: utf-8 -*-
"""
Module with helper functions for geo files.
"""

import enum
import datetime
import filecmp
import logging
import os
from pathlib import Path
import pprint
import shutil
import tempfile
import time
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union
import warnings

import fiona
import geopandas as gpd
from osgeo import gdal
import pandas as pd
import pyproj

from geofileops.util import geometry_util
from geofileops.util.geometry_util import GeometryType, PrimitiveType
from geofileops.util import geoseries_util
from geofileops.util import _io_util
from geofileops.util import _ogr_util
from geofileops.util.geofiletype import GeofileType

#####################################################################
# First define/init some general variables/constants
#####################################################################

# Get a logger...
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

# Enable exceptions for GDAL
gdal.UseExceptions()

# Disable this annoying warning in fiona
warnings.filterwarnings(
    action="ignore",
    category=RuntimeWarning,
    message="Sequential read of iterator was interrupted. Resetting iterator. "
    "This can negatively impact the performance.",
)

# Hardcoded prj string to replace faulty ones
PRJ_EPSG_31370 = (
    'PROJCS["Belge_1972_Belgian_Lambert_72",GEOGCS["Belge 1972",'
    'DATUM["D_Belge_1972",SPHEROID["International_1924",6378388,297]],'
    'PRIMEM["Greenwich",0],UNIT["Degree",0.017453292519943295]],'
    'PROJECTION["Lambert_Conformal_Conic"],'
    'PARAMETER["standard_parallel_1",51.16666723333333],'
    'PARAMETER["standard_parallel_2",49.8333339],'
    'PARAMETER["latitude_of_origin",90],'
    'PARAMETER["central_meridian",4.367486666666666],'
    'PARAMETER["false_easting",150000.013],'
    'PARAMETER["false_northing",5400088.438],('
    'UNIT["Meter",1],AUTHORITY["EPSG",31370]]'
)

#####################################################################
# The real work
#####################################################################


def listlayers(
    path: Union[str, "os.PathLike[Any]"], verbose: bool = False
) -> List[str]:
    """
    Get the list of layers in a geofile.

    Args:
        path (PathLike): path to the file to get info about
        verbose (bool, optional): True to enable verbose logging. Defaults to False.

    Returns:
        List[str]: the list of layers
    """
    return fiona.listlayers(str(path))


class ColumnInfo:
    """
    A data object containing meta-information about a column.

    Attributes:
        name (str): the name of the column.
        gdal_type (str): the type of the column according to gdal.
        width (int): the width of the column, if specified.
    """

    def __init__(
        self,
        name: str,
        gdal_type: str,
        width: int,
        precision: int,
    ):
        self.name = name
        self.gdal_type = gdal_type
        self.width = width
        self.precision = precision

    def __repr__(self):
        return f"{self.__class__}({self.__dict__})"


class LayerInfo:
    """
    A data object containing meta-information about a layer.

    Attributes:
        name (str): the name of the layer.
        featurecount (int): the number of features (rows) in the layer.
        total_bounds (Tuple[float, float, float, float]): the bounding box of
            the layer.
        geometrycolumn (str): name of the column that contains the
            primary geometry.
        geometrytypename (str): the geometry type name of the geometrycolumn.
            The type name returned is one of the following: POINT, MULTIPOINT,
            LINESTRING, MULTILINESTRING, POLYGON, MULTIPOLYGON, COLLECTION.
        geometrytype (GeometryType): the geometry type of the geometrycolumn.
        columns (dict): the columns (other than the geometry column) that
            are available on the layer with their properties as a dict.
        crs (pyproj.CRS): the spatial reference of the layer.
        errors (List[str]): list of errors in the layer, eg. invalid column
            names,...
    """

    def __init__(
        self,
        name: str,
        featurecount: int,
        total_bounds: Tuple[float, float, float, float],
        geometrycolumn: str,
        geometrytypename: str,
        geometrytype: GeometryType,
        columns: Dict[str, ColumnInfo],
        crs: Optional[pyproj.CRS],
        errors: List[str],
    ):
        self.name = name
        self.featurecount = featurecount
        self.total_bounds = total_bounds
        self.geometrycolumn = geometrycolumn
        self.geometrytypename = geometrytypename
        self.geometrytype = geometrytype
        self.columns = columns
        self.crs = crs
        self.errors = errors

    def __repr__(self):
        return f"{self.__class__}({self.__dict__})"


def get_layerinfo(
    path: Union[str, "os.PathLike[Any]"], layer: Optional[str] = None
) -> LayerInfo:
    """
    Get information about a layer in the geofile.

    Raises an exception if the layer definition has errors like invalid column
    names,...

    Args:
        path (PathLike): path to the file to get info about
        layer (str): the layer you want info about. Doesn't need to be
            specified if there is only one layer in the geofile.

    Returns:
        LayerInfo: the information about the layer.
    """
    # Init
    path = Path(path)
    if not path.exists():
        raise ValueError(f"File does not exist: {path}")

    datasource = None
    try:
        datasource = gdal.OpenEx(str(path))
        if layer is not None:
            datasource_layer = datasource.GetLayer(layer)
        elif datasource.GetLayerCount() == 1:
            datasource_layer = datasource.GetLayerByIndex(0)
        else:
            raise ValueError(f"No layer specified, and file has <> 1 layer: {path}")

        # If the layer doesn't exist, return
        if datasource_layer is None:
            raise ValueError(f"Layer {layer} not found in file: {path}")

        # Get column info
        columns = {}
        errors = []
        geofiletype = GeofileType(path)
        layer_defn = datasource_layer.GetLayerDefn()
        for i in range(layer_defn.GetFieldCount()):
            name = layer_defn.GetFieldDefn(i).GetName()
            # TODO: think whether the type name should be converted to other names
            gdal_type = layer_defn.GetFieldDefn(i).GetTypeName()
            width = layer_defn.GetFieldDefn(i).GetWidth()
            width = width if width > 0 else None
            precision = layer_defn.GetFieldDefn(i).GetPrecision()
            precision = precision if precision > 0 else None
            illegal_column_chars = ['"']
            for illegal_char in illegal_column_chars:
                if illegal_char in name:
                    errors.append(
                        f"Column name {name} contains illegal char: {illegal_char} "
                        f"in file {path}, layer {layer}"
                    )
            column_info = ColumnInfo(
                name=name, gdal_type=gdal_type, width=width, precision=precision
            )
            columns[name] = column_info
            if geofiletype == GeofileType.ESRIShapefile:
                if name.casefold() == "geometry":
                    errors.append(
                        "An attribute column 'geometry' is not supported in a shapefile"
                    )

        # Get geometry column info...
        geometrytypename = gdal.ogr.GeometryTypeToName(datasource_layer.GetGeomType())
        geometrytypename = geometrytypename.replace(" ", "").upper()

        # For shape files, the difference between the 'MULTI' variant and the
        # single one doesn't exists... so always report MULTI variant by convention.
        if GeofileType(path) == GeofileType.ESRIShapefile:
            if (
                geometrytypename.startswith("POLYGON")
                or geometrytypename.startswith("LINESTRING")
                or geometrytypename.startswith("POINT")
            ):
                geometrytypename = f"MULTI{geometrytypename}"
        if geometrytypename == "UNKNOWN(ANY)":
            geometrytypename = "GEOMETRY"

        # Geometrytype
        if geometrytypename != "NONE":
            geometrytype = GeometryType[geometrytypename]
        else:
            geometrytype = None

        # If the geometry type is not None, fill out the extra properties
        geometrycolumn = None
        extent = None
        crs = None
        total_bounds = None
        if geometrytype is not None:
            # Geometry column name
            geometrycolumn = datasource_layer.GetGeometryColumn()
            if geometrycolumn == "":
                geometrycolumn = "geometry"
            # Convert extent (xmin, xmax, ymin, ymax) to bounds (xmin, ymin, xmax, ymax)
            extent = datasource_layer.GetExtent()
            total_bounds = (extent[0], extent[2], extent[1], extent[3])
            # CRS
            spatialref = datasource_layer.GetSpatialRef()
            if spatialref is not None:
                crs = pyproj.CRS(spatialref.ExportToWkt())

                # If spatial ref has no epsg, try to find corresponding one
                crs_epsg = crs.to_epsg()
                if crs_epsg is None:
                    if crs.name in [
                        "Belge 1972 / Belgian Lambert 72",
                        "Belge_1972_Belgian_Lambert_72",
                        "Belge_Lambert_1972",
                        "BD72 / Belgian Lambert 72",
                    ]:
                        # Belgian Lambert in name, so assume 31370
                        crs = pyproj.CRS.from_epsg(31370)

                        # If shapefile, add correct 31370 .prj file
                        if GeofileType(path) == GeofileType.ESRIShapefile:
                            prj_path = path.parent / f"{path.stem}.prj"
                            if prj_path.exists():
                                prj_rename_path = path.parent / f"{path.stem}_orig.prj"
                                if not prj_rename_path.exists():
                                    prj_path.rename(prj_rename_path)
                                else:
                                    prj_path.unlink()
                                prj_path.write_text(PRJ_EPSG_31370)

            return LayerInfo(
                name=datasource_layer.GetName(),
                featurecount=datasource_layer.GetFeatureCount(),
                total_bounds=total_bounds,
                geometrycolumn=geometrycolumn,
                geometrytypename=geometrytypename,
                geometrytype=geometrytype,
                columns=columns,
                crs=crs,
                errors=errors,
            )
        else:
            errors.append("Layer doesn't have a geometry column!")

    finally:
        if datasource is not None:
            del datasource

    # If we didn't return or raise yet here, there must have been errors
    errors_str = pprint.pformat(errors)
    raise Exception(
        f"Errors in layer definition of file {path}, layer {layer}: \n{errors_str}"
    )


def get_only_layer(path: Union[str, "os.PathLike[Any]"]) -> str:
    """
    Get the layername for a file that only contains one layer.

    If the file contains multiple layers, an exception is thrown.

    Args:
        path (PathLike): the file.

    Raises:
        ValueError: an invalid parameter value was passed.

    Returns:
        str: the layer name
    """
    layers = fiona.listlayers(str(path))
    nb_layers = len(layers)
    if nb_layers == 1:
        return layers[0]
    elif nb_layers == 0:
        raise ValueError(f"Error: No layers found in {path}")
    else:
        raise ValueError(f"Error: More than 1 layer found in {path}: {layers}")


def get_default_layer(path: Union[str, "os.PathLike[Any]"]) -> str:
    """
    Get the default layer name to be used for a layer in this file.

    This is the stem of the filepath.

    Args:
        path (Union[str,): The path to the file.

    Returns:
        str: The default layer name.
    """
    return Path(path).stem


def execute_sql(
    path: Union[str, "os.PathLike[Any]"],
    sql_stmt: str,
    sql_dialect: Optional[str] = None,
):
    """
    Execute a sql statement (DML or DDL) on the file. Is equivalent to running
    ogrinfo on a file with the -sql parameter.
    More info here: https://gdal.org/programs/ogrinfo.html

    To run SELECT statements on a file, use read_file_sql().

    Args:
        path (PathLike): The path to the file.
        sql_stmt (str): The sql statement to execute.
        sql_dialect (str): The sql dialect to use:
            * None: use the native SQL dialect of the geofile.
            * 'OGRSQL': force the use of the OGR SQL dialect.
            * 'SQLITE': force the use of the SQLITE dialect.
            Defaults to None.
    """
    datasource = None
    try:
        datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)
        result = datasource.ExecuteSQL(sql_stmt, dialect=sql_dialect)
        datasource.ReleaseResultSet(result)
    finally:
        if datasource is not None:
            del datasource


def create_spatial_index(
    path: Union[str, "os.PathLike[Any]"],
    layer: Optional[str] = None,
    cache_size_mb: int = 128,
    exist_ok: bool = False,
    force_rebuild: bool = False,
):
    """
    Create a spatial index on the layer specified.

    Args:
        path (PathLike): The file path.
        layer (str, optional): The layer. If not specified, and there is only
            one layer in the file, this layer is used. Otherwise exception.
        cache_size_mb (int, optional): memory in MB that can be used while
            creating spatial index for spatialite files (.gpkg or .sqlite).
            Defaults to 512.
        exist_ok (bool, options): If True and the index exists already, don't
            throw an error.
        force_rebuild (bool, options): True to force rebuild even if index
            exists already. Defaults to False.
    """
    # Init
    path = Path(path)
    if layer is None:
        layer = get_only_layer(path)

    # If index already exists, remove index or return
    if has_spatial_index(path, layer) is True:
        if force_rebuild is True:
            remove_spatial_index(path, layer)
        elif exist_ok is True:
            return
        else:
            raise Exception(
                f"Error adding spatial index to {path}.{layer}, it exists already"
            )

    # Now really add index
    datasource = None
    try:
        geofiletype = GeofileType(path)
        if geofiletype.is_spatialite_based:
            # The config options need to be set before opening the file!
            geometrycolumn = get_layerinfo(path, layer).geometrycolumn
            with _ogr_util.set_config_options({"OGR_SQLITE_CACHE": cache_size_mb}):
                datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)
                sql = f"SELECT CreateSpatialIndex('{layer}', '{geometrycolumn}')"
                result = datasource.ExecuteSQL(sql, dialect="SQLITE")
                datasource.ReleaseResultSet(result)
        else:
            datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)
            result = datasource.ExecuteSQL(f'CREATE SPATIAL INDEX ON "{layer}"')
            datasource.ReleaseResultSet(result)
    except Exception as ex:
        raise Exception(f"Error adding spatial index to {path}.{layer}") from ex
    finally:
        if datasource is not None:
            del datasource


def has_spatial_index(
    path: Union[str, "os.PathLike[Any]"], layer: Optional[str] = None
) -> bool:
    """
    Check if the layer/column has a spatial index.

    Args:
        path (PathLike): The file path.
        layer (str, optional): The layer. Defaults to None.

    Raises:
        ValueError: an invalid parameter value was passed.

    Returns:
        bool: True if the spatial column exists.
    """
    # Init
    path = Path(path)

    # Now check the index
    datasource = None
    geofiletype = GeofileType(path)
    try:
        if geofiletype.is_spatialite_based:
            layerinfo = get_layerinfo(path, layer)
            datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_READONLY)
            sql = f"""
                SELECT HasSpatialIndex('{layerinfo.name}',
                                       '{layerinfo.geometrycolumn}')
            """
            result = datasource.ExecuteSQL(sql, dialect="SQLITE")
            has_spatial_index = result.GetNextFeature().GetField(0) == 1
            datasource.ReleaseResultSet(result)
            return has_spatial_index
        elif geofiletype == GeofileType.ESRIShapefile:
            index_path = path.parent / f"{path.stem}.qix"
            return index_path.exists()
        else:
            raise ValueError(f"has_spatial_index not supported for {path}")
    finally:
        if datasource is not None:
            del datasource


def remove_spatial_index(
    path: Union[str, "os.PathLike[Any]"], layer: Optional[str] = None
):
    """
    Remove the spatial index from the layer specified.

    Args:
        path (PathLike): The file path.
        layer (str, optional): The layer. If not specified, and there is only
            one layer in the file, this layer is used. Otherwise exception.
    """
    # Init
    path = Path(path)

    # Now really remove index
    datasource = None
    geofiletype = GeofileType(path)
    layerinfo = get_layerinfo(path, layer)
    try:
        if geofiletype.is_spatialite_based:
            datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)
            result = datasource.ExecuteSQL(
                f"SELECT DisableSpatialIndex('{layerinfo.name}', '{layerinfo.geometrycolumn}')",  # noqa: E501
                dialect="SQLITE",
            )
            datasource.ReleaseResultSet(result)
        elif geofiletype == GeofileType.ESRIShapefile:
            # DROP SPATIAL INDEX ON ... command gives an error, so just remove .qix
            index_path = path.parent / f"{path.stem}.qix"
            index_path.unlink()
        else:
            raise Exception(
                f"remove_spatial_index is not supported for {path.suffix} file"
            )
    finally:
        if datasource is not None:
            del datasource


def rename_layer(
    path: Union[str, "os.PathLike[Any]"], new_layer: str, layer: Optional[str] = None
):
    """
    Rename the layer specified.

    Args:
        path (PathLike): The file path.
        layer (Optional[str]): The layer name. If not specified, and there is only
            one layer in the file, this layer is used. Otherwise exception.
        new_layer (str): The new layer name. If not specified, and there is only
            one layer in the file, this layer is used. Otherwise exception.
    """
    # Check input parameters
    path = Path(path)
    if layer is None:
        layer = get_only_layer(path)

    # Now really rename
    datasource = None
    geofiletype = GeofileType(path)
    try:
        if geofiletype.is_spatialite_based:
            datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)
            sql_stmt = f'ALTER TABLE "{layer}" RENAME TO "{new_layer}"'
            result = datasource.ExecuteSQL(sql_stmt)
            datasource.ReleaseResultSet(result)
        elif geofiletype == GeofileType.ESRIShapefile:
            raise ValueError(f"rename_layer is not possible for {geofiletype} file")
        else:
            raise ValueError(f"rename_layer is not implemented for {path.suffix} file")
    finally:
        if datasource is not None:
            del datasource


def rename_column(
    path: Union[str, "os.PathLike[Any]"],
    column_name: str,
    new_column_name: str,
    layer: Optional[str] = None,
):
    """
    Rename the column specified.

    Args:
        path (PathLike): The file path.
        column_name (str): the current column name.
        new_column_name (str): the new column name.
        layer (Optional[str]): The layer name. If not specified, and there is only
            one layer in the file, this layer is used. Otherwise exception.
    """
    # Check input parameters
    path = Path(path)
    if layer is None:
        layer = get_only_layer(path)
    info = get_layerinfo(path)
    if column_name not in info.columns and new_column_name in info.columns:
        logger.info(
            f"Column {column_name} seems to be renamed already to {new_column_name}"
        )
        return

    # Now really rename
    datasource = None
    geofiletype = GeofileType(path)
    try:
        if geofiletype.is_spatialite_based:
            datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)
            sql_stmt = (
                f'ALTER TABLE "{layer}" '
                f'RENAME COLUMN "{column_name}" TO "{new_column_name}"'
            )
            result = datasource.ExecuteSQL(sql_stmt)
            datasource.ReleaseResultSet(result)
        elif geofiletype == GeofileType.ESRIShapefile:
            raise ValueError(f"rename_column is not possible for {geofiletype} file")
        else:
            raise ValueError(f"rename_column is not implemented for {path.suffix} file")
    finally:
        if datasource is not None:
            del datasource


class DataType(enum.Enum):
    """
    This enum defines the standard data types that can be used for columns.
    """

    TEXT = "TEXT"
    """Column with text data: ~ string, char, varchar, clob."""
    INTEGER = "INTEGER"
    """Column with integer data."""
    REAL = "REAL"
    """Column with floating point data: ~ float, double."""
    DATE = "DATE"
    """Column with date data."""
    TIMESTAMP = "TIMESTAMP"
    """Column with timestamp data: ~ datetime."""
    BOOLEAN = "BOOLEAN"
    """Column with boolean data."""
    BLOB = "BLOB"
    """Column with binary data."""
    NUMERIC = "NUMERIC"
    """Column with numeric data: exact decimal data."""


def add_column(
    path: Union[str, "os.PathLike[Any]"],
    name: str,
    type: Union[DataType, str],
    expression: Union[str, int, float, None] = None,
    expression_dialect: Optional[str] = None,
    layer: Optional[str] = None,
    force_update: bool = False,
    width: Optional[int] = None,
):
    """
    Add a column to a layer of the geofile.

    Args:
        path (PathLike): Path to the geofile.
        name (str): Name for the new column.
        type (str): Column type of the new column.
        expression (str, optional): SQLite expression to use to update
            the value. Defaults to None.
        expression_dialect (str, optional): SQL dialect used for the expression.
        layer (str, optional): The layer name. If None and the geofile
            has only one layer, that layer is used. Defaults to None.
        force_update (bool, optional): If the column already exists, execute
            the update anyway. Defaults to False.
        width (int, optional): the width of the field.

    Raises:
        ex: [description]
    """
    # Init
    if isinstance(type, DataType):
        type_str = type.value
    else:
        type_lower = type.lower()
        if type_lower == "string":
            # TODO: think whether being flexible here is a good idea...
            type_str = "TEXT"
        elif type_lower == "binary":
            type_str = "BLOB"
        elif type_lower == "time":
            type_str = "DATETIME"
        else:
            type_str = type
    path = Path(path)
    if layer is None:
        layer = get_only_layer(path)
    layerinfo_orig = get_layerinfo(path, layer)

    # Go!
    datasource = None
    try:
        # If column doesn't exist yet, create it
        columns_upper = [column.upper() for column in layerinfo_orig.columns]
        if name.upper() not in columns_upper:
            width_str = f"({width})" if width is not None else ""
            sql_stmt = (
                f'ALTER TABLE "{layer}" ADD COLUMN "{name}" {type_str}{width_str}'
            )
            datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)
            result = datasource.ExecuteSQL(sql_stmt)
            datasource.ReleaseResultSet(result)
        else:
            logger.warning(f"Column {name} existed already in {path}, layer {layer}")

        # If an expression was provided and update can be done, go for it...
        if expression is not None and (
            name not in layerinfo_orig.columns or force_update is True
        ):
            if datasource is None:
                datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)
            sql_stmt = f'UPDATE "{layer}" SET "{name}" = {expression}'
            result = datasource.ExecuteSQL(sql_stmt, dialect=expression_dialect)
            datasource.ReleaseResultSet(result)
    finally:
        if datasource is not None:
            del datasource


def drop_column(
    path: Union[str, "os.PathLike[Any]"], column_name: str, layer: Optional[str] = None
):
    """
    Drop the column specified.

    Args:
        path (PathLike): The file path.
        column_name (str): the column name.
        layer (Optional[str]): The layer name. If not specified, and there is only
            one layer in the file, this layer is used. Otherwise exception.
    """
    # Check input parameters
    path = Path(path)
    if layer is None:
        layer = get_only_layer(path)
    info = get_layerinfo(path, layer)
    if column_name not in info.columns:
        logger.info(
            f"Column {column_name} not present so cannot be dropped, so just return"
        )
        return

    # Now really rename
    datasource = None
    try:
        datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)
        sql_stmt = f'ALTER TABLE "{layer}" DROP COLUMN "{column_name}"'
        result = datasource.ExecuteSQL(sql_stmt)
        datasource.ReleaseResultSet(result)
    finally:
        if datasource is not None:
            del datasource


def update_column(
    path: Union[str, "os.PathLike[Any]"],
    name: str,
    expression: str,
    layer: Optional[str] = None,
    where: Optional[str] = None,
):
    """
    Update a column from a layer of the geofile.

    Args:
        path (PathLike): Path to the geofile
        name (str): Name for the new column
        expression (str): SQLite expression to use to update
            the value.
        layer (str, optional): The layer name. If None and the geofile
            has only one layer, that layer is used. Defaults to None.
        layer (str, optional): SQL where clause to restrict the rows that will
            be updated. Defaults to None.

    Raises:
        ValueError: an invalid parameter value was passed.
    """

    # Init
    path = Path(path)
    if layer is None:
        layer = get_only_layer(path)
    layerinfo_orig = get_layerinfo(path, layer)
    columns_upper = [column.upper() for column in layerinfo_orig.columns]
    if name.upper() not in columns_upper:
        # If column doesn't exist yet, error!
        raise ValueError(f"Column {name} doesn't exist in {path}, layer {layer}")

    # Go!
    datasource = None
    try:
        datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)
        sqlite_stmt = f'UPDATE "{layer}" SET "{name}" = {expression}'
        if where is not None:
            sqlite_stmt += f"\n WHERE {where}"
        result = datasource.ExecuteSQL(sqlite_stmt, dialect="SQLITE")
        datasource.ReleaseResultSet(result)
    finally:
        if datasource is not None:
            del datasource


def read_file(
    path: Union[str, "os.PathLike[Any]"],
    layer: Optional[str] = None,
    columns: Optional[Iterable[str]] = None,
    bbox=None,
    rows=None,
    ignore_geometry: bool = False,
) -> gpd.GeoDataFrame:
    """
    Reads a file to a geopandas GeoDataframe.

    The file format is detected based on the filepath extension.

    Args:
        path (file path): path to the file to read from
        layer (str, optional): The layer to read. Defaults to None,
            then reads the only layer in the file or throws error.
        columns (Iterable[str], optional): The (non-geometry) columns to read.
            Defaults to None, then all columns are read.
        bbox ([type], optional): Read only geometries intersecting this bbox.
            Defaults to None, then all rows are read.
        rows ([type], optional): Read only the rows specified.
            Defaults to None, then all rows are read.
        ignore_geometry (bool, optional): True not to read/return the geometry.
            Is retained for backwards compatibility, but it is recommended to
            use read_file_nogeom for improved type checking. Defaults to False.

    Raises:
        ValueError: an invalid parameter value was passed.

    Returns:
        gpd.GeoDataFrame: the data read.
    """
    result_gdf = _read_file_base(
        path=path,
        layer=layer,
        columns=columns,
        bbox=bbox,
        rows=rows,
        ignore_geometry=ignore_geometry,
    )

    # No assert to keep backwards compatibility
    return result_gdf  # type: ignore


def read_file_nogeom(
    path: Union[str, "os.PathLike[Any]"],
    layer: Optional[str] = None,
    columns: Optional[Iterable[str]] = None,
    bbox=None,
    rows=None,
) -> pd.DataFrame:
    """
    Reads a file to a pandas Dataframe.

    The file format is detected based on the filepath extension.

    Args:
        path (file path): path to the file to read from
        layer (str, optional): The layer to read. Defaults to None,
            then reads the only layer in the file or throws error.
        columns (Iterable[str], optional): The (non-geometry) columns to read.
            Defaults to None, then all columns are read.
        bbox ([type], optional): Read only geometries intersecting this bbox.
            Defaults to None, then all rows are read.
        rows ([type], optional): Read only the rows specified.
            Defaults to None, then all rows are read.
        ignore_geometry (bool, optional): True not to read/return the geomatry.
            Defaults to False.

    Raises:
        ValueError: an invalid parameter value was passed.

    Returns:
        pd.DataFrame: the data read.
    """
    result_gdf = _read_file_base(
        path=path,
        layer=layer,
        columns=columns,
        bbox=bbox,
        rows=rows,
        ignore_geometry=True,
    )
    assert isinstance(result_gdf, pd.DataFrame)
    return result_gdf


def _read_file_base(
    path: Union[str, "os.PathLike[Any]"],
    layer: Optional[str] = None,
    columns: Optional[Iterable[str]] = None,
    bbox=None,
    rows=None,
    ignore_geometry: bool = False,
) -> Union[pd.DataFrame, gpd.GeoDataFrame]:
    """
    Reads a file to a pandas Dataframe.

    The file format is detected based on the filepath extension.

    Args:
        path (file path): path to the file to read from
        layer (str, optional): The layer to read. Defaults to None,
            then reads the only layer in the file or throws error.
        columns (Iterable[str], optional): The (non-geometry) columns to read.
            Defaults to None, then all columns are read.
        bbox ([type], optional): Read only geometries intersecting this bbox.
            Defaults to None, then all rows are read.
        rows ([type], optional): Read only the rows specified.
            Defaults to None, then all rows are read.
        ignore_geometry (bool, optional): True not to read/return the geomatry.
            Defaults to False.

    Raises:
        ValueError: an invalid parameter value was passed.

    Returns:
        Union[pd.DataFrame, gpd.GeoDataFrame]: the data read.
    """
    # Init
    path = Path(path)
    if path.exists() is False:
        raise ValueError(f"File doesnt't exist: {path}")
    geofiletype = GeofileType(path)

    # If no layer name specified, check if there is only one layer in the file.
    if layer is None:
        layer = get_only_layer(path)

    # Depending on the extension... different implementations
    if geofiletype == GeofileType.ESRIShapefile:
        result_gdf = gpd.read_file(
            str(path), bbox=bbox, rows=rows, ignore_geometry=ignore_geometry
        )
    elif geofiletype == GeofileType.GeoJSON:
        result_gdf = gpd.read_file(
            str(path), bbox=bbox, rows=rows, ignore_geometry=ignore_geometry
        )
    elif geofiletype.is_spatialite_based:
        result_gdf = gpd.read_file(
            str(path),
            layer=layer,
            bbox=bbox,
            rows=rows,
            ignore_geometry=ignore_geometry,
        )
    else:
        raise ValueError(f"Not implemented for geofiletype {geofiletype}")

    # If columns to read are specified... filter non-geometry columns
    # case-insensitive
    if columns is not None:
        columns_upper = [column.upper() for column in columns]
        columns_upper.append("GEOMETRY")
        columns_to_keep = [
            col for col in result_gdf.columns if (col.upper() in columns_upper)
        ]
        result_gdf = result_gdf[columns_to_keep]

    # assert to evade pyLance warning
    assert isinstance(result_gdf, pd.DataFrame) or isinstance(
        result_gdf, gpd.GeoDataFrame
    )
    return result_gdf


def read_file_sql(
    path: Union[str, "os.PathLike[Any]"],
    sql_stmt: str,
    sql_dialect: str = "SQLITE",
    layer: Optional[str] = None,
    ignore_geometry: bool = False,
) -> Union[pd.DataFrame, gpd.GeoDataFrame]:
    """
    Reads a file to a GeoPandas GeoDataFrame, using an sql statement to filter
    the data.

    Args:
        path (file path): path to the file to read from
        sql_stmt (str): sql statement to use
        sql_dialect (str, optional): Sql dialect used. Defaults to 'SQLITE'.
        layer (str, optional): The layer to read. If no layer is specified,
            reads the only layer in the file or throws an Exception.
        ignore_geometry (bool, optional): True not to read/return the geomatry.
            Defaults to False.

    Returns:
        Union[pd.DataFrame, gpd.GeoDataFrame]: The data read.
    """

    # Check and init some parameters/variables
    path = Path(path)
    layer_list = None
    if layer is not None:
        layer_list = [layer]

    # Now we're ready to go!
    with tempfile.TemporaryDirectory() as tmpdir:
        # Execute sql against file and write to temp file
        tmp_path = Path(tmpdir) / "read_file_sql_tmp_file.gpkg"
        _ogr_util.vector_translate(
            input_path=path,
            output_path=tmp_path,
            sql_stmt=sql_stmt,
            sql_dialect=sql_dialect,
            input_layers=layer_list,
            options={"LAYER_CREATION.SPATIAL_INDEX": False},
        )

        # Read and return result
        return _read_file_base(tmp_path, ignore_geometry=ignore_geometry)


def to_file(
    gdf: gpd.GeoDataFrame,
    path: Union[str, "os.PathLike[Any]"],
    layer: Optional[str] = None,
    force_multitype: bool = False,
    append: bool = False,
    append_timeout_s: int = 600,
    index: bool = True,
):
    """
    Writes a pandas dataframe to file.

    The fileformat is detected based on the filepath extension.

    Args:
        gdf (gpd.GeoDataFrame): The GeoDataFrame to export to file.
        path (Union[str,): The file path to write to.
        layer (str, optional): The layer to read. If no layer is specified,
            reads the only layer in the file or throws an Exception.
        force_multitype (bool, optional): force the geometry type to a multitype
            for file types that require one geometrytype per layer.
            Defaults to False.
        append (bool, optional): True to append to the file. Defaults to False.
        append_timeout_s (int, optional): The maximum timeout to wait when the
            output file is already being written to by another process.
            Defaults to 600.
        index (bool, optional): True to write the pandas index to the file as
            well. Defaults to True.

    Raises:
        ValueError: an invalid parameter value was passed.
        RuntimeError: timeout was reached while trying to append data to path.
    """
    # TODO: think about if possible/how to support adding optional parameter and pass
    # them to next function, example encoding, float_format,...

    # Check input parameters
    path = Path(path)

    # If no layer name specified, use the filename (without extension)
    if layer is None:
        layer = Path(path).stem
    # If the dataframe is empty, log warning and return
    if len(gdf) <= 0:
        # logger.warn(f"Cannot write an empty dataframe to {filepath}.{layer}")
        return

    def write_to_file(
        gdf: gpd.GeoDataFrame,
        path: Path,
        layer: str,
        index: bool = True,
        force_multitype: bool = False,
        append: bool = False,
    ):

        # Change mode if append is true
        if append is True:
            if path.exists():
                mode = "a"
            else:
                mode = "w"
        else:
            mode = "w"

        geofiletype = GeofileType(path)
        if geofiletype == GeofileType.ESRIShapefile:
            if index is True:
                gdf_to_write = gdf.reset_index(drop=True)
            else:
                gdf_to_write = gdf
            gdf_to_write.to_file(str(path), driver=geofiletype.ogrdriver, mode=mode)
        elif geofiletype == GeofileType.GPKG:
            # Try to harmonize the geometrytype to one (multi)type, as GPKG
            # doesn't like > 1 type in a layer
            gdf_to_write = gdf.copy()
            gdf_to_write.geometry = geoseries_util.harmonize_geometrytypes(
                gdf.geometry, force_multitype=force_multitype
            )
            gdf_to_write.to_file(
                str(path), layer=layer, driver=geofiletype.ogrdriver, mode=mode
            )
        elif geofiletype == GeofileType.SQLite:
            gdf.to_file(str(path), layer=layer, driver=geofiletype.ogrdriver, mode=mode)
        elif geofiletype == GeofileType.GeoJSON:
            gdf.to_file(str(path), driver=geofiletype.ogrdriver, mode=mode)
        else:
            raise ValueError(f"Not implemented for geofiletype {geofiletype}")

    # If no append, just write to output path
    if append is False:
        write_to_file(
            gdf=gdf,
            path=path,
            layer=layer,
            index=index,
            force_multitype=force_multitype,
            append=append,
        )
    else:
        # If append is asked, check if the fiona driver supports appending. If
        # not, write to temporary output file

        # Remark: fiona pre-1.8.14 didn't support appending to geopackage. Once
        # older versions becomes rare, dependency can be put to this version, and
        # this code can be cleaned up...
        geofiletype = GeofileType(path)
        gdftemp_path = None
        gdftemp_lockpath = None
        if "a" not in fiona.supported_drivers[geofiletype.ogrdriver]:
            # Get a unique temp file path. The file cannot be created yet, so
            # only create a lock file to evade other processes using the same
            # temp file name
            gdftemp_path, gdftemp_lockpath = _io_util.get_tempfile_locked(
                base_filename="gdftemp", suffix=path.suffix, dirname="geofile_to_file"
            )
            write_to_file(
                gdf,
                path=gdftemp_path,
                layer=layer,
                index=index,
                force_multitype=force_multitype,
            )

        # Files don't typically support having multiple processes writing
        # simultanously to them, so use lock file to synchronize access.
        lockfile = Path(f"{str(path)}.lock")
        start_time = datetime.datetime.now()
        while True:
            if _io_util.create_file_atomic(lockfile) is True:
                try:
                    # If gdf wasn't written to temp file, use standard write-to-file
                    if gdftemp_path is None:
                        write_to_file(
                            gdf=gdf,
                            path=path,
                            layer=layer,
                            index=index,
                            force_multitype=force_multitype,
                            append=True,
                        )
                    else:
                        # If gdf written to temp file, use append_to_nolock + cleanup
                        _append_to_nolock(src=gdftemp_path, dst=path, dst_layer=layer)
                        remove(gdftemp_path)
                        if gdftemp_lockpath is not None:
                            gdftemp_lockpath.unlink()
                finally:
                    lockfile.unlink()
                    return
            else:
                time_waiting = (datetime.datetime.now() - start_time).total_seconds()
                if time_waiting > append_timeout_s:
                    raise RuntimeError(
                        f"to_file timeout of {append_timeout_s} reached, stop append "
                        f"to {path}!"
                    )

            # Sleep for a second before trying again
            time.sleep(1)


def get_crs(path: Union[str, "os.PathLike[Any]"]) -> pyproj.CRS:
    """
    Get the CRS (projection) of the file

    Args:
        path (PathLike): Path to the file.

    Returns:
        pyproj.CRS: The projection of the file
    """
    # TODO: seems like support for multiple layers in the file isn't here yet???
    with fiona.open(str(path), "r") as geofile:
        assert geofile is not None
        return pyproj.CRS(geofile.crs)


def is_geofile(path: Union[str, "os.PathLike[Any]"]) -> bool:
    """
    Determines based on the filepath if this is a geofile.

    Args:
        path (PathLike): The file path.

    Returns:
        bool: True if it is a geo file.
    """
    return is_geofile_ext(Path(path).suffix)


def is_geofile_ext(file_ext: str) -> bool:
    """
    Determines based on the file extension if this is a geofile.

    Args:
        file_ext (str): the extension.

    Returns:
        bool: True if it is a geofile.
    """
    try:
        # If the driver can be determined, it is a (supported) geo file.
        _ = GeofileType(file_ext)
        return True
    except Exception:
        return False


def cmp(
    path1: Union[str, "os.PathLike[Any]"], path2: Union[str, "os.PathLike[Any]"]
) -> bool:
    """
    Compare if two geofiles are identical.

    For geofiles that use multiple files, all relevant files must be identical.
    Eg. for shapefiles, the .shp, .shx and .dbf file must be identical.

    Args:
        path1 (PathLike): path to the first file.
        path2 (PathLike): path to the second file.

    Returns:
        bool: True if the files are identical
    """
    # Check input parameters
    path1_p = Path(path1)
    path2_p = Path(path2)

    # For a shapefile, multiple files need to be compared
    if path1_p.suffix.lower() == ".shp":
        path2_noext, _ = os.path.splitext(path2_p)
        shapefile_base_suffixes = [".shp", ".dbf", ".shx"]
        path1_noext = path1_p.parent / path1_p.stem
        path2_noext = path2_p.parent / path2_p.stem
        for ext in shapefile_base_suffixes:
            if not filecmp.cmp(f"{str(path1_noext)}{ext}", f"{str(path2_noext)}{ext}"):
                logger.info(
                    f"File {path1_noext}{ext} is different from {path2_noext}{ext}"
                )
                return False
        return True
    else:
        return filecmp.cmp(str(path1_p), str(path2_p))


def copy(src: Union[str, "os.PathLike[Any]"], dst: Union[str, "os.PathLike[Any]"]):
    """
    Copies the geofile from src to dst. Is the source file is a geofile containing
    of multiple files (eg. .shp) all files are copied.

    Args:
        src (PathLike): the file to copy.
        dst (PathLike): the location to copy the file(s) to.
    """
    # Check input parameters
    src = Path(src)
    dst = Path(dst)
    geofiletype = GeofileType(src)

    # Copy the main file
    shutil.copy(str(src), dst)

    # For some file types, extra files need to be copied
    # If dest is a dir, just use move. Otherwise concat dest filepaths
    if geofiletype.suffixes_extrafiles is not None:
        if dst.is_dir():
            for suffix in geofiletype.suffixes_extrafiles:
                srcfile = src.parent / f"{src.stem}{suffix}"
                if srcfile.exists():
                    shutil.copy(str(srcfile), dst)
        else:
            for suffix in geofiletype.suffixes_extrafiles:
                srcfile = src.parent / f"{src.stem}{suffix}"
                dstfile = dst.parent / f"{dst.stem}{suffix}"
                if srcfile.exists():
                    shutil.copy(str(srcfile), dstfile)


def move(src: Union[str, "os.PathLike[Any]"], dst: Union[str, "os.PathLike[Any]"]):
    """
    Moves the geofile from src to dst. If the source file is a geofile containing
    of multiple files (eg. .shp) all files are moved.

    Args:
        src (PathLike): the file to move
        dst (PathLike): the location to move the file(s) to
    """
    # Check input parameters
    src = Path(src)
    dst = Path(dst)
    geofiletype = GeofileType(src)

    # Move the main file
    shutil.move(str(src), dst, copy_function=_io_util.copyfile)

    # For some file types, extra files need to be moved
    # If dest is a dir, just use move. Otherwise concat dest filepaths
    if geofiletype.suffixes_extrafiles is not None:
        if dst.is_dir():
            for suffix in geofiletype.suffixes_extrafiles:
                srcfile = src.parent / f"{src.stem}{suffix}"
                if srcfile.exists():
                    shutil.move(str(srcfile), dst, copy_function=_io_util.copyfile)
        else:
            for suffix in geofiletype.suffixes_extrafiles:
                srcfile = src.parent / f"{src.stem}{suffix}"
                dstfile = dst.parent / f"{dst.stem}{suffix}"
                if srcfile.exists():
                    shutil.move(str(srcfile), dstfile, copy_function=_io_util.copyfile)


def remove(path: Union[str, "os.PathLike[Any]"]):
    """
    Removes the geofile. Is it is a geofile composed of multiple files
    (eg. .shp) all files are removed.
    If .lock files are present, they are removed as well.

    Args:
        path (PathLike): the file to remove
    """
    # Check input parameters
    path = Path(path)
    geofiletype = GeofileType(path)

    # If there is a lock file, remove it
    lockfile_path = path.parent / f"{path.name}.lock"
    lockfile_path.unlink(missing_ok=True)

    # Remove the main file
    if path.exists():
        path.unlink()

    # For some file types, extra files need to be removed
    if geofiletype.suffixes_extrafiles is not None:
        for suffix in geofiletype.suffixes_extrafiles:
            curr_path = path.parent / f"{path.stem}{suffix}"
            if curr_path.exists():
                curr_path.unlink()


def append_to(
    src: Union[str, "os.PathLike[Any]"],
    dst: Union[str, "os.PathLike[Any]"],
    src_layer: Optional[str] = None,
    dst_layer: Optional[str] = None,
    src_crs: Union[int, str, None] = None,
    dst_crs: Union[int, str, None] = None,
    reproject: bool = False,
    explodecollections: bool = False,
    force_output_geometrytype: Union[GeometryType, str, None] = None,
    create_spatial_index: bool = True,
    append_timeout_s: int = 600,
    transaction_size: int = 50000,
    options: dict = {},
):
    """
    Append src file to the dst file.

    Remark: append is not supported for all filetypes in fiona/geopandas (0.8)
    so workaround via gdal needed.

    The options parameter can be used to pass any type of options to GDAL in
    the following form:
        { "<option_type>.<option_name>": <option_value> }

    The option types can be any of the following:
        - LAYER_CREATION: layer creation option (lco)
        - DATASET_CREATION: dataset creation option (dsco)
        - INPUT_OPEN: input dataset open option (oo)
        - DESTINATION_OPEN: destination dataset open option (doo)
        - CONFIG: config option (config)

    The options can be found in the [GDAL vector driver documentation]
    (https://gdal.org/drivers/vector/index.html).

    Args:
        src (Union[str,): source file path.
        dst (Union[str,): destination file path.
        src_layer (str, optional): source layer. Defaults to None.
        dst_layer (str, optional): destination layer. Defaults to None.
        src_crs (str, optional): an epsg int or anything supported
            by the OGRSpatialReference.SetFromUserInput() call, which includes
            an EPSG string (eg. "EPSG:4326"), a well known text (WKT) CRS
            definition,... Defaults to None.
        dst_crs (str, optional): an epsg int or anything supported
            by the OGRSpatialReference.SetFromUserInput() call, which includes
            an EPSG string (eg. "EPSG:4326"), a well known text (WKT) CRS
            definition,... Defaults to None.
        reproject (bool, optional): True to reproject while converting the
            file. Defaults to False.
        explodecollections (bool), optional): True to output only simple geometries.
            Defaults to False.
        force_output_geometrytype (GeometryType, optional): geometry type.
            to (try to) force the output to. Defaults to None.
        create_spatial_index (bool, optional): True to create a spatial index
            on the destination file/layer. If the LAYER_CREATION.SPATIAL_INDEX
            parameter is specified in options, create_spatial_index is ignored.
            Defaults to True.
        append_timeout_s (int, optional): timeout to use if the output file is
            being written to by another process already. Defaults to 600.
        transaction_size (int, optional): Transaction size.
            Defaults to 50000.
        options (dict, optional): options to pass to gdal.
        verbose (bool, optional): True to write verbose output. Defaults to False.

    Raises:
        ValueError: an invalid parameter value was passed.
        RuntimeError: timeout was reached while trying to append data to path.
    """
    # Check/clean input params
    src = Path(src)
    dst = Path(dst)
    if force_output_geometrytype is not None:
        force_output_geometrytype = GeometryType(force_output_geometrytype)

    # Files don't typically support having multiple processes writing
    # simultanously to them, so use lock file to synchronize access.
    lockfile = Path(f"{str(dst)}.lock")

    # If the destination file doesn't exist yet, but the lockfile does,
    # try removing the lockfile as it might be a ghost lockfile.
    if dst.exists() is False and lockfile.exists() is True:
        try:
            lockfile.unlink()
        except Exception:
            _ = None

    # Creating lockfile and append
    start_time = datetime.datetime.now()
    while True:

        if _io_util.create_file_atomic(lockfile) is True:
            try:
                # append
                _append_to_nolock(
                    src=src,
                    dst=dst,
                    src_layer=src_layer,
                    dst_layer=dst_layer,
                    src_crs=src_crs,
                    dst_crs=dst_crs,
                    reproject=reproject,
                    explodecollections=explodecollections,
                    force_output_geometrytype=force_output_geometrytype,
                    create_spatial_index=create_spatial_index,
                    transaction_size=transaction_size,
                    options=options,
                )
            finally:
                lockfile.unlink()
                return
        else:
            time_waiting = (datetime.datetime.now() - start_time).total_seconds()
            if time_waiting > append_timeout_s:
                raise RuntimeError(
                    f"append_to timeout of {append_timeout_s} reached, so stop write "
                    f"to {dst}!"
                )

        # Sleep for a second before trying again
        time.sleep(1)


def _append_to_nolock(
    src: Path,
    dst: Path,
    src_layer: Optional[str] = None,
    dst_layer: Optional[str] = None,
    src_crs: Union[int, str, None] = None,
    dst_crs: Union[int, str, None] = None,
    reproject: bool = False,
    explodecollections: bool = False,
    create_spatial_index: bool = True,
    force_output_geometrytype: Optional[GeometryType] = None,
    transaction_size: int = 50000,
    options: dict = {},
):
    # Check/clean input params
    options = _ogr_util._prepare_gdal_options(options)
    if "LAYER_CREATION.SPATIAL_INDEX" not in options:
        options["LAYER_CREATION.SPATIAL_INDEX"] = create_spatial_index

    # When creating/appending to a shapefile, launder the columns names via
    # a sql statement, otherwise when appending the laundered columns will
    # get NULL values instead of the data.
    sql_stmt = None
    if dst.suffix.lower() == ".shp":
        src_columns = get_layerinfo(src).columns
        columns_laundered = _launder_column_names(src_columns)
        columns_aliased = [
            f'"{column}" AS "{laundered}"' for column, laundered in columns_laundered
        ]
        layer = src_layer if src_layer is not None else get_only_layer(src)
        sql_stmt = f'SELECT {", ".join(columns_aliased)} FROM "{layer}"'

    # Go!
    translate_info = _ogr_util.VectorTranslateInfo(
        input_path=src,
        output_path=dst,
        input_layers=src_layer,
        output_layer=dst_layer,
        input_srs=src_crs,
        output_srs=dst_crs,
        sql_stmt=sql_stmt,
        sql_dialect="OGRSQL",
        reproject=reproject,
        transaction_size=transaction_size,
        append=True,
        update=True,
        explodecollections=explodecollections,
        force_output_geometrytype=force_output_geometrytype,
        options=options,
    )
    _ogr_util.vector_translate_by_info(info=translate_info)


def convert(
    src: Union[str, "os.PathLike[Any]"],
    dst: Union[str, "os.PathLike[Any]"],
    src_layer: Optional[str] = None,
    dst_layer: Optional[str] = None,
    src_crs: Union[str, int, None] = None,
    dst_crs: Union[str, int, None] = None,
    reproject: bool = False,
    explodecollections: bool = False,
    force_output_geometrytype: Optional[GeometryType] = None,
    create_spatial_index: bool = True,
    options: dict = {},
    force: bool = False,
):
    """
    Append src file to the dst file.

    The options parameter can be used to pass any type of options to GDAL in
    the following form:
        { "<option_type>.<option_name>": <option_value> }

    The option types can be any of the following:
        - LAYER_CREATION: layer creation option (lco)
        - DATASET_CREATION: dataset creation option (dsco)
        - INPUT_OPEN: input dataset open option (oo)
        - DESTINATION_OPEN: destination dataset open option (doo)
        - CONFIG: config option (config)

    The options can be found in the [GDAL vector driver documentation]
    (https://gdal.org/drivers/vector/index.html).

    Args:
        src (PathLike): The source file path.
        dst (PathLike): The destination file path.
        src_layer (str, optional): The source layer. If None and there is only
            one layer in the src file, that layer is taken. Defaults to None.
        dst_layer (str, optional): The destination layer. If None, the file
            stem is taken as layer name. Defaults to None.
        src_crs (Union[str, int], optional): an epsg int or anything supported
            by the OGRSpatialReference.SetFromUserInput() call, which includes
            an EPSG string (eg. "EPSG:4326"), a well known text (WKT) CRS
            definition,... Defaults to None.
        dst_crs (Union[str, int], optional): an epsg int or anything supported
            by the OGRSpatialReference.SetFromUserInput() call, which includes
            an EPSG string (eg. "EPSG:4326"), a well known text (WKT) CRS
            definition,... Defaults to None.
        reproject (bool, optional): True to reproject while converting the
            file. Defaults to False.
        explodecollections (bool, optional): True to output only simple
            geometries. Defaults to False.
        force_output_geometrytype (GeometryType, optional): Geometry type.
            to (try to) force the output to. Defaults to None.
        create_spatial_index (bool, optional): True to create a spatial index
            on the destination file/layer. If the LAYER_CREATION.SPATIAL_INDEX
            parameter is specified in options, create_spatial_index is ignored.
            Defaults to True.
        options (dict, optional): options to pass to gdal.
        force (bool, optional): overwrite existing output file(s)
            Defaults to False.
    """
    src = Path(src)
    dst = Path(dst)

    # If dest file exists already, remove it
    if dst.exists():
        if force is True:
            remove(dst)
        else:
            logger.info(f"Output file exists already, so stop: {dst}")
            return

    # Convert
    logger.info(f"Convert {src} to {dst}")
    _append_to_nolock(
        src,
        dst,
        src_layer,
        dst_layer,
        src_crs=src_crs,
        dst_crs=dst_crs,
        reproject=reproject,
        explodecollections=explodecollections,
        force_output_geometrytype=force_output_geometrytype,
        create_spatial_index=create_spatial_index,
        options=options,
    )


def _launder_column_names(columns: Iterable) -> List[Tuple[str, str]]:
    """
    Launders the column names passed to comply with shapefile restrictions.

    Rationale: normally gdal launders them if needed, but when you append
    multiple files to a shapefile with columns that need to be laundered
    they are not matched and so are appended with NULL values for these
    columns. Normally the -relaxedFieldNameMatch parameter in ogr2ogr
    should fix this, but it seems that this isn't supported for shapefiles.

    Laundering is based on this text from the gdal shapefile driver
    documentation:

    Shapefile feature attributes are stored in an associated .dbf file, and
    so attributes suffer a number of limitations:
    -   Attribute names can only be up to 10 characters long.
        The OGR Shapefile driver tries to generate unique field
        names. Successive duplicate field names, including those created by
        truncation to 10 characters, will be truncated to 8 characters and
        appended with a serial number from 1 to 99.

        For example:

        -  a → a, a → a_1, A → A_2;
        -  abcdefghijk → abcdefghij, abcdefghijkl → abcdefgh_1

    -   Only Integer, Integer64, Real, String and Date (not DateTime, just
        year/month/day) field types are supported. The various list, and
        binary field types cannot be created.
    -   The field width and precision are directly used to establish storage
        size in the .dbf file. This means that strings longer than the field
        width, or numbers that don't fit into the indicated field format will
        suffer truncation.
    -   Integer fields without an explicit width are treated as width 9, and
        extended to 10 or 11 if needed.
    -   Integer64 fields without an explicit width are treated as width 18,
        and extended to 19 or 20 if needed.
    -   Real (floating point) fields without an explicit width are treated as
        width 24 with 15 decimal places of precision.
    -   String fields without an assigned width are treated as 80 characters.

    Args:
        columns (Iterable): the columns to launder.

    Returns: a List of tupples with the original and laundered column names.
    """
    laundered = []
    laundered_upper = []
    for column in columns:
        # Doubles in casing aree not allowed either
        if len(column) <= 10:
            if column.upper() not in laundered_upper:
                laundered_upper.append(column.upper())
                laundered.append((column, column))
                continue

        # Laundering is needed
        column_laundered = column[:10]
        if column_laundered.upper() not in laundered_upper:
            laundered_upper.append(column_laundered.upper())
            laundered.append((column, column_laundered))
        else:
            # Just taking first 10 characters didn't help
            for index in range(1, 101):
                if index >= 100:
                    raise NotImplementedError(
                        "Not supported to launder > 99 columns starting "
                        f"with {column_laundered[:8]}"
                    )
                if index <= 9:
                    column_laundered = f"{column_laundered[:8]}_{index}"
                else:
                    column_laundered = f"{column_laundered[:8]}{index}"
                if column_laundered.upper() not in laundered_upper:
                    laundered_upper.append(column_laundered.upper())
                    laundered.append((column, column_laundered))
                    break

    return laundered


def get_driver(path: Union[str, "os.PathLike[Any]"]) -> str:
    """
    Get the driver to use for the file extension of this filepath.

    DEPRECATED, use GeometryType(Path).ogrdriver.

    Args:
        path (PathLike): The file path.

    Returns:
        str: The OGR driver name.
    """
    warnings.warn(
        "get_driver is deprecated, use GeometryType(Path).ogrdriver", FutureWarning
    )
    return GeofileType(Path(path)).ogrdriver


def get_driver_for_ext(file_ext: str) -> str:
    """
    Get the driver to use for this file extension.

    DEPRECATED, use GeometryType(file_ext).ogrdriver.

    Args:
        file_ext (str): The extentension.

    Raises:
        ValueError: If input geometrytype is not known.

    Returns:
        str: The OGR driver name.
    """
    warnings.warn(
        "get_driver_for_ext is deprecated, use GeometryType(Path).ogrdriver",
        FutureWarning,
    )
    return GeofileType(file_ext).ogrdriver


def to_multi_type(geometrytypename: str) -> str:
    """
    Map the input geometry type to the corresponding 'MULTI' geometry type...

    DEPRECATED, use to_multigeometrytype

    Args:
        geometrytypename (str): Input geometry type

    Raises:
        ValueError: If input geometrytype is not known.

    Returns:
        str: Corresponding 'MULTI' geometry type
    """
    warnings.warn(
        "to_generaltypeid is deprecated, use GeometryType.to_multigeometrytype",
        FutureWarning,
    )
    return geometry_util.GeometryType(geometrytypename).to_multitype.name


def to_generaltypeid(geometrytypename: str) -> int:
    """
    Map the input geometry type name to the corresponding geometry type id:
        * 1 = POINT-type
        * 2 = LINESTRING-type
        * 3 = POLYGON-type

    DEPRECATED, use to_primitivetypeid()

    Args:
        geometrytypename (str): Input geometry type

    Raises:
        ValueError: If input geometrytype is not known.

    Returns:
        int: Corresponding geometry type id
    """
    warnings.warn(
        "to_generaltypeid is deprecated, use GeometryType.to_primitivetypeid",
        FutureWarning,
    )
    return geometry_util.GeometryType(geometrytypename).to_primitivetype.value
