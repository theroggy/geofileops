"""Module with helper functions for geo files."""

import enum
import filecmp
import logging
import os
import pprint
import shutil
import string
import tempfile
import time
import warnings
import zipfile
from collections.abc import Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any, Literal, Union

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import pyproj
from geopandas.io import file as gpd_io_file
from osgeo import gdal, ogr
from pandas.api.types import is_integer_dtype
from pygeoops import GeometryType, PrimitiveType  # noqa: F401

from geofileops._compat import GDAL_GTE_311
from geofileops.helpers._configoptions_helper import ConfigOptions
from geofileops.util import (
    _geofileinfo,
    _geoseries_util,
    _io_util,
    _ogr_sql_util,
    _ogr_util,
    _sqlite_util,
)
from geofileops.util._geopath_util import GeoPath

try:
    import fiona
except ImportError:
    fiona = None

logger = logging.getLogger(__name__)

# Enable exceptions for GDAL
gdal.UseExceptions()
gdal.ogr.UseExceptions()

# Disable this warning in fiona
warnings.filterwarnings(
    action="ignore",
    category=RuntimeWarning,
    message=(
        "^Sequential read of iterator was interrupted. Resetting iterator. "
        "This can negatively impact the performance.$"
    ),
)

# Disable this warning in pyogrio
warnings.filterwarnings(
    action="ignore",
    category=UserWarning,
    message="^Layer .* does not have any features to read$",
)
# Set logging level for pyogrio to warning
pyogrio_logger = logging.getLogger("pyogrio")
pyogrio_logger.setLevel(logging.WARNING)

# Hardcoded 31370 prj string to replace faulty ones
PRJ_EPSG_31370 = (
    'PROJCS["Belge_1972_Belgian_Lambert_72",'
    'GEOGCS["Belge 1972",'
    'DATUM["D_Belge_1972",SPHEROID["International_1924",6378388,297]],'
    'PRIMEM["Greenwich",0],'
    'UNIT["Degree",0.017453292519943295]'
    "],"
    'PROJECTION["Lambert_Conformal_Conic"],'
    'PARAMETER["standard_parallel_1",51.16666723333333],'
    'PARAMETER["standard_parallel_2",49.8333339],'
    'PARAMETER["latitude_of_origin",90],'
    'PARAMETER["central_meridian",4.367486666666666],'
    'PARAMETER["false_easting",150000.013],'
    'PARAMETER["false_northing",5400088.438],'
    'UNIT["Meter",1],'
    'AUTHORITY["EPSG",31370]'
    "]"
)


def listlayers(
    path: Union[str, "os.PathLike[Any]"], only_spatial_layers: bool = True
) -> list[str]:
    """Get the list of layers in a geofile.

    Args:
        path (PathLike): path to the file to get info about. |GDAL_vsi| paths are also
            supported.
        only_spatial_layers (bool, optional): True to only list spatial layers.
            False to list all tables.

    Raises:
        FileNotFoundError: if the file is not found.
        Exception: an error occured opening or reading the file.

    Returns:
        List[str]: the list of layers

    .. |GDAL_vsi| raw:: html

        <a href="https://gdal.org/en/stable/user/virtual_file_systems.html" target="_blank">GDAL vsi</a>

    """  # noqa: E501
    if str(path).lower().endswith((".shp", ".shp.zip")):
        if not _vsi_exists(path):
            raise FileNotFoundError(f"File not found: {path}")
        return [GeoPath(path).stem]

    datasource = None
    try:
        datasource = gdal.OpenEx(
            str(path), nOpenFlags=gdal.OF_VECTOR | gdal.OF_READONLY | gdal.OF_SHARED
        )
        return _listlayers(datasource, only_spatial_layers)

    except Exception as ex:
        if str(ex).endswith("No such file or directory"):
            raise FileNotFoundError(f"File not found: {path}") from ex

        ex.args = (f"listlayers error for {path}:\n  {ex}",)
        raise
    finally:
        datasource = None


def _listlayers(datasource: gdal.Dataset, only_spatial_layers: bool) -> list[str]:
    """Get the list of layers in a datasource.

    Remark: the datasource won't be opened nor closed in this function, this is the
    responsibility of the calling function!

    Args:
        datasource (gdal.Dataset): the gdal DataSet to get the layers from.
        only_spatial_layers (bool): True to only list spatial layers.

    Returns:
        list[str]: the layers found.
    """
    nb_layers = datasource.GetLayerCount()
    layers = []
    for layer_id in range(nb_layers):
        datasource_layer = datasource.GetLayerByIndex(layer_id)
        if not only_spatial_layers or datasource_layer.GetGeometryColumn() != "":
            layers.append(datasource_layer.GetName())

    return layers


class ColumnInfo:
    """A data object containing meta-information about a column.

    Attributes:
        name (str): the name of the column.
        gdal_type (str): the type of the column according to gdal.
        width (int): the width of the column, if specified.
    """

    def __init__(
        self,
        name: str,
        gdal_type: str,
        width: int | None,
        precision: int | None,
    ):
        """Constructor of ColumnInfo.

        Args:
            name (str): the column name.
            gdal_type (str): the gdal type of the column.
            width (Optional[int]): the width of the column, if applicable.
            precision (Optional[int]): the precision of the column, if applicable.
        """
        self.name = name
        self.gdal_type = gdal_type
        self.width = width
        self.precision = precision

    def __repr__(self):
        """Overrides the representation property of ColumnInfo."""
        return f"{self.__class__}({self.__dict__})"


class LayerInfo:
    """A data object containing meta-information about a layer.

    Attributes:
        name (str): the name of the layer.
        featurecount (int): the number of features (rows) in the layer.
        total_bounds (Tuple[float, float, float, float]): the bounding box of
            the layer: (minx, miny, maxx, maxy).
        geometrycolumn (str): name of the column that contains the
            primary geometry.
        geometrytypename (str): the geometry type name of the geometrycolumn.
            The type name returned is one of the following: POINT, MULTIPOINT,
            LINESTRING, MULTILINESTRING, POLYGON, MULTIPOLYGON, COLLECTION.
        geometrytype (GeometryType): the geometry type of the geometrycolumn.
        columns (dict): the columns (other than the geometry column) that
            are available on the layer with their properties as a dict.
        fid_column (str): column name of the FID column. Is "" for file types that don't
            explicitly store an FID, like shapefile.
        crs (pyproj.CRS): the spatial reference of the layer.
        errors (List[str]): list of errors in the layer, eg. invalid column
            names,...
    """

    def __init__(
        self,
        name: str,
        featurecount: int,
        total_bounds: tuple[float, float, float, float],
        geometrycolumn: str,
        geometrytypename: str,
        columns: dict[str, ColumnInfo],
        fid_column: str,
        crs: pyproj.CRS | None,
        errors: list[str],
    ):
        """Constructor of Layerinfo.

        Args:
            name (str): name of the layer.
            featurecount (int): number of features in the layer.
            total_bounds (Tuple[float, float, float, float]): the bounds of the layer.
            geometrycolumn (str): the name of the geometry column.
            geometrytypename (str): the name of the geometry column type.
            columns (Dict[str, ColumnInfo]): the attribute columns of the layer.
            fid_column (str): the name of the fid column.
            crs (Optional[pyproj.CRS]): the crs of the layer.
            errors (List[str]): errors encountered reading the layer info.
        """
        self.name = name
        self.featurecount = featurecount
        self.total_bounds = total_bounds
        self.geometrycolumn = geometrycolumn
        self.geometrytypename = geometrytypename
        self.columns = columns
        self.fid_column = fid_column
        self.crs = crs
        self.errors = errors

    @property
    def geometrytype(self):
        """The geometry type of the geometrycolumn."""
        if self.geometrytypename == "NONE":
            return None

        return GeometryType(self.geometrytypename)

    def __repr__(self):
        """Overrides the representation property of LayerInfo."""
        return f"{self.__class__}({self.__dict__})"


def get_layer_geometrytypes(
    path: Union[str, "os.PathLike[Any]"], layer: str | None = None
) -> list[str]:
    """Get the geometry types in the layer by examining each geometry in the layer.

    The general geometry type of the layer can be determined using
    :meth:`~get_layerinfo`.

    Args:
        path (PathLike): path to the file to get info about. |GDAL_vsi| paths are also
            supported.
        layer (str): the layer you want info about. Doesn't need to be
            specified if there is only one layer in the geofile.

    Returns:
        List[str]: the geometry types in the layer.

    .. |GDAL_vsi| raw:: html

        <a href="https://gdal.org/en/stable/user/virtual_file_systems.html" target="_blank">GDAL vsi</a>

    """  # noqa: E501
    sql_stmt = """
        SELECT DISTINCT
               CASE
                 WHEN CastToSingle({geometrycolumn}) IS NOT NULL THEN
                     ST_GeometryType(CastToSingle({geometrycolumn}))
                 ELSE ST_GeometryType({geometrycolumn})
               END AS geom_type
          FROM "{input_layer}" layer
    """
    result_df = read_file(path, sql_stmt=sql_stmt, sql_dialect="SQLITE")
    return result_df["geom_type"].to_list()


def get_layerinfo(
    path: Union[str, "os.PathLike[Any]"],
    layer: str | None = None,
    raise_on_nogeom: bool = True,
    datasource: gdal.Dataset | None = None,
) -> LayerInfo:
    """Get information about a layer in a geofile.

    Args:
        path (PathLike): path to the file to get info about. |GDAL_vsi| paths are also
            supported.
        layer (str, optional): the layer you want info about. Doesn't need to be
            specified if there is only one layer in the geofile.
        raise_on_nogeom (bool, optional): True to raise if the layer doesn't have a
            geometry column. If False, the returned LayerInfo.geometrycolumn will be
            None. Defaults to True.
        datasource (gdal.Dataset, optional): the already opened gdal dataset found on
            `path`. This can be used to avoid opening and closing the file many times.
            If specified, the datasource will not be closed! Defaults to None.

    Raises:
        ValueError if the layer definition has errors like invalid column names,...

    Returns:
        LayerInfo: the information about the layer.

    .. |GDAL_vsi| raw:: html

        <a href="https://gdal.org/en/stable/user/virtual_file_systems.html" target="_blank">GDAL vsi</a>

    """  # noqa: E501
    datasource_specified = datasource is not None
    try:
        if datasource is None:
            datasource = gdal.OpenEx(
                str(path), nOpenFlags=gdal.OF_VECTOR | gdal.OF_READONLY | gdal.OF_SHARED
            )
        datasource_layer = _get_layer(datasource, layer)

        # Get column info
        columns = {}
        errors = []
        driver = datasource.GetDriver().ShortName
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
                        f"in {path}#{layer}"
                    )
            column_info = ColumnInfo(
                name=name, gdal_type=gdal_type, width=width, precision=precision
            )
            columns[name] = column_info
            if driver == "ESRI Shapefile":
                if name.casefold() == "geometry":
                    errors.append(
                        "An attribute column 'geometry' is not supported in a shapefile"
                    )

        # Get geometry column name.
        geometrytypename = _ogr_util.ogrtype_to_name(datasource_layer.GetGeomType())

        # For shape files, the difference between the 'MULTI' variant and the
        # single one doesn't exists... so always report MULTI variant by convention.
        if geometrytypename != "NONE" and driver == "ESRI Shapefile":
            if not geometrytypename.startswith("MULTI"):
                geometrytypename = f"MULTI{geometrytypename}"

        # If the geometry type is not None, fill out the extra properties
        geometrycolumn = None
        extent = None
        crs = None
        total_bounds = None
        if geometrytypename != "NONE":
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
                if crs.to_epsg() is None:
                    crs = _crs_custom_match(crs, path)

        elif raise_on_nogeom:
            errors.append("Layer doesn't have a geometry column!")

        # If there were no errors, everything was OK so we can return.
        # Remark: for e.g. for a ".shp.zip" file the layer name will include .shp at the
        # end, but this is not an error! If it isn't there, using the layer name in SQL
        # statements on the ".shp.zip" file will lead to "table not found" errors.
        if len(errors) == 0:
            return LayerInfo(
                name=datasource_layer.GetName(),
                featurecount=datasource_layer.GetFeatureCount(),
                total_bounds=total_bounds,  # type: ignore[arg-type]
                geometrycolumn=geometrycolumn,  # type: ignore[arg-type]
                geometrytypename=geometrytypename,
                columns=columns,
                fid_column=datasource_layer.GetFIDColumn(),
                crs=crs,
                errors=errors,
            )

    except Exception as ex:
        if str(ex).endswith("No such file or directory"):
            raise FileNotFoundError(f"File not found: {path}") from ex

        ex.args = (f"get_layerinfo error for {path}#{layer}:\n  {ex}",)
        raise
    finally:
        if not datasource_specified:
            # Close the datasource if it wasn't passed in as a parameter
            datasource = None

    # If we didn't return or raise yet here, there must have been errors
    errors_str = pprint.pformat(errors)
    raise ValueError(
        f"Errors in layer definition of file {path}, layer {layer}: \n{errors_str}"
    )


