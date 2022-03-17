# -*- coding: utf-8 -*-
"""
Module exposing all supported operations on geomatries in geofiles.
"""

import logging
import logging.config
import os
from pathlib import Path
from typing import Any, Callable, List, Optional, Union

from geofileops.util import geofileops_gpd
from geofileops.util import geofileops_sql
from geofileops.util.geometry_util import BufferEndCapStyle, BufferJoinStyle, SimplifyAlgorithm, GeometryType 

################################################################################
# Some init
################################################################################

logger = logging.getLogger(__name__)

################################################################################
# The real work
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
    """
    Apply a python lambda function on the geometry column of the input file. 

    The result is written to the output file specified.

    Examples for the func parameter:
        * if only_geom_input is True:
            ``func=lambda geom: geometry_util.remove_inner_rings(``
                    ``geom, min_area_to_keep=1)``
            
        * if only_geom_input is False:
            ``func=lambda row: geometry_util.remove_inner_rings(``
                    ``row.geometry, min_area_to_keep=1)``
            
    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        func (Callable): lambda function to apply to the geometry column.
        only_geom_input (bool, optional): If True, only the geometry 
            column is available. If False, the entire row is input. 
            Remark: when False, the operation is 50% slower. Defaults to True.
        input_layer (str, optional): input layer name. Optional if the input 
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the input 
            file only contains one layer.
        columns (List[str], optional): list of columns to return. If None,
            all columns are returned.
        explodecollections (bool, optional): True to output only simple geometries. 
            Defaults to False.
        nb_parallel (int, optional): the number of parallel processes to use. 
            Defaults to -1: use all available processors.
        batchsize (int, optional): indicative number of rows to process per 
            batch. A smaller batch size, possibly in combination with a 
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        verbose (bool, optional): write more info to the output. 
            Defaults to False.
        force (bool, optional): overwrite existing output file(s). 
            Defaults to False.
    """
    logger.info(f"Start apply on {input_path}")
    return geofileops_gpd.apply(
            input_path=Path(input_path),
            output_path=Path(output_path),
            func=func,
            only_geom_input=only_geom_input,
            input_layer=input_layer,
            output_layer=output_layer,
            columns=columns,
            explodecollections=explodecollections,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            verbose=verbose,
            force=force)

