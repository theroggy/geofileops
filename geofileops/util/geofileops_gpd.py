# -*- coding: utf-8 -*-
"""
Module containing the implementation of Geofile operations using GeoPandas.
"""

from concurrent import futures
import datetime
import enum
import logging
import logging.config
import math
import multiprocessing
from pathlib import Path
import pickle
import time
import shutil
from typing import Any, Callable, List, Optional, Tuple, NamedTuple
import warnings

# Don't show this geopandas warning...
warnings.filterwarnings('ignore', 'GeoSeries.isna', UserWarning)

import cloudpickle
import geopandas as gpd
import psutil
import shapely.geometry as sh_geom

import geofileops as gfo
from geofileops.util import general_util
from geofileops.util import geofileops_sql
from geofileops.util import geometry_util
from geofileops.util.geometry_util import GeometryType, PrimitiveType, SimplifyAlgorithm 
from geofileops.util import geoseries_util
from geofileops.util import grid_util
from geofileops.util import io_util
from geofileops.util import ogr_util

################################################################################
# Some init
################################################################################

logger = logging.getLogger(__name__)

################################################################################
# Some helper functions
################################################################################

class ParallelizationConfig():
    def __init__(self, 
            bytes_basefootprint: int = 50*1024*1024, 
            bytes_per_row: int = 100, 
            min_avg_rows_per_batch: int = 1000, 
            max_avg_rows_per_batch: int = 10000, 
            bytes_min_per_process = None, 
            bytes_usable = None):
        self.bytes_basefootprint = bytes_basefootprint
        self.bytes_per_row = bytes_per_row
        self.min_avg_rows_per_batch = min_avg_rows_per_batch
        self.max_avg_rows_per_batch = max_avg_rows_per_batch
        if bytes_min_per_process is None:
            self.bytes_min_per_process = bytes_basefootprint + bytes_per_row * min_avg_rows_per_batch
        else:
            self.bytes_min_per_process = bytes_min_per_process
        if bytes_usable is None: 
            self.bytes_usable = psutil.virtual_memory().available * 0.9
        else:
            self.bytes_usable = bytes_usable

parallelizationParams = NamedTuple('result', [('nb_parallel', int), ('nb_batches_recommended', int), ('nb_rows_per_batch', int)])
def get_parallelization_params(
        nb_rows_total: int,
        nb_parallel: int = -1,
        prev_nb_batches: Optional[int] = None,
        parallelization_config: Optional[ParallelizationConfig] = None) -> parallelizationParams:
    """
    Determines recommended parallelization params.

    Args:
        nb_rows_total (int): The total number of rows that will be processed
        nb_parallel (int, optional): The level of parallelization requested. 
            If -1, tries to use all resources available. Defaults to -1.
        prev_nb_batches (int, optional): If applicable, the number of batches 
            used in a previous pass of the calculation. Defaults to None.
        verbose (bool, optional): [description]. Defaults to False.

    Returns:
        parallelizationParams (NamedTuple('result', [('nb_parallel', int), ('nb_batches_recommended', int), ('nb_rows_per_batch', int)])): The recommended parameters.
    """
    # Init parallelization config

    # If config is None, set to empty dict
    if parallelization_config is not None:
        parallelization_config_local = parallelization_config
    else:
        parallelization_config_local = ParallelizationConfig()
    
    # If the number of rows is really low, just use one batch
    # TODO: for very complex features, possibly this limit is not a good idea
    if nb_rows_total < parallelization_config_local.min_avg_rows_per_batch:
        return parallelizationParams(1, 1, nb_rows_total)

    if(nb_parallel == -1):
        nb_parallel = multiprocessing.cpu_count()

    logger.debug(f"memory_usable: {general_util.formatbytes(parallelization_config_local.bytes_usable)}, with:")
    logger.debug(f"  -> mem.available: {general_util.formatbytes(psutil.virtual_memory().available)}")
    logger.debug(f"  -> swap.free: {general_util.formatbytes(psutil.swap_memory().free)}") 

    # If not enough memory for the amount of parallellism asked, reduce
    if (nb_parallel * parallelization_config_local.bytes_min_per_process) > parallelization_config_local.bytes_usable:
        nb_parallel = int(parallelization_config_local.bytes_usable/parallelization_config_local.bytes_min_per_process)
        logger.debug(f"Nb_parallel reduced to {nb_parallel} to evade excessive memory usage")

    # Optimal number of batches and rows per batch based on memory usage
    nb_batches = math.ceil(
            (nb_rows_total*parallelization_config_local.bytes_per_row*nb_parallel)/
            (parallelization_config_local.bytes_usable-parallelization_config_local.bytes_basefootprint*nb_parallel))
    
    # Make sure the average batch doesn't contain > max_avg_rows_per_batch
    batch_size = math.ceil(nb_rows_total/nb_batches)
    if batch_size > parallelization_config_local.max_avg_rows_per_batch:
        batch_size = parallelization_config_local.max_avg_rows_per_batch
        nb_batches = math.ceil(nb_rows_total/batch_size)
    mem_predicted = (parallelization_config_local.bytes_basefootprint + batch_size*parallelization_config_local.bytes_per_row)*nb_batches

    # Make sure there are enough batches to use as much parallelism as possible
    if nb_batches > 1 and nb_batches < nb_parallel:
        if prev_nb_batches is None:
            nb_batches = round(nb_parallel*1.25)
        elif nb_batches < prev_nb_batches/4:
            nb_batches = round(nb_parallel*1.25)
    
    batch_size = math.ceil(nb_rows_total/nb_batches)

    # Log result
    logger.debug(f"nb_batches_recommended: {nb_batches}, rows_per_batch: {batch_size}")
    logger.debug(f" -> nb_rows_input_layer: {nb_rows_total}") 
    logger.debug(f" -> will result in mem_predicted: {general_util.formatbytes(mem_predicted)}")

    return parallelizationParams(nb_parallel, nb_batches, batch_size)