def get_only_layer(path: Union[str, "os.PathLike[Any]"]) -> str:
    """Get the layername for a file that only contains one layer.

    If the file contains multiple layers, an exception is thrown.

    Args:
        path (PathLike): the file. |GDAL_vsi| paths are also supported.

    Raises:
        ValueError: an invalid parameter value was passed.

    Returns:
        str: the layer name

    .. |GDAL_vsi| raw:: html

        <a href="https://gdal.org/en/stable/user/virtual_file_systems.html" target="_blank">GDAL vsi</a>

    """  # noqa: E501
    try:
        datasource = gdal.OpenEx(
            str(path), nOpenFlags=gdal.OF_VECTOR | gdal.OF_READONLY | gdal.OF_SHARED
        )

        return _get_only_layer(datasource).GetName()

    except Exception as ex:
        if str(ex).endswith("No such file or directory"):
            raise FileNotFoundError(f"File not found: {path}") from ex

        ex.args = (f"get_only_layer error for {path}:\n  {ex}",)
        raise
    finally:
        datasource = None


def _get_layer(datasource: gdal.Dataset, layer: str | LayerInfo | None) -> ogr.Layer:
    """Get the gdal layer specified in the datasource.

    If layer is None and there is only one layer in the datasource, this layer is
    returned. If there are multiple layers, an exception is thrown.

    Remark: the datasource won't be opened nor closed in this function, this is the
    responsibility of the calling function!

    Args:
        datasource (gdal.Dataset): the gdal DataSet to get the only layer from.
        layer (str or LayerInfo, optional): the layer to get. If not specified, and
            there is only one layer in the file, this layer is used. Otherwise
            exception.

    Raises:
        ValueError: if the layer specified is not found, or if no or > 1 layers are
            found in the datasource.

    Returns:
        ogr.Layer: the layer.
    """
    layername = layer.name if isinstance(layer, LayerInfo) else layer
    if layername is not None:
        datasource_layer = datasource.GetLayer(layername)
        if datasource_layer is None:
            raise ValueError(f"Layer {layername} not found in file")
        return datasource_layer

    else:
        return _get_only_layer(datasource)


def _get_only_layer(datasource: gdal.Dataset) -> ogr.Layer:
    """Get the gdal layer for datasource that only contains one layer.

    Remark: the datasource won't be opened nor closed in this function, this is the
    responsibility of the calling function!

    Args:
        datasource (gdal.Dataset): the gdal DataSet to get the only layer from.

    Raises:
        ValueError: if no or > 1 layers are found in the datasource.

    Returns:
        ogr.Layer: the only layer found in the datasource.
    """
    nb_layers = datasource.GetLayerCount()
    if nb_layers == 1:
        return datasource.GetLayerByIndex(0)
    elif nb_layers == 0:
        raise ValueError("No layers found in dataset")
    else:
        # Check if there is only one spatial layer
        layers = _listlayers(datasource=datasource, only_spatial_layers=True)
        if len(layers) == 1:
            return datasource.GetLayer(layers[0])
        else:
            raise ValueError(
                f"input has > 1 layers: a layer must be specified: {layers}"
            )


def get_default_layer(path: Union[str, "os.PathLike[Any]"]) -> str:
    """Get the default layer name to be used for a layer in this file.

    This is the stem of the filepath.

    Args:
        path (Union[str,): The path to the file.

    Returns:
        str: The default layer name.
    """
    return GeoPath(path).stem


def execute_sql(
    path: Union[str, "os.PathLike[Any]"],
    sql_stmt: str,
    sql_dialect: str | None = None,
):
    """Execute a SQL statement (DML or DDL) on the file.

    To run SELECT SQL statements on a file, use :meth:`~read_file`.

    Args:
        path (PathLike): The path to the file.
        sql_stmt (str): The SQL statement to execute.
        sql_dialect (str): The SQL dialect to use:
            * None: use the native SQL dialect of the geofile.
            * 'OGRSQL': force the use of the OGR SQL dialect.
            * 'SQLITE': force the use of the SQLITE dialect.
            Defaults to None.

    See Also:
        * :func:`read_file`: read a layer to a (Geo)DataFrame, optionally using a SQL
          statement
        * :func:`update_column`: update the values of a column in the layer
        * :func:`add_column`: add a column to the layer, optionally using a SQL
          expression to fill out the values

    """
    datasource = None
    try:
        datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)
        result = datasource.ExecuteSQL(sql_stmt, dialect=sql_dialect)
        datasource.ReleaseResultSet(result)

    except Exception as ex:
        ex.args = (f"execute_sql error for {path}\n  {ex}",)
        raise
    finally:
        datasource = None


def create_spatial_index(
    path: Union[str, "os.PathLike[Any]"],
    layer: str | LayerInfo | None = None,
    cache_size_mb: int | None = 128,
    exist_ok: bool = False,
    force_rebuild: bool = False,
    no_geom_ok: bool = False,
):
    """Create a spatial index on the layer specified.

    Args:
        path (PathLike): The file path.
        layer (str or LayerInfo, optional): The layer. If not specified, and there is
            only one layer in the file, this layer is used. Otherwise exception.
        cache_size_mb (int, optional): cache memory in MB that can be used while
            creating spatial index for spatialite files (.gpkg or .sqlite). If None,
            the default cache_size from sqlite is used. Defaults to 128.
        exist_ok (bool, optional): If True and the index already exists, don't
            throw an error. Defaults to False.
        force_rebuild (bool, options): True to force rebuild even if index
            already exists. Defaults to False.
        no_geom_ok (bool, options): If True and the file doesn't have a geometry column,
            don't throw an error. Defaults to False.

    See Also:
        * :func:`has_spatial_index`: check if the layer has a spatial index
        * :func:`remove_spatial_index`: remove the spatial index from the layer

    """
    if not isinstance(layer, LayerInfo):
        layer = get_layerinfo(path, layer, raise_on_nogeom=not no_geom_ok)
    if no_geom_ok and layer.geometrycolumn is None:
        return
    if exist_ok and force_rebuild:
        raise ValueError("exist_ok and force_rebuild can't both be True")

    # Add index
    path_info = _geofileinfo.get_geofileinfo(path)
    try:
        # Use has_spatial_index up-front to check if there is an index. To avoid needing
        # R/W permissions, don't open the file in update mode yet.
        remove_spatial_index_needed = False
        if has_spatial_index(path, layer):
            if force_rebuild:
                remove_spatial_index_needed = True
            elif exist_ok:
                return
            else:
                raise RuntimeError(
                    f"spatial index already exists on {path}#{layer.name}"
                )

        # The config options need to be set before opening the file!
        with _ogr_util.set_config_options({"OGR_SQLITE_CACHE": cache_size_mb}):
            datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)
            # If index already exists, remove index or return
            if remove_spatial_index_needed:
                remove_spatial_index(path, layer, datasource=datasource)

            if path_info.is_spatialite_based:
                geometrycolumn = layer.geometrycolumn
                sql = f"SELECT CreateSpatialIndex('{layer.name}', '{geometrycolumn}')"
                result = datasource.ExecuteSQL(sql, dialect="SQLITE")
                datasource.ReleaseResultSet(result)
            else:
                result = datasource.ExecuteSQL(
                    f'CREATE SPATIAL INDEX ON "{layer.name}"'
                )
                datasource.ReleaseResultSet(result)

    except Exception as ex:
        if isinstance(ex, ValueError) and str(ex).startswith(
            "has_spatial_index not supported for"
        ):
            raise ValueError(
                f"create_spatial_index not supported for {path_info.driver}: {path}"
            ) from ex
        else:
            ex.args = (f"create_spatial_index error: {ex}, for {path}#{layer.name}",)
        raise
    finally:
        datasource = None

    if not has_spatial_index(path, layer.name):
        raise RuntimeError(f"create_spatial_index failed on {path}#{layer.name}")


def has_spatial_index(
    path: Union[str, "os.PathLike[Any]"],
    layer: str | LayerInfo | None = None,
    no_geom_ok: bool = False,
    datasource: gdal.Dataset | None = None,
) -> bool:
    """Check if the layer/column has a spatial index.

    Args:
        path (PathLike): The path to the datasource.
        layer (str, optional): The layer. Defaults to None.
        no_geom_ok (bool, options): If True and the file doesn't have a geometry column,
            don't throw an error. Defaults to False.
        datasource (gdal.Dataset, optional): the already opened gdal dataset found on
            `path`. This can be used to avoid opening and closing the file many times.
            If specified, the datasource will not be closed! Defaults to None.

    Raises:
        ValueError: an invalid parameter value was passed.

    Returns:
        bool: True if a spatial index exists, False if it doesn't exist.
    """
    datasource_specified = datasource is not None
    try:
        path_info = _geofileinfo.get_geofileinfo(path)
        if path_info.is_spatialite_based:
            if datasource is None:
                datasource = gdal.OpenEx(
                    str(path),
                    nOpenFlags=gdal.OF_VECTOR | gdal.OF_READONLY | gdal.OF_SHARED,
                )
            datasource_layer = _get_layer(datasource, layer)
            layername = datasource_layer.GetName()

            # The layer doesn't have a geometry column, so there can be no spatial index
            if datasource_layer.GetGeomType() is None:
                if no_geom_ok:
                    return False
                else:
                    raise ValueError(f"Layer {layername} has no geometry column")

            geometrycolumn = datasource_layer.GetGeometryColumn()
            if geometrycolumn == "":
                geometrycolumn = "geometry"

            sql = f"SELECT HasSpatialIndex('{layername}', '{geometrycolumn}')"
            result = datasource.ExecuteSQL(sql, dialect="SQLITE")
            has_spatial_index = result.GetNextFeature().GetField(0) == 1
            datasource.ReleaseResultSet(result)

            return has_spatial_index

        elif path_info.driver == "ESRI Shapefile":
            path_p = Path(path)
            index_path = path_p.parent / f"{path_p.stem}.qix"
            return index_path.exists()

        else:
            raise ValueError(f"has_spatial_index not supported for {path_info.driver}")
    except ValueError:
        raise
    except Exception as ex:
        layername = layer.name if isinstance(layer, LayerInfo) else layer
        ex.args = (f"has_spatial_index error: {ex}, for {path}#{layername}",)
        raise
    finally:
        if not datasource_specified:
            # Close the datasource if it wasn't passed in as a parameter
            datasource = None


def remove_spatial_index(
    path: Union[str, "os.PathLike[Any]"],
    layer: str | LayerInfo | None = None,
    datasource: gdal.Dataset | None = None,
):
    """Remove the spatial index from the layer specified.

    Args:
        path (PathLike): The file path.
        layer (str or LayerInfo, optional): The layer. If not specified, and there is
            only one layer in the file, this layer is used. Otherwise exception.
        datasource (gdal.Dataset, optional): the already opened gdal dataset (in update
            mode!) found on `path`. This can be used to avoid opening and closing the
            file many times. If specified, the datasource will not be closed! Defaults
            to None.

    See Also:
        * :func:`create_spatial_index`: create a spatial index on the layer
        * :func:`has_spatial_index`: check if the layer has a spatial index

    """
    datasource_specified = datasource is not None
    try:
        if datasource is None:
            datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)

        if not isinstance(layer, LayerInfo):
            layer = get_layerinfo(path, layer, datasource=datasource)
        path_info = _geofileinfo.get_geofileinfo(path)

        if path_info.is_spatialite_based and not str(path).lower().endswith(
            ".gpkg.zip"
        ):
            result = datasource.ExecuteSQL(
                "SELECT DisableSpatialIndex("
                f"      '{layer.name}', '{layer.geometrycolumn}')",
                dialect="SQLITE",
            )
            datasource.ReleaseResultSet(result)
        elif path_info.driver == "ESRI Shapefile":
            # DROP SPATIAL INDEX ON ... command gives an error, so just remove .qix
            path_p = Path(path)
            index_path = path_p.parent / f"{path_p.stem}.qix"
            index_path.unlink(missing_ok=True)
        else:
            raise ValueError(
                f"remove_spatial_index not supported for {path_info.driver}: {path}"
            )

    except ValueError:
        raise
    except Exception as ex:
        layer_name = layer.name if isinstance(layer, LayerInfo) else layer
        ex.args = (f"remove_spatial_index error: {ex}, for {path}#{layer_name}",)
        raise
    finally:
        if not datasource_specified:
            # Close the datasource if it wasn't passed in as a parameter
            datasource = None


