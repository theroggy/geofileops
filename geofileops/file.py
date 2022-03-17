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
from typing import Any, List, Optional, Tuple, Union
import warnings

import fiona
import geopandas as gpd
from osgeo import gdal
import pandas as pd
import pyproj

from geofileops.util import geometry_util
from geofileops.util.geometry_util import GeometryType, PrimitiveType
from geofileops.util import geoseries_util
from geofileops.util import io_util
from geofileops.util import ogr_util
from geofileops.util.geofiletype import GeofileType

#-------------------------------------------------------------
# First define/init some general variables/constants
#-------------------------------------------------------------

# Get a logger...
logger = logging.getLogger(__name__)
#logger.setLevel(logging.DEBUG)

# Enable exceptions for GDAL
gdal.UseExceptions()

# Disable this annoying warning in fiona
warnings.filterwarnings(
        action="ignore", 
        category=RuntimeWarning, 
        message="Sequential read of iterator was interrupted. Resetting iterator. This can negatively impact the performance.")

# Hardcoded prj string to replace faulty ones
PRJ_EPSG_31370 = 'PROJCS["Belge_1972_Belgian_Lambert_72",GEOGCS["Belge 1972",DATUM["D_Belge_1972",SPHEROID["International_1924",6378388,297]],PRIMEM["Greenwich",0],UNIT["Degree",0.017453292519943295]],PROJECTION["Lambert_Conformal_Conic"],PARAMETER["standard_parallel_1",51.16666723333333],PARAMETER["standard_parallel_2",49.8333339],PARAMETER["latitude_of_origin",90],PARAMETER["central_meridian",4.367486666666666],PARAMETER["false_easting",150000.013],PARAMETER["false_northing",5400088.438],UNIT["Meter",1],AUTHORITY["EPSG",31370]]'

#-------------------------------------------------------------
# The real work
#-------------------------------------------------------------

'''
def write_vrt(
        input_layer_paths: List[Tuple[Path, str]],
        output_path: Path):
    """
    Create a vrt file where all layers in input_layer_paths.

    Args:
        input_layer_paths (dict): [description]
        output_path (Path): [description]
    """

    # Create vrt file
    with open(output_path, "w") as vrt_file:
        vrt_file.write(f'<OGRVRTDataSource>\n')

        # Loop over all layers and add them to vrt file
        for index, input_layer_path in enumerate(input_layer_paths):
            vrt_file.write(f'  <OGRVRTLayer name="{input_layer_path[1]}">\n')
            vrt_file.write(f'    <SrcDataSource>{input_layer_path[0]}</SrcDataSource>\n')
            vrt_file.write(f'    <SrcLayer>{input_layer_path[1]}</SrcLayer>\n')
            vrt_file.write(f'  </OGRVRTLayer>\n')

            # layer index
            vrt_file.write(f'  <OGRVRTLayer name="rtree_{input_layer_path[1]}_geom">\n')
            vrt_file.write(f'    <SrcDataSource>{input_layer_path[0]}</SrcDataSource>\n')
            vrt_file.write(f'    <SrcLayer>rtree_{input_layer_path[1]}_geom</SrcLayer>\n')
            vrt_file.write(f'    <Field name="minx" />\n')
            vrt_file.write(f'    <Field name="miny" />\n')
            vrt_file.write(f'    <Field name="maxx" />\n')
            vrt_file.write(f'    <Field name="maxy" />\n')
            vrt_file.write(f'    <GeometryType>wkbNone</GeometryType>\n')
            vrt_file.write(f'  </OGRVRTLayer>\n')
            
        vrt_file.write(f'</OGRVRTDataSource>\n')
'''