class GeoOperation(enum.Enum):
    SIMPLIFY = "simplify"
    BUFFER = "buffer"
    CONVEXHULL = "convexhull"
    APPLY = "apply"

################################################################################
# The real stuff
################################################################################

def apply(
        input_path: Path,
        output_path: Path,
        func: Callable[[Any], Any],
        only_geom_input: bool = True,
        input_layer: Optional[str] = None,
        output_layer: Optional[str] = None,
        columns: Optional[List[str]] = None,
        explodecollections: bool = False,
        nb_parallel: int = -1,
        batchsize: int = -1,
        verbose: bool = False,
        force: bool = False):
    # Init
    operation_params = {
            "only_geom_input": only_geom_input,
            "pickled_func": cloudpickle.dumps(func)
        }

    # Go!
    return _apply_geooperation_to_layer(
            input_path=input_path,
            output_path=output_path,
            operation=GeoOperation.APPLY,
            operation_params=operation_params,
            input_layer=input_layer,
            output_layer=output_layer,
            columns=columns,
            explodecollections=explodecollections,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            verbose=verbose,
            force=force)

def buffer(
        input_path: Path,
        output_path: Path,
        distance: float,
        quadrantsegments: int = 5,
        endcap_style: geometry_util.BufferEndCapStyle = geometry_util.BufferEndCapStyle.ROUND,
        join_style: geometry_util.BufferJoinStyle = geometry_util.BufferJoinStyle.ROUND,
        mitre_limit: float = 5.0,
        single_sided: bool = False,
        input_layer: Optional[str] = None,
        output_layer: Optional[str] = None,
        columns: Optional[List[str]] = None,
        explodecollections: bool = False,
        nb_parallel: int = -1,
        batchsize: int = -1,
        verbose: bool = False,
        force: bool = False):
    # Init
    operation_params = {
            "distance": distance,
            "quadrantsegments": quadrantsegments,
            "endcap_style": endcap_style,
            "join_style": join_style,
            "mitre_limit": mitre_limit,
            "single_sided": single_sided
        }

    # Go!
    return _apply_geooperation_to_layer(
            input_path=input_path,
            output_path=output_path,
            operation=GeoOperation.BUFFER,
            operation_params=operation_params,
            input_layer=input_layer,
            output_layer=output_layer,
            columns=columns,
            explodecollections=explodecollections,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            verbose=verbose,
            force=force)

def convexhull(
        input_path: Path,
        output_path: Path,
        input_layer: Optional[str] = None,
        output_layer: Optional[str] = None,
        columns: Optional[List[str]] = None,
        explodecollections: bool = False,
        nb_parallel: int = -1,
        batchsize: int = -1,
        verbose: bool = False,
        force: bool = False):
    # Init
    operation_params = {}
    
    # Go!
    return _apply_geooperation_to_layer(
            input_path=input_path,
            output_path=output_path,
            operation=GeoOperation.CONVEXHULL,
            operation_params=operation_params,
            input_layer=input_layer,
            output_layer=output_layer,
            columns=columns,
            explodecollections=explodecollections,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            verbose=verbose,
            force=force)

def simplify(
        input_path: Path,
        output_path: Path,
        tolerance: float,
        algorithm: SimplifyAlgorithm = SimplifyAlgorithm.RAMER_DOUGLAS_PEUCKER,
        lookahead: int = 8,
        input_layer: Optional[str] = None,
        output_layer: Optional[str] = None,
        columns: Optional[List[str]] = None,
        explodecollections: bool = False,
        nb_parallel: int = -1,
        batchsize: int = -1,
        verbose: bool = False,
        force: bool = False):
    # Init
    operation_params = {
            'tolerance': tolerance,
            'algorithm': algorithm,
            'step': lookahead
        }
    
    # Go!
    return _apply_geooperation_to_layer(
            input_path=input_path,
            output_path=output_path,
            operation=GeoOperation.SIMPLIFY,
            operation_params=operation_params,
            input_layer=input_layer,
            output_layer=output_layer,
            columns=columns,
            explodecollections=explodecollections,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            verbose=verbose,
            force=force)