def rename_layer(
    path: Union[str, "os.PathLike[Any]"], new_layer: str, layer: str | None = None
):
    """Rename the layer specified.

    Args:
        path (PathLike): The file path.
        layer (Optional[str]): The layer name. If not specified, and there is only
            one layer in the file, this layer is used. Otherwise exception.
        new_layer (str): The new layer name. If not specified, and there is only
            one layer in the file, this layer is used. Otherwise exception.
    """
    # Renaming the layer name is not possible for single layer file formats.
    path_info = _geofileinfo.get_geofileinfo(path)
    if path_info.is_singlelayer:
        raise ValueError(f"rename_layer not possible for {path_info.driver} file")

    # Now really rename
    try:
        datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)
        datasource_layer = _get_layer(datasource, layer)
        layername = datasource_layer.GetName()

        if not datasource_layer.TestCapability(gdal.ogr.OLCRename):
            raise ValueError(f"rename_layer not supported for {path}")

        # If the layer name only differs in case, we need to rename it first to a
        # temporary layer name to avoid an error.
        if layername.lower() == new_layer.lower():
            datasource_layer.Rename(f"tmp_{layername}")

        # Rename layer
        datasource_layer.Rename(new_layer)
    except Exception as ex:
        ex.args = (f"rename_layer error: {ex}, for {path}#{layer}",)
        raise
    finally:
        datasource = None


def rename_column(
    path: Union[str, "os.PathLike[Any]"],
    column_name: str,
    new_column_name: str,
    layer: str | None = None,
):
    """Rename the column specified.

    Args:
        path (PathLike): the file path.
        column_name (str): current column name.
        new_column_name (str): new column name.
        layer (Optional[str]): layer name. If not specified, and there is only
            one layer in the file, this layer is used. Otherwise exception.

    See Also:
        * :func:`add_column`: add a column to the layer
        * :func:`drop_column`: drop a column from the layer
        * :func:`get_layerinfo`: get information about the layer, including the list of
          columns
        * :func:`update_column`: update a column of the layer

    """
    # Check input parameters
    layerinfo = get_layerinfo(path, layer, raise_on_nogeom=False)
    if column_name not in layerinfo.columns and new_column_name in layerinfo.columns:
        logger.info(
            f"Column {column_name} seems to be renamed already to {new_column_name}"
        )
        return

    # Now really rename
    try:
        datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)
        datasource_layer = datasource.GetLayer(layerinfo.name)
        if not datasource_layer.TestCapability(gdal.ogr.OLCAlterFieldDefn):
            raise ValueError(f"rename_column not supported for {path}")
        layer_defn = datasource_layer.GetLayerDefn()

        # If the column name only differs in case, we need to rename it first to a
        # temporary column name to avoid an error.
        if column_name.lower() == new_column_name.lower():
            columns_lower = {column.lower() for column in layerinfo.columns}
            for index in range(9999):
                temp_column_name = f"tmp_{index}"
                if temp_column_name not in columns_lower:
                    break
            field_index = layer_defn.GetFieldIndex(column_name)
            field_defn = layer_defn.GetFieldDefn(field_index)
            renamed_field = gdal.ogr.FieldDefn(temp_column_name, field_defn.GetType())
            datasource_layer.AlterFieldDefn(
                field_index,
                renamed_field,
                gdal.ogr.ALTER_NAME_FLAG,
            )
            column_name = f"{temp_column_name}"

        # Rename column
        field_index = layer_defn.GetFieldIndex(column_name)
        field_defn = layer_defn.GetFieldDefn(field_index)
        renamed_field = gdal.ogr.FieldDefn(new_column_name, field_defn.GetType())
        datasource_layer.AlterFieldDefn(
            field_index,
            renamed_field,
            gdal.ogr.ALTER_NAME_FLAG,
        )

    except Exception as ex:
        # If it is the ValueError thrown above, just raise
        if isinstance(ex, ValueError) and str(ex).startswith(
            "rename_column not supported for"
        ):
            raise

        # It is another error... add some more context
        ex.args = (f"rename_column error: {ex} for {path}#{layerinfo.name}",)
        raise
    finally:
        datasource = None


class DataType(enum.Enum):
    """This enum defines the standard data types that can be used for columns."""

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
    type: DataType | str,
    expression: str | float | None = None,
    expression_dialect: str | None = None,
    layer: str | None = None,
    force_update: bool = False,
    width: int | None = None,
):
    """Add a column to a layer of the geofile.

    You can specify an `expression` to use to fill out the value of the column. For file
    formats that support transactions, the column won't be added if updating the value
    fails.

    Args:
        path (PathLike): Path to the geofile.
        name (str): Name for the new column.
        type (str): Column type of the new column. For GPKG, the supported data types
            can be found in the |gpkg_specs_datatypes|.
        expression (str; int or float, optional): SQL expression to use to fill out the
            column value. It should be in SQLite syntax and |spatialite_reference_link|
            functions can be used. Defaults to None.
        expression_dialect (str, optional): SQL dialect used for the expression.
        layer (str, optional): The layer name. If None and the geofile
            has only one layer, that layer is used. Defaults to None.
        force_update (bool, optional): If the column already exists, execute
            the update anyway. Defaults to False.
        width (int, optional): the width of the field.

    See Also:
        * :func:`drop_column`: drop a column from the layer
        * :func:`get_layerinfo`: get information about the layer, including the list of
          columns
        * :func:`rename_column`: rename a column in the layer
        * :func:`update_column`: update a column of the layer

    Examples:
        A typical example is to add a column with the area of the geometry to the layer.
        This uses the `ST_Area` function from spatialite (|spatialite_reference_link|):

        .. code-block:: python

            gfo.add_column(
                "file.gpkg", name="area", type="REAL", expression="ST_Area(geom)",
            )


        For string/text type columns, not that in SQL it is mandatory to use single
        quotes around the string value. For example:

        .. code-block:: python

            gfo.add_column(
                "file.gpkg", type="TEXT", name="text_column", expression="'Hello!'"
            )


        You can also use more complex SQL expressions like CASE WHEN statements:

        .. code-block:: python

            expression = '''
                CASE
                    WHEN "type" = 'A' THEN 1
                    WHEN "type" = 'B' THEN 2
                    ELSE 3
                END
            '''
            gfo.add_column("file.gpkg", "type_id", "INT", expression=expression)


    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    .. |gpkg_specs_datatypes| raw:: html

        <a href="https://www.geopackage.org/spec/#:~:text=Table%201.%20GeoPackage%20Data%20Types" target="_blank">Geopackage specification</a>

    """  # noqa: E501
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
        elif type_lower == "integer64":
            type_str = "INTEGER"
        else:
            type_str = type

    start = time.perf_counter()
    layerinfo = get_layerinfo(path, layer, raise_on_nogeom=False)
    layer = layerinfo.name

    # Go!
    datasource = None
    try:
        # If column doesn't exist yet, create it
        columns_upper = [column.upper() for column in layerinfo.columns]
        if name.upper() not in columns_upper:
            logger.info(f"Add column {name} to {path}#{layer}")
            width_str = f"({width})" if width is not None else ""
            sql_stmt = (
                f'ALTER TABLE "{layer}" ADD COLUMN "{name}" {type_str}{width_str}'
            )
            datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)
            _ogr_util.StartTransaction(datasource)
            datasource.ExecuteSQL(sql_stmt)
        else:
            logger.warning(f"Column {name} existed already in {path}#{layer}")

        # If an expression was provided and update can be done, go for it...
        if expression is not None and (
            name not in layerinfo.columns or force_update is True
        ):
            if datasource is None:
                datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)
                _ogr_util.StartTransaction(datasource)
            sql_stmt = f'UPDATE "{layer}" SET "{name}" = {expression}'
            datasource.ExecuteSQL(sql_stmt, dialect=expression_dialect)

        _ogr_util.CommitTransaction(datasource)

    except Exception as ex:
        _ogr_util.RollbackTransaction(datasource)
        ex.args = (f"add_column error for {path}#{layer}:\n  {ex}",)
        raise
    finally:
        datasource = None

        # Log time taken if it was slow.
        took = time.perf_counter() - start
        if took > 2:  # pragma: no cover
            logger.info(f"Ready, add_column of {name} took {took:.2f}")


def drop_column(
    path: Union[str, "os.PathLike[Any]"], column_name: str, layer: str | None = None
):
    """Drop the column specified.

    Args:
        path (PathLike): The file path.
        column_name (str): the column name.
        layer (Optional[str]): The layer name. If not specified, and there is only
            one layer in the file, this layer is used. Otherwise a ValueError is
            raised.

    See Also:
        * :func:`add_column`: add a column to the layer
        * :func:`get_layerinfo`: get information about the layer, including the list of
          columns
        * :func:`rename_column`: rename a column in the layer
        * :func:`update_column`: update a column of the layer
    """
    # Check input parameters
    layerinfo = get_layerinfo(path, layer, raise_on_nogeom=False)
    layer = layerinfo.name
    if column_name not in layerinfo.columns:
        logger.info(f"Column {column_name} not present so cannot be dropped.")
        return

    # Now really rename
    try:
        datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)
        sql_stmt = f'ALTER TABLE "{layer}" DROP COLUMN "{column_name}"'
        result = datasource.ExecuteSQL(sql_stmt)
        datasource.ReleaseResultSet(result)

    except Exception as ex:
        ex.args = (f"drop_column error for {path}#{layer}:\n  {ex}",)
        raise
    finally:
        datasource = None


def update_column(
    path: Union[str, "os.PathLike[Any]"],
    name: str,
    expression: str,
    layer: str | None = None,
    where: str | None = None,
):
    """Update a column from a layer of the geofile.

    Args:
        path (PathLike): Path to the geofile.
        name (str): Name for the new column
        expression (str): SQL expression to use to update the column value. It should be
            in SQLite syntax and |spatialite_reference_link| functions can be used.
            Defaults to None.
        layer (str, optional): The layer name. If None and the geofile
            has only one layer, that layer is used. Defaults to None.
        where (str, optional): SQL where clause to restrict the rows that will
            be updated. Defaults to None.

    See Also:
        * :func:`add_column`: add a column to the layer
        * :func:`drop_column`: drop a column from the layer
        * :func:`get_layerinfo`: get information about the layer, including the list of
          columns
        * :func:`rename_column`: rename a column in the layer

    Examples:
        A typical example is to update an "area" column after doing an operation on the
        geometry. This uses the `ST_Area` function from spatialite
        (|spatialite_reference_link|):

        .. code-block:: python

            gfo.update_column("file.gpkg", name="area", expression="ST_Area(geom)")


        For string/text type columns, not that in SQL it is mandatory to use single
        quotes around the string value. For example:

        .. code-block:: python

            gfo.update_column("file.gpkg", name="text_column", expression="'Hello!'")


        You can also use more complex SQL expressions like CASE WHEN statements:

        .. code-block:: python

            expression = '''
                CASE
                    WHEN "type" = 'A' THEN 1
                    WHEN "type" = 'B' THEN 2
                    ELSE 3
                END
            '''
            gfo.update_column("file.gpkg", name="type_id", expression=expression)


    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>
    """  # noqa: E501
    # Init
    logger.info(f"Update column {name} in {path}#{layer}")

    start = time.perf_counter()
    layerinfo = get_layerinfo(path, layer)
    columns_upper = [column.upper() for column in layerinfo.columns]
    if layerinfo.geometrycolumn is not None:
        columns_upper.append(layerinfo.geometrycolumn.upper())
    if name.upper() not in columns_upper:
        # If column doesn't exist yet, error!
        raise ValueError(f"Column {name} doesn't exist in {path}#{layerinfo.name}")

    # Go!
    try:
        datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)
        sqlite_stmt = f'UPDATE "{layerinfo.name}" SET "{name}" = {expression}'
        if where is not None:
            sqlite_stmt += f"\n WHERE {where}"
        result = datasource.ExecuteSQL(sqlite_stmt, dialect="SQLITE")
        datasource.ReleaseResultSet(result)

    except Exception as ex:
        ex.args = (f"update_column error for {path}#{layerinfo.name}:\n  {ex}",)
        raise
    finally:
        datasource = None

        # Log time taken if it was slow.
        took = time.perf_counter() - start
        if took > 2:  # pragma: no cover
            logger.info(f"Ready, update_column of {name} took {took:.2f}")


