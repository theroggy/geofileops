# -*- coding: utf-8 -*-
"""
Module containing utilities regarding the usage of ogr functionalities.
"""

#-------------------------------------
# Import/init needed modules
#-------------------------------------
from io import StringIO
import logging
import os
from pathlib import Path
import pprint
import re
import subprocess
import tempfile
from threading import Lock
import time
from typing import List, Optional, Tuple, Union

import geopandas as gpd
from osgeo import gdal
gdal.UseExceptions() 
gdal.ConfigurePythonLogging(logger_name='gdal', enable_debug=False)

import geofileops as gfo
from geofileops.util.geofiletype import GeofileType
from geofileops.util.geometry_util import GeometryType

#-------------------------------------------------------------
# First define/init some general variables/constants
#-------------------------------------------------------------

# Make sure only one instance per process is running
lock = Lock()

# Get a logger...
logger = logging.getLogger(__name__)

#-------------------------------------------------------------
# The real work
#-------------------------------------------------------------

def get_drivers() -> dict:
    drivers = {}
    for i in range(gdal.GetDriverCount()):
        driver = gdal.GetDriver(i)
        drivers[driver.ShortName] = driver.GetDescription()
    return drivers

class VectorTranslateInfo:
    def __init__(
            self,
            input_path: Path, 
            output_path: Path,
            translate_description: Optional[str] = None,
            input_layers: Union[List[str], str, None] = None,
            output_layer: Optional[str] = None,
            spatial_filter: Optional[Tuple[float, float, float, float]] = None,
            clip_bounds: Optional[Tuple[float, float, float, float]] = None, 
            sql_stmt: Optional[str] = None,
            sql_dialect: Optional[str] = None,
            transaction_size: int = 65536,
            append: bool = False,
            update: bool = False,
            create_spatial_index: Optional[bool] = None,
            explodecollections: bool = False,
            force_output_geometrytype: Optional[GeometryType] = None,
            input_prelude_statements: List[str] = [],
            sqlite_journal_mode: Optional[str] = None,
            verbose: bool = False):
        self.input_path = input_path
        self.output_path = output_path
        self.translate_description = translate_description
        self.input_layers = input_layers
        self.output_layer = output_layer
        self.spatial_filter = spatial_filter
        self.clip_bounds = clip_bounds
        self.sql_stmt = sql_stmt
        self.sql_dialect = sql_dialect
        self.transaction_size = transaction_size
        self.append = append
        self.update = update
        self.create_spatial_index = create_spatial_index
        self.explodecollections = explodecollections
        self.force_output_geometrytype = force_output_geometrytype
        self.input_prelude_statements = input_prelude_statements
        self.sqlite_journal_mode = sqlite_journal_mode
        self.verbose = verbose
  
def vector_translate_by_info(info: VectorTranslateInfo):

    return vector_translate( 
            input_path=info.input_path,
            output_path=info.output_path,
            translate_description=info.translate_description,
            input_layers=info.input_layers,
            output_layer=info.output_layer,
            spatial_filter=info.spatial_filter,
            clip_bounds=info.clip_bounds,
            sql_stmt=info.sql_stmt,
            sql_dialect=info.sql_dialect,
            transaction_size=info.transaction_size,
            append=info.append,
            update=info.update,
            create_spatial_index=info.create_spatial_index,
            explodecollections=info.explodecollections,
            force_output_geometrytype=info.force_output_geometrytype,
            input_prelude_statements=info.input_prelude_statements,
            sqlite_journal_mode=info.sqlite_journal_mode,
            verbose=info.verbose)