def _apply_geooperation_to_layer(
        input_path: Path,
        output_path: Path,
        operation: GeoOperation,
        operation_params: dict,
        input_layer: Optional[str] = None,
        columns: Optional[List[str]] = None,
        output_layer: Optional[str] = None,
        explodecollections: bool = False,
        nb_parallel: int = -1,
        batchsize: int = -1,
        verbose: bool = False,
        force: bool = False):
    """
    Applies a geo operation on a layer.

    The operation to apply can be one of the the following:
      - BUFFER: apply a buffer. Operation parameters:
          - distance: distance to buffer
          - quadrantsegments: number of points used to represent 1/4 of a circle
          - endcap_style: buffer style to use for a point or the end points of 
            a line:
            - ROUND: for points and lines the ends are buffered rounded. 
            - FLAT: a point stays a point, a buffered line will end flat 
              at the end points
            - SQUARE: a point becomes a square, a buffered line will end 
              flat at the end points, but elongated by "distance" 
        - join_style: buffer style to use for corners in a line or a polygon 
          boundary:
            - ROUND: corners in the result are rounded
            - MITRE: corners in the result are sharp
            - BEVEL: are flattened
        - mitre_limit: in case of join_style MITRE, if the 
            spiky result for a sharp angle becomes longer than this limit, it 
            is "beveled" at this distance. Defaults to 5.0.
        - single_sided: only one side of the line is buffered, 
            if distance is negative, the left side, if distance is positive, 
            the right hand side. Only relevant for line geometries. 
      - CONVEXHULL: appy a convex hull.
      - SIMPLIFY: simplify the geometry. Operation parameters:
          - algorithm: vector_util.SimplifyAlgorithm
          - tolerance: maximum distance to simplify.
          - lookahead: for LANG, the number of points to forward-look
      - APPLY: apply a lambda function. Operation parameter:
          - pickled_func: lambda function to apply, pickled to bytes.
          - only_geom_input: if True, only the geometry is available as 
            input for the lambda function. If false, the row is the input.  

    Args:
        input_path (Path): [description]
        output_path (Path): [description]
        operation (GeoOperation): the geo operation to apply.
        operation_params (dict, optional): the parameters for the geo operation. 
            Defaults to None. 
        input_layer (str, optional): [description]. Defaults to None.
        output_layer (str, optional): [description]. Defaults to None.
        columns (List[str], optional): If not None, only output the columns 
            specified. Defaults to None.
        explodecollections (bool, optional): True to convert all multi-geometries to 
            singular ones during the geooperation. Defaults to False.
        nb_parallel (int, optional): [description]. Defaults to -1.
        batchsize (int, optional): indicative number of rows to process per 
            batch. A smaller batch size, possibly in combination with a 
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        verbose (bool, optional): [description]. Defaults to False.
        force (bool, optional): [description]. Defaults to False.
    """
    ##### Init #####
    start_time = datetime.datetime.now()
    if input_layer is None:
        input_layer = gfo.get_only_layer(input_path)
    if output_path.exists():
        if force is False:
            logger.info(f"Stop {operation}: output exists already {output_path}")
            return
        else:
            gfo.remove(output_path)
    if input_layer is None:
        input_layer = gfo.get_only_layer(input_path)
    if output_layer is None:
        output_layer = gfo.get_default_layer(output_path)

    ##### Prepare tmp files #####
    tempdir = io_util.create_tempdir(f"geofileops/{operation.value}")
    logger.info(f"Start calculation to temp files in {tempdir}")

    try:
        ##### Calculate #####
        # Remark: calculating can be done in parallel, but only one process 
        # can write to the same output file at the time...

        # Calculate the best number of parallel processes and batches for 
        # the available resources
        layerinfo = gfo.get_layerinfo(input_path, input_layer)
        nb_rows_total = layerinfo.featurecount
        if batchsize > 0:
            parallellization_config = ParallelizationConfig(max_avg_rows_per_batch=batchsize)
        else:
            parallellization_config = ParallelizationConfig(max_avg_rows_per_batch=50000)
        nb_parallel, nb_batches, real_batchsize = get_parallelization_params(
                nb_rows_total=nb_rows_total,
                nb_parallel=nb_parallel,
                parallelization_config=parallellization_config)
        
        # TODO: determine the optimal batch sizes with min and max of rowid will 
        # in some case improve performance
        '''
        sql_stmt = f'SELECT MIN(rowid) as min_rowid, MAX(rowid) as max_rowid FROM "{input_layer}"'
        result = geogfo.read_file_sql(path=temp_path, sql_stmt=sql_stmt, layer=input_layer)
        if len(result) == 1:
            min_rowid = result['min_rowid'].values[0]
            max_rowid = result['max_rowid'].values[0]
            nb_rowids_per_batch = (max_rowid - min_rowid)/nb_batches
        else:
            raise Exception(f"Error determining min_rowid and max_rowid for {temp_path}, layer {input_layer}")
        '''

        with futures.ProcessPoolExecutor(
                max_workers=nb_parallel, 
                initializer=general_util.initialize_worker()) as calculate_pool:

            # Prepare output filename
            output_tmp_path = tempdir / output_path.name

            row_offset = 0
            batches = {}    
            future_to_batch_id = {}
            nb_done = 0
            
            logger.debug(f"Start calculation on {nb_rows_total} rows in {nb_batches} batches, so {real_batchsize} per batch")

            for batch_id in range(nb_batches):

                batches[batch_id] = {}
                batches[batch_id]['layer'] = output_layer

                # Output each batch to a seperate temporary file, otherwise there 
                # are timeout issues when processing large files
                output_tmp_partial_path = tempdir / f"{output_path.stem}_{batch_id}{output_path.suffix}"
                batches[batch_id]['tmp_partial_output_path'] = output_tmp_partial_path

                # For the last translate_id, take all rowid's left...
                if batch_id < nb_batches-1:
                    rows = slice(row_offset, row_offset + real_batchsize)
                else:
                    rows = slice(row_offset, nb_rows_total)

                # Remark: this temp file doesn't need spatial index
                future = calculate_pool.submit(
                        _apply_geooperation,
                        input_path=input_path,
                        output_path=output_tmp_partial_path,
                        operation=operation,
                        operation_params=operation_params,
                        input_layer=input_layer,
                        columns=columns,     
                        output_layer=output_layer,
                        rows=rows,
                        explodecollections=explodecollections,
                        verbose=verbose,
                        force=force)
                future_to_batch_id[future] = batch_id
                row_offset += real_batchsize
            
            # Loop till all parallel processes are ready, but process each one 
            # that is ready already
            general_util.report_progress(start_time, nb_done, nb_batches, operation.value, nb_parallel)
            for future in futures.as_completed(future_to_batch_id):
                try:
                    result = future.result()

                    # If the calculate gave results, copy to output
                    batch_id = future_to_batch_id[future]
                    tmp_partial_output_path = batches[batch_id]['tmp_partial_output_path']
                    if tmp_partial_output_path.exists() and tmp_partial_output_path.stat().st_size > 0:
                        gfo.append_to(
                                src=tmp_partial_output_path, 
                                dst=output_tmp_path, 
                                create_spatial_index=False)
                        gfo.remove(tmp_partial_output_path)
                    
                except Exception as ex:
                    batch_id = future_to_batch_id[future]
                    #calculate_pool.shutdown()
                    logger.exception(f"Error executing {batches[batch_id]}")

                # Log the progress and prediction speed
                nb_done += 1
                general_util.report_progress(start_time, nb_done, nb_batches, operation.value, nb_parallel)

        ##### Round up and clean up ##### 
        # Now create spatial index and move to output location
        if output_tmp_path.exists():
            gfo.create_spatial_index(path=output_tmp_path, layer=output_layer)
            gfo.move(output_tmp_path, output_path)
        else:
            logger.warning(f"Result of {operation} was empty!f")

    finally:
        # Clean tmp dir
        shutil.rmtree(tempdir)
        logger.info(f"{operation} ready, took {datetime.datetime.now()-start_time}!")