def read_file(
    path: Union[str, "os.PathLike[Any]"],
    layer: str | None = None,
    columns: Iterable[str] | None = None,
    bbox=None,
    rows=None,
    where: str | None = None,
    sql_stmt: str | None = None,
    sql_dialect: Literal["SQLITE", "OGRSQL"] | None = None,
    ignore_geometry: bool = False,
    fid_as_index: bool = False,
    **kwargs,
) -> gpd.GeoDataFrame:
    """Reads a file to a geopandas GeoDataframe.

    The file format is detected based on the filepath extension.

    If ``sql_stmt`` is specified, the sqlite query can contain following placeholders
    that will be automatically replaced for you:

      * {geometrycolumn}: the column where the primary geometry is stored.
      * {columns_to_select_str}: if ``columns`` is not None, those columns,
        otherwise all columns of the layer.
      * {input_layer}: the layer name of the input layer.

    Example SQL statement with placeholders:
    ::

        SELECT {geometrycolumn}
              {columns_to_select_str}
          FROM "{input_layer}" layer

    The underlying library used to read the file can be choosen using the
    "GFO_IO_ENGINE" environment variable. Possible values are "fiona" and "pyogrio".
    This option is created as a temporary fallback to "fiona" for cases where "pyogrio"
    gives issues, so please report issues if they are encountered. In the future support
    for the "fiona" engine most likely will be removed. Default engine is "pyogrio".

    When a file with CURVE geometries is read, they are transformed on the fly to LINEAR
    geometries, as shapely/geopandas doesn't support CURVE geometries.

    Args:
        path (file path): path to the file to read from. |GDAL_vsi|_ paths are also
            supported.
        layer (str, optional): The layer to read. If None and there is only one layer in
            the file it is read, otherwise an error is thrown. Defaults to None.
        columns (Iterable[str], optional): The (non-geometry) columns to read will
            be returned in the order specified. If None, all standard columns are read.
            In addition to standard columns, it is also possible
            to specify "fid", a unique index available in all input files. Note that the
            "fid" will be aliased eg. to "fid_1". Defaults to None.
        bbox (Tuple, optional): return only geometries intersecting this bbox.
            Defaults to None, then all rows are read.
        rows (slice, optional): return only the rows specified. For many file formats
            (e.g. Geopackage) this is slow, so using e.g. a where filter instead is
            recommended. Defaults to None, then all rows are returned.
        where (str, optional): where clause to filter features in layer by attribute
            values. If the datasource natively supports sql, its specific SQL dialect
            should be used (eg. SQLite and GeoPackage: `SQLITE`_, PostgreSQL). If it
            doesn't, the `OGRSQL WHERE`_ syntax should be used. Note that it is not
            possible to overrule the SQL dialect, this is only possible when you use the
            SQL parameter. Examples: ``"ISO_A3 = 'CAN'"``,
            ``"POP_EST > 10000000 AND POP_EST < 100000000"``. Defaults to None.
        sql_stmt (str): SQL statement to use. Only supported with "pyogrio" engine.
        sql_dialect (str, optional): SQL dialect used. Options are None, "SQLITE" or
            "OGRSQL". If None, for data sources with explicit SQL support the statement
            is processed by the default SQL engine (e.g. for Geopackage and Spatialite
            this is "SQLITE"). For data sources without native SQL support (e.g. .shp),
            the "OGRSQL" dialect is the default. If the "SQLITE" dialect is specified,
            |spatialite_reference_link| functions can also be used. Defaults to None.
        ignore_geometry (bool, optional): True not to read/return the geometry.
            Defaults to False.
        fid_as_index (bool, optional): If True, will use the FIDs of the features that
            were read as the index of the GeoDataFrame. May start at 0 or 1 depending on
            the driver. Defaults to False.
        **kwargs: All additional parameters will be passed on to the io-engine used
            ("pyogrio" or "fiona").

    Raises:
        ValueError: an invalid parameter value was passed.

    Returns:
        gpd.GeoDataFrame: the data read.

    .. |OGRSQL WHERE| raw:: html

        <a href="https://gdal.org/user/ogr_sql_dialect.html#where" target="_blank">OGRSQL WHERE</a>

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    .. |GDAL_vsi| raw:: html

        <a href="https://gdal.org/en/stable/user/virtual_file_systems.html" target="_blank">GDAL vsi</a>

    """  # noqa: E501
    result_gdf = _read_file_base(
        path=path,
        layer=layer,
        columns=columns,
        bbox=bbox,
        rows=rows,
        where=where,
        sql_stmt=sql_stmt,
        sql_dialect=sql_dialect,
        ignore_geometry=ignore_geometry,
        fid_as_index=fid_as_index,
        **kwargs,
    )

    # No assert to keep backwards compatibility
    return result_gdf


def read_file_nogeom(
    path: Union[str, "os.PathLike[Any]"],
    layer: str | None = None,
    columns: Iterable[str] | None = None,
    bbox=None,
    rows=None,
    sql_stmt: str | None = None,
    sql_dialect: Literal["SQLITE", "OGRSQL"] | None = None,
    fid_as_index: bool = False,
) -> pd.DataFrame:
    """DEPRECATED: please use read_file with option ignore_geometry=True."""
    warnings.warn(
        "read_file_nogeom is deprecated: use read_file with ignore_geometry=True",
        FutureWarning,
        stacklevel=2,
    )
    result_gdf = _read_file_base(
        path=path,
        layer=layer,
        columns=columns,
        bbox=bbox,
        rows=rows,
        sql_stmt=sql_stmt,
        sql_dialect=sql_dialect,
        ignore_geometry=True,
        fid_as_index=fid_as_index,
    )
    assert isinstance(result_gdf, pd.DataFrame)
    return result_gdf


def _read_file_base(
    path: Union[str, "os.PathLike[Any]"],
    layer: str | None = None,
    columns: Iterable[str] | None = None,
    bbox=None,
    rows=None,
    where: str | None = None,
    sql_stmt: str | None = None,
    sql_dialect: Literal["SQLITE", "OGRSQL"] | None = None,
    ignore_geometry: bool = False,
    fid_as_index: bool = False,
    **kwargs,
) -> pd.DataFrame | gpd.GeoDataFrame:
    """Reads a file to a pandas Dataframe."""
    # Check if the fid column needs to be read as column via the columns parameter
    fid_as_column = False
    if isinstance(columns, str):
        # If a string is passed, convert to list
        columns = [columns]
    if columns is not None:
        if "fid" in [column.lower() for column in columns]:
            fid_as_column = True

    # Read with the engine specified
    engine = ConfigOptions.io_engine
    if engine == "pyogrio":
        gdf = _read_file_base_pyogrio(
            path=path,
            layer=layer,
            columns=columns,
            bbox=bbox,
            rows=rows,
            where=where,
            sql_stmt=sql_stmt,
            sql_dialect=sql_dialect,
            ignore_geometry=ignore_geometry,
            fid_as_index=fid_as_index or fid_as_column,
            **kwargs,
        )
    elif engine == "fiona":
        gdf = _read_file_base_fiona(
            path=path,
            layer=layer,
            columns=columns,
            bbox=bbox,
            rows=rows,
            where=where,
            sql_stmt=sql_stmt,
            sql_dialect=sql_dialect,
            ignore_geometry=ignore_geometry,
            fid_as_index=fid_as_index or fid_as_column,
            **kwargs,
        )
    else:
        raise ValueError(f"Unsupported engine: {engine}")

    # Copy the index to a column if needed...
    if fid_as_column:
        gdf["fid"] = gdf.index
        if not fid_as_index:
            gdf = gdf.reset_index(drop=True)

    return gdf


def _read_file_base_fiona(
    path: Union[str, "os.PathLike[Any]"],
    layer: str | None = None,
    columns: Iterable[str] | None = None,
    bbox=None,
    rows=None,
    where: str | None = None,
    sql_stmt: str | None = None,
    sql_dialect: Literal["SQLITE", "OGRSQL"] | None = None,
    ignore_geometry: bool = False,
    fid_as_index: bool = False,
    **kwargs,
) -> pd.DataFrame | gpd.GeoDataFrame:
    """Reads a file to a pandas Dataframe using fiona.

    The "fiona" IO engine is deprecated and will be removed in the future.
    """
    warnings.warn(
        "Using GFO_IO_ENGINE=fiona is deprecated. In a future version this will be"
        "ignored.",
        FutureWarning,
        stacklevel=4,
    )

    if ignore_geometry and columns == []:
        return pd.DataFrame()
    if sql_stmt is not None:
        raise ValueError("sql_stmt is not supported with fiona engine")

    # If no layer name specified, check if there is only one layer in the file.
    if layer is None:
        layer = get_only_layer(path)

    # VERY DIRTY hack to get the fid

    tmp_fid_path = None
    try:
        if fid_as_index:
            # Make a copy/copy input file to geopackage,
            # as we will add an fid/rowd column
            tmp_fid_path = Path(tempfile.mkdtemp()) / f"{Path(path).stem}.gpkg"
            path_info = _geofileinfo.get_geofileinfo(path)
            if path_info.driver == "GPKG":
                copy(path, tmp_fid_path, keep_permissions=False)
            else:
                copy_layer(path, tmp_fid_path)
            fid_column = get_layerinfo(
                tmp_fid_path, layer=layer, raise_on_nogeom=False
            ).fid_column
            if path_info.is_fid_zerobased:
                # fid in shapefile is 0 based, so fid-1
                add_column(
                    tmp_fid_path,
                    "__TMP_GEOFILEOPS_FID",
                    "INTEGER",
                    f"{fid_column}-1",
                    layer=layer,
                )
            else:
                add_column(
                    tmp_fid_path,
                    "__TMP_GEOFILEOPS_FID",
                    "INTEGER",
                    fid_column,
                    layer=layer,
                )

            path = tmp_fid_path

        # Checking if field/column names should be read is case sensitive in fiona, so
        # make sure the column names specified have the same casing.
        columns_prepared = None
        if columns is not None:
            layerinfo = get_layerinfo(path, layer=layer, raise_on_nogeom=False)
            columns_upper_lookup = {column.upper(): column for column in columns}
            columns_prepared = {
                column: columns_upper_lookup[column.upper()]
                for column in layerinfo.columns
                if column.upper() in columns_upper_lookup
            }

        # Read...
        columns_list = None if columns_prepared is None else list(columns_prepared)
        result_gdf = gpd.read_file(
            str(path),
            layer=layer,
            bbox=bbox,
            rows=rows,
            columns=columns_list,
            where=where,
            sql=sql_stmt,
            sql_dialect=sql_dialect,
            ignore_geometry=ignore_geometry,
            **kwargs,
        )

        # Set the index to the backed-up fid
        if fid_as_index:
            result_gdf = result_gdf.set_index("__TMP_GEOFILEOPS_FID")
            result_gdf.index.name = "fid"

        # Reorder columns + change casing so they are the same as columns parameter
        if columns_prepared is not None and len(columns_prepared) > 0:
            columns_to_keep = list(columns_prepared)
            if "geometry" in result_gdf.columns:
                columns_to_keep += ["geometry"]
            result_gdf = result_gdf[columns_to_keep]
            result_gdf = result_gdf.rename(columns=columns_prepared)

        # Starting from fiona 1.9, string columns with all None values are read as being
        # float columns. Convert them to object type.
        float_cols = list(result_gdf.select_dtypes(["float64"]).columns)
        if len(float_cols) > 0:
            # Check for all float columns found if they should be object columns instead
            if fiona is None:
                raise ImportError(
                    "fiona is not installed, but needed to read the file with"
                    " GFO_IO_ENGINE=fiona. Please install fiona."
                )

            with fiona.open(path, layer=layer) as collection:
                assert collection.schema is not None
                properties = collection.schema["properties"]
                for col in float_cols:
                    if col in properties and properties[col].startswith("str"):
                        result_gdf[col] = (
                            result_gdf[col].astype(object).replace(np.nan, None)
                        )
    finally:
        if (
            tmp_fid_path is not None
            and ConfigOptions.remove_temp_files
            and tmp_fid_path.parent.exists()
        ):
            shutil.rmtree(tmp_fid_path.parent, ignore_errors=True)

    return result_gdf