def vector_translate(
        input_path: Union[Path, str], 
        output_path: Path,
        translate_description: Optional[str] = None,
        input_layers: Union[List[str], str, None] = None,
        output_layer: Optional[str] = None,
        spatial_filter: Optional[Tuple[float, float, float, float]] = None,
        clip_bounds: Optional[Tuple[float, float, float, float]] = None, 
        sql_stmt: Optional[str] = None,
        sql_dialect: Optional[str] = None,
        transaction_size: int = 65536,
        append: bool = False,
        update: bool = False,
        create_spatial_index: Optional[bool] = None,
        explodecollections: bool = False,
        force_output_geometrytype: Optional[GeometryType] = None,
        input_prelude_statements: List[str] = [],
        sqlite_journal_mode: Optional[str] = None,
        verbose: bool = False) -> bool:

    # Remark: when executing a select statement, I keep getting error that 
    # there are two columns named "geom" as he doesnt see the "geom" column  
    # in the select as a geometry column. Probably a version issue. Maybe 
    # try again later.
    args = []

    # Cleanup the input_layers variable.
    if isinstance(input_path, Path) and input_path.suffix.lower() == '.shp':
        # For shapefiles, having input_layers not None gives issues
        input_layers = None
    elif sql_stmt is not None:
        # If a sql statement is passed, the input layers are not relevant,
        # and ogr2ogr will give a warning, so clear it.
        input_layers = None
     
    # Sql'ing, Filtering, clipping  
    if spatial_filter is not None:
        args.extend(['-spat', str(spatial_filter[0]), str(spatial_filter[1]), 
                    str(spatial_filter[2]), str(spatial_filter[3])])
    if clip_bounds is not None:
        args.extend(['-clipsrc', str(clip_bounds[0]), str(clip_bounds[1]), 
                    str(clip_bounds[2]), str(clip_bounds[3])])
    '''
    if sqlite_stmt is not None:
        args.extend(['-sql', sqlite_stmt, '-dialect', 'sqlite'])
    '''

    # Input file open options
    if len(input_prelude_statements) > 0:
        input_prelude_statements_str = f'PRELUDE_STATEMENTS="{"; ".join(input_prelude_statements)}"'
        args.extend(['-oo', input_prelude_statements_str])

    # Output file options
    if output_path.exists() is True:
        if append is True:
            args.append('-append')
        if update is True:
            args.append('-update')

    # Files
    #args.append(output_path)
    #args.append(input_path)

    # Output layer options
    if explodecollections is True:
        args.append('-explodecollections')
    if output_layer is not None:
        args.extend(['-nln', output_layer])
    if force_output_geometrytype is not None:
        args.extend(['-nlt', force_output_geometrytype.name])
    args.extend(['-nlt', 'PROMOTE_TO_MULTI'])
    if transaction_size is not None:
        args.extend(['-gt', str(transaction_size)])

    # Output layer creation options
    layerCreationOptions = []
    # TODO: should check if the layer exists instead of the file
    if not output_path.exists():
        if create_spatial_index is not None:
            if create_spatial_index is True:
                layerCreationOptions.extend(['SPATIAL_INDEX=YES'])
            else:
                layerCreationOptions.extend(['SPATIAL_INDEX=NO'])
    
    # Get output format from the filename
    output_filetype = GeofileType(output_path)

    # Sqlite specific options
    datasetCreationOptions = []
    if output_filetype == GeofileType.SQLite:
        # Use the spatialite type of sqlite
        #datasetCreationOptions.extend(['-dsco', 'SPATIALITE=YES'])
        datasetCreationOptions.append('SPATIALITE=YES')
      
    '''
    # Try if the busy_timeout isn't giving problems rather than solving them...
    if sqlite_journal_mode is not None:
        datasetCreationOptions.extend(['--config', 'OGR_SQLITE_PRAGMA', f"journal_mode={sqlite_journal_mode},busy_timeout=5000"])  
    else:
        datasetCreationOptions.extend(['--config OGR_SQLITE_PRAGMA busy_timeout=5000'])  
    '''
    if sqlite_journal_mode is not None:
        gdal.SetConfigOption('OGR_SQLITE_PRAGMA', f"journal_mode={sqlite_journal_mode}")

    #if append is False:
    #    args.extend(['--config', 'OGR_SQLITE_PRAGMA', '"journal_mode=WAL"'])
    #    args.extend(['-dsco', 'ADD_GPKG_OGR_CONTENTS=NO'])
    #else:
    #    args.extend(['--config', 'OGR_SQLITE_PRAGMA', 'busy_timeout=-1'])  
    #args.extend(['--config', 'OGR_SQLITE_SYNCHRONOUS', 'OFF'])  
    gdal.SetConfigOption('OGR_SQLITE_CACHE', '128')

    options = gdal.VectorTranslateOptions(
            options=args, 
            format=output_filetype.ogrdriver, 
            accessMode=None, 
            srcSRS=None, 
            dstSRS=None, 
            reproject=False, 
            SQLStatement=sql_stmt,
            SQLDialect=sql_dialect,
            where=None, #"geom IS NOT NULL", 
            selectFields=None, 
            addFields=False, 
            forceNullable=False, 
            spatFilter=spatial_filter, 
            spatSRS=None,
            datasetCreationOptions=datasetCreationOptions, 
            layerCreationOptions=layerCreationOptions, 
            layers=input_layers,
            layerName=output_layer,
            geometryType=None, 
            dim=None, 
            segmentizeMaxDist=None, 
            zField=None, 
            skipFailures=False, 
            limit=None, 
            callback=None, 
            callback_data=None)

    input_ds = None
    try: 
        # In some cases gdal only raises the last exception instead of the stack in VectorTranslate, 
        # so you lose necessary details! -> uncomment gdal.DontUseExceptions() when debugging!
        
        #gdal.DontUseExceptions()
        gdal.UseExceptions() 
        gdal.ConfigurePythonLogging(logger_name='gdal', enable_debug=False)

        logger.debug(f"Execute {sql_stmt} on {input_path}")
        input_ds = gdal.OpenEx(str(input_path))
        
        # TODO: memory output support might be interesting to support
        result_ds = gdal.VectorTranslate(
                destNameOrDestDS=str(output_path),
                srcDS=input_ds,
                #SQLStatement=sql_stmt,
                #SQLDialect=sql_dialect,
                #layerName=output_layer
                options=options)

        if result_ds is None:
            raise Exception("BOEM")
        else:
            if result_ds.GetLayerCount() == 0:
                del result_ds
                if output_path.exists():
                    gfo.remove(output_path)
    except Exception as ex:
        message = f"Error executing {sql_stmt}"
        logger.exception(message)
        raise Exception(message) from ex
    finally:
        if input_ds is not None:
            del input_ds
        
    return True