def listlayers(
        path: Union[str, 'os.PathLike[Any]'],
        verbose: bool = False) -> List[str]:
    """
    Get the list of layers in a geofile.

    Args:
        path (PathLike): path to the file to get info about
        verbose (bool, optional): True to enable verbose logging. Defaults to False.

    Returns:
        List[str]: the list of layers
    """
    return fiona.listlayers(str(path))

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
        columns (List[str]): the columns (other than the geometry column) that 
            are available on the layer.
        crs (pyproj.CRS): the spatial reference of the layer.
        errors (List[str]): list of errors in the layer, eg. invalid column 
            names,... 
    """
    def __init__(self, 
            name: str,
            featurecount: int, 
            total_bounds: Tuple[float, float, float, float],
            geometrycolumn: str, 
            geometrytypename: str,
            geometrytype: GeometryType,
            columns: List[str],
            crs: Optional[pyproj.CRS],
            errors: List[str]):
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
        path: Union[str, 'os.PathLike[Any]'],
        layer: Optional[str] = None) -> LayerInfo:
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
    ##### Init #####
    path_p = Path(path)
    if not path_p.exists():
        raise ValueError(f"File does not exist: {path_p}")
        
    datasource = None
    try:
        datasource = gdal.OpenEx(str(path_p))
        if layer is not None: #and GeofileType(path_p).is_singlelayer is False:
            datasource_layer = datasource.GetLayer(layer)
        elif datasource.GetLayerCount() == 1:
            datasource_layer = datasource.GetLayerByIndex(0)
        else:
            raise ValueError(f"No layer specified, and file has <> 1 layer: {path_p}")

        # If the layer doesn't exist, return 
        if datasource_layer is None:
            raise ValueError(f"Layer {layer} not found in file: {path_p}")

        # Get column info
        columns = []
        errors = []
        geofiletype = GeofileType(path_p)
        layer_defn = datasource_layer.GetLayerDefn()
        for i in range(layer_defn.GetFieldCount()):
            name = layer_defn.GetFieldDefn(i).GetName()
            illegal_column_chars = ['"']
            for illegal_char in illegal_column_chars:
                if illegal_char in name:
                    errors.append(f"Column name {name} contains illegal char: {illegal_char} in file {path_p}, layer {layer}")
            columns.append(name)
            if geofiletype == GeofileType.ESRIShapefile:
                if name.casefold() == "geometry":
                    errors.append(f"An attribute column named 'geometry' is not supported in a shapefile")

        # Get geometry column info...
        geometrytypename = gdal.ogr.GeometryTypeToName(datasource_layer.GetGeomType())
        geometrytypename = geometrytypename.replace(' ', '').upper()
        
        # For shape files, the difference between the 'MULTI' variant and the 
        # single one doesn't exists... so always report MULTI variant by convention.
        if GeofileType(path_p) == GeofileType.ESRIShapefile:
            if(geometrytypename.startswith('POLYGON')
            or geometrytypename.startswith('LINESTRING')
            or geometrytypename.startswith('POINT')):
                geometrytypename = f"MULTI{geometrytypename}"
        if geometrytypename == 'UNKNOWN(ANY)':
            geometrytypename = 'GEOMETRY'
            
        # Geometrytype
        if geometrytypename != 'NONE':
            geometrytype = GeometryType[geometrytypename]
        else:
            geometrytype = None

        # If the geometry type is not None, fill out the extra properties    
        geometrycolumn = None
        extent= None
        crs = None
        total_bounds = None
        if geometrytype is not None:
            # Geometry column name
            geometrycolumn = datasource_layer.GetGeometryColumn()
            if geometrycolumn == '':
                geometrycolumn = 'geometry'
            # Convert gdal extent (xmin, xmax, ymin, ymax) to bounds (xmin, ymin, xmax, ymax)
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
                            "BD72 / Belgian Lambert 72"]:
                        # Belgian Lambert in name, so assume 31370
                        crs = pyproj.CRS.from_epsg(31370)

                        # If shapefile, add correct 31370 .prj file
                        if GeofileType(path_p) == GeofileType.ESRIShapefile:
                            prj_path = path_p.parent / f"{path_p.stem}.prj"
                            if prj_path.exists():
                                prj_rename_path = path_p.parent / f"{path_p.stem}_orig.prj"
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
                errors=errors)
        else:
            errors.append("Layer doesn't have a geometry column!")    

    finally:
        if datasource is not None:
            del datasource    

    # If we didn't return or raise yet here, there must have been errors
    raise Exception(f"Errors found in layer definition of file {path_p}, layer {layer}: \n{pprint.pprint(errors)}")

def get_only_layer(path: Union[str, 'os.PathLike[Any]']) -> str:
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

def get_default_layer(path: Union[str, 'os.PathLike[Any]']) -> str:
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
        path: Union[str, 'os.PathLike[Any]'],
        sql_stmt: str,
        sql_dialect: Optional[str] = None):
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
    ogr_util.vector_info(
            path=Path(path),
            sql_stmt=sql_stmt, 
            sql_dialect=sql_dialect, 
            readonly=False)

def create_spatial_index(
        path: Union[str, 'os.PathLike[Any]'],
        layer: Optional[str] = None):
    """
    Create a spatial index on the layer specified.

    Args:
        path (PathLike): The file path.
        layer (str, optional): The layer. If not specified, and there is only 
            one layer in the file, this layer is used. Otherwise exception.
    """
    # Init
    path_p = Path(path)
    layerinfo = get_layerinfo(path_p, layer)

    # Now really add index
    datasource = None
    try:
        datasource = gdal.OpenEx(str(path_p), nOpenFlags=gdal.OF_UPDATE)
        geofiletype = GeofileType(path_p)    
        if geofiletype.is_spatialite_based:
            datasource.ExecuteSQL(
                    f"SELECT CreateSpatialIndex('{layerinfo.name}', '{layerinfo.geometrycolumn}')",                
                    dialect='SQLITE') 
        else:
            datasource.ExecuteSQL(f'CREATE SPATIAL INDEX ON "{layerinfo.name}"')
    except Exception as ex:
        raise Exception(f"Error adding spatial index to {path_p}.{layerinfo.name}") from ex
    finally:
        if datasource is not None:
            del datasource

def has_spatial_index(
        path: Union[str, 'os.PathLike[Any]'],
        layer: Optional[str] = None,
        geometrycolumn: Optional[str] = None) -> bool:
    """
    Check if the layer/column has a spatial index.

    Args:
        path (PathLike): The file path.
        layer (str, optional): The layer. Defaults to None.
        geometrycolumn (str, optional): The geometry column to check. 
            Defaults to None.

    Raises:
        ValueError: an invalid parameter value was passed.

    Returns:
        bool: True if the spatial column exists.
    """
    # Init
    path_p = Path(path)

    # Now check the index
    geofiletype = GeofileType(path_p)    
    if geofiletype.is_spatialite_based:
        layerinfo = get_layerinfo(path_p, layer)

        datasource = None
        try:
            data_source = gdal.OpenEx(str(path_p), nOpenFlags=gdal.OF_READONLY)
            result = data_source.ExecuteSQL(
                    f"SELECT HasSpatialIndex('{layerinfo.name}', '{layerinfo.geometrycolumn}')",
                    dialect='SQLITE')
            row = result.GetNextFeature()
            has_spatial_index = row.GetField(0)
            return (has_spatial_index == 1)
        finally:
            if datasource is not None:
                del datasource
    elif geofiletype == GeofileType.ESRIShapefile:
        index_path = path_p.parent / f"{path_p.stem}.qix" 
        return index_path.exists()
    else:
        raise ValueError(f"has_spatial_index not supported for {path_p}")

def remove_spatial_index(
        path: Union[str, 'os.PathLike[Any]'],
        layer: Optional[str] = None):
    """
    Remove the spatial index from the layer specified.

    Args:
        path (PathLike): The file path.
        layer (str, optional): The layer. If not specified, and there is only 
            one layer in the file, this layer is used. Otherwise exception.
    """
    # Init
    path_p = Path(path)
    layerinfo = get_layerinfo(path_p, layer)

    # Now really remove index
    datasource = None
    geofiletype = GeofileType(path_p)  
    try:
        if geofiletype.is_spatialite_based:
            datasource = gdal.OpenEx(str(path_p), nOpenFlags=gdal.OF_UPDATE)
            datasource.ExecuteSQL(
                    f"SELECT DisableSpatialIndex('{layerinfo.name}', '{layerinfo.geometrycolumn}')",
                    dialect='SQLITE') 
        elif geofiletype == GeofileType.ESRIShapefile:
            # DROP SPATIAL INDEX ON ... command gives an error, so just remove .qix
            index_path = path_p.parent / f"{path_p.stem}.qix" 
            index_path.unlink()
        else:
            raise Exception(f"remove_spatial_index is not supported for {path_p.suffix} file")
            #datasource = gdal.OpenEx(str(path_p), nOpenFlags=gdal.OF_UPDATE)
            #datasource.ExecuteSQL(f'DROP SPATIAL INDEX ON "{layerinfo.name}"')
    finally:
        if datasource is not None:
            del datasource

def rename_layer(
        path: Union[str, 'os.PathLike[Any]'],
        new_layer: str,
        layer: Optional[str] = None):
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
    path_p = Path(path)
    if layer is None:
        layer = get_only_layer(path_p)

    # Now really rename
    datasource = None
    geofiletype = GeofileType(path_p)  
    try:
        if geofiletype.is_spatialite_based:
            datasource = gdal.OpenEx(str(path_p), nOpenFlags=gdal.OF_UPDATE)
            sql_stmt = f'ALTER TABLE "{layer}" RENAME TO "{new_layer}"'
            datasource.ExecuteSQL(sql_stmt)
        elif geofiletype == GeofileType.ESRIShapefile:
            raise ValueError(f"rename_layer is not possible for {geofiletype} file")
        else:
            raise ValueError(f"rename_layer is not implemented for {path_p.suffix} file")
    finally:
        if datasource is not None:
            del datasource

def rename_column(
        path: Union[str, 'os.PathLike[Any]'],
        column_name: str,
        new_column_name: str,
        layer: Optional[str] = None):
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
    path_p = Path(path)
    if layer is None:
        layer = get_only_layer(path_p)
    info = get_layerinfo(path_p)
    if column_name not in info.columns and new_column_name in info.columns:
        logger.info(f"Column {column_name} seems to be renamed already to {new_column_name}, so just return")
        return

    # Now really rename
    datasource = None
    geofiletype = GeofileType(path_p)  
    try:
        if geofiletype.is_spatialite_based:
            datasource = gdal.OpenEx(str(path_p), nOpenFlags=gdal.OF_UPDATE)
            sql_stmt = f'ALTER TABLE "{layer}" RENAME COLUMN "{column_name}" TO "{new_column_name}"'
            datasource.ExecuteSQL(sql_stmt)
        elif geofiletype == GeofileType.ESRIShapefile:
            raise ValueError(f"rename_layer is not possible for {geofiletype} file")
        else:
            raise ValueError(f"rename_layer is not implemented for {path_p.suffix} file")
    finally:
        if datasource is not None:
            del datasource
            
class DataType(enum.Enum):
    """
    This enum defines the standard data types that can be used for columns. 
    """
    TEXT = 'TEXT'           
    """Column with text data: ~ string, char, varchar, clob."""
    INTEGER = 'INTEGER'     
    """Column with integer data."""
    REAL = 'REAL'           
    """Column with floating point data: ~ float, double."""
    DATE = 'DATE'           
    """Column with date data."""
    TIMESTAMP = 'TIMESTAMP' 
    """Column with timestamp data: ~ datetime."""
    BOOLEAN = 'BOOLEAN'     
    """Column with boolean data."""
    BLOB = 'BLOB'           
    """Column with binary data."""
    NUMERIC = 'NUMERIC'     
    """Column with numeric data: exact decimal data."""
    
def add_column(
        path: Union[str, 'os.PathLike[Any]'],
        name: str,
        type: Union[DataType, str],
        expression: Union[str, int, float, None] = None, 
        layer: Optional[str] = None,
        force_update: bool = False):
    """
    Add a column to a layer of the geofile.

    Args:
        path (PathLike): Path to the geofile
        name (str): Name for the new column
        type (DataType, str): Column type of the new column.
        expression (str, optional): SQLite expression to use to update 
            the value. Defaults to None.
        layer (str, optional): The layer name. If None and the geofile
            has only one layer, that layer is used. Defaults to None.
        force_update (bool, optional): If the column already exists, execute 
            the update anyway. Defaults to False. 

    Raises:
        ex: [description]
    """

    ##### Init #####
    if isinstance(type, DataType):
        type_str = type.value
    else:
        type_str = type
    path_p = Path(path)
    if layer is None:
        layer = get_only_layer(path_p)
    layerinfo_orig = get_layerinfo(path_p, layer)
    
    ##### Go! #####
    datasource = None
    try:
        #datasource = gdal.OpenEx(str(path_p), nOpenFlags=gdal.OF_UPDATE)
        columns_upper = [column.upper() for column in layerinfo_orig.columns]
        if name.upper() not in columns_upper:
            # If column doesn't exist yet, create it
            #if name not in getlayerinfo(path_p, layer=layer).columns:
            sqlite_stmt = f'ALTER TABLE "{layer}" ADD COLUMN "{name}" {type_str}'
            ogr_util.vector_info(path=path_p, sql_stmt=sqlite_stmt, sql_dialect='SQLITE', readonly=False)
            #datasource.ExecuteSQL(sqlite_stmt, dialect='SQLITE')
        else:
            logger.warning(f"Column {name} existed already in {path_p}, layer {layer}")
            
        # If an expression was provided and update can be done, go for it...
        if(expression is not None 
           and (name not in layerinfo_orig.columns 
                or force_update is True)):
            sqlite_stmt = f'UPDATE "{layer}" SET "{name}" = {expression}'
            ogr_util.vector_info(path=path_p, sql_stmt=sqlite_stmt, sql_dialect='SQLITE', readonly=False)
            #datasource.ExecuteSQL(sqlite_stmt, dialect='SQLITE')
    finally:
        if datasource is not None:
            del datasource

def update_column(
        path: Union[str, 'os.PathLike[Any]'],
        name: str, 
        expression: str,
        layer: Optional[str] = None,
        where: Optional[str] = None):
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

    ##### Init #####
    path_p = Path(path)
    if layer is None:
        layer = get_only_layer(path_p)
    layerinfo_orig = get_layerinfo(path_p, layer)
    
    ##### Go! #####
    datasource = None
    try:
        #datasource = gdal.OpenEx(str(path_p), nOpenFlags=gdal.OF_UPDATE)
        columns_upper = [column.upper() for column in layerinfo_orig.columns]
        if name.upper() not in columns_upper:
            # If column doesn't exist yet, error!
            raise ValueError(f"Column {name} doesn't exist in {path_p}, layer {layer}")
            
        # If an expression was provided and update can be done, go for it...
        sqlite_stmt = f'UPDATE "{layer}" SET "{name}" = {expression}'
        if where is not None:
            sqlite_stmt += f"\n WHERE {where}"
        ogr_util.vector_info(path=path_p, sql_stmt=sqlite_stmt, sql_dialect='SQLITE', readonly=False)
        #datasource.ExecuteSQL(sqlite_stmt, dialect='SQLITE')
    finally:
        if datasource is not None:
            del datasource

def read_file(
        path: Union[str, 'os.PathLike[Any]'],
        layer: Optional[str] = None,
        columns: Optional[List[str]] = None,
        bbox = None,
        rows = None,
        ignore_geometry: bool = False) -> gpd.GeoDataFrame:
    """
    Reads a file to a geopandas GeoDataframe. 
    
    The file format is detected based on the filepath extension.

    Args:
        path (file path): path to the file to read from
        layer (str, optional): The layer to read. Defaults to None,  
            then reads the only layer in the file or throws error.
        columns (List[str], optional): The (non-geometry) columns to read. 
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
            ignore_geometry=ignore_geometry)

    # No assert to keep backwards compatibility
    return result_gdf    # type: ignore