def _read_file_base_pyogrio(
    path: Union[str, "os.PathLike[Any]"],
    layer: str | LayerInfo | None = None,
    columns: Iterable[str] | None = None,
    bbox=None,
    rows=None,
    where: str | None = None,
    sql_stmt: str | None = None,
    sql_dialect: Literal["SQLITE", "OGRSQL"] | None = None,
    ignore_geometry: bool = False,
    fid_as_index: bool = False,
    **kwargs,
) -> pd.DataFrame | gpd.GeoDataFrame:
    """Reads a file to a pandas Dataframe using pyogrio."""
    # Convert rows slice object to pyogrio parameters
    if rows is not None:
        skip_features = rows.start
        max_features = rows.stop - rows.start
    else:
        skip_features = 0
        max_features = None
    # Arrow doesn't support filtering rows like this
    # use_arrow = True if rows is None else False

    # If no sql_stmt specified
    columns_prepared = None
    if sql_stmt is None:
        # Checking if column names should be read is case sensitive in pyogrio, so
        # make sure the column names specified have the same casing.
        if columns is not None:
            if not isinstance(layer, LayerInfo):
                layer = get_layerinfo(path, layer, raise_on_nogeom=False)
            columns_upper_lookup = {column.upper(): column for column in columns}
            columns_prepared = {
                column: columns_upper_lookup[column.upper()]
                for column in layer.columns
                if column.upper() in columns_upper_lookup
            }

        # If no sql + no layer specified, there should be only one layer in the file.
        if layer is None:
            layer = get_only_layer(path)
    else:
        # Fill out placeholders, keep columns_prepared None because column filtering
        # should happen in sql_stmt.
        sql_stmt = _fill_out_sql_placeholders(
            path=path, layer=layer, sql_stmt=sql_stmt, columns=columns
        )
        # Specifying a layer as well as an SQL statement in pyogrio is not supported.
        layer = None

    # Read!
    columns_list = None if columns_prepared is None else list(columns_prepared)
    layername = layer.name if isinstance(layer, LayerInfo) else layer
    result_gdf = pyogrio.read_dataframe(
        path,
        layer=layername,
        columns=columns_list,
        bbox=bbox,
        skip_features=skip_features,
        max_features=max_features,
        where=where,
        sql=sql_stmt,
        sql_dialect=sql_dialect,
        read_geometry=not ignore_geometry,
        fid_as_index=fid_as_index,
        **kwargs,
    )

    # Reorder columns + change casing so they are the same as columns parameter
    if columns_prepared is not None and len(columns_prepared) > 0:
        columns_to_keep = list(columns_prepared)
        if not isinstance(layer, LayerInfo):
            layer = get_layerinfo(path, raise_on_nogeom=False)
        if layer.geometrycolumn is not None and not ignore_geometry:
            columns_to_keep += ["geometry"]
        result_gdf = result_gdf[columns_to_keep]
        result_gdf = result_gdf.rename(columns=columns_prepared)

    # Cast columns that are of object type, but contain datetime.date or datetime.date
    # to proper datetime64 columns.
    if len(result_gdf) > 0:
        for column in result_gdf.select_dtypes(include=["object"]):
            if isinstance(result_gdf[column].iloc[0], date | datetime):
                result_gdf[column] = pd.to_datetime(result_gdf[column])

    assert isinstance(result_gdf, gpd.GeoDataFrame | pd.DataFrame)
    return result_gdf


def _fill_out_sql_placeholders(
    path: Union[str, "os.PathLike[Any]"],
    layer: str | LayerInfo | None,
    sql_stmt: str,
    columns: Iterable[str] | None,
) -> str:
    # Fill out placeholders in the sql_stmt if needed:
    placeholders = [
        name for _, name, _, _ in string.Formatter().parse(sql_stmt) if name
    ]
    format_kwargs: dict[str, Any] = {}
    for placeholder in placeholders:
        if not isinstance(layer, LayerInfo):
            layer = get_layerinfo(path, layer, raise_on_nogeom=False)

        if placeholder == "input_layer":
            format_kwargs[placeholder] = layer.name
        elif placeholder == "geometrycolumn":
            format_kwargs[placeholder] = layer.geometrycolumn
        elif placeholder == "columns_to_select_str":
            columns_asked = None if columns is None else list(columns)
            formatter = _ogr_sql_util.ColumnFormatter(
                columns_asked=columns_asked,
                columns_in_layer=layer.columns,
                fid_column=layer.fid_column,
            )
            format_kwargs[placeholder] = formatter.prefixed_aliased()

        else:
            raise ValueError(
                f"unknown placeholder {placeholder} in sql_stmt: {sql_stmt}"
            )

    if len(format_kwargs) > 0:
        sql_stmt = sql_stmt.format(**format_kwargs)
    return sql_stmt


def read_file_sql(
    path: Union[str, "os.PathLike[Any]"],
    sql_stmt: str,
    sql_dialect: Literal["SQLITE", "OGRSQL"] | None = "SQLITE",
    layer: str | None = None,
    ignore_geometry: bool = False,
) -> pd.DataFrame | gpd.GeoDataFrame:
    """DEPRECATED: Reads a file using an SQL statement.

    Args:
        path (file path): path to the file to read from
        sql_stmt (str): SQL statement to use
        sql_dialect (str, optional): SQL dialect used. Defaults to 'SQLITE'.
        layer (str, optional): The layer to read. If no layer is specified,
            reads the only layer in the file or throws an Exception.
        ignore_geometry (bool, optional): True not to read/return the geomatry.
            Defaults to False.

    Returns:
        Union[pd.DataFrame, gpd.GeoDataFrame]: The data read.
    """
    warnings.warn(
        'read_file_sql is deprecated: use read_file! Mind: sql_dialect is not "SQLITE" '
        "by default there!",
        FutureWarning,
        stacklevel=2,
    )

    # Run
    return _read_file_base(
        path,
        sql_stmt=sql_stmt,
        sql_dialect=sql_dialect,
        layer=layer,
        ignore_geometry=ignore_geometry,
    )


def to_file(
    gdf: pd.DataFrame | gpd.GeoDataFrame,
    path: Union[str, "os.PathLike[Any]"],
    layer: str | None = None,
    force_output_geometrytype: GeometryType | str | None = None,
    force_multitype: bool = False,
    append: bool = False,
    append_timeout_s: int = 600,
    index: bool | None = None,
    create_spatial_index: bool | None = None,
    **kwargs,
):
    """Writes a pandas dataframe to file.

    The fileformat is detected based on the filepath extension.

    The underlying library used to write the file can be choosen using the
    "GFO_IO_ENGINE" environment variable. Possible values are "fiona" and "pyogrio", but
    using "fiona" is deprecated and will be ignored in a future version. The default
    engine is "pyogrio".

    Args:
        gdf (gpd.GeoDataFrame): The GeoDataFrame to export to file.
        path (Union[str,): The file path to write to. |GDAL_vsi| paths can be used for
            handlers with write support.
        layer (str, optional): The layer to read. If no layer is specified,
            reads the only layer in the file or throws an Exception.
        force_output_geometrytype (Union[GeometryType, str], optional): Geometry type
            to (try to) force the output to. Defaults to None.
            Mark: compared to other functions in gfo with this parameter, the behaviour
            here is limited to the following:
                - for empty input gdf's, a standard geometry type (eg. Polygon,...) can
                  be used to force the geometry column to be of that type.
                - if force_output_geometrytype is a MULTI type, parameter
                  force_multitype becomes True.
        force_multitype (bool, optional): force the geometry type to a multitype
            for file types that require one geometrytype per layer.
            Defaults to False.
        append (bool, optional): True to append to the file/layer if it already exists.
            If it doesn't exist yet, it is created. Defaults to False.
        append_timeout_s (int, optional): The maximum timeout to wait when the
            output file is already being written to by another process.
            Defaults to 600.
        index (bool, optional): If True, write index into one or more columns (for
            MultiIndex). None writes the index into one or more columns only if the
            index is named, is a MultiIndex, or has a non-integer data type.
            If False, no index is written. Defaults to None.
        create_spatial_index (bool, optional): True to force creation of spatial index,
            False to avoid creation. None leads to the default behaviour of gdal.
            Defaults to None.
        **kwargs: All additional parameters will be passed on to the io-engine used
            ("pyogrio" or "fiona").

    Raises:
        ValueError: an invalid parameter value was passed.
        RuntimeError: timeout was reached while trying to append data to path.

    .. |GDAL_vsi| raw:: html

        <a href="https://gdal.org/en/stable/user/virtual_file_systems.html" target="_blank">GDAL vsi</a>

    """  # noqa: E501
    # Check input parameters
    # ----------------------
    # If no layer name specified, determine one
    if layer is None:
        if append and _vsi_exists(path):
            layer = get_only_layer(path)
        else:
            layer = get_default_layer(path)

    # If force_output_geometrytype is a string, check if it is a "standard" geometry
    # type, as GDAL also supports special geometry types like "PROMOTE_TO_MULTI"
    if isinstance(force_output_geometrytype, str):
        force_output_geometrytype = force_output_geometrytype.upper()
        try:
            # Verify if it is a "standard" geometry type, as GDAL also supports
            # special geometry types like "PROMOTE_TO_MULTI"
            force_output_geometrytype = GeometryType[force_output_geometrytype]
        except Exception:
            raise ValueError(
                f"Unsupported force_output_geometrytype: {force_output_geometrytype}"
            ) from None
    if force_output_geometrytype is not None and force_output_geometrytype.is_multitype:  # type: ignore[union-attr]
        force_multitype = True

    engine = ConfigOptions.io_engine

    # Write file with the correct engine
    if engine == "pyogrio":
        return _to_file_pyogrio(
            gdf=gdf,
            path=path,
            layer=layer,
            force_output_geometrytype=force_output_geometrytype,
            force_multitype=force_multitype,
            append=append,
            append_timeout_s=append_timeout_s,
            index=index,
            create_spatial_index=create_spatial_index,
            **kwargs,
        )
    elif engine == "fiona":
        return _to_file_fiona(
            gdf=gdf,
            path=path,
            layer=layer,
            force_output_geometrytype=force_output_geometrytype,
            force_multitype=force_multitype,
            append=append,
            append_timeout_s=append_timeout_s,
            index=index,
            create_spatial_index=create_spatial_index,
            **kwargs,
        )
    else:
        raise ValueError(f"Unsupported engine: {engine}")


def _to_file_fiona(
    gdf: pd.DataFrame | gpd.GeoDataFrame,
    path: Union[str, "os.PathLike[Any]"],
    layer: str,
    force_output_geometrytype: GeometryType | str | None = None,
    force_multitype: bool = False,
    append: bool = False,
    append_timeout_s: int = 600,
    index: bool | None = None,
    create_spatial_index: bool | None = None,
    **kwargs,
):
    """Writes a pandas dataframe to file using fiona.

    The "fiona" IO engine is deprecated and will be removed in the future.
    """
    warnings.warn(
        "Using GFO_IO_ENGINE=fiona is deprecated. In a future version this will be"
        "ignored.",
        FutureWarning,
        stacklevel=3,
    )
    if append and not _vsi_exists(path):
        append = False

    # Shapefile doesn't support datetime columns, so first cast them to string
    if Path(path).suffix.lower() in [".shp", ".dbf"]:
        gdf = gdf.copy()
        # Columns that have a proper datetime64 type
        for column in gdf.select_dtypes(include=["datetime64"]):
            gdf[column] = gdf[column].astype(str)

        # Columns that are of object type, but contain datetime.date or datetime.date
        # type data instead of strings.
        if len(gdf) > 0:
            for column in gdf.select_dtypes(include=["object"]):
                if isinstance(gdf[column][0], (date | datetime)):
                    gdf[column] = gdf[column].astype(str)

    # Handle some specific cases where the file schema needs to be manipulated.
    schema = None
    if not isinstance(gdf, gpd.GeoDataFrame) or (
        isinstance(gdf, gpd.GeoDataFrame) and "geometry" not in gdf.columns
    ):
        # No geometry, so prepare to be written as attribute table: add geometry column
        # with None geometry type in schema
        # With older versions of pandas and/or geopandas, without the copy the actual
        # gdf is changed and returned which isn't OK.
        # This caused test_to_file with .csv to fail for the "minimal" CI env.
        gdf = gpd.GeoDataFrame(gdf.copy(), geometry=[None for i in gdf.index])

        schema = gpd_io_file.infer_schema(gdf)
        schema["geometry"] = "None"
        create_spatial_index = None
    elif (
        len(gdf) == 0
        and force_output_geometrytype is not None
        and isinstance(force_output_geometrytype, GeometryType)
    ):
        # If the gdf is empty but a geometry type is specified, use the specified type
        schema = gpd_io_file.infer_schema(gdf)
        # Geometry type must be in camelcase for fiona
        schema["geometry"] = force_output_geometrytype.name_camelcase
    assert isinstance(gdf, gpd.GeoDataFrame)

    # Convert force_output_geometrytype to string to simplify code afterwards
    if isinstance(force_output_geometrytype, GeometryType):
        force_output_geometrytype = force_output_geometrytype.name

    # No the file can actually be written
    # -----------------------------------
    # Fiona doesn't support the output geometrytype parameter as used in gdal, so as a
    # lightweight implementation just set force
    def write_to_file(
        gdf: gpd.GeoDataFrame,
        path: Union[str, "os.PathLike[Any]"],
        layer: str,
        index: bool | None = None,
        force_output_geometrytype: str | None = None,
        force_multitype: bool = False,
        append: bool = False,
        schema: dict | None = None,
        create_spatial_index: bool | None = None,
        **kwargs,
    ):
        # Prepare args for to_file
        if append:
            mode = "a"
        else:
            mode = "w"

        kwargs["engine"] = "fiona"
        kwargs["mode"] = mode
        drivername = _geofileinfo.get_driver(path)
        kwargs["driver"] = drivername
        kwargs["index"] = index
        if create_spatial_index is not None:
            kwargs["SPATIAL_INDEX"] = create_spatial_index
        if force_output_geometrytype is not None:
            kwargs["geometrytype"] = force_output_geometrytype
        if schema is not None:
            kwargs["schema"] = schema

        # Now we can write
        if drivername == "GPKG":
            # Try to harmonize the geometrytype to one (multi)type, as GPKG
            # doesn't like > 1 type in a layer
            if schema is None or (len(gdf) > 0 and schema["geometry"] != "None"):
                gdf = gdf.copy()
                gdf.geometry = _geoseries_util.harmonize_geometrytypes(
                    gdf.geometry, force_multitype=force_multitype
                )
            gdf.to_file(str(path), layer=layer, **kwargs)
        else:
            gdf.to_file(str(path), layer=layer, **kwargs)

    # If no append, just write to output path
    if not append:
        write_to_file(
            gdf=gdf,
            path=path,
            layer=layer,
            index=index,
            force_output_geometrytype=force_output_geometrytype,
            force_multitype=force_multitype,
            append=append,
            schema=schema,
            create_spatial_index=create_spatial_index,
            **kwargs,
        )
    else:
        path_info = _geofileinfo.get_geofileinfo(path)

        # Files don't typically support having multiple processes writing
        # simultanously to them, so use lock file to synchronize access.
        lockfile = Path(f"{path!s}.lock")
        start_time = datetime.now()
        ready = False
        while not ready:
            if _io_util.create_file_atomic(lockfile) is True:
                try:
                    write_to_file(
                        gdf=gdf,
                        path=path,
                        layer=layer,
                        index=index,
                        force_output_geometrytype=force_output_geometrytype,
                        force_multitype=force_multitype,
                        append=True,
                        schema=schema,
                        create_spatial_index=create_spatial_index,
                        **kwargs,
                    )
                except Exception as ex:
                    # If sqlite output file locked, also retry
                    if path_info.is_spatialite_based and str(ex) not in [
                        "database is locked",
                        "attempt to write a readonly database",
                    ]:
                        raise ex
                finally:
                    ready = True
                    lockfile.unlink()
            else:
                time_waiting = (datetime.now() - start_time).total_seconds()
                if time_waiting > append_timeout_s:
                    raise RuntimeError(
                        f"to_file timeout of {append_timeout_s} reached, stop append "
                        f"to {path}!"
                    )

            # Sleep for a second before trying again
            time.sleep(1)