def _apply_geooperation(
        input_path: Path,
        output_path: Path,
        operation: GeoOperation,
        operation_params: dict,
        input_layer: Optional[str] = None,
        output_layer: Optional[str] = None,
        columns: Optional[List[str]] = None,
        rows = None,
        explodecollections: bool = False,
        verbose: bool = False,
        force: bool = False) -> str:
    
    ##### Init #####
    if output_path.exists():
        if force is False:
            message = f"Stop {operation}: output exists already {output_path}"
            return message
        else:
            gfo.remove(output_path)

    ##### Now go! #####
    start_time = datetime.datetime.now()
    data_gdf = gfo.read_file(path=input_path, layer=input_layer, columns=columns, rows=rows)
    if len(data_gdf) == 0:
        message = f"No input geometries found for rows: {rows} in layer: {input_layer} in input_path: {input_path}"
        return message

    if operation is GeoOperation.BUFFER:
        data_gdf.geometry = data_gdf.geometry.buffer(
                distance=operation_params['distance'], 
                resolution=operation_params['quadrantsegments'],
                cap_style=operation_params['endcap_style'].value,
                join_style=operation_params['join_style'].value,
                mitre_limit=operation_params['mitre_limit'],
                single_sided=operation_params['single_sided'])
        #data_gdf['geometry'] = [sh_geom.Polygon(sh_geom.mapping(x)['coordinates']) for x in data_gdf.geometry]
    elif operation is GeoOperation.CONVEXHULL:
        data_gdf.geometry = data_gdf.geometry.convex_hull
    elif operation is GeoOperation.SIMPLIFY:
        data_gdf.geometry = geoseries_util.simplify_ext(
                data_gdf.geometry,
                algorithm=operation_params['algorithm'], 
                tolerance=operation_params['tolerance'], 
                lookahead=operation_params['step'])
    elif operation is GeoOperation.APPLY:
        func = pickle.loads(operation_params["pickled_func"])
        if operation_params["only_geom_input"] is True:
            data_gdf.geometry = data_gdf.geometry.apply(func)
        else:
            data_gdf.geometry = data_gdf.apply(func, axis=1)
    else:
        raise Exception(f"Operation not supported: {operation}")     

    # Remove rows where geom is empty
    data_gdf = data_gdf[~data_gdf.geometry.is_empty] 
    data_gdf = data_gdf[~data_gdf.geometry.isna()] 
    
    if explodecollections:
        data_gdf = data_gdf.explode(ignore_index=True) # type: ignore

    if len(data_gdf) > 0:
        # assert to evade pyLance warning
        assert isinstance(data_gdf, gpd.GeoDataFrame)
        # Use force_multitype, to evade warnings when some batches contain 
        # singletype and some contain multitype geometries  
        gfo.to_file(
                gdf=data_gdf, path=output_path, layer=output_layer, index=False,
                force_multitype=True)

    message = f"Took {datetime.datetime.now()-start_time} for {len(data_gdf)} rows ({rows})!"
    return message