def read_file_nogeom(
        path: Union[str, 'os.PathLike[Any]'],
        layer: Optional[str] = None,
        columns: Optional[List[str]] = None,
        bbox = None,
        rows = None) -> pd.DataFrame:
    """
    Reads a file to a pandas Dataframe. 
    
    The file format is detected based on the filepath extension.

    Args:
        path (file path): path to the file to read from
        layer (str, optional): The layer to read. Defaults to None,  
            then reads the only layer in the file or throws error.
        columns (List[str], optional): The (non-geometry) columns to read. 
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
            ignore_geometry=True)
    assert isinstance(result_gdf, pd.DataFrame)
    return result_gdf

def _read_file_base(
        path: Union[str, 'os.PathLike[Any]'],
        layer: Optional[str] = None,
        columns: Optional[List[str]] = None,
        bbox = None,
        rows = None,
        ignore_geometry: bool = False) -> Union[pd.DataFrame, gpd.GeoDataFrame]:
    """
    Reads a file to a pandas Dataframe. 
    
    The file format is detected based on the filepath extension.

    Args:
        path (file path): path to the file to read from
        layer (str, optional): The layer to read. Defaults to None,  
            then reads the only layer in the file or throws error.
        columns (List[str], optional): The (non-geometry) columns to read. 
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
    path_p = Path(path)
    if path_p.exists() is False:
        raise ValueError(f"File doesnt't exist: {path}")
    geofiletype = GeofileType(path_p)

    # If no layer name specified, check if there is only one layer in the file.
    if layer is None:
        layer = get_only_layer(path_p)

    # Depending on the extension... different implementations
    if geofiletype == GeofileType.ESRIShapefile:
        result_gdf = gpd.read_file(str(path_p), bbox=bbox, rows=rows, ignore_geometry=ignore_geometry)
    elif geofiletype == GeofileType.GeoJSON:
        result_gdf = gpd.read_file(str(path_p), bbox=bbox, rows=rows, ignore_geometry=ignore_geometry)
    elif geofiletype.is_spatialite_based:
        result_gdf = gpd.read_file(str(path_p), layer=layer, bbox=bbox, rows=rows, ignore_geometry=ignore_geometry)
    else:
        raise ValueError(f"Not implemented for geofiletype {geofiletype}")

    # If columns to read are specified... filter non-geometry columns 
    # case-insensitive 
    if columns is not None:
        columns_upper = [column.upper() for column in columns]
        columns_upper.append('GEOMETRY')
        columns_to_keep = [col for col in result_gdf.columns if (col.upper() in columns_upper)]
        result_gdf = result_gdf[columns_to_keep]
    
    # assert to evade pyLance warning 
    assert isinstance(result_gdf, pd.DataFrame) or isinstance(result_gdf, gpd.GeoDataFrame) 
    return result_gdf