def _to_file_pyogrio(
    gdf: gpd.GeoDataFrame,
    path: Union[str, "os.PathLike[Any]"],
    layer: str,
    force_output_geometrytype: GeometryType | str | None = None,
    force_multitype: bool = False,
    append: bool = False,
    append_timeout_s: int = 600,
    index: bool | None = None,
    create_spatial_index: bool | None = None,
    **kwargs,
):
    """Writes a pandas dataframe to file using pyogrio."""
    # Check upfront if append is going to work to give nice error
    if append and _vsi_exists(path):
        kwargs["append"] = True
        layerinfo = get_layerinfo(path, layer, raise_on_nogeom=False)

        # Determine columns and compare them
        file_cols = [col.upper() for col in layerinfo.columns]
        if layerinfo.geometrycolumn is not None:
            gdf_cols = [col.upper() for col in gdf.columns if col != gdf.geometry.name]
        else:
            gdf_cols = [col.upper() for col in gdf.columns]
        if gdf_cols != file_cols:
            raise ValueError(
                "destination layer doesn't have the same columns as gdf: "
                f"{file_cols} vs {gdf_cols}"
            )

    # Prepare kwargs to use in geopandas.to_file
    if create_spatial_index is not None:
        kwargs["SPATIAL_INDEX"] = create_spatial_index
    path_info = _geofileinfo.get_geofileinfo(path)
    kwargs["driver"] = path_info.driver
    kwargs["index"] = index
    if force_output_geometrytype is not None:
        if isinstance(force_output_geometrytype, GeometryType):
            force_output_geometrytype = force_output_geometrytype.name_camelcase
        kwargs["geometry_type"] = force_output_geometrytype
    if force_multitype:
        kwargs["promote_to_multi"] = True
    if not path_info.is_singlelayer:
        kwargs["layer"] = layer

    # Temp fix for bug in pyogrio 0.7.2 (https://github.com/geopandas/pyogrio/pull/324)
    # Logic based on geopandas.to_file
    if list(gdf.index.names) == [None] and is_integer_dtype(gdf.index.dtype):
        gdf = gdf.reset_index(drop=True)

    # Now we can write
    # If there is no geometry column in the input, never create a spatial index.
    if isinstance(gdf, gpd.GeoDataFrame) is False or (
        isinstance(gdf, gpd.GeoDataFrame) and "geometry" not in gdf.columns
    ):
        # If geometry column should be written, specifying SPATIAL INDEX is not allowed.
        kwargs.pop("SPATIAL_INDEX", None)
        pyogrio.write_dataframe(gdf, str(path), **kwargs)
    else:
        kwargs["engine"] = "pyogrio"
        gdf.to_file(str(path), **kwargs)


def get_crs(
    path: Union[str, "os.PathLike[Any]"],
    layer: str | None = None,
    min_confidence: int = 70,
) -> pyproj.CRS | None:
    """Get the CRS (projection) of the file.

    Args:
        path (PathLike): path to the file. |GDAL_vsi| paths are supported.
        layer (Optional[str]): layer name. If not specified, and there is only
            one layer in the file, this layer is used. Otherwise exception.
        min_confidence (int): a value between 0-100 where 100 is the most confident.
            It is used to match the crs info found in the file to a crs defined by
            EPSG.

    Returns:
        pyproj.CRS: The projection of the file.

    .. |GDAL_vsi| raw:: html

        <a href="https://gdal.org/en/stable/user/virtual_file_systems.html" target="_blank">GDAL vsi</a>

    """  # noqa: E501
    # Check input parameters
    crs = None
    try:
        datasource = gdal.OpenEx(
            str(path), nOpenFlags=gdal.OF_VECTOR | gdal.OF_READONLY | gdal.OF_SHARED
        )
        datasource_layer = _get_layer(datasource, layer)

        # Get the crs
        spatialref = datasource_layer.GetSpatialRef()
        if spatialref is not None:
            crs = pyproj.CRS(spatialref.ExportToWkt())

            # If spatial ref has no epsg, try to find corresponding one
            if crs.to_epsg(min_confidence=min_confidence) is None:
                crs = _crs_custom_match(crs, path)

    except ValueError:
        raise
    except Exception as ex:
        ex.args = (f"get_crs error: {ex} for {path}#{layer}",)
        raise
    finally:
        datasource = None

    return crs


def _crs_custom_match(
    crs: pyproj.CRS, path_to_fix: Union[str, "os.PathLike[Any]", None]
) -> pyproj.CRS:
    """Custom matching of crs's not matched automatically, based on name.

    If path_to_fix is specified, the corresponding .prj file located on the path will be
    replaced by a conforming .prj file if a match is found.

    Args:
        crs (pyproj.CRS): the crs to find a match for.
        path_to_fix (Optional[Path]): path to the geofile. If the file is a shapefile
            and a crs is found, the prj file will be replaced by one of the crs found.

    Returns:
        pyproj.CRS: the crs found.
    """
    if crs.name in [
        "Belge 1972 / Belgian Lambert 72",
        "Belge_1972_Belgian_Lambert_72",
        "Belge_Lambert_1972",
        "BD72 / Belgian Lambert 72",
    ]:
        # Belgian Lambert in name, so assume 31370
        crs = pyproj.CRS.from_epsg(31370)

        # If path is specified and it is a shapefile, add correct 31370 .prj file
        if path_to_fix is not None:
            path_to_fix = Path(path_to_fix)
            driver = _geofileinfo.get_driver(path_to_fix)
            if driver == "ESRI Shapefile":
                prj_path = path_to_fix.parent / f"{path_to_fix.stem}.prj"
                if prj_path.exists():
                    prj_rename_path = (
                        path_to_fix.parent / f"{path_to_fix.stem}_orig.prj"
                    )
                    if not prj_rename_path.exists():
                        prj_path.rename(prj_rename_path)
                    else:
                        prj_path.unlink()
                    prj_path.write_text(PRJ_EPSG_31370)

    return crs


def is_geofile(path: Union[str, "os.PathLike[Any]"]) -> bool:
    """Determines based on the filepath if this is a geofile.

    DEPRECATED.

    Args:
        path (PathLike): The file path.

    Returns:
        bool: True if it is a geo file.
    """
    warnings.warn(
        "is_geofile is deprecated and will be removed in a future version",
        FutureWarning,
        stacklevel=2,
    )
    return is_geofile_ext(Path(path).suffix)


def is_geofile_ext(file_ext: str) -> bool:
    """Determines based on the file extension if this is a geofile.

    DEPRECATED.

    Args:
        file_ext (str): the extension.

    Returns:
        bool: True if it is a geofile.
    """
    warnings.warn(
        "is_geofile_ext is deprecated and will be removed in a future version",
        FutureWarning,
        stacklevel=2,
    )
    try:
        # If the driver can be determined, it is a (supported) geo file.
        _ = _geofileinfo.GeofileType(file_ext)
        return True
    except Exception:
        return False


def cmp(
    path1: Union[str, "os.PathLike[Any]"], path2: Union[str, "os.PathLike[Any]"]
) -> bool:
    """Compare if two geofiles are identical.

    For geofiles that use multiple files, all relevant files must be identical.
    Eg. for shapefiles, the .shp, .shx and .dbf file must be identical.

    Args:
        path1 (PathLike): path to the first file. |GDAL_vsi| paths are not supported.
        path2 (PathLike): path to the second file. |GDAL_vsi| paths are not supported.

    Returns:
        bool: True if the files are identical

    .. |GDAL_vsi| raw:: html

        <a href="https://gdal.org/en/stable/user/virtual_file_systems.html" target="_blank">GDAL vsi</a>

    """  # noqa: E501
    # Check input parameters
    path1 = Path(path1)
    path2 = Path(path2)

    # For a shapefile, multiple files need to be compared
    if path1.suffix.lower() == ".shp":
        shapefile_base_suffixes = [".shp", ".dbf", ".shx"]
        for suffix in shapefile_base_suffixes:
            if not filecmp.cmp(path1.with_suffix(suffix), path2.with_suffix(suffix)):
                logger.info(
                    f"File {path1.with_suffix(suffix)} is different from "
                    f"{path2.with_suffix(suffix)}"
                )
                return False
        return True
    else:
        return filecmp.cmp(str(path1), str(path2))


def copy(
    src: Union[str, "os.PathLike[Any]"],
    dst: Union[str, "os.PathLike[Any]"],
    keep_permissions: bool = True,
):
    """Copies the geofile from src to dst.

    If the source file is a geofile containing of multiple files (eg. .shp) all files
    are copied.

    Args:
        src (PathLike): the file to copy. |GDAL_vsi| paths are not supported.
        dst (PathLike): the location to copy the file(s) to.
        keep_permissions (bool, optional): True to keep the file permissions of the
            source file. Defaults to True.

    .. |GDAL_vsi| raw:: html

        <a href="https://gdal.org/en/stable/user/virtual_file_systems.html" target="_blank">GDAL vsi</a>

    """  # noqa: E501
    # Check input parameters
    src = Path(src)
    dst = Path(dst)
    if not src.exists():
        raise FileNotFoundError(f"File not found: {src}")

    src_info = _geofileinfo.get_geofileinfo(src)

    # Copy the main file
    if keep_permissions:
        shutil.copy(str(src), dst)
    else:
        dstfile = dst / src.name if dst.is_dir() else dst
        shutil.copyfile(src, dstfile)

    # For some file types, extra files need to be copied
    # If dest is a dir, just use move. Otherwise concat dest filepaths

    for suffix in src_info.suffixes_extrafiles:
        srcfile = src.parent / f"{src.stem}{suffix}"
        dstfile = (
            dst / f"{src.stem}{suffix}"
            if dst.is_dir()
            else dst.parent / f"{dst.stem}{suffix}"
        )
        if srcfile.exists() and not dstfile.exists():
            if keep_permissions:
                shutil.copy(str(srcfile), dstfile)
            else:
                shutil.copyfile(srcfile, dstfile)