def dissolve(
        input_path: Path,  
        output_path: Path,
        groupby_columns: Optional[List[str]] = None,
        columns: Optional[List[str]] = [],
        aggfunc: str = 'first',
        explodecollections: bool = True,
        tiles_path: Optional[Path] = None,
        nb_squarish_tiles: int = 1,
        input_layer: Optional[str] = None,
        output_layer: Optional[str] = None,
        nb_parallel: int = -1,
        batchsize: int = -1,
        verbose: bool = False,
        force: bool = False) -> dict:
    """
    Function that applies a dissolve on the input gfo.

    More detailed documentation in module geofileops!
    """

    ##### Init #####
    start_time = datetime.datetime.now()
    operation = 'dissolve'
    result_info = {}
    
    # Check input parameters
    if aggfunc != 'first':
        raise NotImplementedError(f"aggfunc != 'first' is not implemented: {aggfunc}")
    if groupby_columns is not None and len(groupby_columns) == 0:
        raise Exception(f"groupby_columns == [] is not supported. It should be None in this case")
    if not input_path.exists():
        raise Exception(f"input_path does not exist: {input_path}")
    layerinfo = gfo.get_layerinfo(input_path, input_layer)
    if layerinfo.geometrytype.to_primitivetype in [PrimitiveType.POINT, PrimitiveType.LINESTRING]:
        if tiles_path is not None or nb_squarish_tiles > 1:
            raise Exception(f"Dissolve to tiles (tiles_path, nb_squarish_tiles) is not supported for {layerinfo.geometrytype}")
    if output_path.exists():
        if force is False:
            result_info['message'] = f"Stop {operation}: output exists already {output_path} and force is false"
            logger.info(result_info['message'])
            return result_info
        else:
            gfo.remove(output_path)
    
    # Prepare columns to retain
    if columns is None:
        # If no columns specified, keep all columns
        columns_to_retain = layerinfo.columns
    else:
        # If columns specified, add groupby_columns if they are not specified
        columns_to_retain = columns.copy()
        if groupby_columns is not None:
            for column in groupby_columns:
                if column not in columns_to_retain:
                    columns_to_retain.append(column)

    # If a tiles_path is specified, read those tiles... 
    result_tiles_gdf = None
    if tiles_path is not None:
        result_tiles_gdf = gfo.read_file(tiles_path)
        if nb_parallel == -1:
            nb_cpu = multiprocessing.cpu_count()
            nb_parallel = nb_cpu #int(1.25 * nb_cpu)
            logger.debug(f"Nb cpus found: {nb_cpu}, nb_parallel: {nb_parallel}")
    else:
        # Else, create a grid based on the number of tiles wanted as result
        layerinfo = gfo.get_layerinfo(input_path, input_layer)
        result_tiles_gdf = grid_util.create_grid2(layerinfo.total_bounds, nb_squarish_tiles, layerinfo.crs)
        if len(result_tiles_gdf) > 1:
            gfo.to_file(result_tiles_gdf, output_path.parent / f"{output_path.stem}_tiles.gpkg")

    ##### Now start dissolving... #####
    # Line and point layers are:
    #   * not so large (memory-wise)
    #   * aren't computationally heavy
    # Additionally line layers are a pain to handle correctly because of 
    # rounding issues at the borders of tiles... so just dissolve them using 
    # geopandas.   
    if layerinfo.geometrytype.to_primitivetype in [PrimitiveType.POINT, PrimitiveType.LINESTRING]:
        input_gdf = gfo.read_file(input_path, input_layer)

        # Geopandas < 0.9 didn't support dissolving without groupby
        if groupby_columns is None or len(groupby_columns) == 0:
            union_geom = input_gdf.geometry.unary_union

            # Only keep geometries of primitive type of input 
            union_geom_cleaned = geometry_util.collection_extract(
                    union_geom, layerinfo.geometrytype.to_primitivetype)
            diss_gdf = gpd.GeoDataFrame(geometry=[union_geom_cleaned], crs=input_gdf.crs)
        else:
            diss_gdf = input_gdf.dissolve(by=groupby_columns, aggfunc=aggfunc, as_index=False)

        # Explodecollections if needed
        if explodecollections is True:
            # assert to evade pyLance warning
            assert isinstance(diss_gdf, gpd.GeoDataFrame)
            diss_gdf = diss_gdf.explode(ignore_index=True)
        
        # Now write to file
        # assert to evade pyLance warning
        assert isinstance(diss_gdf, gpd.GeoDataFrame)
        gfo.to_file(diss_gdf, output_path, output_layer)

    elif layerinfo.geometrytype.to_primitivetype is PrimitiveType.POLYGON:

        # The dissolve for polygons is done in several passes, and after the first 
        # pass, only the 'onborder' features are further dissolved, as the 
        # 'notonborder' features are already OK.  
        tempdir = io_util.create_tempdir(f"geofileops/{operation}")
        try:
            pass_input_path = input_path
            if output_layer is None:
                output_layer = gfo.get_default_layer(output_path)
            output_tmp_path = tempdir / f"{output_path.stem}.gpkg"
            prev_nb_batches = None
            last_pass = False
            pass_id = 0
            logger.info(f"Start dissolve on file {input_path}")
            while True:
                
                # Get some info of the file that needs to be dissolved
                layerinfo = gfo.get_layerinfo(pass_input_path, input_layer)
                nb_rows_total = layerinfo.featurecount
                
                # Calculate the best number of parallel processes and batches for 
                # the available resources
                if batchsize > 0:
                    parallelization_config = ParallelizationConfig(max_avg_rows_per_batch=batchsize)
                else:
                    parallelization_config = ParallelizationConfig()
                nb_parallel, nb_batches_recommended, _ = get_parallelization_params(
                        nb_rows_total=nb_rows_total,
                        nb_parallel=nb_parallel,
                        prev_nb_batches=prev_nb_batches,
                        parallelization_config=parallelization_config)

                # If the ideal number of batches is close to the nb. result tiles asked,  
                # dissolve towards the asked result!
                # If not, a temporary result is created using smaller tiles 
                if nb_batches_recommended <= len(result_tiles_gdf)*1.1:
                    tiles_gdf = result_tiles_gdf
                    last_pass = True
                elif len(result_tiles_gdf) == 1:
                    # Create a grid based on the ideal number of batches, but make 
                    # sure the number is smaller than the maximum... 
                    nb_squarish_tiles_max = None
                    if prev_nb_batches is not None:
                        nb_squarish_tiles_max = max(prev_nb_batches-1, 1)
                    tiles_gdf = grid_util.create_grid2(
                            total_bounds=layerinfo.total_bounds, 
                            nb_squarish_tiles=nb_batches_recommended, 
                            nb_squarish_tiles_max=nb_squarish_tiles_max, 
                            crs=layerinfo.crs)
                else:
                    # If a grid is specified already, add extra columns/rows instead of 
                    # creating new one...
                    tiles_gdf = grid_util.split_tiles(
                            result_tiles_gdf, nb_batches_recommended)
                gfo.to_file(tiles_gdf, tempdir / f"{output_path.stem}_{pass_id}_tiles.gpkg")

                # If the number of tiles ends up as 1, it is the last pass anyway...
                if len(tiles_gdf) == 1:
                    last_pass = True

                # If we are not in the last pass, onborder parcels will need extra 
                # processing still in further passes, so are saved in a seperate 
                # gfo. The notonborder rows are final immediately 
                if last_pass is not True:
                    output_tmp_onborder_path = tempdir / f"{output_path.stem}_{pass_id}_onborder.gpkg"
                else:
                    output_tmp_onborder_path = output_tmp_path
                
                # Now go!
                logger.info(f"Start dissolve pass {pass_id} to {len(tiles_gdf)} tiles (nb_parallel: {nb_parallel})")       
                result = _dissolve_polygons_pass(
                        input_path=pass_input_path,
                        output_notonborder_path=output_tmp_path,
                        output_onborder_path=output_tmp_onborder_path,
                        explodecollections=explodecollections,
                        groupby_columns=groupby_columns,
                        columns=columns_to_retain,
                        aggfunc=aggfunc,
                        tiles_gdf=tiles_gdf,
                        input_layer=input_layer,        
                        output_layer=output_layer,
                        nb_parallel=nb_parallel,
                        verbose=verbose,
                        force=force)

                # Prepare the next pass...
                # The input path are the onborder rows...
                prev_nb_batches = len(tiles_gdf)
                pass_input_path = output_tmp_onborder_path
                pass_id += 1

                # If we are ready...
                if last_pass is True:
                    break

            ##### Calculation ready! Now finalise output! #####
            # If there is a result on border, append it to the rest
            if(str(output_tmp_onborder_path) != str(output_tmp_path) 
                    and output_tmp_onborder_path.exists()):
                gfo.append_to(output_tmp_onborder_path, output_tmp_path, dst_layer=output_layer)

            # If there is a result...
            if output_tmp_path.exists():
                # Prepare columns to keep 
                columns_str = ''
                for column in columns_to_retain:
                    columns_str += f', "{column}"'
                
                # Now move tmp file to output location, but order the rows randomly
                # to evade having all complex geometries together...
                orderby_column = 'temp_ordercolumn_geohash'
                _add_orderby_column(
                        path=output_tmp_path, layer=output_layer, name=orderby_column)
                
                # Prepare SQL statement for final output file 
                # If there is a groupby and explodedecollections is False...
                if explodecollections is False and groupby_columns is not None:
                    # All tiles are already dissolved to groups, but now the 
                    # results from all tiles still need to be 
                    # grouped/collected together
                    # Remark: if explodecollections is true, it is useless to 
                    # first group them here, as they will be exploded again 
                    # in the select() call later on.
                    logger.info("Collect prepared features to multi* and write to output file")
                    groupby_columns_with_prefix = [f'"{column}"' for column in groupby_columns]
                    groupby_columns_str = ", ".join(groupby_columns_with_prefix)
                    sql_stmt = f'''
                            SELECT ST_Collect({{geometrycolumn}}) AS {{geometrycolumn}}
                                  {columns_str} 
                            FROM "{output_layer}" 
                            GROUP BY {groupby_columns_str}
                            ORDER BY MAX({orderby_column})'''
                else:
                    # No group by columns, so only need to reorder output file 
                    # and possibly collect all featurs together. 
                    if explodecollections is True:
                        geom_select = '{geometrycolumn}'
                    else:
                        geom_select = 'ST_Collect({geometrycolumn}) AS {geometrycolumn}'
                    logger.info("Write final result to output file")
                    sql_stmt = f'''
                            SELECT {geom_select} 
                                  {columns_str} 
                            FROM "{output_layer}" 
                            ORDER BY {orderby_column}'''
                # Go!
                geofileops_sql.select(
                        output_tmp_path, output_path, sql_stmt, output_layer=output_layer,
                        explodecollections=explodecollections)

        finally:
            # Clean tmp dir if it exists...
            if tempdir.exists():
                shutil.rmtree(tempdir)
    else:
        raise NotImplementedError(f"Unsupported input geometrytype: {layerinfo.geometrytype}")

    # Return result info
    result_info['message'] = f"Dissolve completely ready, took {datetime.datetime.now()-start_time}!"
    logger.info(result_info['message'])
    return result_info