"""
def vector_translate_exe(
        input_path: Path, 
        output_path: Path,
        translate_description: Optional[str] = None,
        input_layers: Union[List[str], str, None] = None,
        output_layer: Optional[str] = None,
        spatial_filter: Optional[Tuple[float, float, float, float]] = None,
        clip_bounds: Optional[Tuple[float, float, float, float]] = None, 
        sql_stmt: Optional[str] = None,
        sql_dialect: Optional[str] = None,
        transaction_size: int = 10000,
        append: bool = False,
        update: bool = False,
        create_spatial_index: Optional[bool] = None,
        explodecollections: bool = False,
        force_output_geometrytype: Optional[GeometryType] = None,
        sqlite_journal_mode: Optional[str] = None,
        verbose: bool = False) -> bool:

    ##### Init #####
    if output_layer is None:
        output_layer = output_path.stem
    if os.name == 'nt':
        ogr2ogr_exe = 'ogr2ogr.exe'
    else:
        ogr2ogr_exe = 'ogr2ogr'
    
    # Add all parameters to args list
    args = [str(ogr2ogr_exe)]
    #if verbose:
    #    args.append('-progress')

    # Sql'ing, Filtering, clipping  
    if spatial_filter is not None:
        args.extend(['-spat', str(spatial_filter[0]), str(spatial_filter[1]), 
                    str(spatial_filter[2]), str(spatial_filter[3])])
    if clip_bounds is not None:
        args.extend(['-clipsrc', str(clip_bounds[0]), str(clip_bounds[1]), 
                    str(clip_bounds[2]), str(clip_bounds[3])])
    if sql_stmt is not None:
        args.extend(['-sql', sql_stmt])
    if sql_dialect is not None:
        args.extend(['-dialect', sql_dialect])

    # Output file options
    if output_path.exists() is True:
        if append is True:
            args.append('-append')
        if update is True:
            args.append('-update')

    # Files and input layer(s)
    args.append(str(output_path))
    args.append(str(input_path))
    
    # Treat input_layers variable
    # Remarks: 
    #   * For shapefiles, having input_layers not None gives issues
    #   * If a sql statement is passed, the input layers are not relevant,
    #     and ogr2ogr will give a warning, so clear it.
    if(input_layers is not None 
       and input_path.suffix.lower() != '.shp'
       and sql_stmt is None):
        if isinstance(input_layers, str):
            args.append(input_layers)
        else:
            for input_layer in input_layers:
                args.append(input_layer)
            
    # Output layer options
    if explodecollections is True:
        args.append('-explodecollections')
    if output_layer is not None:
        args.extend(['-nln', output_layer])
    if force_output_geometrytype is not None:
        args.extend(['-nlt', force_output_geometrytype.name])
    args.extend(['-nlt', 'PROMOTE_TO_MULTI'])
    if create_spatial_index is not None:
        if create_spatial_index is True:
            args.extend(['-lco', 'SPATIAL_INDEX=YES'])
        else:
            args.extend(['-lco', 'SPATIAL_INDEX=NO'])
    if transaction_size is not None:
        args.extend(['-gt', str(transaction_size)])
    
    # Sqlite specific options:
    output_filetype = GeofileType(output_path)
    if output_filetype == GeofileType.SQLite:
        # Use the spatialite type of sqlite
        args.extend(['-dsco', 'SPATIALITE=YES'])

    '''
    # Try if the busy_timeout isn't giving problems rather than solving them...
    if sqlite_journal_mode is not None:
        args.extend(['--config', 'OGR_SQLITE_PRAGMA', f"journal_mode={sqlite_journal_mode},busy_timeout=5000"])  
    else:
        args.extend(['--config', 'OGR_SQLITE_PRAGMA', 'busy_timeout=5000'])  
    '''
    if sqlite_journal_mode is not None:
        args.extend(['--config', 'OGR_SQLITE_PRAGMA', f"journal_mode={sqlite_journal_mode}"])  

    #if append is False:
    #    args.extend(['--config', 'OGR_SQLITE_PRAGMA', '"journal_mode=WAL"'])
    #    args.extend(['-dsco', 'ADD_GPKG_OGR_CONTENTS=NO'])
    #else:
    #    args.extend(['--config', 'OGR_SQLITE_PRAGMA', 'busy_timeout=-1'])  
    #args.extend(['--config', 'OGR_SQLITE_SYNCHRONOUS', 'OFF'])  
    args.extend(['--config', 'OGR_SQLITE_CACHE', '128'])

    ##### Now start ogr2ogr #####
    # Save whether the output file exists already prior to the operation
    output_path_exists_already = output_path.exists()

    # Make sure the output dir exists
    os.makedirs(output_path.parent, exist_ok=True)

    # Geopackage/sqlite files are very sensitive for being locked, so retry till 
    # file is not locked anymore... 
    # TODO: ideally, the child processes would die when the parent is killed!
    returncode = None
    err = None
    for retry_count in range(10):
        if translate_description is not None:
            logger.debug(f"Start '{translate_description}' with retry_count: {retry_count}")

        # Start process!
        process = subprocess.Popen(args, 
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=-1, encoding='utf-8')
        output, err = process.communicate()
        returncode = process.returncode

        # If an error occured
        if returncode > 0:
            if str(err).startswith("ERROR 1: database is locked"):
                logger.warn(f"'ERROR 1: database is locked' occured during {translate_description}, retry nb: {retry_count}")
                time.sleep(1)
                continue
            else:
                # If output_path didn't exist yet before, clean it up... if it exists
                if not output_path_exists_already:
                    if output_path.exists():
                        gfo.remove(output_path)
                raise Exception(f"Error executing {pprint.pformat(args)}\n\t-> Return code: {returncode}\n\t-> Error: {err}\n\t->Output: {output}")
        elif(err is not None and err != ""
             and not str(err).startswith(r"Warning 1: Layer creation options ignored since an existing layer is")):
            # No error, but data (warnings) in stderr
            # Remark: the warning about layer creating options is common and not interesting: ignore!
            logger.warn(f"Finished executing {pprint.pformat(args)}")
            logger.warn(f"\t-> Returncode ok, but stderr contains: {err}")

        # Check if the output file contains data
        if output_path.exists():
            fileinfo = _getfileinfo(output_path, readonly=False)
            if len(fileinfo['layers']) == 0:
                output_path.unlink()
                if verbose is True:
                    logger.warn(f"Finished, but empty result for '{translate_description}'")
            elif translate_description is not None:
                if verbose is True:
                    logger.info(f"Finished '{translate_description}'")
                else:
                    logger.debug(f"Finished '{translate_description}'")
        else:
            if verbose is True:
                logger.warn(f"Finished, but empty result for '{translate_description}'")
                
        return True

    # If we get here, the retries didn't suffice to get it executed properly
    raise Exception(f"Error executing {pprint.pformat(args)}\n\t-> Return code: {returncode}\n\t-> Error: {err}")
"""