def move(src: Union[str, "os.PathLike[Any]"], dst: Union[str, "os.PathLike[Any]"]):
    """Moves the geofile from src to dst.

    If the source file is a geofile containing of multiple files (eg. .shp) all files
    are moved.

    Args:
        src (PathLike): the file to move
        dst (PathLike): the location to move the file(s) to
    """
    # Check input parameters
    src = Path(src)
    dst = Path(dst)
    src_info = _geofileinfo.get_geofileinfo(src)

    # For some file types, extra files need to be moved
    dst_is_dir = dst.is_dir()
    for suffix in src_info.suffixes_extrafiles:
        if src.suffix.lower() == suffix:
            # Skip the main file, as it should be moved last
            continue

        srcfile = src.parent / f"{src.stem}{suffix}"
        if dst_is_dir:
            # If the destination is a dir, we can just move the extra files to the dir
            dst_tmp = dst
        else:
            # If dst is not a dir concat dest filepath...
            dst_tmp = dst.parent / f"{dst.stem}{suffix}"

        if srcfile.exists():
            shutil.move(str(srcfile), dst_tmp)

    # Move the main file last, so that checks if the geofile exists are only
    # True once all files have been moved.
    shutil.move(str(src), dst)


def remove(path: Union[str, "os.PathLike[Any]"], missing_ok: bool = False):
    """Removes the geofile.

    Is it is a geofile composed of multiple files (eg. .shp) all files are removed.
    If .lock files are present, they are removed as well.

    Args:
        path (PathLike): the file to remove
        missing_ok (bool, optional): True not to give an error if the file to be removed
            doesn't exist. Defaults to False.
    """
    # Check input parameters
    path = Path(path)
    path_info = _geofileinfo.get_geofileinfo(path)

    # If there is a lock file, remove it
    lockfile_path = path.parent / f"{path.name}.lock"
    lockfile_path.unlink(missing_ok=True)

    # Remove the main file
    path.unlink(missing_ok=missing_ok)

    # For some file types, extra files need to be removed
    for suffix in path_info.suffixes_extrafiles:
        curr_path = path.parent / f"{path.stem}{suffix}"
        curr_path.unlink(missing_ok=True)


def append_to(
    src: Union[str, "os.PathLike[Any]"],
    dst: Union[str, "os.PathLike[Any]"],
    src_layer: str | None = None,
    dst_layer: str | None = None,
    src_crs: int | str | None = None,
    dst_crs: int | str | None = None,
    columns: Iterable[str] | None = None,
    where: str | None = None,
    sql_stmt: str | None = None,
    sql_dialect: Literal["SQLITE", "OGRSQL"] | None = None,
    reproject: bool = False,
    explodecollections: bool = False,
    force_output_geometrytype: GeometryType | str | None = None,
    create_spatial_index: bool | None = None,
    append_timeout_s: int = 600,
    transaction_size: int = 50000,
    preserve_fid: bool | None = None,
    dst_dimensions: str | None = None,
    options: dict = {},
):
    """DEPRECATED: use copy_layer with write_mode='add_layer' or write_mode='append'.

    If you explicitly would like to keep the option to use the current undocumented file
    locking mechanism present in append_to, please open an issue asking for this in
    https://github.com/geofileops/geofileops/issues
    """
    warnings.warn(
        "append_to is deprecated: use copy_layer with write_mode='append' or "
        "write_mode='add_layer'. It will be removed in a future version.",
        FutureWarning,
        stacklevel=2,
    )

    # Files don't typically support having multiple processes writing
    # simultanously to them, so use lock file to synchronize access.
    lockfile = f"{dst!s}.lock"

    # If the destination file doesn't exist yet, but the lockfile does,
    # try removing the lockfile as it might be a ghost lockfile.
    if not _vsi_exists(dst) and _vsi_exists(lockfile):
        try:
            gdal.Unlink(lockfile)
        except Exception:
            _ = None

    # Creating lockfile and append
    start_time = datetime.now()
    ready = False
    while not ready:
        if _io_util.create_file_atomic(lockfile):
            try:
                # append
                copy_layer(
                    src=src,
                    dst=dst,
                    src_layer=src_layer,
                    dst_layer=dst_layer,
                    write_mode="append",
                    src_crs=src_crs,
                    dst_crs=dst_crs,
                    columns=columns,
                    where=where,
                    sql_stmt=sql_stmt,
                    sql_dialect=sql_dialect,
                    reproject=reproject,
                    explodecollections=explodecollections,
                    force_output_geometrytype=force_output_geometrytype,
                    create_spatial_index=create_spatial_index,
                    transaction_size=transaction_size,
                    preserve_fid=preserve_fid,
                    dst_dimensions=dst_dimensions,
                    options=options,
                )
            finally:
                ready = True
                gdal.Unlink(lockfile)
        else:
            time_waiting = (datetime.now() - start_time).total_seconds()
            if time_waiting > append_timeout_s:
                raise RuntimeError(
                    f"append_to timeout of {append_timeout_s} reached, so stop write "
                    f"to {dst}!"
                )

        # Sleep for a second before trying again
        time.sleep(1)


def convert(
    src: Union[str, "os.PathLike[Any]"],
    dst: Union[str, "os.PathLike[Any]"],
    src_layer: str | None = None,
    dst_layer: str | None = None,
    src_crs: str | int | None = None,
    dst_crs: str | int | None = None,
    where: str | None = None,
    reproject: bool = False,
    explodecollections: bool = False,
    force_output_geometrytype: GeometryType | str | None = None,
    create_spatial_index: bool | None = None,
    preserve_fid: bool | None = None,
    options: dict = {},
    append: bool = False,
    force: bool = False,
):
    """DEPRECATED: please use copy_layer."""
    warnings.warn(
        "convert is deprecated: use copy_layer. It will be removed in a future "
        "version.",
        FutureWarning,
        stacklevel=2,
    )
    return copy_layer(
        src=src,
        dst=dst,
        src_layer=src_layer,
        dst_layer=dst_layer,
        src_crs=src_crs,
        dst_crs=dst_crs,
        where=where,
        reproject=reproject,
        explodecollections=explodecollections,
        force_output_geometrytype=force_output_geometrytype,
        create_spatial_index=create_spatial_index,
        preserve_fid=preserve_fid,
        options=options,
        append=append,
        force=force,
    )


def copy_layer(
    src: Union[str, "os.PathLike[Any]"],
    dst: Union[str, "os.PathLike[Any]"],
    src_layer: str | LayerInfo | None = None,
    dst_layer: str | None = None,
    write_mode: str = "create",
    src_crs: str | int | None = None,
    dst_crs: str | int | None = None,
    columns: Iterable[str] | None = None,
    where: str | None = None,
    sql_stmt: str | None = None,
    sql_dialect: Literal["SQLITE", "OGRSQL"] | None = None,
    reproject: bool = False,
    explodecollections: bool = False,
    force_output_geometrytype: GeometryType | str | None = None,
    create_spatial_index: bool | None = None,
    transaction_size: int = 50000,
    preserve_fid: bool | None = None,
    dst_dimensions: str | None = None,
    options: dict = {},
    append: bool = False,
    force: bool = False,
):
    """Copy a layer from a source to a destination dataset.

    Typical use cases:
      - convert a file from one fileformat to another
      - reproject a layer to another spatial reference
      - export a subset of a layer using the `where` or `sql_stmt` parameter
      - add a layer to an existing file as a new layer (`write_mode="add_layer"`)
      - append a layer to an existing layer (`write_mode="append"`)

    If an `sql_stmt` is specified, the sqlite query can contain following placeholders
    that will be automatically replaced for you:

      * {geometrycolumn}: the column where the primary geometry is stored.
      * {columns_to_select_str}: if 'columns' is not None, those columns,
        otherwise all columns of the layer.
      * {input_layer}: the layer name of the input layer.

    Example SQL statement with placeholders:
    ::

        SELECT {geometrycolumn}
              {columns_to_select_str}
          FROM "{input_layer}" layer


    The options parameter can be used to pass any type of options to GDAL in
    the following form:
        { "<option_type>.<option_name>": <option_value> }

    The option types can be any of the following:
        - LAYER_CREATION: layer creation option (lco)
        - DATASET_CREATION: dataset creation option (dsco)
        - INPUT_OPEN: input dataset open option (oo)
        - DESTINATION_OPEN: destination dataset open option (doo)
        - CONFIG: config option (config)

    The options can be found in the |GDAL_vector_driver_documentation|.

    Args:
        src (PathLike): The source path. |GDAL_vsi| paths are also supported.
        dst (PathLike): The destination path. |GDAL_vsi| paths can be used for handlers
            with write support.
        src_layer (str, optional): The source layer. If the source contains a single
            layer, that layer will be taken if `src_layer` is None. If it contains
            multiple layers, `src_layer` is mandatory unless `sql_stmt` is specified.
            Defaults to None.
        dst_layer (str, optional): The destination layer. If None, the destination file
            stem is taken as layer name. Defaults to None.
        write_mode (str, optional): The write mode. Defaults to "create". Valid values:

            - "create": create a new destination file. If the file already exists and
                `force=True` the function just returns, if `force=False` the file is
                overwritten.
            - "add_layer": add the source layer to the destination file as a new layer.
                When using "add_layer", `dst_layer` should be specified. If the layer
                already exists and `force=True` the function just returns, if
                `force=False` the layer is overwritten.
            - "append": append the source layer to the destination layer, if the
                layer already exists. If not, the file and/or layer will be created.
                If the file already contains layers named differently than the default
                layer name for the file, `dst_layer` becomes mandatory.
            - "append_add_fields": append the source layer to the destination layer,
                adding fields from the source layer that are not present in the
                destination layer. If the layer doesn't exist, it will be created.
                If the file already contains layers named differently than the default
                layer name for the file, `dst_layer` becomes mandatory.

        src_crs (Union[str, int], optional): an epsg int or anything supported
            by the OGRSpatialReference.SetFromUserInput() call, which includes
            an EPSG string (eg. "EPSG:4326"), a well known text (WKT) CRS
            definition,... Defaults to None.
        dst_crs (Union[str, int], optional): an epsg int or anything supported
            by the OGRSpatialReference.SetFromUserInput() call, which includes
            an EPSG string (eg. "EPSG:4326"), a well known text (WKT) CRS
            definition,... Defaults to None.
        columns (Iterable[str], optional): The (non-geometry) columns to read will
            be returned in the order specified. If None, all standard columns are read.
            In addition to standard columns, it is also possible
            to specify "fid", a unique index available in all input files. Note that the
            "fid" will be aliased eg. to "fid_1". Defaults to None.
        where (str, optional): only append the rows from src that comply to the filter
            specified. Applied before ``explodecollections``. Filter should be in sqlite
            SQL WHERE syntax and |spatialite_reference_link| functions can be used. If
            where contains the {geometrycolumn} placeholder, it is filled out with the
            geometry column name of the src file. Defaults to None.
        sql_stmt (str): SQL statement to use. Only supported with "pyogrio" engine.
        sql_dialect (str, optional): SQL dialect used. Options are None, "SQLITE" or
            "OGRSQL". If None, for data sources with explicit SQL support the statement
            is processed by the default SQL engine (e.g. for Geopackage and Spatialite
            this is "SQLITE"). For data sources without native SQL support (e.g. .shp),
            the "OGRSQL" dialect is the default. If the "SQLITE" dialect is specified,
            |spatialite_reference_link| functions can also be used. Defaults to None.
        reproject (bool, optional): True to reproject while converting the
            file. Defaults to False.
        explodecollections (bool, optional): True to output only simple
            geometries. Defaults to False.
        force_output_geometrytype (Union[GeometryType, str], optional): Geometry type.
            to (try to) force the output to. In addition to geometry types, it is also
            possible to specify PROMOTE_TO_MULTI to convert all geometries to
            multigeometries or CONVERT_TO_LINEAR to convert CURVE geometries to linear.
            Defaults to None.
        create_spatial_index (bool, optional): True to create a spatial index
            on the destination file/layer. If None, the default behaviour by gdal for
            that file type is respected. If the LAYER_CREATION.SPATIAL_INDEX
            parameter is specified in options, create_spatial_index is ignored.
            Defaults to None.
        transaction_size (int, optional): Transaction size. Defaults to 50000.
        preserve_fid (bool, optional): True to make an extra effort to preserve fid's of
            the source layer to the destination layer. False not to do any effort. None
            to use the default behaviour of gdal, that already preserves in some cases.
            Some file formats don't explicitly store the fid (e.g. shapefile), so they
            will never be able to preserve fids. Defaults to None.
        dst_dimensions (str, optional): Force the dimensions of the destination layer to
            the value specified. Valid values: "XY", "XYZ", "XYM" or "XYZM".
            Defaults to None.
        options (dict, optional): options to pass to gdal.
        append (bool, optional): True to append to the destination layer if it already
            exists. Deprecated: use write_mode='append'. Defaults to False.
        force (bool, optional): True to overwrite the output file/layer (depending on
            `write_mode`) if it already exists. False to just return if the output
            file/layer exists. Defaults to False.

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    .. |GDAL_vector_driver_documentation| raw:: html

        <a href="https://gdal.org/drivers/vector/index.html" target="_blank">GDAL vector driver documentation</a>

    .. |GDAL_vsi| raw:: html

        <a href="https://gdal.org/en/stable/user/virtual_file_systems.html" target="_blank">GDAL vsi</a>

    """  # noqa: E501
    # The append parameter is deprecated, but keep backwards compatibility
    if append:
        if write_mode != "create":
            raise ValueError("append parameter is deprecated, use write_mode='append'")
        warnings.warn(
            "append parameter is deprecated, use write_mode='append'",
            FutureWarning,
            stacklevel=2,
        )
        write_mode = "append"

    # Determine the access mode and whether to add missing fields when appending
    add_fields = False
    access_mode = _determine_access_mode(dst, dst_layer, write_mode, force)
    if access_mode is None:
        # The file/layer exists already and force is false, so we can return
        return
    elif access_mode == "create":
        # GDAL expects None for create mode
        access_mode = None
    elif access_mode == "append":
        # As we will actually be appending to an existing layer, the layer
        # creation option regarding spatial index creation should not be passed.
        create_spatial_index = None
        if write_mode == "append_add_fields":
            add_fields = True

    # Check/clean input params
    if isinstance(columns, str):
        # If a string is passed, convert to list
        columns = [columns]

    if where is not None:
        if not isinstance(src_layer, LayerInfo):
            src_layer = get_layerinfo(src, src_layer, raise_on_nogeom=False)
        where = where.format(geometrycolumn=src_layer.geometrycolumn)

    if sql_stmt is not None:
        # Fill out placeholders.
        sql_stmt = _fill_out_sql_placeholders(
            path=src, layer=src_layer, sql_stmt=sql_stmt, columns=columns
        )

    if dst_layer is None:
        dst_layer = get_default_layer(dst)
    src_layername = src_layer.name if isinstance(src_layer, LayerInfo) else src_layer

    # If the source and destination files are GeoPackages, and it involves a simple data
    # copy, it is faster to copy the data directly in sqlite instead of via GDAL.
    if (
        access_mode == "append"
        and not add_fields
        and Path(src).suffix.lower() == ".gpkg"
        and Path(dst).suffix.lower() == ".gpkg"
        and not sql_stmt
        and (sql_dialect is None or sql_dialect == "SQLITE")
        and not explodecollections
        and not reproject
        and force_output_geometrytype is None
        and dst_dimensions is None
        and (options is None or len(options) == 0)
        and src_crs is None
        and dst_crs is None
        and Path(src).exists()
        and Path(dst).exists()
        and ConfigOptions.copy_layer_sqlite_direct
    ):
        # TODO: sql_stmt?, access_mode="create", create_spatial_index, dst_crs?
        try:
            name = src_layername if src_layername is not None else get_only_layer(src)
            preserve_fid_local = preserve_fid if preserve_fid is not None else False
            _sqlite_util.copy_table(
                input_path=src,
                output_path=dst,
                input_table=name,
                output_table=dst_layer,
                columns=columns,
                where=where,
                preserve_fid=preserve_fid_local,
            )
            return

        except Exception as ex:
            logger.info(
                f"Failed to copy data directly in sqlite, retry with gdal: {ex}"
            )

    options = _ogr_util._prepare_gdal_options(options)
    if (
        create_spatial_index is not None
        and "LAYER_CREATION.SPATIAL_INDEX" not in options
    ):
        options["LAYER_CREATION.SPATIAL_INDEX"] = create_spatial_index

    # When destination is a shapefile, some extra things need to be done/checked.
    if sql_stmt is None and Path(dst).suffix.lower() == ".shp":
        # If the destination file doesn't exist yet, and the source file has
        # geometrytype "Geometry", raise because type is not supported by shp (and will
        # default to linestring).
        if not isinstance(src_layer, LayerInfo):
            src_layer = get_layerinfo(src, src_layer, raise_on_nogeom=False)
            src_layername = src_layer.name
        if (
            force_output_geometrytype is None
            and src_layer.geometrytypename in ["GEOMETRY", "GEOMETRYCOLLECTION"]
            and not _vsi_exists(dst)
        ):
            raise ValueError(
                f"src file {src} has geometrytype {src_layer.geometrytypename} "
                "which is not supported in .shp. Maybe use force_output_geometrytype?"
            )

        # Launder the columns names via a SQL statement, otherwise when appending the
        # laundered columns will get NULL values instead of the data.
        if columns is None:
            columns = src_layer.columns
        columns_laundered = _launder_column_names(columns)
        columns_aliased = [
            f'"{column}" AS "{laundered}"' for column, laundered in columns_laundered
        ]
        # If there is a where specified, integrate it...
        where_clause = ""
        if where is not None:
            where_clause = f"WHERE {where}"
            where = None
        geometrycolumn = ""
        if src_layer.geometrycolumn is not None:
            geometrycolumn = f"{src_layer.geometrycolumn}, "
        sql_stmt = f"""
            SELECT {geometrycolumn}{", ".join(columns_aliased)}
              FROM "{src_layer.name}"
             {where_clause}
        """
        sql_dialect = "SQLITE"
        columns = None

    # Go!
    translate_info = _ogr_util.VectorTranslateInfo(
        input_path=src,
        output_path=dst,
        input_layers=src_layername,
        output_layer=dst_layer,
        access_mode=access_mode,
        input_srs=src_crs,
        output_srs=dst_crs,
        columns=columns,
        sql_stmt=sql_stmt,
        sql_dialect=sql_dialect,
        where=where,
        reproject=reproject,
        transaction_size=transaction_size,
        explodecollections=explodecollections,
        force_output_geometrytype=force_output_geometrytype,
        options=options,
        preserve_fid=preserve_fid,
        dst_dimensions=dst_dimensions,
        add_fields=add_fields,
    )
    _ogr_util.vector_translate_by_info(info=translate_info)