def _dissolve_polygons_pass(
        input_path: Path,  
        output_notonborder_path: Path,
        output_onborder_path: Path,
        explodecollections: bool,
        groupby_columns: Optional[List[str]],
        columns: List[str],
        aggfunc: str,
        tiles_gdf: gpd.GeoDataFrame,
        input_layer: Optional[str],        
        output_layer: Optional[str],
        nb_parallel: int,
        verbose: bool,
        force: bool) -> dict:

    # Start calculation in parallel
    start_time = datetime.datetime.now()
    result_info = {}
    start_time = datetime.datetime.now()
    input_layerinfo = gfo.get_layerinfo(input_path, input_layer)
    nb_rows_total = input_layerinfo.featurecount
    with futures.ProcessPoolExecutor(
            max_workers=nb_parallel, 
            initializer=general_util.initialize_worker()) as calculate_pool:

        # Prepare output filename
        tempdir = output_onborder_path.parent

        batches = {}    
        future_to_batch_id = {}    
        nb_rows_done = 0
        for batch_id, tile in enumerate(tiles_gdf.itertuples()):
    
            batches[batch_id] = {}
            batches[batch_id]['layer'] = output_layer

            # Output each batch to a seperate temporary file, otherwise there 
            # are timeout issues when processing large files
            output_notonborder_tmp_partial_path = tempdir / f"{output_notonborder_path.stem}_{batch_id}{output_notonborder_path.suffix}"
            batches[batch_id]['output_notonborder_tmp_partial_path'] = output_notonborder_tmp_partial_path
            output_onborder_tmp_partial_path = tempdir / f"{output_onborder_path.stem}_{batch_id}{output_onborder_path.suffix}"
            batches[batch_id]['output_onborder_tmp_partial_path'] = output_onborder_tmp_partial_path
            
            future = calculate_pool.submit(
                    _dissolve_polygons,
                    input_path=input_path,
                    output_notonborder_path=output_notonborder_tmp_partial_path,
                    output_onborder_path=output_onborder_tmp_partial_path,
                    explodecollections=explodecollections,
                    groupby_columns=groupby_columns,
                    columns=columns,
                    aggfunc=aggfunc,
                    input_geometrytype=input_layerinfo.geometrytype,
                    input_layer=input_layer,        
                    output_layer=output_layer,
                    bbox=tile.geometry.bounds,
                    verbose=verbose)
            future_to_batch_id[future] = batch_id
        
        # Loop till all parallel processes are ready, but process each one 
        # that is ready already
        general_util.report_progress(start_time, nb_rows_done, nb_rows_total, 'dissolve')
        for future in futures.as_completed(future_to_batch_id):
            try:
                # If the calculate gave results
                batch_id = future_to_batch_id[future]
                result = future.result()

                if result is not None:
                    nb_rows_done += result['nb_rows_done']
                    if result['nb_rows_done'] > 0 and result['total_time'] > 0:
                        rows_per_sec = round(result['nb_rows_done']/result['total_time'])
                        logger.debug(f"Batch {batch_id} ready, processed {result['nb_rows_done']} rows in {rows_per_sec} rows/sec")
                        if 'perfstring' in result:
                            logger.debug(f"Perfstring: {result['perfstring']}")
                    
                    # Start copy of the result to a common file
                    batch_id = future_to_batch_id[future]

                    # If the calculate gave results, copy to output
                    output_notonborder_tmp_partial_path = batches[batch_id]['output_notonborder_tmp_partial_path']
                    if output_notonborder_tmp_partial_path.exists() and output_notonborder_tmp_partial_path.stat().st_size > 0:
                        gfo.append_to(
                                src=output_notonborder_tmp_partial_path, 
                                dst=output_notonborder_path)
                        gfo.remove(output_notonborder_tmp_partial_path)
                            
                    # If the calculate gave results, copy to output
                    output_onborder_tmp_partial_path = batches[batch_id]['output_onborder_tmp_partial_path']
                    if output_onborder_tmp_partial_path.exists() and output_onborder_tmp_partial_path.stat().st_size > 0:
                        gfo.append_to(
                                src=output_onborder_tmp_partial_path, 
                                dst=output_onborder_path)
                        gfo.remove(output_onborder_tmp_partial_path)

            except Exception as ex:
                batch_id = future_to_batch_id[future]
                message = f"Error executing {batches[batch_id]}: {ex}"
                logger.exception(message)
                calculate_pool.shutdown()
                raise Exception(message) from ex

            # Log the progress and prediction speed
            general_util.report_progress(start_time, nb_rows_done, nb_rows_total, 'dissolve')   
    
    logger.info(f"Dissolve pass ready, took {datetime.datetime.now()-start_time}!")
                
    return result_info