def buffer(
        input_path: Union[str, 'os.PathLike[Any]'],
        output_path: Union[str, 'os.PathLike[Any]'],
        distance: float,
        quadrantsegments: int = 5,
        endcap_style: BufferEndCapStyle = BufferEndCapStyle.ROUND,
        join_style: BufferJoinStyle = BufferJoinStyle.ROUND,
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
    """
    Applies a buffer operation on geometry column of the input file.
    
    The result is written to the output file specified. 

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        distance (float): the buffer size to apply. In projected coordinate 
            systems this is typically in meter, in geodetic systems this is 
            typically in degrees.
        quadrantsegments (int): the number of points a quadrant needs to be 
            approximated with for rounded styles. Defaults to 5.
        endcap_style (BufferEndCapStyle, optional): buffer style to use for a 
            point or the end points of a line. Defaults to ROUND.

              * ROUND: for points and lines the ends are buffered rounded. 
              * FLAT: a point stays a point, a buffered line will end flat 
                at the end points
              * SQUARE: a point becomes a square, a buffered line will end 
                flat at the end points, but elongated by "distance" 
        join_style (BufferJoinStyle, optional): buffer style to use for 
            corners in a line or a polygon boundary. Defaults to ROUND.

              * ROUND: corners in the result are rounded
              * MITRE: corners in the result are sharp
              * BEVEL: are flattened
        mitre_limit (float, optional): in case of join_style MITRE, if the 
            spiky result for a sharp angle becomes longer than this limit, it 
            is "beveled" at this distance. Defaults to 5.0.
        single_sided (bool, optional): only one side of the line is buffered, 
            if distance is negative, the left side, if distance is positive, 
            the right hand side. Only relevant for line geometries. 
            Defaults to False.
        input_layer (str, optional): input layer name. Optional if the input 
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the input 
            file only contains one layer.
        columns (List[str], optional): list of columns to return. If None,
            all columns are returned.
        explodecollections (bool, optional): True to output only simple geometries. 
            Defaults to False.
        nb_parallel (int, optional): the number of parallel processes to use. 
            Defaults to -1: use all available processors.
        batchsize (int, optional): indicative number of rows to process per 
            batch. A smaller batch size, possibly in combination with a 
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        verbose (bool, optional): write more info to the output. 
            Defaults to False.
        force (bool, optional): overwrite existing output file(s). 
            Defaults to False.

    **Buffer style options**

    Using the different buffer style option parameters you can control how the 
    buffer is created:

    - **quadrantsegments** *(int)*
    
      .. list-table:: 
         :header-rows: 1

         * - 5 (default)
           - 2
           - 1
         * - |buffer_quadrantsegments_5|
           - |buffer_quadrantsegments_2|
           - |buffer_quadrantsegments_1|

    - **endcap_style** *(BufferEndCapStyle)*

      .. list-table:: 
         :header-rows: 1

         * - ROUND (default)
           - FLAT
           - SQUARE
         * - |buffer_endcap_round|
           - |buffer_endcap_flat|
           - |buffer_endcap_square|

    - **join_style** *(BufferJoinStyle)*

      .. list-table:: 
         :header-rows: 1

         * - ROUND (default)
           - MITRE
           - BEVEL
         * - |buffer_joinstyle_round|
           - |buffer_joinstyle_mitre|
           - |buffer_joinstyle_bevel|

    - **mitre** *(float)*
    
      .. list-table:: 
         :header-rows: 1

         * - 5.0 (default)
           - 2.5
           - 1.0
         * - |buffer_mitre_50|
           - |buffer_mitre_25|
           - |buffer_mitre_10|

    .. |buffer_quadrantsegments_5| image:: ../_static/images/buffer_quadrantsegments_5.png
        :alt: Buffer with quadrantsegments=5
    .. |buffer_quadrantsegments_2| image:: ../_static/images/buffer_quadrantsegments_2.png
        :alt: Buffer with quadrantsegments=2
    .. |buffer_quadrantsegments_1| image:: ../_static/images/buffer_quadrantsegments_1.png
        :alt: Buffer with quadrantsegments=1
    .. |buffer_endcap_round| image:: ../_static/images/buffer_endcap_round.png
        :alt: Buffer with endcap_style=BufferEndCapStyle.ROUND (default)
    .. |buffer_endcap_flat| image:: ../_static/images/buffer_endcap_flat.png
        :alt: Buffer with endcap_style=BufferEndCapStyle.FLAT
    .. |buffer_endcap_square| image:: ../_static/images/buffer_endcap_square.png
        :alt: Buffer with endcap_style=BufferEndCapStyle.SQUARE
    .. |buffer_joinstyle_round| image:: ../_static/images/buffer_joinstyle_round.png
        :alt: Buffer with joinstyle=BufferJoinStyle.ROUND (default)
    .. |buffer_joinstyle_mitre| image:: ../_static/images/buffer_joinstyle_mitre.png
        :alt: Buffer with joinstyle=BufferJoinStyle.MITRE
    .. |buffer_joinstyle_bevel| image:: ../_static/images/buffer_joinstyle_bevel.png
        :alt: Buffer with joinstyle=BufferJoinStyle.BEVEL
    .. |buffer_mitre_50| image:: ../_static/images/buffer_mitre_50.png
        :alt: Buffer with mitre=5.0
    .. |buffer_mitre_25| image:: ../_static/images/buffer_mitre_25.png
        :alt: Buffer with mitre=2.5
    .. |buffer_mitre_10| image:: ../_static/images/buffer_mitre_10.png
        :alt: Buffer with mitre=1.0
    
    """
    logger.info(f"Start buffer on {input_path} with distance: {distance} and quadrantsegments: {quadrantsegments}")
    if(endcap_style == BufferEndCapStyle.ROUND
            and join_style == BufferJoinStyle.ROUND
            and single_sided is False):
        # If default buffer options for spatialite, use the faster sql version
        return geofileops_sql.buffer(
                input_path=Path(input_path),
                output_path=Path(output_path),
                distance=distance,
                quadrantsegments=quadrantsegments,
                input_layer=input_layer,
                output_layer=output_layer,
                columns=columns,
                explodecollections=explodecollections,
                nb_parallel=nb_parallel,
                batchsize=batchsize,
                verbose=verbose,
                force=force)
    else:
        # If special buffer options, use geopandas version
        return geofileops_gpd.buffer(
                input_path=Path(input_path),
                output_path=Path(output_path),
                distance=distance,
                quadrantsegments=quadrantsegments,
                endcap_style=endcap_style,
                join_style=join_style,
                mitre_limit=mitre_limit,
                single_sided=single_sided,
                input_layer=input_layer,
                output_layer=output_layer,
                columns=columns,
                explodecollections=explodecollections,
                nb_parallel=nb_parallel,
                batchsize=batchsize,
                verbose=verbose,
                force=force)


def convexhull(
        input_path: Union[str, 'os.PathLike[Any]'],
        output_path: Union[str, 'os.PathLike[Any]'],
        input_layer: Optional[str] = None,
        output_layer: Optional[str] = None,
        columns: Optional[List[str]] = None,
        explodecollections: bool = False,
        nb_parallel: int = -1,
        batchsize: int = -1,
        verbose: bool = False,
        force: bool = False):
    """
    Applies a convexhull operation on the input file.
    
    The result is written to the output file specified. 

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        input_layer (str, optional): input layer name. Optional if the input 
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the input 
            file only contains one layer.
        columns (List[str], optional): If not None, only output the columns 
            specified. Defaults to None.
        explodecollections (bool, optional): True to output only simple geometries. 
            Defaults to False.
        nb_parallel (int, optional): the number of parallel processes to use. 
            Defaults to -1: use all available processors.
        batchsize (int, optional): indicative number of rows to process per 
            batch. A smaller batch size, possibly in combination with a 
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        verbose (bool, optional): write more info to the output. 
            Defaults to False.
        force (bool, optional): overwrite existing output file(s). 
            Defaults to False.
    """
    logger.info(f"Start convexhull on {input_path}")
    return geofileops_sql.convexhull(
            input_path=Path(input_path),
            output_path=Path(output_path),
            input_layer=input_layer,
            output_layer=output_layer,
            columns=columns,
            explodecollections=explodecollections,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            verbose=verbose,
            force=force)

def delete_duplicate_geometries(
        input_path: Union[str, 'os.PathLike[Any]'],
        output_path: Union[str, 'os.PathLike[Any]'],
        input_layer: Optional[str] = None,
        output_layer: Optional[str] = None,
        columns: Optional[List[str]] = None,
        explodecollections: bool = False,
        verbose: bool = False,
        force: bool = False):
    """
    Copy all rows to the output file, except for duplicate geometries.

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        input_layer (str, optional): input layer name. Optional if the input 
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the input 
            file only contains one layer.
        columns (List[str], optional): If not None, only output the columns 
            specified. Defaults to None.
        explodecollections (bool, optional): True to output only simple geometries. 
            Defaults to False.
        verbose (bool, optional): write more info to the output. 
            Defaults to False.
        force (bool, optional): overwrite existing output file(s). 
            Defaults to False.
    """
    logger.info(f"Start delete_duplicate_geometries on {input_path}")
    return geofileops_sql.delete_duplicate_geometries(
            input_path=Path(input_path),
            output_path=Path(output_path),
            input_layer=input_layer,
            output_layer=output_layer,
            columns=columns,
            explodecollections=explodecollections,
            verbose=verbose,
            force=force)
    
def dissolve(
        input_path: Union[str, 'os.PathLike[Any]'],  
        output_path: Union[str, 'os.PathLike[Any]'],
        explodecollections: bool,
        groupby_columns: Optional[List[str]] = None,
        columns: Optional[List[str]] = [],
        aggfunc: str = 'first',
        tiles_path: Union[str, 'os.PathLike[Any]', None] = None,
        nb_squarish_tiles: int = 1,
        clip_on_tiles: bool = True,
        input_layer: Optional[str] = None,        
        output_layer: Optional[str] = None,
        nb_parallel: int = -1,
        batchsize: int = -1,
        verbose: bool = False,
        force: bool = False):
    """
    Applies a dissolve operation on the geometry column of the input file.

    For the other columns, only aggfunc = 'first' is supported at the moment. 

    If the output is tiled (by specifying a tiles_path or nb_squarish_tiles > 1), 
    the result will be clipped on the output tiles and the tile borders are 
    never crossed.

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        explodecollections (bool): True to output only simple geometries. If 
            False is specified, this can result in huge geometries for large 
            files, so beware...   
        groupby_columns (List[str], optional): columns to group on while 
            aggregating. Defaults to None, resulting in a spatial union of all 
            geometries that touch.
        columns (List[str], optional): columns to retain in the output file. 
            The columns in parameter groupby_columns are always retained. The
            other columns specified are aggregated as specified in parameter 
            aggfunc. If None is specified, all columns are retained.
            Defaults to [] (= only the groupby_columns are retained).
        aggfunc (str, optional): aggregation function to apply to columns not 
            grouped on. Only 'first' is supported at the moment. 
            Defaults to 'first'.
        tiles_path (PathLike, optional): a path to a geofile containing tiles. 
            If specified, the output will be dissolved/unioned only within the 
            tiles provided. 
            Can be used to evade huge geometries being created if the input 
            geometries are very interconnected. 
            Defaults to None (= the output is not tiled).
        nb_squarish_tiles (int, optional): the approximate number of tiles the 
            output should be dissolved/unioned to. If > 1, a tiling grid is 
            automatically created based on the total bounds of the input file.
            The input geometries will be dissolved/unioned only within the 
            tiles generated.   
            Can be used to evade huge geometries being created if the input 
            geometries are very interconnected. 
            Defaults to 1 (= the output is not tiled).
        clip_on_tiles (bool, optional): deprecated: should always be True! 
            If the output is tiled (by specifying a tiles_path 
            or a nb_squarish_tiles > 1), the result will be clipped 
            on the output tiles and the tile borders are never crossed.
            When False, a (scalable, fast) implementation always resulted in 
            some geometries not being merged or in duplicates. 
            Defaults to True.
        input_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        nb_parallel (int, optional): the number of parallel processes to use. 
            Defaults to -1: use all available processors.
        batchsize (int, optional): indicative number of rows to process per 
            batch. A smaller batch size, possibly in combination with a 
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        verbose (bool, optional): write more info to the output. 
            Defaults to False.
        force (bool, optional): overwrite existing output file(s). 
            Defaults to False.
    """
    # Init
    if clip_on_tiles is False:
        logger.warn("The clip_on_tiles parameter is deprecated! It is ignored and always treated as True. When False, a fast implementation results in some geometries not being merged or in duplicates.")
        if tiles_path is not None or nb_squarish_tiles > 1:
            raise Exception("clip_on_tiles is deprecated, and the behaviour of clip_on_tiles is False is not supported anymore.")
    tiles_path_p = None
    if tiles_path is not None:
        tiles_path_p = Path(tiles_path)
    
    # If an empty list of geometry columns is passed, convert it to None to 
    # simplify the rest of the code 
    if groupby_columns is not None and len(groupby_columns) == 0:
        groupby_columns = None

    logger.info(f"Start dissolve on {input_path} to {output_path}")
    return geofileops_gpd.dissolve(
            input_path=Path(input_path),
            output_path=Path(output_path),
            explodecollections=explodecollections,
            groupby_columns=groupby_columns,
            columns=columns,
            aggfunc=aggfunc,
            tiles_path=tiles_path_p,
            nb_squarish_tiles=nb_squarish_tiles,
            input_layer=input_layer,        
            output_layer=output_layer,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            verbose=verbose,
            force=force)

def isvalid(
        input_path: Union[str, 'os.PathLike[Any]'],
        output_path: Union[str, 'os.PathLike[Any]', None] = None,
        only_invalid: bool = False,
        input_layer: Optional[str] = None,
        output_layer: Optional[str] = None,
        nb_parallel: int = -1,
        batchsize: int = -1,
        verbose: bool = False,
        force: bool = False) -> bool:
    """
    Checks for all geometries in the geofile if they are valid, and writes the 
    results to the output file

    Args:
        input_path (PathLike): The input file.
        output_path (PathLike, optional): The output file path. If not 
            specified the result will be written in a new file alongside the 
            input file. Defaults to None.
        only_invalid (bool, optional): if True, only put invalid results in the
            output file. Deprecated: always treated as True.
        input_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        nb_parallel (int, optional): the number of parallel processes to use. 
            Defaults to -1: use all available processors.
        batchsize (int, optional): indicative number of rows to process per 
            batch. A smaller batch size, possibly in combination with a 
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        verbose (bool, optional): write more info to the output. 
            Defaults to False.
        force (bool, optional): overwrite existing output file(s). 
            Defaults to False.

    Returns:
        bool: True if all geometries were valid.
    """

    # Check parameters
    if output_path is not None:
        output_path_p = Path(output_path)
    else:
        input_path_p = Path(input_path)
        output_path_p = input_path_p.parent / f"{input_path_p.stem}_isvalid{input_path_p.suffix}" 

    # Go!
    logger.info(f"Start isvalid on {input_path}")
    return geofileops_sql.isvalid(
            input_path=Path(input_path),
            output_path=output_path_p,
            input_layer=input_layer, 
            output_layer=output_layer,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            verbose=verbose,
            force=force)

def makevalid(
        input_path: Union[str, 'os.PathLike[Any]'],
        output_path: Union[str, 'os.PathLike[Any]'],
        input_layer: Optional[str] = None,        
        output_layer: Optional[str] = None,
        columns: Optional[List[str]] = None,
        explodecollections: bool = False, 
        force_output_geometrytype: Optional[GeometryType] = None,
        precision: Optional[float] = None,
        nb_parallel: int = -1,
        batchsize: int = -1,
        verbose: bool = False,
        force: bool = False):
    """
    Makes all geometries in the input file valid and writes the result to the
    output path.

    Args:
        input_path (PathLike): The input file.
        output_path (PathLike): The file to write the result to.
        input_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        columns (List[str], optional): If not None, only output the columns 
            specified. Defaults to None.
        explodecollections (bool, optional): True to output only simple geometries. 
            Defaults to False.
        force_output_geometrytype (GeometryType, optional): The output geometry type to 
            force. Defaults to None, and then the geometry type of the input is used 
        precision (floas, optional): the precision to keep in the coordinates. 
            Eg. 0.001 to keep 3 decimals. None doesn't change the precision.
            Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use. 
            Defaults to -1: use all available processors.
        batchsize (int, optional): indicative number of rows to process per 
            batch. A smaller batch size, possibly in combination with a 
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        verbose (bool, optional): write more info to the output. 
            Defaults to False.
        force (bool, optional): overwrite existing output file(s). 
            Defaults to False.
    """

    logger.info(f"Start makevalid on {input_path}")
    geofileops_sql.makevalid(
            input_path=Path(input_path),
            output_path=Path(output_path),
            input_layer=input_layer,        
            output_layer=output_layer,
            columns=columns,
            explodecollections=explodecollections,
            force_output_geometrytype=force_output_geometrytype,
            precision=precision,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            verbose=verbose,
            force=force)

def select(
        input_path: Union[str, 'os.PathLike[Any]'],
        output_path: Union[str, 'os.PathLike[Any]'],
        sql_stmt: str,
        sql_dialect: str = 'SQLITE',
        input_layer: Optional[str] = None,
        output_layer: Optional[str] = None,
        columns: Optional[List[str]] = None,
        explodecollections: bool = False,
        force_output_geometrytype: Union[GeometryType, str, None] = None,
        nb_parallel: int = 1,
        batchsize: int = -1,
        verbose: bool = False,
        force: bool = False):
    """
    Execute an sqlite style SQL query on the file. 
    
    By convention, the sqlite query can contain following placeholders that
    will be automatically replaced for you:

      * {geometrycolumn}: the column where the primary geometry is stored.
      * {columns_to_select_str}: if 'columns' is not None, those columns, 
        otherwise all columns of the layer.
      * {input_layer}: the layer name of the input layer.
      * {batch_filter}: the filter used to process in parallel per batch. 
    
    Example: Copy all rows with a certain minimum area to the output file. 
    ::        
    
        import geofileops as gfo

        minimum_area = 100
        sql_stmt = f'''
                SELECT {{geometrycolumn}}
                      {{columns_to_select_str}}
                  FROM "{{input_layer}}"
                 WHERE 1=1
                   {{batch_filter}}
                   AND ST_Area({{geometrycolumn}}) > {minimum_area}
                '''
        gfo.select(
                input_path=...,
                output_path=...,
                sql_stmt=sql_stmt)

    Some important remarks:

    * Because some sql statement won't give the same result when parallellized 
      (eg. when using a group by statement), nb_parallel is 1 by default. 
      If you do want to use parallel processing, specify nb_parallel + make 
      sure to include the placeholder {batch_filter} in your sql_stmt. 
      This placeholder will be replaced with a filter of the form 
      'AND rowid >= x AND rowid < y'.
    * Table names are best double quoted as in the example, because some 
      characters are otherwise not supported in the table name, eg. '-'.
    * Besides the standard sqlite sql syntacs, you can use the spatialite 
      functions as documented here: |sqlite_reference_link|   

    .. |sqlite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    The result is written to the output file specified.

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        sql_stmt (str): the statement to execute
        sql_dialect (str, optional): the sql dialect to use. If None is passed,
            the default sql dialect of the underlying source is used. The 
            default is 'SQLITE'.
        input_layer (str, optional): input layer name. Optional if the input 
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the input
            file only contains one layer.
        columns (List[str], optional): If not None AND the column placeholders 
            are used in the sql statement, only output the columns specified. 
            Defaults to None.
        explodecollections (bool, optional): True to convert all multi-geometries to 
            singular ones after the dissolve. Defaults to False.
        force_output_geometrytype (GeometryType, optional): The output geometry type to 
            force. Defaults to None, and then the geometry type of the input is used 
        nb_parallel (int, optional): the number of parallel processes to use. 
            Defaults to 1. To use all available cores, pass -1. 
        batchsize (int, optional): indicative number of rows to process per 
            batch. A smaller batch size, possibly in combination with a 
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        verbose (bool, optional): write more info to the output. Defaults to False.
        force (bool, optional): overwrite existing output file(s). Defaults to False.
    """
    logger.info(f"Start select on {input_path}")

    # Convert force_output_geometrytype to GeometryType (if necessary)
    if force_output_geometrytype is not None:
        force_output_geometrytype = GeometryType(force_output_geometrytype)
        
    return geofileops_sql.select(
            input_path=Path(input_path),
            output_path=Path(output_path),
            sql_stmt=sql_stmt,
            sql_dialect=sql_dialect,
            input_layer=input_layer,        
            output_layer=output_layer,
            columns=columns,
            explodecollections=explodecollections,
            force_output_geometrytype=force_output_geometrytype,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            verbose=verbose,
            force=force)

def simplify(
        input_path: Union[str, 'os.PathLike[Any]'],
        output_path: Union[str, 'os.PathLike[Any]'],
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
    """
    Applies a simplify operation on geometry column of the input file.
    
    The result is written to the output file specified. 

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        tolerance (float): mandatory for the following algorithms:  

                * RAMER_DOUGLAS_PEUCKER: distance to use as tolerance.
                * LANG: distance to use as tolerance.
                * VISVALINGAM_WHYATT: area to use as tolerance.

            In projected coordinate systems this tolerance will typically be 
            in meter, in geodetic systems this is typically in degrees.
        algorithm (SimplifyAlgorithm, optional): algorithm to use.
            Defaults to SimplifyAlgorithm.RAMER_DOUGLAS_PEUCKER.
        lookahead (int, optional): used for LANG algorithm. Defaults to 8.
        input_layer (str, optional): input layer name. Optional if the input 
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the input 
            file only contains one layer.
        columns (List[str], optional): If not None, only output the columns 
            specified. Defaults to None.
        explodecollections (bool, optional): True to output only simple geometries. 
            Defaults to False.
        nb_parallel (int, optional): the number of parallel processes to use. 
            Defaults to -1: use all available processors.
        batchsize (int, optional): indicative number of rows to process per 
            batch. A smaller batch size, possibly in combination with a 
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        verbose (bool, optional): write more info to the output. 
            Defaults to False.
        force (bool, optional): overwrite existing output file(s). 
            Defaults to False.
    """
    logger.info(f"Start simplify on {input_path} with tolerance {tolerance}")
    if algorithm == SimplifyAlgorithm.RAMER_DOUGLAS_PEUCKER:
        return geofileops_sql.simplify(
                input_path=Path(input_path),
                output_path=Path(output_path),
                tolerance=tolerance,
                input_layer=input_layer,
                output_layer=output_layer,
                columns=columns,
                explodecollections=explodecollections,
                nb_parallel=nb_parallel,
                batchsize=batchsize,
                verbose=verbose,
                force=force)
    else:
        return geofileops_gpd.simplify(
                input_path=Path(input_path),
                output_path=Path(output_path),
                tolerance=tolerance,
                algorithm=algorithm,
                lookahead=lookahead,
                input_layer=input_layer,
                output_layer=output_layer,
                columns=columns,
                explodecollections=explodecollections,
                nb_parallel=nb_parallel,
                batchsize=batchsize,
                verbose=verbose,
                force=force)

def erase(
        input_path: Union[str, 'os.PathLike[Any]'],
        erase_path: Union[str, 'os.PathLike[Any]'],
        output_path: Union[str, 'os.PathLike[Any]'],
        input_layer: Optional[str] = None,
        input_columns: Optional[List[str]] = None,
        erase_layer: Optional[str] = None,
        output_layer: Optional[str] = None,
        explodecollections: bool = False,
        nb_parallel: int = -1,
        batchsize: int = -1,
        verbose: bool = False,
        force: bool = False):
    """
    Erase all geometries in the erase layer from the input layer.

    Args:
        input_path (PathLike): The file to erase from.
        erase_path (PathLike): The file with the geometries to erase with.
        output_path (PathLike): the file to write the result to
        input1_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        input1_columns (List[str], optional): columns to select. If no columns
            specified, all columns are selected.
        erase_layer (str, optional): erase layer name. Optional if the  
            file only contains one layer.
        output_layer (str, optional): output layer name. Optional if the  
            file only contains one layer.
        explodecollections (bool, optional): True to convert all multi-geometries to 
            singular ones after the dissolve. Defaults to False.
        nb_parallel (int, optional): the number of parallel processes to use. 
            Defaults to -1: use all available processors.
        batchsize (int, optional): indicative number of rows to process per 
            batch. A smaller batch size, possibly in combination with a 
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        verbose (bool, optional): write more info to the output. 
             Defaults to False.
        force (bool, optional): overwrite existing output file(s). 
            Defaults to False.

    Returns:
        [type]: [description]
    """

    logger.info(f"Start erase on {input_path} with {erase_path} to {output_path}")
    return geofileops_sql.erase(
        input_path=Path(input_path),
        erase_path=Path(erase_path),
        output_path=Path(output_path),
        input_layer=input_layer,
        input_columns=input_columns,
        erase_layer=erase_layer,
        output_layer=output_layer,
        explodecollections=explodecollections,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        verbose=verbose,
        force=force)

def export_by_location(
        input_to_select_from_path: Union[str, 'os.PathLike[Any]'],
        input_to_compare_with_path: Union[str, 'os.PathLike[Any]'],
        output_path: Union[str, 'os.PathLike[Any]'],
        min_area_intersect: Optional[float] = None,
        area_inters_column_name: Optional[str] = 'area_inters',
        input1_layer: Optional[str] = None,
        input1_columns: Optional[List[str]] = None,
        input2_layer: Optional[str] = None,
        input2_columns: Optional[List[str]] = None,
        output_layer: Optional[str] = None,
        nb_parallel: int = -1,
        batchsize: int = -1,
        verbose: bool = False,
        force: bool = False):
    """
    Exports all features in input_to_select_from_path that intersect with any 
    features in input_to_compare_with_path.
    
    Args:
        input_to_select_from_path (PathLike): the 1st input file
        input_to_compare_with_path (PathLike): the 2nd input file
        output_path (PathLike): the file to write the result to
        min_area_intersect (float, optional): minimum area of the intersection.
            Defaults to None.
        area_inters_column_name (str, optional): column name of the intersect 
            area. Defaults to 'area_inters'. In None, no area column is added.
        input1_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        input1_columns (List[str], optional): columns to select. If no columns
            specified, all columns are selected.
        input2_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        input2_columns (List[str], optional): columns to select. If no columns
            specified, all columns are selected.
        output_layer (str, optional): output layer name. Optional if the  
            file only contains one layer.
        nb_parallel (int, optional): the number of parallel processes to use. 
            Defaults to -1: use all available processors.
        batchsize (int, optional): indicative number of rows to process per 
            batch. A smaller batch size, possibly in combination with a 
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        verbose (bool, optional): write more info to the output. 
            Defaults to False.
        force (bool, optional): overwrite existing output file(s). 
            Defaults to False.
    """
    logger.info(f"Start export_by_location: select from {input_to_select_from_path} interacting with {input_to_compare_with_path} to {output_path}")
    return geofileops_sql.export_by_location(
            input_to_select_from_path=Path(input_to_select_from_path),
            input_to_compare_with_path=Path(input_to_compare_with_path),
            output_path=Path(output_path),
            min_area_intersect=min_area_intersect,
            area_inters_column_name=area_inters_column_name,
            input1_layer=input1_layer,
            input1_columns=input1_columns,
            input2_layer=input2_layer,
            input2_columns=input2_columns,
            output_layer=output_layer,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            verbose=verbose,
            force=force)

def export_by_distance(
        input_to_select_from_path: Union[str, 'os.PathLike[Any]'],
        input_to_compare_with_path: Union[str, 'os.PathLike[Any]'],
        output_path: Union[str, 'os.PathLike[Any]'],
        max_distance: float,
        input1_layer: Optional[str] = None,
        input1_columns: Optional[List[str]] = None,
        input2_layer: Optional[str] = None,
        output_layer: Optional[str] = None,
        nb_parallel: int = -1,
        batchsize: int = -1,
        verbose: bool = False,
        force: bool = False):
    """
    Exports all features in input_to_select_from_path that are within the 
    distance specified of any features in input_to_compare_with_path.
    
    Args:
        input_to_select_from_path (PathLike): the 1st input file
        input_to_compare_with_path (PathLike): the 2nd input file
        output_path (PathLike): the file to write the result to
        max_distance (float): maximum distance
        input1_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        input1_columns (List[str], optional): columns to select. If no columns
            specified, all columns are selected.
        input2_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        output_layer (str, optional): output layer name. Optional if the  
            file only contains one layer.
        nb_parallel (int, optional): the number of parallel processes to use. 
            Defaults to -1: use all available processors.
        batchsize (int, optional): indicative number of rows to process per 
            batch. A smaller batch size, possibly in combination with a 
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        verbose (bool, optional): write more info to the output. 
            Defaults to False.
        force (bool, optional): overwrite existing output file(s). 
            Defaults to False.
    """
    logger.info(f"Start export_by_distance: select from {input_to_select_from_path} within max_distance of {max_distance} from {input_to_compare_with_path} to {output_path}")
    return geofileops_sql.export_by_distance(
            input_to_select_from_path=Path(input_to_select_from_path),
            input_to_compare_with_path=Path(input_to_compare_with_path),
            output_path=Path(output_path),
            max_distance=max_distance,
            input1_layer=input1_layer,
            input1_columns=input1_columns,
            input2_layer=input2_layer,
            output_layer=output_layer,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            verbose=verbose,
            force=force)

def intersect(
        input1_path: Union[str, 'os.PathLike[Any]'],
        input2_path: Union[str, 'os.PathLike[Any]'],
        output_path: Union[str, 'os.PathLike[Any]'],
        input1_layer: Optional[str] = None,
        input1_columns: Optional[List[str]] = None,
        input1_columns_prefix: str = 'l1_',
        input2_layer: Optional[str] = None,
        input2_columns: Optional[List[str]] = None,
        input2_columns_prefix: str = 'l2_',
        output_layer: Optional[str] = None,
        explodecollections: bool = False,
        nb_parallel: int = -1,
        batchsize: int = -1,
        verbose: bool = False,
        force: bool = False):
    """
    Calculate the pairwise intersection of alle features in input1 with all 
    features in input2.
    
    Args:
        input1_path (PathLike): the 1st input file
        input2_path (PathLike): the 2nd input file
        output_path (PathLike): the file to write the result to
        input1_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        input1_columns (List[str], optional): columns to select. If no columns
            specified, all columns are selected.
        input2_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        input2_columns (List[str], optional): columns to select. If no columns
            specified, all columns are selected.
        output_layer (str, optional): output layer name. Optional if the  
            file only contains one layer.
        explodecollections (bool, optional): True to convert all multi-geometries to 
            singular ones after the dissolve. Defaults to False.
        nb_parallel (int, optional): the number of parallel processes to use. 
            Defaults to -1: use all available processors.
        batchsize (int, optional): indicative number of rows to process per 
            batch. A smaller batch size, possibly in combination with a 
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        verbose (bool, optional): write more info to the output. 
            Defaults to False.
        force (bool, optional): overwrite existing output file(s). 
            Defaults to False.
    """
    logger.info(f"Start intersect between {input1_path} and {input2_path} to {output_path}")
    return geofileops_sql.intersect(
            input1_path=Path(input1_path),
            input2_path=Path(input2_path),
            output_path=Path(output_path),
            input1_layer=input1_layer,
            input1_columns=input1_columns,
            input1_columns_prefix=input1_columns_prefix,
            input2_layer=input2_layer,
            input2_columns=input2_columns,
            input2_columns_prefix=input2_columns_prefix,
            output_layer=output_layer,
            explodecollections=explodecollections,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            verbose=verbose,
            force=force)

def join_by_location(
        input1_path: Path,
        input2_path: Path,
        output_path: Path,
        discard_nonmatching: bool = True,
        min_area_intersect: Optional[float] = None,
        area_inters_column_name: Optional[str] = None,
        input1_layer: Optional[str] = None,
        input1_columns: Optional[List[str]] = None,
        input1_columns_prefix: str = 'l1_',
        input2_layer: Optional[str] = None,
        input2_columns: Optional[List[str]] = None,
        input2_columns_prefix: str = 'l2_',
        output_layer: Optional[str] = None,
        nb_parallel: int = -1,
        batchsize: int = -1,
        verbose: bool = False,
        force: bool = False):
    """
    Joins all features in input1 that intersect with any 
    features in input2.
    
    Args:
        input1_path (PathLike): the 1st input file
        input2_path (PathLike): the 2nd input file
        output_path (PathLike): the file to write the result to
        discard_nonmatching (bool, optional): pass False to keep rows in the 
            "select layer" if they don't compy to the spatial operation anyway 
            (=outer join). Defaults to True (=inner join). 
        min_area_intersect (float, optional): minimum area of the intersection.
            Defaults to None.
        area_inters_column_name (str, optional): column name of the intersect 
            area. Defaults to 'area_inters'. In None, no area column is added.
        input1_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        input1_columns (List[str], optional): columns to select. If no columns
            specified, all columns are selected.
        input2_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        input2_columns (List[str], optional): columns to select. If no columns
            specified, all columns are selected.
        output_layer (str, optional): output layer name. Optional if the  
            file only contains one layer.
        nb_parallel (int, optional): the number of parallel processes to use. 
            Defaults to -1: use all available processors.
        batchsize (int, optional): indicative number of rows to process per 
            batch. A smaller batch size, possibly in combination with a 
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        verbose (bool, optional): write more info to the output. 
            Defaults to False.
        force (bool, optional): overwrite existing output file(s). 
            Defaults to False.
    """
    logger.info(f"Start join_by_location: select from {input1_path} joined with {input2_path} to {output_path}")
    return geofileops_sql.join_by_location(
            input1_path=Path(input1_path),
            input2_path=Path(input2_path),
            output_path=Path(output_path),
            discard_nonmatching=discard_nonmatching,
            min_area_intersect=min_area_intersect,
            area_inters_column_name=area_inters_column_name,
            input1_layer=input1_layer,
            input1_columns=input1_columns,
            input1_columns_prefix=input1_columns_prefix,
            input2_layer=input2_layer,
            input2_columns=input2_columns,
            input2_columns_prefix=input2_columns_prefix,
            output_layer=output_layer,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            verbose=verbose,
            force=force)

def join_nearest(
        input1_path: Path,
        input2_path: Path,
        output_path: Path,
        nb_nearest: int,
        input1_layer: Optional[str] = None,
        input1_columns: Optional[List[str]] = None,
        input1_columns_prefix: str = 'l1_',
        input2_layer: Optional[str] = None,
        input2_columns: Optional[List[str]] = None,
        input2_columns_prefix: str = 'l2_',
        output_layer: Optional[str] = None,
        nb_parallel: int = -1,
        batchsize: int = -1,
        verbose: bool = False,
        force: bool = False):
    """
    Joins features in input1 with the nb_nearest features that are closest to 
    them in input2.
    
    Args:
        input1_path (PathLike): the 1st input file
        input2_path (PathLike): the 2nd input file
        output_path (PathLike): the file to write the result to
        nb_nearest (int): the number of nearest features from input 2 to join 
            to input1. 
        input1_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        input1_columns (List[str], optional): columns to select. If no columns
            specified, all columns are selected.
        input2_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        input2_columns (List[str], optional): columns to select. If no columns
            specified, all columns are selected.
        output_layer (str, optional): output layer name. Optional if the  
            file only contains one layer.
        nb_parallel (int, optional): the number of parallel processes to use. 
            Defaults to -1: use all available processors.
        batchsize (int, optional): indicative number of rows to process per 
            batch. A smaller batch size, possibly in combination with a 
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        verbose (bool, optional): write more info to the output. 
            Defaults to False.
        force (bool, optional): overwrite existing output file(s). 
            Defaults to False.
    """
    logger.info(f"Start join_nearest: select from {input1_path} joined with {input2_path} to {output_path}")
    return geofileops_sql.join_nearest(
            input1_path=Path(input1_path),
            input2_path=Path(input2_path),
            output_path=Path(output_path),
            nb_nearest=nb_nearest,
            input1_layer=input1_layer,
            input1_columns=input1_columns,
            input1_columns_prefix=input1_columns_prefix,
            input2_layer=input2_layer,
            input2_columns=input2_columns,
            input2_columns_prefix=input2_columns_prefix,
            output_layer=output_layer,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            verbose=verbose,
            force=force)

def select_two_layers(
        input1_path: Path,
        input2_path: Path,
        output_path: Path,
        sql_stmt: str,
        input1_layer: Optional[str] = None,
        input1_columns: Optional[List[str]] = None,
        input1_columns_prefix: str = 'l1_',
        input2_layer: Optional[str] = None,
        input2_columns: Optional[List[str]] = None,
        input2_columns_prefix: str = 'l2_',
        output_layer: Optional[str] = None,
        explodecollections: bool = False,
        force_output_geometrytype: Optional[GeometryType] = None,
        nb_parallel: int = 1,
        batchsize: int = -1,
        verbose: bool = False,
        force: bool = False):
    """
    Executes the sqlite query specified on the 2 input layers specified.

    By convention, the sqlite query can contain following placeholders that
    will be automatically replaced for you:

      * {input1_layer}: name of input layer 1 
      * {input1_geometrycolumn}: name of input geometry column 1
      * {layer1_columns_prefix_str}: komma seperated columns of 
        layer 1, prefixed with "layer1"
      * {layer1_columns_prefix_alias_str}: komma seperated columns of 
        layer 1, prefixed with "layer1" and with column name aliases
      * {layer1_columns_from_subselect_str}: komma seperated columns of 
        layer 1, prefixed with "sub"
      * {input1_databasename}: the database alias for input 1   
      * {input2_layer}: name of input layer 1 
      * {input2_geometrycolumn}: name of input geometry column 2
      * {layer2_columns_prefix_str}: komma seperated columns of 
        layer 2, prefixed with "layer2"
      * {layer2_columns_prefix_alias_str}: komma seperated columns of 
        layer 2, prefixed with "layer2" and with column name aliases
      * {layer2_columns_from_subselect_str}: komma seperated columns of 
        layer 2, prefixed with "sub"
      * {layer2_columns_prefix_alias_null_str}: komma seperated columns of 
        layer 2, but with NULL for all values and with column aliases
      * {input2_databasename}: the database alias for input 2   
      * {batch_filter}: the filter to be applied per batch when using 
        parallel processing
    
    Example: left outer join all features in input1 layer with all rows 
    in input2 on join_id. 
    ::        
    
        import geofileops as gfo

        minimum_area = 100
        sql_stmt = f'''
                SELECT layer1.{{input1_geometrycolumn}}
                      {{layer1_columns_prefix_alias_str}}
                      {{layer2_columns_prefix_alias_str}}
                  FROM {{input1_databasename}}."{{input1_layer}}" layer1
                  LEFT OUTER JOIN {{input2_databasename}}."{{input2_layer}}" layer2 
                    ON layer1.join_id = layer2.join_id
                 WHERE 1=1
                   {{batch_filter}}
                   AND ST_Area(layer1.{{input1_geometrycolumn}}) > {minimum_area}
                '''
        gfo.select_two_layers(
                input1_path=...,
                input2_path=...,
                output_path=...,
                sql_stmt=sql_stmt)

    Some important remarks:

    * Because some sql statement won't give the same result when parallellized 
      (eg. when using a group by statement), nb_parallel is 1 by default. 
      If you do want to use parallel processing, specify nb_parallel + make 
      sure to include the placeholder {batch_filter} in your sql_stmt. 
      This placeholder will be replaced with a filter of the form 
      'AND rowid >= x AND rowid < y'.
    * Table names are best double quoted as in the example, because some 
      characters are otherwise not supported in the table name, eg. '-'.
    * Besides the standard sqlite sql syntacs, you can use the spatialite 
      functions as documented here: |sqlite_reference_link|   

    .. |sqlite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    The result is written to the output file specified.
    
    Args:
        input1_path (PathLike): the 1st input file
        input2_path (PathLike): the 2nd input file
        output_path (PathLike): the file to write the result to
        input1_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        input1_columns (List[str], optional): columns to select. If no columns
            specified, all columns are selected.
        input2_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        input2_columns (List[str], optional): columns to select. If no columns
            specified, all columns are selected.
        output_layer (str, optional): output layer name. Optional if the  
            file only contains one layer.
        explodecollections (bool, optional): True to convert all multi-geometries to 
            singular ones after the dissolve. Defaults to False.
        force_output_geometrytype (GeometryType, optional): The output geometry 
            type to force. Defaults to None, and then the geometry type of the 
            input1 layer is used.
        nb_parallel (int, optional): the number of parallel processes to use. 
            Defaults to -1: use all available processors.
        batchsize (int, optional): indicative number of rows to process per 
            batch. A smaller batch size, possibly in combination with a 
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        verbose (bool, optional): write more info to the output. 
            Defaults to False.
        force (bool, optional): overwrite existing output file(s). 
            Defaults to False.

    **Some more advanced example queries**

    An ideal place to get inspiration to write you own advanced queries 
    is in the following source code file: |geofileops_sql_link|.

    Additionally, there are some examples listed here that highlight 
    other features/possibilities.  

    .. |geofileops_sql_link| raw:: html

        <a href="https://github.com/theroggy/geofileops/blob/master/geofileops/util/geofileops_sql.py" target="_blank">geofileops_sql.py</a>

    *Join nearest features*

    For each feature in layer1, get the nearest feature of layer2 with the 
    same values for the column join_id.

        .. code-block:: sqlite3

            WITH join_with_dist AS (
                SELECT layer2.{{input2_geometrycolumn}}
                      {{layer1_columns_prefix_alias_str}}
                      {{layer2_columns_prefix_alias_str}}
                      ,ST_Distance(layer2.{{input2_geometrycolumn}}
                      ,layer1.{{input1_geometrycolumn}}) AS distance
                 FROM {{input1_databasename}}."{{input1_layer}}" layer1
                 JOIN {{input2_databasename}}."{{input2_layer}}" layer2 
                   ON layer1.join_id = layer2.join_id
                )
            SELECT * 
              FROM join_with_dist jwd
             WHERE distance = (
                   SELECT MIN(distance) FROM join_with_dist jwd_sub 
                    WHERE jwd_sub.l1_join_id = jwd.l1_join_id)
             ORDER BY distance DESC
    """
    logger.info(f"Start select_two_layers: select from {input1_path} and {input2_path} to {output_path}")
    return geofileops_sql.select_two_layers(
            input1_path=Path(input1_path),
            input2_path=Path(input2_path),
            output_path=Path(output_path),
            sql_stmt=sql_stmt,
            input1_layer=input1_layer,
            input1_columns=input1_columns,
            input1_columns_prefix=input1_columns_prefix,
            input2_layer=input2_layer,
            input2_columns=input2_columns,
            input2_columns_prefix=input2_columns_prefix,
            output_layer=output_layer,
            explodecollections=explodecollections,
            force_output_geometrytype=force_output_geometrytype,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            verbose=verbose,
            force=force)

def split(
        input1_path: Union[str, 'os.PathLike[Any]'],
        input2_path: Union[str, 'os.PathLike[Any]'],
        output_path: Union[str, 'os.PathLike[Any]'],
        input1_layer: Optional[str] = None,
        input1_columns: Optional[List[str]] = None,
        input1_columns_prefix: str = 'l1_',
        input2_layer: Optional[str] = None,
        input2_columns: Optional[List[str]] = None,
        input2_columns_prefix: str = 'l2_',
        output_layer: Optional[str] = None,
        explodecollections: bool = False,
        nb_parallel: int = -1,
        batchsize: int = -1,
        verbose: bool = False,
        force: bool = False):
    """
    Split the features in input1 with all features in input2.

    The result is the equivalent of an intersect between the two layers + layer 
    1 erased with layer 2. 
    In ArcMap and SAGA this operation is called "Identity".
    
    Args:
        input1_path (PathLike): the 1st input file
        input2_path (PathLike): the 2nd input file
        output_path (PathLike): the file to write the result to
        input1_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        input1_columns (List[str], optional): columns to select. If no columns
            specified, all columns are selected.
        input2_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        input2_columns (List[str], optional): columns to select. If no columns
            specified, all columns are selected.
        output_layer (str, optional): output layer name. Optional if the  
            file only contains one layer.
        explodecollections (bool, optional): True to convert all multi-geometries to 
            singular ones after the dissolve. Defaults to False.
        nb_parallel (int, optional): the number of parallel processes to use. 
            Defaults to -1: use all available processors.
        batchsize (int, optional): indicative number of rows to process per 
            batch. A smaller batch size, possibly in combination with a 
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        verbose (bool, optional): write more info to the output. 
            Defaults to False.
        force (bool, optional): overwrite existing output file(s). 
            Defaults to False.
    """
    logger.info(f"Start split between {input1_path} and {input2_path} to {output_path}")
    return geofileops_sql.split(
            input1_path=Path(input1_path),
            input2_path=Path(input2_path),
            output_path=Path(output_path),
            input1_layer=input1_layer,
            input1_columns=input1_columns,
            input1_columns_prefix=input1_columns_prefix,
            input2_layer=input2_layer,
            input2_columns=input2_columns,
            input2_columns_prefix=input2_columns_prefix,
            output_layer=output_layer,
            explodecollections=explodecollections,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            verbose=verbose,
            force=force)

def union(
        input1_path: Path,
        input2_path: Path,
        output_path: Path,
        input1_layer: Optional[str] = None,
        input1_columns: Optional[List[str]] = None,
        input1_columns_prefix: str = 'l1_',
        input2_layer: Optional[str] = None,
        input2_columns: Optional[List[str]] = None,
        input2_columns_prefix: str = 'l2_',
        output_layer: Optional[str] = None,
        explodecollections: bool = False,
        nb_parallel: int = -1,
        batchsize: int = -1,
        verbose: bool = False,
        force: bool = False):
    """
    Calculates the "union" of the two input layers.
    
    Args:
        input1_path (PathLike): the 1st input file
        input2_path (PathLike): the 2nd input file
        output_path (PathLike): the file to write the result to
        input1_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        input1_columns (List[str], optional): columns to select. If no columns
            specified, all columns are selected.
        input2_layer (str, optional): input layer name. Optional if the  
            file only contains one layer.
        input2_columns (List[str], optional): columns to select. If no columns
            specified, all columns are selected.
        output_layer (str, optional): output layer name. Optional if the  
            file only contains one layer.
        explodecollections (bool, optional): True to convert all multi-geometries to 
            singular ones after the dissolve. Defaults to False.
        nb_parallel (int, optional): the number of parallel processes to use. 
            Defaults to -1: use all available processors.
        batchsize (int, optional): indicative number of rows to process per 
            batch. A smaller batch size, possibly in combination with a 
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        verbose (bool, optional): write more info to the output. 
            Defaults to False.
        force (bool, optional): overwrite existing output file(s). 
            Defaults to False.
    """
    logger.info(f"Start union: select from {input1_path} and {input2_path} to {output_path}")
    return geofileops_sql.union(
            input1_path=Path(input1_path),
            input2_path=Path(input2_path),
            output_path=Path(output_path),
            input1_layer=input1_layer,
            input1_columns=input1_columns,
            input1_columns_prefix=input1_columns_prefix,
            input2_layer=input2_layer,
            input2_columns=input2_columns,
            input2_columns_prefix=input2_columns_prefix,
            output_layer=output_layer,
            explodecollections=explodecollections,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            verbose=verbose,
            force=force)