def _getfileinfo(
        path: Path,
        readonly: bool = True,
        verbose: bool = False) -> dict:
            
    # Get info
    info_str = vector_info(
            path=path, 
            readonly=readonly,
            verbose=verbose)

    # Prepare result
    result_dict = {}
    result_dict['info_str'] = info_str
    result_dict['layers'] = []
    info_strio = StringIO(str(info_str))
    for line in info_strio.readlines():
        line = line.strip()
        if re.match(r"\A\d: ", line):
            # It is a layer, now extract only the layer name
            logger.debug(f"This is a layer: {line}")
            layername_with_geomtype = re.sub(r"\A\d: ", "", line)
            layername = re.sub(r" [(][a-zA-Z ]+[)]\Z", "", layername_with_geomtype)
            result_dict['layers'].append(layername)

    return result_dict

'''
def vector_info_py(
        path: Path, 
        task_description = None,
        layer: str = None,
        readonly: bool = False,
        report_summary: bool = False,
        sql_stmt: str = None,
        sql_dialect: str = None, 
        skip_health_check: bool = False,      
        verbose: bool = False):
    """"Run a command"""

    ##### Init #####
    if not path.exists():
        raise Exception(f"File does not exist: {path}")

    if(skip_health_check is False
       and sql_stmt is not None 
       and sql_dialect is not None
       and sql_dialect.upper() == 'SQLITE' 
       and path.suffix.lower() == '.gpkg'):
        _, sql_dialect = get_gdal_to_use(sql_stmt)

        # Warn that updates with 'INDIRECT_SQLITE' give terrible performance!
        if sql_dialect == 'INDIRECT_SQLITE':
            logger.warn(f"sql_stmt needs 'INDIRECT_SQLITE', but this is gonna be slow!\n\t{sql_stmt}")  

    # Add all parameters to args list
    args = []
    #args.extend(['--config', 'OGR_SQLITE_PRAGMA', 'journal_mode=WAL'])  
    if readonly is True:
        args.append('-ro')
    if report_summary is True:
        args.append('-so')
    if sql_stmt is not None:
        args.extend(['-sql', sql_stmt])
    if sql_dialect is not None:
        args.extend(['-dialect', sql_dialect])

    # File and optionally the layer
    args.append(str(path))
    if layer is not None:
        # ogrinfo doesn't like + need quoted layer names, so remove single and double quotes
        layer_stripped = layer.strip("'\"")
        args.append(layer_stripped)

    info_options = gdal.InfoOptions(
            options=args, 
            format='text', 
            deserialize=True, 
            computeMinMax=False, 
            reportHistograms=False, 
            reportProj4=False, 
            stats=False, 
            approxStats=False, 
            computeChecksum=False, 
            showGCPs=True, 
            showMetadata=True, 
            showRAT=True, 
            showColorTable=True, 
            listMDD=False, 
            showFileList=True, 
            allMetadata=False, 
            extraMDDomains=None, 
            wktFormat=None)

    result = gdal.Info(
            ds=str(path),
            options=info_options)
'''