def _dissolve_polygons(
        input_path: Path,
        output_notonborder_path: Path,
        output_onborder_path: Path,
        explodecollections: bool,
        groupby_columns: Optional[List[str]],
        columns: List[str],
        aggfunc: str,
        input_geometrytype: GeometryType,
        input_layer: Optional[str],        
        output_layer: Optional[str],
        bbox: Tuple[float, float, float, float],
        verbose: bool) -> dict:

    ##### Init #####
    perfinfo = {}
    start_time = datetime.datetime.now()
    return_info = {"input_path": input_path,
                   "output_notonborder_path": output_notonborder_path,
                   "output_onborder_path": output_onborder_path,
                   "bbox": bbox,
                   "nb_rows_done": 0,
                   "total_time": 0,
                   "perfinfo": ""
                }

    # Read all records that are in the bbox
    retry_count = 0
    start_read = datetime.datetime.now()
    while True:
        try:
            input_gdf = gfo.read_file(
                    path=input_path, layer=input_layer, bbox=bbox, columns=columns)
            break
        except Exception as ex:
            if str(ex) == 'database is locked':
                if retry_count < 10:
                    retry_count += 1
                    time.sleep(1)
                else:
                    raise Exception("retried 10 times, database still locked") from ex
            else:
                raise ex

    # Check result
    perfinfo['time_read'] = (datetime.datetime.now()-start_read).total_seconds()
    return_info['nb_rows_done'] = len(input_gdf)
    if return_info['nb_rows_done'] == 0:
        message = f"No input geometries found in {input_path}"
        logger.info(message)
        return_info['message'] = message
        return_info['total_time'] = (datetime.datetime.now()-start_time).total_seconds()
        return return_info

    # Now the real processing
    start_dissolve = datetime.datetime.now()
    diss_gdf = input_gdf.dissolve(by=groupby_columns, aggfunc=aggfunc, as_index=False, dropna=False)
    perfinfo['time_dissolve'] = (datetime.datetime.now()-start_dissolve).total_seconds()

    # If explodecollections is True and For polygons, explode multi-geometries.
    # If needed they will be 'collected' afterwards to multipolygons again.
    if(explodecollections is True 
        or input_geometrytype in [GeometryType.POLYGON, GeometryType.MULTIPOLYGON]):
        # assert to evade pyLance warning 
        assert isinstance(diss_gdf, gpd.GeoDataFrame)
        diss_gdf = diss_gdf.explode(ignore_index=True)

    # Clip the result on the borders of the bbox not to have overlaps 
    # between the different tiles. 
    # If this is not applied, this results in some geometries not being merged 
    # or in duplicates.
    # REMARK: for (multi)linestrings, the endpoints created by the clip are not 
    # always the same due to rounding, so dissolving in a next pass doesn't 
    # always result in linestrings being re-connected... Because dissolving 
    # lines isn't so computationally heavy anyway, drop support here.    
    if bbox is not None:
        start_clip = datetime.datetime.now()
        bbox_polygon = sh_geom.Polygon([(bbox[0], bbox[1]), (bbox[0], bbox[3]), (bbox[2], bbox[3]), (bbox[2], bbox[1]), (bbox[0], bbox[1])])
        bbox_gdf = gpd.GeoDataFrame([1], geometry=[bbox_polygon], crs=input_gdf.crs)
        
        # keep_geom_type=True gaves sometimes error, and still does in 0.9.0
        # so use own implementation of keep_geom_type 
        diss_gdf = gpd.clip(diss_gdf, bbox_gdf) #, keep_geom_type=True)

        # Only keep geometries of the primitive type specified after clip...
        assert isinstance(diss_gdf, gpd.GeoDataFrame)
        diss_gdf.geometry = geoseries_util.geometry_collection_extract(
                diss_gdf.geometry, input_geometrytype.to_primitivetype)

        perfinfo['time_clip'] = (datetime.datetime.now()-start_clip).total_seconds()

    # Drop rows with None/empty geometries 
    diss_gdf = diss_gdf[~diss_gdf.geometry.isna()]
    diss_gdf = diss_gdf[~diss_gdf.geometry.is_empty]

    # If there is no result, return
    if len(diss_gdf) == 0:
        message = f"Result is empty for {input_path}"
        return_info['message'] = message
        return_info['perfinfo'] = perfinfo
        return_info['total_time'] = (datetime.datetime.now()-start_time).total_seconds()
        return return_info

    # Save the result to destination file(s)
    start_to_file = datetime.datetime.now()

    # If the tiles don't need to be merged afterwards, we can just save the result as it is
    if str(output_notonborder_path) == str(output_onborder_path):
        # assert to evade pyLance warning 
        assert isinstance(diss_gdf, gpd.GeoDataFrame)
        # Use force_multitype, to evade warnings when some batches contain 
        # singletype and some contain multitype geometries  
        gfo.to_file(
                diss_gdf, output_notonborder_path, 
                layer=output_layer, force_multitype=True)
    else:
        # If not, save the polygons on the border seperately
        bbox_lines_gdf = gpd.GeoDataFrame(
                geometry=geoseries_util.polygons_to_lines(
                        gpd.GeoSeries([sh_geom.box(bbox[0], bbox[1], bbox[2], bbox[3])])), 
                crs=input_gdf.crs)
        onborder_gdf = gpd.sjoin(diss_gdf, bbox_lines_gdf, predicate='intersects')
        onborder_gdf.drop('index_right', axis=1, inplace=True)
        if len(onborder_gdf) > 0:
            # assert to evade pyLance warning 
            assert isinstance(onborder_gdf, gpd.GeoDataFrame)
            # Use force_multitype, to evade warnings when some batches contain 
            # singletype and some contain multitype geometries  
            gfo.to_file(
                    onborder_gdf, output_onborder_path, 
                    layer=output_layer, force_multitype=True)
        
        notonborder_gdf = diss_gdf[~diss_gdf.index.isin(onborder_gdf.index)]
        if len(notonborder_gdf) > 0:
            # assert to evade pyLance warning 
            assert isinstance(notonborder_gdf, gpd.GeoDataFrame) 
            # Use force_multitype, to evade warnings when some batches contain 
            # singletype and some contain multitype geometries  
            gfo.to_file(
                    notonborder_gdf, output_notonborder_path, 
                    layer=output_layer, force_multitype=True)
    perfinfo['time_to_file'] = (datetime.datetime.now()-start_to_file).total_seconds()

    # Finalise...
    message = f"dissolve ready in {datetime.datetime.now()-start_time} on {input_path}!"
    logger.debug(message)
    
    # Collect perfinfo
    total_perf_time = 0
    perfstring = ""
    for perfcode in perfinfo:
        total_perf_time += perfinfo[perfcode]
        perfstring += f"{perfcode}: {perfinfo[perfcode]:.2f}, "
    return_info['total_time'] = (datetime.datetime.now()-start_time).total_seconds()
    perfinfo['unaccounted'] = return_info['total_time'] - total_perf_time
    perfstring += f"unaccounted: {perfinfo['unaccounted']:.2f}"
    
    # Return
    return_info['perfinfo'] = perfinfo
    return_info['perfstring'] = perfstring
    return_info['message'] = message
    return return_info