def read_file_sql(
        path: Union[str, 'os.PathLike[Any]'],
        sql_stmt: str,
        sql_dialect: str = 'SQLITE',
        layer: Optional[str] = None,
        ignore_geometry: bool = False) -> Union[pd.DataFrame, gpd.GeoDataFrame]:
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
    path_p = Path(path)
    layer_list = None
    if layer is not None:
        layer_list = [layer]

    # Now we're ready to go!
    with tempfile.TemporaryDirectory() as tmpdir:
        # Execute sql againts file and write to temp file
        tmp_path = Path(tmpdir) / 'read_file_sql_tmp_file.gpkg'
        ogr_util.vector_translate(
                input_path=path_p,
                output_path=tmp_path,
                sql_stmt=sql_stmt,
                sql_dialect=sql_dialect,
                input_layers=layer_list,
                create_spatial_index=False)
            
        # Read and return result
        return _read_file_base(tmp_path, ignore_geometry=ignore_geometry)

def to_file(
        gdf: gpd.GeoDataFrame,
        path: Union[str, 'os.PathLike[Any]'],
        layer: Optional[str] = None,
        force_multitype: bool = False,
        append: bool = False,
        append_timeout_s: int = 600,
        index: bool = True):
    """
    Writes a pandas dataframe to file. The fileformat is detected based on the filepath extension.

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
    # TODO: think about if possible/how to support adding optional parameter and pass them to next 
    # function, example encoding, float_format,...

    # Check input parameters
    path_p = Path(path)

    # If no layer name specified, use the filename (without extension)
    if layer is None:
        layer = Path(path_p).stem
    # If the dataframe is empty, log warning and return
    if len(gdf) <= 0:
        #logger.warn(f"Cannot write an empty dataframe to {filepath}.{layer}")
        return

    def write_to_file(
            gdf: gpd.GeoDataFrame,
            path: Path, 
            layer: str, 
            index: bool = True,
            force_multitype: bool = False,
            append: bool = False):

        # Change mode if append is true
        if append is True:
            if path.exists():
                mode = 'a'
            else:
                mode = 'w'
        else:
            mode = 'w'

        geofiletype = GeofileType(path)
        if geofiletype == GeofileType.ESRIShapefile:
            if index is True:
                gdf_to_write = gdf.reset_index(drop=True)
            else:
                gdf_to_write = gdf
            gdf_to_write.to_file(str(path), mode=mode)
        elif geofiletype == GeofileType.GPKG:
            # Try to harmonize the geometrytype to one (multi)type, as GPKG
            # doesn't like > 1 type in a layer
            gdf_to_write = gdf.copy()
            gdf_to_write.geometry = geoseries_util.harmonize_geometrytypes(
                    gdf.geometry, force_multitype=force_multitype)
            gdf_to_write.to_file(str(path), layer=layer, driver=geofiletype.ogrdriver, mode=mode)
        elif geofiletype == GeofileType.SQLite:
            gdf.to_file(str(path), layer=layer, driver=geofiletype.ogrdriver, mode=mode)
        else:
            raise ValueError(f"Not implemented for geofiletype {geofiletype}")

    # If no append, just write to output path
    if append is False:
        write_to_file(gdf=gdf, path=path_p, layer=layer, index=index, 
                force_multitype=force_multitype, append=append)
    else:
        # If append is asked, check if the fiona driver supports appending. If
        # not, write to temporary output file 
        
        # Remark: fiona pre-1.8.14 didn't support appending to geopackage. Once 
        # older versions becomes rare, dependency can be put to this version, and 
        # this code can be cleaned up...
        geofiletype = GeofileType(path_p)
        gdftemp_path = None
        gdftemp_lockpath = None
        if 'a' not in fiona.supported_drivers[geofiletype.ogrdriver]:
            # Get a unique temp file path. The file cannot be created yet, so 
            # only create a lock file to evade other processes using the same 
            # temp file name 
            gdftemp_path, gdftemp_lockpath = io_util.get_tempfile_locked(
                    base_filename='gdftemp',
                    suffix=path_p.suffix,
                    dirname='geofile_to_file')
            write_to_file(gdf, path=gdftemp_path, layer=layer, index=index, 
                    force_multitype=force_multitype)  
        
        # Files don't typically support having multiple processes writing 
        # simultanously to them, so use lock file to synchronize access.
        lockfile = Path(f"{str(path_p)}.lock")
        start_time = datetime.datetime.now()
        while(True):
            if io_util.create_file_atomic(lockfile) is True:
                try:
                    # If gdf wasn't written to temp file, use standard write-to-file
                    if gdftemp_path is None:
                        write_to_file(gdf=gdf, path=path_p, layer=layer, index=index, 
                                force_multitype=force_multitype, append=True)
                    else:
                        # If gdf was written to temp file, use append_to_nolock + cleanup
                        _append_to_nolock(src=gdftemp_path, dst=path_p, dst_layer=layer)
                        remove(gdftemp_path)
                        if gdftemp_lockpath is not None:
                            gdftemp_lockpath.unlink()
                finally:
                    lockfile.unlink()
                    return
            else:
                time_waiting = (datetime.datetime.now()-start_time).total_seconds()
                if time_waiting > append_timeout_s:
                    raise RuntimeError(f"to_file timeout of {append_timeout_s} reached, so stop trying append to {path_p}!")
            
            # Sleep for a second before trying again
            time.sleep(1)
        
def get_crs(path: Union[str, 'os.PathLike[Any]']) -> pyproj.CRS:
    """
    Get the CRS (projection) of the file

    Args:
        path (PathLike): Path to the file.

    Returns:
        pyproj.CRS: The projection of the file
    """
    # TODO: seems like support for multiple layers in the file isn't here yet??? 
    with fiona.open(str(path), 'r') as geofile:
        assert geofile is not None
        return pyproj.CRS(geofile.crs)

def is_geofile(path: Union[str, 'os.PathLike[Any]']) -> bool:
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
    except:
        return False

def cmp(path1: Union[str, 'os.PathLike[Any]'], 
        path2: Union[str, 'os.PathLike[Any]']) -> bool:
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
    if path1_p.suffix.lower() == '.shp':
        path2_noext, _ = os.path.splitext(path2_p)
        shapefile_base_suffixes = [".shp", ".dbf", ".shx"]
        path1_noext = path1_p.parent / path1_p.stem
        path2_noext = path2_p.parent / path2_p.stem
        for ext in shapefile_base_suffixes:
            if not filecmp.cmp(f"{str(path1_noext)}{ext}", f"{str(path2_noext)}{ext}"):
                logger.info(f"File {path1_noext}{ext} is different from {path2_noext}{ext}")
                return False
        return True
    else:
        return filecmp.cmp(str(path1_p), str(path2_p))
    
def copy(
        src: Union[str, 'os.PathLike[Any]'], 
        dst: Union[str, 'os.PathLike[Any]']):
    """
    Copies the geofile from src to dst. Is the source file is a geofile containing
    of multiple files (eg. .shp) all files are copied.

    Args:
        src (PathLike): the file to copy.
        dst (PathLike): the location to copy the file(s) to.
    """
    # Check input parameters
    src_p = Path(src)
    dst_p = Path(dst)
    geofiletype = GeofileType(src_p)

    # Copy the main file
    shutil.copy(str(src_p), dst_p)

    # For some file types, extra files need to be copied
    # If dest is a dir, just use move. Otherwise concat dest filepaths
    if geofiletype.suffixes_extrafiles is not None:
        if dst_p.is_dir():
            for suffix in geofiletype.suffixes_extrafiles:
                srcfile = src_p.parent / f"{src_p.stem}{suffix}"
                if srcfile.exists():
                    shutil.copy(str(srcfile), dst_p)
        else:
            for suffix in geofiletype.suffixes_extrafiles:
                srcfile = src_p.parent / f"{src_p.stem}{suffix}"
                dstfile = dst_p.parent / f"{dst_p.stem}{suffix}"
                if srcfile.exists():
                    shutil.copy(str(srcfile), dstfile)                

def move(
        src: Union[str, 'os.PathLike[Any]'], 
        dst: Union[str, 'os.PathLike[Any]']):
    """
    Moves the geofile from src to dst. If the source file is a geofile containing
    of multiple files (eg. .shp) all files are moved.

    Args:
        src (PathLike): the file to move
        dst (PathLike): the location to move the file(s) to
    """
    # Check input parameters
    src_p = Path(src)
    dst_p = Path(dst)
    geofiletype = GeofileType(src_p)

    # Move the main file
    shutil.move(str(src_p), dst_p, copy_function=io_util.copyfile)

    # For some file types, extra files need to be moved
    # If dest is a dir, just use move. Otherwise concat dest filepaths
    if geofiletype.suffixes_extrafiles is not None:
        if dst_p.is_dir():
            for suffix in geofiletype.suffixes_extrafiles:
                srcfile = src_p.parent / f"{src_p.stem}{suffix}"
                if srcfile.exists():
                    shutil.move(str(srcfile), dst_p, copy_function=io_util.copyfile)
        else:
            for suffix in geofiletype.suffixes_extrafiles:
                srcfile = src_p.parent / f"{src_p.stem}{suffix}"
                dstfile = dst_p.parent / f"{dst_p.stem}{suffix}"
                if srcfile.exists():
                    shutil.move(str(srcfile), dstfile, copy_function=io_util.copyfile)

def remove(path: Union[str, 'os.PathLike[Any]']):
    """
    Removes the geofile. Is it is a geofile composed of multiple files 
    (eg. .shp) all files are removed. 
    If .lock files are present, they are removed as well. 

    Args:
        path (PathLike): the file to remove
    """
    # Check input parameters
    path_p = Path(path)
    geofiletype = GeofileType(path_p)
    
    # If there is a lock file, remove it
    lockfile_path = path_p.parent / f"{path_p.name}.lock"
    lockfile_path.unlink(missing_ok=True)

    # Remove the main file
    if path_p.exists():
        path_p.unlink()

    # For some file types, extra files need to be removed
    if geofiletype.suffixes_extrafiles is not None:
        for suffix in geofiletype.suffixes_extrafiles:
            curr_path = path_p.parent / f"{path_p.stem}{suffix}"
            if curr_path.exists():
                curr_path.unlink()

def append_to(
        src: Union[str, 'os.PathLike[Any]'], 
        dst: Union[str, 'os.PathLike[Any]'],
        src_layer: Optional[str] = None,
        dst_layer: Optional[str] = None,
        explodecollections: bool = False,
        force_output_geometrytype: Union[GeometryType, str, None] = None,
        create_spatial_index: bool = True,
        append_timeout_s: int = 600,
        transaction_size: int = 50000,
        verbose: bool = False):
    """
    Append src file to the dst file.

    remark: append is not supported for all filetypes in fiona/geopandas (0.8)
    so workaround via gdal needed.

    Args:
        src (Union[str,): source file path.
        dst (Union[str,): destination file path.
        src_layer (str, optional): source layer. Defaults to None.
        dst_layer (str, optional): destination layer. Defaults to None.
        explodecollections (bool), optional): True to output only simple geometries. 
            Defaults to False.
        force_output_geometrytype (GeometryType, optional): geometry type. 
            to (try to) force the output to. Defaults to None.
        create_spatial_index (bool, optional): True to create a spatial index 
            on the destination file/layer. Defaults to True.
        append_timeout_s (int, optional): timeout to use if the output file is
            being written to by another process already. Defaults to 600.
        transaction_size (int, optional): Transaction size. 
            Defaults to 50000.
        verbose (bool, optional): True to write verbose output. Defaults to False.

    Raises:
        ValueError: an invalid parameter value was passed.
        RuntimeError: timeout was reached while trying to append data to path.
    """
    src_p = Path(src)
    dst_p = Path(dst)
    if force_output_geometrytype is not None:
        force_output_geometrytype = GeometryType(force_output_geometrytype)
    
    # Files don't typically support having multiple processes writing 
    # simultanously to them, so use lock file to synchronize access.
    lockfile = Path(f"{str(dst_p)}.lock")

    # If the destination file doesn't exist yet, but the lockfile does, 
    # try removing the lockfile as it might be a ghost lockfile. 
    if dst_p.exists() is False and lockfile.exists() is True:
        try: 
            lockfile.unlink()
        except:
            None

    # Creating lockfile and append
    start_time = datetime.datetime.now()
    while(True):
            
        if io_util.create_file_atomic(lockfile) is True:
            try:
                # append
                _append_to_nolock(
                        src=src_p, 
                        dst=dst_p,
                        src_layer=src_layer,
                        dst_layer=dst_layer,
                        explodecollections=explodecollections,
                        force_output_geometrytype=force_output_geometrytype,
                        create_spatial_index=create_spatial_index,
                        transaction_size=transaction_size,
                        verbose=verbose)
            finally:
                lockfile.unlink()
                return
        else:
            time_waiting = (datetime.datetime.now()-start_time).total_seconds()
            if time_waiting > append_timeout_s:
                raise RuntimeError(f"append_to timeout of {append_timeout_s} reached, so stop trying to write to {dst_p}!")
        
        # Sleep for a second before trying again
        time.sleep(1)

def _append_to_nolock(
        src: Path, 
        dst: Path,
        src_layer: Optional[str] = None,
        dst_layer: Optional[str] = None,
        explodecollections: bool = False,
        force_output_geometrytype: Optional[GeometryType] = None,
        create_spatial_index: bool = True,
        transaction_size: int = 50000,
        verbose: bool = False):
    # Append
    translate_info = ogr_util.VectorTranslateInfo(
            input_path=src,
            output_path=dst,
            translate_description=None,
            input_layers=src_layer,
            output_layer=dst_layer,
            transaction_size=transaction_size,
            append=True,
            update=True,
            explodecollections=explodecollections,
            force_output_geometrytype=force_output_geometrytype,
            create_spatial_index=create_spatial_index,
            verbose=verbose)
    ogr_util.vector_translate_by_info(info=translate_info)

def convert(
        src: Union[str, 'os.PathLike[Any]'], 
        dst: Union[str, 'os.PathLike[Any]'],
        src_layer: Optional[str] = None,
        dst_layer: Optional[str] = None,
        explodecollections: bool = False,
        force_output_geometrytype: Optional[GeometryType] = None,
        force: bool = False):
    """
    Convert the source file to the destination file. File types will be 
    detected based on the file extensions.

    Args:
        src (PathLike): The source file path.
        dst (PathLike): The destination file path.
        src_layer (str, optional): The source layer. If None and there is only  
            one layer in the src file, that layer is taken. Defaults to None.
        dst_layer (str, optional): The destination layer. If None, the file 
            stem is taken as layer name. Defaults to None.
        explodecollections (bool), optional): True to output only simple 
            geometries. Defaults to False.
        force_output_geometrytype (GeometryType, optional): Geometry type. 
            to (try to) force the output to. Defaults to None.
        force (bool, optional): overwrite existing output file(s). 
            Defaults to False.
    """
    src_p = Path(src)
    dst_p = Path(dst)

    # If dest file exists already, remove it
    if dst_p.exists():
        if force is True:
            remove(dst_p)
        else:
            logger.info(f"Output file exists already, so stop: {dst_p}")
            return

    # Convert
    logger.info(f"Convert {src_p} to {dst_p}")
    _append_to_nolock(src_p, dst_p, src_layer, dst_layer, 
            explodecollections=explodecollections, 
            force_output_geometrytype=force_output_geometrytype)

def get_driver(path: Union[str, 'os.PathLike[Any]']) -> str:
    """
    Get the driver to use for the file extension of this filepath.

    DEPRECATED, use GeometryType(Path).ogrdriver.

    Args:
        path (PathLike): The file path.

    Returns:
        str: The OGR driver name.
    """
    warnings.warn("get_driver is deprecated, use GeometryType(Path).ogrdriver", FutureWarning)
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
    warnings.warn("get_driver_for_ext is deprecated, use GeometryType(Path).ogrdriver", FutureWarning)
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
    warnings.warn("to_generaltypeid is deprecated, use GeometryType.to_multigeometrytype", FutureWarning)
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
    warnings.warn("to_generaltypeid is deprecated, use GeometryType.to_primitivetypeid", FutureWarning)
    return geometry_util.GeometryType(geometrytypename).to_primitivetype.value