def geo_sozip(
    input_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
):
    """Zip a geofile to a seek-optimized zip file.

    For geofile types that consist of multiple files (eg. shapefiles), all relevant
    (existing) files are included in the zip.

    Args:
        input_path (PathLike): the geofile to zip.
        output_path (PathLike): the output zip file.
    """
    if not GDAL_GTE_311:
        raise RuntimeError("sozip requires gdal>=3.11")

    # For some file types, extra files need to be included
    input_info = _geofileinfo.get_geofileinfo(input_path)
    input_path_suffix = Path(input_path).suffix
    input_path_no_suffix = Path(input_path).with_suffix("").as_posix()

    input_paths = []
    if _vsi_exists(input_path):
        input_paths.append(input_path)
    for suffix in input_info.suffixes_extrafiles:
        if suffix == input_path_suffix:
            continue
        extra_path = f"{input_path_no_suffix}{suffix}"
        if _vsi_exists(extra_path):
            input_paths.append(extra_path)

    gdal.Run(
        "vsi", "sozip", "create", input=input_paths, output=output_path, no_paths=True
    )


def _zip(src: Union[str, "os.PathLike[Any]"], dst: Union[str, "os.PathLike[Any]"]):
    """Zip a file or directory.

    Args:
        src (PathLike): the file or directory to zip.
        dst (PathLike): the destination zip file.
    """
    # Init input parameters
    src = Path(src)

    # Zip the file or directory
    with zipfile.ZipFile(dst, "w") as zipf:
        if src.is_file():
            zipf.write(src, src.name)
        elif src.is_dir():
            for root, _, files in os.walk(src):
                for file in files:
                    file_path = Path(root) / file
                    zipf.write(file_path, file_path.relative_to(src))


def geo_unzip(
    input_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
) -> Path:
    """Unzip a zipped geofile and return the path to the unzipped geofile.

    The zip file should contain a single geofile. If the file contains a single file,
    that file is returned. If it contains multiple files, the geofile is determined
    based on the file extension. If multiple geofiles are found, an error is raised.

    Args:
        input_path (PathLike): the zip file to unzip.
        output_path (PathLike): the output directory.

    Returns:
        Path: The path to the unzipped geofile in the destination directory.
    """
    geo_suffixes = (".gpkg", ".shp", ".geojson", ".json", ".gpkg.zip", ".shp.zip")
    with zipfile.ZipFile(input_path, "r") as zipf:
        # Determine the geofile in the zip to be able to return it
        files = zipf.filelist
        geofilename = None
        if len(files) == 0:
            raise ValueError(f"No files found in zip: {input_path}")
        elif len(files) == 1:
            geofilename = files[0].filename
        else:
            for file in files:
                if file.filename.endswith(geo_suffixes):
                    if geofilename is not None:
                        raise ValueError(
                            f"Multiple geofiles found in zip: {input_path}, so cannot "
                            "determine which one to return."
                        )
                    geofilename = file.filename

        if geofilename is None:
            raise ValueError(f"No geofile found in zip: {input_path}")

        zipf.extractall(output_path)

    return Path(output_path) / geofilename


def _determine_access_mode(
    dst: Union[str, "os.PathLike[Any]"],
    dst_layer: str | None,
    write_mode: str,
    force: bool,
) -> str | None:
    """Determines an access mode based on the write mode,...

    Does this by checking if the destination file/layer already exists in combination
    with the `write_mode` and `force` parameters.

    Args:
        dst (PathLike): the destination file
        dst_layer (str): the destination layer name
        write_mode (str): the write mode
        force (bool): True to force (re)creation of the file/layer.

    Returns:
        str | None: If None, we can just return. If an access mode, one of the following
            values:
              - "create": the destination file doesn't exist, so create a new file.
              - "overwrite": the destination layer exists, overwrite it.
              - "update": the destination file exists, but destination layer doesn't so
                add the layer to the file.
              - "append": the destination layer exists, append to it.
    """

    def try_listlayers(dst, only_spatial_layers: bool) -> list[str] | None:
        try:
            return listlayers(dst, only_spatial_layers)
        except FileNotFoundError:
            return None

    # Determine the access_mode expected by GDAL based on the write_mode and the
    # destination file/layer.
    if write_mode == "create":
        if _vsi_exists(dst) and not force:
            logger.info(f"Destination file already exists, so stop: {dst}")
            return None
        return "create"

    elif write_mode == "add_layer":
        if dst_layer is None:
            raise ValueError("dst_layer is required when write_mode is 'add_layer'")

        layers = try_listlayers(dst, only_spatial_layers=False)
        if layers is None:
            # The file doesn't seem to exist yet, so set access_mode to None.
            return "create"
        elif dst_layer in layers:
            if not force:
                logger.info(f"dst_layer already exists, so stop: {dst}#{dst_layer}")
                return None
            return "overwrite"
        else:
            return "update"

    elif write_mode in ("append", "append_add_fields"):
        layers = try_listlayers(dst, only_spatial_layers=False)
        if layers is None:
            # The file doesn't seem to exist yet... just continue, the file and layer
            # will be created in this case.
            return "create"
        elif len(layers) == 0:
            # File exists, but there are no layers yet: add the layer
            return "update"
        elif dst_layer is None and len(layers) == 1:
            # No dst_layer specified but only one layer: if the same we can append
            dst_layer = get_default_layer(dst)
            if dst_layer not in layers:
                raise ValueError(
                    "dst_layer is required when write_mode is 'append' or "
                    "'append_add_fields' and there are already other layers than the "
                    "default layername."
                )
            return "append"

        elif dst_layer is None:
            # No dst_layer specified and multiple layers: raise error
            raise ValueError(
                "dst_layer is required when write_mode is 'append' or "
                "'append_add_fields' and there are multiple other layers."
            )
        elif dst_layer in layers:
            return "append"
        else:
            return "update"

    else:
        raise ValueError(f"Invalid write_mode: {write_mode}")


def _vsi_exists(path: Union[str, "os.PathLike[Any]"]) -> bool:
    """Check if a file exists using the VSI file system.

    Args:
        path (str): the path the the file to check if it exists.

    Returns:
        bool: True if the file exists.
    """
    if isinstance(path, Path):
        path = path.as_posix()

    if gdal.VSIStatL(path, gdal.VSI_STAT_EXISTS_FLAG) is None:
        return False

    return True


def _launder_column_names(columns: Iterable) -> list[tuple[str, str]]:
    """Launders the column names passed to comply with shapefile restrictions.

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