def _add_orderby_column(
        path: Path,
        layer: str,
        name: str):

    ### Prepare the expression to calculate the orderby column. ###
    # In a spatial file, a spatial order will make later use more efficiënt, 
    # so use a geohash.
    layerinfo = gfo.get_layerinfo(path)
    if layerinfo.crs is not None and layerinfo.crs.is_geographic:
        # If the coordinates are geographic (in lat/lon degrees), ok
        expression = f"ST_GeoHash({layerinfo.geometrycolumn}, 10)"
    else:
        # If they are not geographic (in lat/lon degrees), they need to be  
        # converted to ~ degrees to be able to calculate a geohash.

        # Properly calculating the transformation to eg. WGS is terribly slow... 
        # expression = f"""ST_GeoHash(ST_Transform(MakePoint(
        #       (MbrMaxX(geom)+MbrMinX(geom))/2, 
        #       (MbrMinY(geom)+MbrMaxY(geom))/2, ST_SRID(geom)), 4326), 10)"""
        # So, do something else that's faster and still gives a good 
        # geographic clustering.
        to_geographic_factor_approx = 90/max(layerinfo.total_bounds)
        expression = f"""ST_GeoHash(MakePoint(
                ((MbrMaxX({layerinfo.geometrycolumn})+MbrMinX({layerinfo.geometrycolumn}))/2)*{to_geographic_factor_approx}, 
                ((MbrMinY({layerinfo.geometrycolumn})+MbrMaxY({layerinfo.geometrycolumn}))/2)*{to_geographic_factor_approx}, 4326), 10)"""      
    
    ### Now we can actually add the column. ###
    gfo.add_column(
            path=path, name=name, type=gfo.DataType.TEXT, expression=expression)
    sqlite_stmt = f'CREATE INDEX {name}_idx ON "{layer}"({name})' 
    ogr_util.vector_info(path=path, sql_stmt=sqlite_stmt, readonly=False)