def vector_info(
        path: Path, 
        task_description = None,
        layer: Optional[str] = None,
        readonly: bool = False,
        report_summary: bool = False,
        sql_stmt: Optional[str] = None,
        sql_dialect: Optional[str] = None, 
        skip_health_check: bool = False,
        verbose: bool = False):
    """"Run a command"""

    ##### Init #####
    if not path.exists():
        raise Exception(f"File does not exist: {path}")
    if os.name == 'nt':
        ogrinfo_exe = 'ogrinfo.exe'
    else:
        ogrinfo_exe = 'ogrinfo'
    
    # Add all parameters to args list
    args = [str(ogrinfo_exe)]
    #args.extend(['--config', 'OGR_SQLITE_PRAGMA', 'journal_mode=WAL'])  
    if readonly is True:
        args.append('-ro')
    if report_summary is True:
        args.append('-so')
    if sql_stmt is not None:
        args.extend(['-sql', sql_stmt])
    if sql_dialect is not None:
        args.extend(['-dialect', sql_dialect])

    # File and optionally the layer
    args.append(str(path))
    if layer is not None:
        # ogrinfo doesn't like + need quoted layer names, so remove single and double quotes
        layer_stripped = layer.strip("'\"")
        args.append(layer_stripped)

    # TODO: ideally, the child processes would die when the parent is killed!

    ##### Run ogrinfo #####
    # Geopackage/sqlite files are very sensitive for being locked, so retry till 
    # file is not locked anymore...
    sleep_time = 1
    returncode = None 
    for retry_count in range(10):
        process = subprocess.Popen(args, 
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=-1, encoding='utf-8')
             
        output, err = process.communicate()
        returncode = process.returncode

        # If an error occured
        if returncode > 0:
            if str(err).startswith("ERROR 1: database is locked"):
                logger.warn(f"'ERROR 1: database is locked' occured during {task_description}, retry nb: {retry_count}")
                time.sleep(sleep_time)
                sleep_time += 1
                continue
            else:
                raise Exception(f"Error executing {pprint.pformat(args)}\n\t-> Return code: {returncode}\n\t-> Error: {err}\n\t->Output: {output}")  
        elif err is not None and err != "":
            # ogrinfo apparently sometimes give a wrong returncode, so if data 
            # in stderr, treat as error as well
            raise Exception(f"Error executing {pprint.pformat(args)}\n\t->Return code: {returncode}\n\t->Error: {err}\n\t->Output: {output}")
        elif verbose is True:
            logger.info(f"Ready executing {pprint.pformat(args)}")

        return output

    # If we get here, the retries didn't suffice to get it executed properly
    raise Exception(f"Error executing {pprint.pformat(args)}\n\t-> Return code: {returncode}")

def _execute_sql(
        path: Path,
        sqlite_stmt: str,
        sql_dialect: Optional[str] = None) -> gpd.GeoDataFrame:
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / 'ogr_util_execute_sql_tmp_file.gpkg'
        vector_translate(
                input_path=path,
                output_path=tmp_path,
                sql_stmt=sqlite_stmt,
                sql_dialect=sql_dialect)
        
        # Return result
        install_info_gdf = gfo.read_file(tmp_path)
        return install_info_gdf
