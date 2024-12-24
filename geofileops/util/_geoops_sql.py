"""Module containing the implementation of Geofile operations using a sql statement."""

import json
import logging
import logging.config
import math
import multiprocessing
import shutil
import string
import warnings
from collections.abc import Iterable
from concurrent import futures
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional, Union

import numpy as np
import pandas as pd
import pygeoops
import shapely
import shapely.geometry.base

import geofileops as gfo
from geofileops import GeometryType, PrimitiveType, fileops
from geofileops._compat import SPATIALITE_GTE_51
from geofileops.fileops import _append_to_nolock
from geofileops.helpers import _parameter_helper
from geofileops.helpers._configoptions_helper import ConfigOptions
from geofileops.util import (
    _general_util,
    _geofileinfo,
    _geoops_gpd,
    _io_util,
    _ogr_sql_util,
    _ogr_util,
    _processing_util,
    _sqlite_util,
)
from geofileops.util._geofileinfo import GeofileInfo

logger = logging.getLogger(__name__)

# -----------------------
# Operations on one layer
# -----------------------


def buffer(
    input_path: Path,
    output_path: Path,
    distance: float,
    quadrantsegments: int = 5,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[list[str]] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = False,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    # Init + prepare sql template for this operation
    # ----------------------------------------------
    operation = f"ST_Buffer({{geometrycolumn}}, {distance}, {quadrantsegments})"

    # For a double sided buffer, a negative buffer is only relevant for polygon types,
    # so only keep polygon results.
    # Negative buffer creates invalid stuff, so use collectionextract to keep only
    # polygons.
    if distance < 0:
        operation = f"ST_CollectionExtract({operation}, 3)"

    # Create the final template
    sql_template = f"""
        SELECT {operation} AS {{geometrycolumn}}
              {{columns_to_select_str}}
            FROM "{{input_layer}}" layer
            WHERE 1=1
              {{batch_filter}}
    """

    # Buffer operation always results in polygons...
    if explodecollections:
        force_output_geometrytype = GeometryType.POLYGON
    else:
        force_output_geometrytype = GeometryType.MULTIPOLYGON

    # Go!
    # ---
    return _single_layer_vector_operation(
        input_path=input_path,
        output_path=output_path,
        sql_template=sql_template,
        geom_selected=True,
        operation_name="buffer",
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        force_output_geometrytype=force_output_geometrytype,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms,
        where_post=where_post,
        sql_dialect="SQLITE",
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def convexhull(
    input_path: Path,
    output_path: Path,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[list[str]] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = False,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    # Init + prepare sql template for this operation
    # ----------------------------------------------
    input_layerinfo = gfo.get_layerinfo(input_path, input_layer)
    sql_template = """
        SELECT ST_ConvexHull({geometrycolumn}) AS {geometrycolumn}
                {columns_to_select_str}
          FROM "{input_layer}" layer
         WHERE 1=1
           {batch_filter}
    """

    # Go!
    # ---
    # Output geometry type same as input geometry type
    return _single_layer_vector_operation(
        input_path=input_path,
        output_path=output_path,
        sql_template=sql_template,
        geom_selected=True,
        operation_name="convexhull",
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        force_output_geometrytype=input_layerinfo.geometrytype,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms,
        where_post=where_post,
        sql_dialect="SQLITE",
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def delete_duplicate_geometries(
    input_path: Path,
    output_path: Path,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[list[str]] = None,
    explodecollections: bool = False,
    keep_empty_geoms: bool = False,
    where_post: Optional[str] = None,
    force: bool = False,
):
    # The query as written doesn't give correct results when parallelized,
    # but it isn't useful to do it for this operation.
    sql_template = """
        SELECT {geometrycolumn} AS {geometrycolumn}
              {columns_to_select_str}
          FROM "{input_layer}" layer
         WHERE layer.rowid IN (
                SELECT MIN(layer_sub.rowid) AS rowid_to_keep
                  FROM "{input_layer}" layer_sub
                 GROUP BY layer_sub.{geometrycolumn}
            )
    """

    # Go!
    input_layer_info = gfo.get_layerinfo(input_path, input_layer)
    return _single_layer_vector_operation(
        input_path=input_path,
        output_path=output_path,
        sql_template=sql_template,
        geom_selected=True,
        operation_name="delete_duplicate_geometries",
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        force_output_geometrytype=input_layer_info.geometrytype,
        gridsize=0.0,
        keep_empty_geoms=keep_empty_geoms,
        where_post=where_post,
        sql_dialect="SQLITE",
        nb_parallel=1,
        batchsize=-1,
        force=force,
    )


def isvalid(
    input_path: Path,
    output_path: Path,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[list[str]] = None,
    explodecollections: bool = False,
    validate_attribute_data: bool = False,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
) -> bool:
    # Prepare sql template for this operation
    sql_template = """
        SELECT ST_IsValidDetail({geometrycolumn}) AS {geometrycolumn}
              ,ST_IsValid({geometrycolumn}) AS isvalid
              ,ST_IsValidReason({geometrycolumn}) AS isvalidreason
              {columns_to_select_str}
          FROM "{input_layer}" layer
         WHERE ST_IsValid({geometrycolumn}) <> 1
           {batch_filter}
    """

    _single_layer_vector_operation(
        input_path=input_path,
        output_path=output_path,
        sql_template=sql_template,
        geom_selected=True,
        operation_name="isvalid",
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        force_output_geometrytype=GeometryType.POINT,
        gridsize=0.0,
        keep_empty_geoms=False,
        where_post=None,
        sql_dialect="SQLITE",
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )

    # Check the number of invalid files
    nb_invalid_geoms = 0
    if output_path.exists():
        nb_invalid_geoms = gfo.get_layerinfo(output_path).featurecount
        if nb_invalid_geoms == 0:
            # Empty result, so everything was valid: remove output file
            gfo.remove(output_path)

    # If output is sqlite based, check if all data can be read
    logger = logging.getLogger("geofileops.isvalid")
    if validate_attribute_data:
        try:
            input_info = _geofileinfo.get_geofileinfo(input_path)
            if input_info.is_spatialite_based:
                _sqlite_util.test_data_integrity(path=input_path)
                logger.debug("test_data_integrity was succesfull")
        except Exception:
            logger.exception(
                f"nb_invalid_geoms: {nb_invalid_geoms} + some attributes "
                "could not be read!"
            )
            return False

    if nb_invalid_geoms > 0:
        logger.info(f"Found {nb_invalid_geoms} invalid geoms in {output_path}")
        return False

    # Nothing invalid found
    return True


def makevalid(
    input_path: Path,
    output_path: Path,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[list[str]] = None,
    explodecollections: bool = False,
    force_output_geometrytype: Union[str, None, GeometryType] = None,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = False,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    # If output file exists already, either clean up or return...
    operation_name = "makevalid"
    logger = logging.getLogger(f"geofileops.{operation_name}")
    if not force and output_path.exists():
        logger.info(f"Stop, output exists already {output_path}")
        return

    # Determine output_geometrytype + make it multitype if it wasn't specified.
    # Otherwise makevalid can result in column type 'GEOMETRY'/'UNKNOWN(ANY)'.
    if force_output_geometrytype is None:
        input_layerinfo = gfo.get_layerinfo(input_path, input_layer)
        force_output_geometrytype = input_layerinfo.geometrytype
        if not explodecollections:
            assert isinstance(force_output_geometrytype, GeometryType)
            force_output_geometrytype = force_output_geometrytype.to_multitype
    if isinstance(force_output_geometrytype, str):
        force_output_geometrytype = GeometryType[force_output_geometrytype]
    assert force_output_geometrytype is not None

    # Init + prepare sql template for this operation
    # ----------------------------------------------
    # Only apply makevalid if the geometry is truly invalid, this is faster.
    # GEOSMakeValid crashes with EMPTY input, so check this first.
    if SPATIALITE_GTE_51:
        operation = """
            IIF({geometrycolumn} IS NULL OR ST_IsEmpty({geometrycolumn}) <> 0,
                NULL,
                IIF(ST_IsValid({geometrycolumn}) = 1,
                    {geometrycolumn},
                    GEOSMakeValid({geometrycolumn}, 0)
               )
            )"""
    else:
        # Prepare sql template for this operation
        operation = """
            IIF(ST_IsValid({geometrycolumn}) = 1,
                {geometrycolumn},
                ST_MakeValid({geometrycolumn})
            )"""

        # If we want a specific geometrytype, only extract the relevant type
        if force_output_geometrytype is not GeometryType.GEOMETRYCOLLECTION:
            primitivetypeid = force_output_geometrytype.to_primitivetype.value
            operation = f"ST_CollectionExtract({operation}, {primitivetypeid})"

    # Now we can prepare the entire statement
    sql_template = f"""
        SELECT {operation} AS {{geometrycolumn}}
              {{columns_to_select_str}}
          FROM "{{input_layer}}" layer
         WHERE 1=1
           {{batch_filter}}
    """

    _single_layer_vector_operation(
        input_path=input_path,
        output_path=output_path,
        sql_template=sql_template,
        geom_selected=True,
        operation_name=operation_name,
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        force_output_geometrytype=force_output_geometrytype,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms,
        where_post=where_post,
        sql_dialect="SQLITE",
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def select(
    input_path: Path,
    output_path: Path,
    sql_stmt: str,
    sql_dialect: Optional[Literal["SQLITE", "OGRSQL"]] = "SQLITE",
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[list[str]] = None,
    explodecollections: bool = False,
    force_output_geometrytype: Optional[GeometryType] = None,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = False,
    nb_parallel: int = 1,
    batchsize: int = -1,
    force: bool = False,
    operation_prefix: str = "",
):
    # Check if output exists already here, to avoid to much logging to be written
    logger = logging.getLogger(f"geofileops.{operation_prefix}select")
    if _io_util.output_exists(path=output_path, remove_if_exists=force):
        return
    logger.debug(f"  -> select to execute:\n{sql_stmt}")

    # If no output geometrytype is specified, use the geometrytype of the input layer
    if force_output_geometrytype is None:
        force_output_geometrytype = gfo.get_layerinfo(
            input_path, input_layer, raise_on_nogeom=False
        ).geometrytype
        if force_output_geometrytype is not None and not explodecollections:
            force_output_geometrytype = force_output_geometrytype.to_multitype

        logger.info(
            "No force_output_geometrytype specified, so defaults to input "
            f"layer geometrytype: {force_output_geometrytype}"
        )

    # Go!
    return _single_layer_vector_operation(
        input_path=input_path,
        output_path=output_path,
        sql_template=sql_stmt,
        geom_selected=None,
        operation_name=f"{operation_prefix}select",
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        force_output_geometrytype=force_output_geometrytype,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms,
        where_post=None,
        sql_dialect=sql_dialect,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def simplify(
    input_path: Path,
    output_path: Path,
    tolerance: float,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[list[str]] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = False,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    # Init + prepare sql template for this operation
    # ----------------------------------------------
    sql_template = f"""
        SELECT ST_SimplifyPreserveTopology({{geometrycolumn}}, {tolerance}
               ) AS {{geometrycolumn}}
              {{columns_to_select_str}}
            FROM "{{input_layer}}" layer
            WHERE 1=1
            {{batch_filter}}
    """

    # Output geometry type same as input geometry type
    input_layer_info = gfo.get_layerinfo(input_path, input_layer)
    return _single_layer_vector_operation(
        input_path=input_path,
        output_path=output_path,
        sql_template=sql_template,
        geom_selected=True,
        operation_name="simplify",
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        force_output_geometrytype=input_layer_info.geometrytype,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms,
        where_post=where_post,
        sql_dialect="SQLITE",
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def _single_layer_vector_operation(
    input_path: Path,
    output_path: Path,
    sql_template: str,
    geom_selected: Optional[bool],
    operation_name: str,
    input_layer: Optional[str],
    output_layer: Optional[str],
    columns: Optional[list[str]],
    explodecollections: bool,
    force_output_geometrytype: Optional[GeometryType],
    gridsize: float,
    keep_empty_geoms: bool,
    where_post: Optional[str],
    sql_dialect: Optional[Literal["SQLITE", "OGRSQL"]],
    nb_parallel: int,
    batchsize: int,
    force: bool,
):
    """Execute a sql query template on the input layer.

    Args:
        input_path (Path): _description_
        output_path (Path): _description_
        sql_template (str): _description_
        geom_selected (Optional[bool]): True if a geometry column is selected in the
            sql_template. False if no geometry column is selected. None if it is
            unclear.
        operation_name (str): _description_
        input_layer (Optional[str]): _description_
        output_layer (Optional[str]): _description_
        columns (Optional[List[str]]): _description_
        explodecollections (bool): _description_
        force_output_geometrytype (Optional[GeometryType]): _description_
        gridsize (float): _description_
        keep_empty_geoms (bool): _description_
        where_post (Optional[str]): _description_
        sql_dialect (Optional[Literal["SQLITE", "OGRSQL"]]): _description_
        nb_parallel (int): _description_
        batchsize (int): _description_
        force (bool): _description_

    Raises:
        ValueError: _description_
        ValueError: _description_
        ValueError: _description_
        Exception: _description_
    """
    # Init
    start_time = datetime.now()
    logger = logging.getLogger(f"geofileops.{operation_name}")

    # Check/clean input parameters...
    if not input_path.exists():
        raise ValueError(f"{operation_name}: input_path doesn't exist: {input_path}")
    if input_path == output_path:
        raise ValueError(f"{operation_name}: output_path must not equal input_path")
    if where_post is not None and where_post == "":
        where_post = None
    if isinstance(columns, str):
        # If a string is passed, convert to list
        columns = [columns]

    # Check/get layer names
    if input_layer is None:
        input_layer = gfo.get_only_layer(input_path)
    if output_layer is None:
        output_layer = gfo.get_default_layer(output_path)

    # If output file exists already, either clean up or return...
    if _io_util.output_exists(path=output_path, remove_if_exists=force):
        return

    # Determine if fid can be preserved
    preserve_fid = False
    if (
        not explodecollections
        and _geofileinfo.get_geofileinfo(input_path).is_spatialite_based
        and _geofileinfo.get_geofileinfo(output_path).is_spatialite_based
    ):
        preserve_fid = True

    # Calculate
    tempdir = _io_util.create_tempdir(f"geofileops/{operation_name.replace(' ', '_')}")
    try:
        # If gridsize != 0.0 or if geom_selected is None we need an sqlite file to be
        # able to determine the columns later on.
        if gridsize != 0.0 or geom_selected is None:
            input_path, input_layer, _, _ = _convert_to_spatialite_based(
                input1_path=input_path, input1_layer=input_layer, tempdir=tempdir
            )

        processing_params = _prepare_processing_params(
            input1_path=input_path,
            input1_layer=input_layer,
            input1_layer_alias="layer",
            tempdir=tempdir,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
        )
        # If None is returned, just stop.
        if processing_params is None or processing_params.batches is None:
            return

        # Get layer info of the input layer to use
        input_layerinfo = gfo.get_layerinfo(
            input_path, input_layer, raise_on_nogeom=False
        )

        # If multiple batches, there should be a batch_filter placeholder sql_template
        nb_batches = len(processing_params.batches)
        if nb_batches > 1:
            placeholders = [
                name for _, name, _, _ in string.Formatter().parse(sql_template) if name
            ]
            if "batch_filter" not in placeholders:
                raise ValueError(
                    "Number batches > 1 requires a batch_filter placeholder in "
                    f"sql_template {sql_template}"
                )

        # Format column string for use in select
        column_formatter = _ogr_sql_util.ColumnFormatter(
            columns_asked=columns,
            columns_in_layer=input_layerinfo.columns,
            fid_column=input_layerinfo.fid_column,
        )

        # Fill out template already for known info
        columns_to_select_str = column_formatter.prefixed_aliased()
        if input_layerinfo.fid_column != "":
            # If there is an fid column defined, select that column as well so the fids
            # can be retained in the output if possible.
            columns_to_select_str = (
                f",{input_layerinfo.fid_column}{columns_to_select_str}"
            )
        sql_template = sql_template.format(
            geometrycolumn=input_layerinfo.geometrycolumn,
            columns_to_select_str=columns_to_select_str,
            input_layer=input_layer,
            batch_filter="{batch_filter}",
        )

        #  to Check if a geometry column is available + selected
        if geom_selected is None:
            if input_layerinfo.geometrycolumn is None:
                # There is no geometry column in the source file
                geom_selected = False
            else:
                # There is a geometry column in the source file, check if it is selected
                sql_tmp = sql_template.format(batch_filter="")
                cols = _sqlite_util.get_columns(
                    sql_stmt=sql_tmp,
                    input_databases={"input_db": input_path},
                )
                geom_selected = input_layerinfo.geometrycolumn in cols

        # Fill out/add to the sql_template what is already possible
        # ---------------------------------------------------------

        # Add application of gridsize around sql_template if specified
        if geom_selected and gridsize != 0.0:
            assert force_output_geometrytype is not None
            gridsize_op = _format_apply_gridsize_operation(
                geometrycolumn=f"sub_gridsize.{input_layerinfo.geometrycolumn}",
                gridsize=gridsize,
                force_output_geometrytype=force_output_geometrytype,
            )

            # Get all columns of the sql_template
            sql_tmp = sql_template.format(batch_filter="")
            cols = _sqlite_util.get_columns(
                sql_stmt=sql_tmp, input_databases={"input_db": input_path}
            )
            attributes = [
                col for col in cols if col.lower() != input_layerinfo.geometrycolumn
            ]
            columns_to_select = _ogr_sql_util.columns_quoted(attributes)
            sql_template = f"""
                SELECT {gridsize_op} AS {input_layerinfo.geometrycolumn}
                      {columns_to_select}
                  FROM
                    ( {sql_template}
                       LIMIT -1 OFFSET 0
                    ) sub_gridsize
            """

        # If empty/null geometries don't need to be kept, filter them away
        if geom_selected and not keep_empty_geoms:
            sql_template = f"""
                SELECT * FROM
                    ( {sql_template}
                       LIMIT -1 OFFSET 0
                    )
                 WHERE {input_layerinfo.geometrycolumn} IS NOT NULL
            """

        # Prepare/apply where_post parameter
        if where_post is not None and not explodecollections:
            # explodecollections is not True, so we can add where_post to sql_stmt.
            # If explodecollections would be True, we need to wait to apply the
            # where_post till after explodecollections is applied, so when appending the
            # partial results to the output file.
            sql_template = f"""
                SELECT * FROM
                    ( {sql_template}
                       LIMIT -1 OFFSET 0
                    )
                    WHERE {where_post}
            """
            # where_post has been applied already so set to None.
            where_post = None

        # When null geometries are being kept, we need to make sure the geom in the
        # first row is not NULL because of a bug in gdal, so add ORDER BY as last step.
        #   -> https://github.com/geofileops/geofileops/issues/308
        if geom_selected and keep_empty_geoms:
            sql_template = f"""
                SELECT * FROM
                    ( {sql_template}
                       LIMIT -1 OFFSET 0
                    )
                 ORDER BY {input_layerinfo.geometrycolumn} IS NULL
            """

        # Fill out geometrycolumn again as there might have popped up extra ones
        sql_template = sql_template.format(
            geometrycolumn=input_layerinfo.geometrycolumn,
            batch_filter="{batch_filter}",
        )

        logger.info(
            f"Start processing ({processing_params.nb_parallel} "
            f"parallel workers, batch size: {processing_params.batchsize})"
        )

        # Prepare temp output filename
        tmp_output_path = tempdir / output_path.name

        # Processing in threads is 2x faster for small datasets (on Windows)
        calculate_in_threads = True if input_layerinfo.featurecount <= 100 else False
        with _processing_util.PooledExecutorFactory(
            threadpool=calculate_in_threads,
            max_workers=processing_params.nb_parallel,
            initializer=_processing_util.initialize_worker(),
        ) as calculate_pool:
            batches: dict[int, dict] = {}
            future_to_batch_id = {}
            for batch_id in processing_params.batches:
                batches[batch_id] = {}
                batches[batch_id]["layer"] = output_layer

                tmp_partial_output_path = (
                    tempdir / f"{output_path.stem}_{batch_id}.gpkg"
                )
                batches[batch_id]["tmp_partial_output_path"] = tmp_partial_output_path

                # Fill out sql_template
                sql_stmt = sql_template.format(
                    batch_filter=processing_params.batches[batch_id]["batch_filter"]
                )
                batches[batch_id]["sql_stmt"] = sql_stmt

                # If there is only one batch, it is faster to create the spatial index
                # immediately. Otherwise no index needed, because partial files still
                # need to be merged to one file later on.
                create_spatial_index = (
                    GeofileInfo(tmp_partial_output_path).default_spatial_index
                    if nb_batches == 1
                    else False
                )
                translate_info = _ogr_util.VectorTranslateInfo(
                    input_path=processing_params.batches[batch_id]["input1_path"],
                    output_path=tmp_partial_output_path,
                    output_layer=output_layer,
                    sql_stmt=sql_stmt,
                    sql_dialect=sql_dialect,
                    explodecollections=explodecollections,
                    force_output_geometrytype=force_output_geometrytype,
                    options={"LAYER_CREATION.SPATIAL_INDEX": create_spatial_index},
                    preserve_fid=preserve_fid,
                )
                future = calculate_pool.submit(
                    _ogr_util.vector_translate_by_info, info=translate_info
                )
                future_to_batch_id[future] = batch_id

            # Loop till all parallel processes are ready, but process each one
            # that is ready already.
            # Calculating can be done in parallel, but only one process can write to
            # the same file at the time.
            nb_done = 0
            _general_util.report_progress(
                start_time,
                nb_done,
                nb_todo=nb_batches,
                operation=operation_name,
                nb_parallel=processing_params.nb_parallel,
            )
            for future in futures.as_completed(future_to_batch_id):
                try:
                    _ = future.result()
                except Exception as ex:
                    batch_id = future_to_batch_id[future]
                    error = str(ex).partition("\n")[0]
                    message = f"Error <{error}> executing {batches[batch_id]}"
                    logger.exception(message)
                    raise Exception(message) from ex

                # Start copy of the result to a common file
                # Remark: give higher priority, because this is the slowest factor
                batch_id = future_to_batch_id[future]
                tmp_partial_output_path = batches[batch_id]["tmp_partial_output_path"]
                nb_done += 1

                # Normally all partial files should exist, but to be sure.
                if not tmp_partial_output_path.exists():
                    logger.warning(f"Result file {tmp_partial_output_path} not found")
                    continue

                if (
                    nb_batches == 1
                    and tmp_partial_output_path.suffix == tmp_output_path.suffix
                    and where_post is None
                ):
                    # If there is only one batch
                    #   + partial file is already is correct file format
                    #   + no more where_post needs to be applied
                    # -> just rename partial file, because it is already OK.
                    gfo.move(tmp_partial_output_path, tmp_output_path)
                else:
                    # Append partial file to full destination file
                    if where_post is not None:
                        info = gfo.get_layerinfo(tmp_partial_output_path, output_layer)
                        where_post = where_post.format(
                            geometrycolumn=info.geometrycolumn
                        )
                    fileops._append_to_nolock(
                        src=tmp_partial_output_path,
                        dst=tmp_output_path,
                        explodecollections=explodecollections,
                        force_output_geometrytype=force_output_geometrytype,
                        where=where_post,
                        create_spatial_index=False,
                        preserve_fid=preserve_fid,
                    )
                    gfo.remove(tmp_partial_output_path)

                # Log the progress and prediction speed
                _general_util.report_progress(
                    start_time,
                    nb_done,
                    nb_todo=nb_batches,
                    operation=operation_name,
                    nb_parallel=processing_params.nb_parallel,
                )

        # Round up and clean up
        # Now create spatial index and move to output location
        if tmp_output_path.exists():
            if (
                GeofileInfo(tmp_output_path).default_spatial_index
                and gfo.get_layerinfo(
                    path=tmp_output_path, layer=output_layer, raise_on_nogeom=False
                ).geometrycolumn
                is not None
            ):
                gfo.create_spatial_index(
                    path=tmp_output_path, layer=output_layer, exist_ok=True
                )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            gfo.move(tmp_output_path, output_path)
        elif (
            gfo.get_driver(tmp_output_path) == "ESRI Shapefile"
            and tmp_output_path.with_suffix(".dbf").exists()
        ):
            # If the output shapefile doesn't have a geometry column, the .shp file
            # doesn't exist but the .dbf does
            output_path.parent.mkdir(parents=True, exist_ok=True)
            gfo.move(
                tmp_output_path.with_suffix(".dbf"), output_path.with_suffix(".dbf")
            )
        else:
            logger.debug("Result was empty!")

    finally:
        # Clean tmp dir
        if ConfigOptions.remove_temp_files:
            shutil.rmtree(tempdir, ignore_errors=True)

    logger.info(f"Ready, took {datetime.now()-start_time}")


# ------------------------
# Operations on two layers
# ------------------------


def clip(
    input_path: Path,
    clip_path: Path,
    output_path: Path,
    input_layer: Optional[str] = None,
    input_columns: Optional[list[str]] = None,
    clip_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
    input_columns_prefix: str = "",
    output_with_spatial_index: Optional[bool] = None,
):
    # Init
    # In the query, important to only extract the geometry types that are expected
    input_layer_info = gfo.get_layerinfo(input_path, input_layer)
    primitivetypeid = input_layer_info.geometrytype.to_primitivetype.value

    # If explodecollections is False and the input type is not point, force the output
    # type to multi, because clip can cause eg. polygons to be split to multipolygons.
    force_output_geometrytype = input_layer_info.geometrytype
    if not explodecollections and force_output_geometrytype is not GeometryType.POINT:
        force_output_geometrytype = force_output_geometrytype.to_multitype

    # Prepare sql template for this operation
    # Remarks:
    # - ST_intersection(geometry , NULL) gives NULL as result! -> hence the CASE
    # - use of the with instead of an inline view is a lot faster
    # - use "LIMIT -1 OFFSET 0" to avoid the subquery flattening. Flattening e.g.
    #   "geom IS NOT NULL" leads to geom operation to be calculated twice!
    # - WHERE geom IS NOT NULL to avoid rows with a NULL geom, they give issues in
    #   later operations.
    input1_layer_rtree = "rtree_{input1_layer}_{input1_geometrycolumn}"
    input2_layer_rtree = "rtree_{input2_layer}_{input2_geometrycolumn}"
    sql_template = f"""
        SELECT * FROM
          ( WITH layer2_unioned AS (
              SELECT layer1.rowid AS layer1_rowid
                    ,ST_union(layer2.{{input2_geometrycolumn}}) AS geom
                FROM {{input1_databasename}}."{{input1_layer}}" layer1
                JOIN {{input1_databasename}}."{input1_layer_rtree}" layer1tree
                  ON layer1.fid = layer1tree.id
                JOIN {{input2_databasename}}."{{input2_layer}}" layer2
                JOIN {{input2_databasename}}."{input2_layer_rtree}" layer2tree
                  ON layer2.fid = layer2tree.id
               WHERE 1=1
                 {{batch_filter}}
                 AND layer1tree.minx <= layer2tree.maxx
                 AND layer1tree.maxx >= layer2tree.minx
                 AND layer1tree.miny <= layer2tree.maxy
                 AND layer1tree.maxy >= layer2tree.miny
                 AND ST_Intersects(
                        layer1.{{input1_geometrycolumn}},
                        layer2.{{input2_geometrycolumn}}) = 1
                 --AND ST_Touches(
                 --       layer1.{{input1_geometrycolumn}},
                 --       layer2.{{input2_geometrycolumn}}) = 0
               GROUP BY layer1.rowid
               LIMIT -1 OFFSET 0
            )
            SELECT CASE WHEN layer2_unioned.geom IS NULL THEN NULL
                        ELSE ST_CollectionExtract(
                               ST_intersection(layer1.{{input1_geometrycolumn}},
                                               layer2_unioned.geom), {primitivetypeid})
                   END as geom
                  {{layer1_columns_prefix_alias_str}}
              FROM {{input1_databasename}}."{{input1_layer}}" layer1
              JOIN layer2_unioned ON layer1.rowid = layer2_unioned.layer1_rowid
             WHERE 1=1
               {{batch_filter}}
             LIMIT -1 OFFSET 0
          )
         WHERE geom IS NOT NULL
    """

    # Go!
    return _two_layer_vector_operation(
        input1_path=input_path,
        input2_path=clip_path,
        output_path=output_path,
        sql_template=sql_template,
        operation_name="clip",
        input1_layer=input_layer,
        input1_columns=input_columns,
        input1_columns_prefix=input_columns_prefix,
        input2_layer=clip_layer,
        input2_columns=None,
        input2_columns_prefix="",
        output_layer=output_layer,
        explodecollections=explodecollections,
        gridsize=gridsize,
        where_post=where_post,
        force_output_geometrytype=force_output_geometrytype,
        output_with_spatial_index=output_with_spatial_index,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def difference(  # noqa: D417
    input1_path: Path,
    input2_path: Path,
    output_path: Path,
    overlay_self: bool,
    input1_layer: Optional[str] = None,
    input1_columns: Optional[list[str]] = None,
    input2_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 2000,
    force: bool = False,
    input_columns_prefix: str = "",
    output_with_spatial_index: Optional[bool] = None,
    operation_prefix: str = "",
    input1_subdivided_path: Union[Path, None] = None,
    input2_subdivided_path: Union[Path, None] = None,
):
    """Calculate the difference between two layers.

    Only arguments specific to the internal difference operation are documented here.
    For the other arguments, check out the corresponding function in geoops.py.

    Args:
        input_columns_prefix (str): Prefix to add to the columns of the input1 layer.
        output_with_spatial_index (Optional[bool], optional): Controls whether the
            output file is created with a spatial index. True to create one, False not
            to create one, None to apply the GDAL standard behaviour. Defaults to None.
        operation_prefix (str, optional): When this function is called from a compounded
            spatial operation, the name of this operation can be specified to show
            clearer progress messages,... Defaults to "".
        input1_subdivided_path (Path | None, optional): If a Path to a file,
            the subdivided version of input1 can be found here. If a Path to root
            (Path("/")), input1 was tested, but it does not need subdividing. If None,
            input1 still needs to be subdivided. Defaults to None.
        input2_subdivided_path (Path | None, optional): If a Path to a file,
            the subdivided version of input1 can be found here. If a Path to root
            (Path("/")), input2 was tested, but it does not need subdividing. If None,
            input2 still needs to be subdivided. Defaults to None.
    """
    # Because there might be extra preparation of the input2 layer before going ahead
    # with the real calculation, do some additional init + checks here...
    start_time = datetime.now()
    if subdivide_coords < 0:
        raise ValueError("subdivide_coords < 0 is not allowed")

    operation_name = f"{operation_prefix}difference"
    logger = logging.getLogger(f"geofileops.{operation_name}")

    input1_layer, input2_layer, output_layer = _validate_params(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        input1_layer=input1_layer,
        input2_layer=input2_layer,
        output_layer=output_layer,
        operation_name=operation_name,
    )
    if _io_util.output_exists(path=output_path, remove_if_exists=force):
        return

    input_layer_info = gfo.get_layerinfo(input1_path, input1_layer)
    primitivetypeid = input_layer_info.geometrytype.to_primitivetype.value

    force_output_geometrytype = input_layer_info.geometrytype
    if explodecollections:
        force_output_geometrytype = force_output_geometrytype.to_singletype
    elif force_output_geometrytype is not GeometryType.POINT:
        # If explodecollections is False and the input type is not point, force the
        # output type to multi, because difference can cause eg. polygons to be split to
        # multipolygons.
        force_output_geometrytype = force_output_geometrytype.to_multitype

    # Subdivide the input layers speeds up further processing if they are complex.
    tempdir = _io_util.create_tempdir(f"geofileops/{operation_name}")

    if input1_subdivided_path is None:
        # input1_subdivided_path is None: try to subdivide.
        input1_subdivided_path = _subdivide_layer(
            path=input1_path,
            layer=input1_layer,
            output_path=tempdir / "subdivided/input1_layer.gpkg",
            subdivide_coords=subdivide_coords,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix=f"{operation_name}/",
        )
    elif input1_subdivided_path == Path("/"):
        # input1_subdivided_path is Path("/"): input1 doesn't contain complex geoms.
        input1_subdivided_path = None

    where_clause_self = "1=1"
    if overlay_self:
        # If we are doing a self overlay
        #   - input1 = input2, so if needed, it has already been subdivided
        #   - we need to filter out rows with the same rowid
        if input1_subdivided_path is None:
            where_clause_self = "layer1.rowid <> layer2_sub.rowid"
        else:
            # Filter out the same rowids using the original fids!
            where_clause_self = "layer1_subdiv.fid_1 <> layer2_sub.fid_1"

        # For overlay self, both subdivided layers are equal
        input2_subdivided_path = input1_subdivided_path

    elif input2_subdivided_path is None:
        # input2_subdivided_path is None: try to subdivide.
        input2_subdivided_path = _subdivide_layer(
            path=input2_path,
            layer=input2_layer,
            output_path=tempdir / "subdivided/input2_layer.gpkg",
            subdivide_coords=subdivide_coords,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix=f"{operation_name}/",
        )

    elif input2_subdivided_path == Path("/"):
        # Input2 was tested previously, but it does not need subdividing
        input2_subdivided_path = None

    # If the input2 layer was subdivided, it can just be used as input2_path
    if input2_subdivided_path is not None:
        input2_path = input2_subdivided_path

    # Prepare sql template for this operation
    # - WHERE geom IS NOT NULL to avoid rows with a NULL geom, they give issues in
    #   later operations
    # - use "LIMIT -1 OFFSET 0" to avoid the subquery flattening. Flattening e.g.
    #   "geom IS NOT NULL" leads to GFO_Difference_Collection calculated double!
    # - Calculate difference in correlated subquery in SELECT clause reduces memory
    #   usage by a factor 10 compared with a WITH with GROUP BY. The WITH with a GROUP
    #   BY on layer1.rowid was a few % faster, but this is not worth it. E.g. for one
    #   test file 4-7 GB per process versus 70-700 MB). For another: crash.
    # - ST_Touches is very slow when the data contains huge geoms -> only ST_intersects
    # - ST_difference(geometry , NULL) gives NULL as result. This is not the wanted end
    #   result: it should be the original geometry. Hence, only if the second parameter
    #   is not NULL, the difference should be calculated. Otherwise return geometry.
    #   second parameter would be NULL and if so, return the first parameter.
    # - Check if the result of the difference is empty (NULL) using IFNULL, and if this
    #   is the case set to 'DIFF_EMPTY'. This way we can make the distinction whether
    #   the subquery is finding a row (no match with spatial index) or if the difference
    #   results in an empty/NULL geometry.
    # - Old comment: tried to return EMPTY GEOMETRY from GFO_Difference_Collection, but
    #   it didn't work to use spatialite's ST_IsEmpty(geom) = 0 to filter on this,
    #   probably because ST_GeomFromWKB doesn't seem to support empty polygons.
    input1_layer_rtree = "rtree_{input1_layer}_{input1_geometrycolumn}"
    input2_layer_rtree = "rtree_{input2_layer}_{input2_geometrycolumn}"
    input1_subdiv_layer_rtree = "rtree_{input1_layer}_{input1_subdiv_geometrycolumn}"

    if input1_subdivided_path is None:
        # The input layer was not subdivided
        sql_template = f"""
            SELECT * FROM (
              SELECT IFNULL(
                       ( SELECT IFNULL(
                                   IIF(COUNT(layer2_sub.rowid) = 0,
                                       layer1.{{input1_geometrycolumn}},
                                       ST_CollectionExtract(
                                          ST_difference(
                                             layer1.{{input1_geometrycolumn}},
                                             ST_Union(layer2_sub.{{input2_geometrycolumn}})
                                          ),
                                          {primitivetypeid}
                                       )
                                   ),
                                   'DIFF_EMPTY'
                                ) AS diff_geom
                           FROM {{input1_databasename}}."{input1_layer_rtree}" layer1tree
                           JOIN {{input2_databasename}}."{{input2_layer}}" layer2_sub
                           JOIN {{input2_databasename}}."{input2_layer_rtree}" layer2tree
                             ON layer2_sub.rowid = layer2tree.id
                          WHERE {where_clause_self}
                            AND layer1tree.id = layer1.rowid
                            AND layer1tree.minx <= layer2tree.maxx
                            AND layer1tree.maxx >= layer2tree.minx
                            AND layer1tree.miny <= layer2tree.maxy
                            AND layer1tree.maxy >= layer2tree.miny
                            AND ST_intersects(layer1.{{input1_geometrycolumn}},
                                              layer2_sub.{{input2_geometrycolumn}}) = 1
                          LIMIT -1 OFFSET 0
                       ),
                       layer1.{{input1_geometrycolumn}}
                     ) AS geom
                    {{layer1_columns_prefix_alias_str}}
                    {{layer2_columns_prefix_alias_null_str}}
                FROM {{input1_databasename}}."{{input1_layer}}" layer1
               WHERE 1=1
                 {{batch_filter}}
               LIMIT -1 OFFSET 0
              )
             WHERE geom IS NOT NULL
               AND geom <> 'DIFF_EMPTY'
               AND ST_IsEmpty(geom) = 0
        """  # noqa: E501
    else:
        # The input layer was subdivided, so the result needs to be unioned and joined
        # with the original input layer to get the original columns.
        sql_template = f"""
            SELECT differenced.geom
                  {{layer1_columns_prefix_alias_str}}
                  {{layer2_columns_prefix_alias_null_str}}
              FROM (
                SELECT layer1_fid_orig, ST_Union(geom) AS geom FROM (
                  SELECT fid_1 AS layer1_fid_orig
                        ,IFNULL(
                           ( SELECT IFNULL(
                                       IIF(COUNT(layer2_sub.rowid) = 0,
                                           layer1_subdiv.{{input1_subdiv_geometrycolumn}},
                                           ST_CollectionExtract(
                                              ST_difference(
                                                 layer1_subdiv.{{input1_subdiv_geometrycolumn}},
                                                 ST_Union(layer2_sub.{{input2_geometrycolumn}})
                                              ),
                                              {primitivetypeid}
                                           )
                                       ),
                                       'DIFF_EMPTY'
                                    ) AS diff_geom
                               FROM {{input1_subdiv_databasename}}."{input1_subdiv_layer_rtree}" layer1tree
                               JOIN {{input2_databasename}}."{{input2_layer}}" layer2_sub
                               JOIN {{input2_databasename}}."{input2_layer_rtree}" layer2tree
                                 ON layer2_sub.rowid = layer2tree.id
                              WHERE {where_clause_self}
                                AND layer1tree.id = layer1_subdiv.rowid
                                AND layer1tree.minx <= layer2tree.maxx
                                AND layer1tree.maxx >= layer2tree.minx
                                AND layer1tree.miny <= layer2tree.maxy
                                AND layer1tree.maxy >= layer2tree.miny
                                AND ST_intersects(layer1_subdiv.{{input1_subdiv_geometrycolumn}},
                                                  layer2_sub.{{input2_geometrycolumn}}) = 1
                              LIMIT -1 OFFSET 0
                           ),
                           layer1_subdiv.{{input1_subdiv_geometrycolumn}}
                         ) AS geom
                    FROM {{input1_subdiv_databasename}}."{{input1_layer}}" layer1_subdiv
                   WHERE 1=1
                     {{batch_filter}}
                   LIMIT -1 OFFSET 0
                  )
                 WHERE geom IS NOT NULL
                   AND geom <> 'DIFF_EMPTY'
                   AND ST_IsEmpty(geom) = 0
                 GROUP BY layer1_fid_orig
                ) differenced
                JOIN {{input1_databasename}}."{{input1_layer}}" layer1
                     ON layer1.fid = differenced.layer1_fid_orig
        """  # noqa: E501

    # Go!
    _two_layer_vector_operation(
        input1_path=input1_path,
        input1_subdivided_path=input1_subdivided_path,
        input2_path=input2_path,
        output_path=output_path,
        sql_template=sql_template,
        operation_name=operation_name,
        input1_layer=input1_layer,
        input1_columns=input1_columns,
        input1_columns_prefix=input_columns_prefix,
        input2_layer=input2_layer,
        input2_columns=[],
        input2_columns_prefix="",
        output_layer=output_layer,
        explodecollections=explodecollections,
        force_output_geometrytype=force_output_geometrytype,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
        output_with_spatial_index=output_with_spatial_index,
        tmp_dir=tempdir,
    )

    # Print time taken
    logger.info(f"Ready, full difference took {datetime.now()-start_time}")


def _subdivide_layer(
    path: Path,
    layer: Optional[str],
    output_path: Path,
    subdivide_coords: int,
    keep_fid: bool = True,
    nb_parallel: int = -1,
    batchsize: int = -1,
    operation_prefix: str = "",
) -> Optional[Path]:
    """Subdivide a layer if needed.

    By default, the original FID, before subdividing, is saved in column 'fid_1' in the
    output file.

    Args:
        path (Path): path to the input file.
        layer (str): layer in the file to be subdivided.
        output_path (Path): the path to create the subdivided file in. If the directory
            doesn't exist yet, it is created.
        subdivide_coords (int): number of coordinates to aim for.
        keep_fid (bool): True to retain the fid column in the output file.
        nb_parallel (int, optional): _description_. Defaults to -1.
        batchsize (int, optional): _description_. Defaults to -1.
        operation_prefix (str, optional): Prefix to use in logging,... Defaults to "".

    Returns:
        Optional[Path]: path to the result or None if it didn't need subdivision.
    """
    if subdivide_coords <= 0:
        return None

    # Only subdivide Polygon layers
    layer_info = gfo.get_layerinfo(path, layer)
    if layer_info.geometrytype.to_primitivetype != PrimitiveType.POLYGON:
        return None

    # If layer has complex geometries, subdivide them.
    layer = layer_info.name
    complexgeom_sql = f"""
        SELECT 1
          FROM "{layer}" layer
         WHERE ST_NPoints({layer_info.geometrycolumn}) > {subdivide_coords}
         LIMIT 1
    """
    logger.info(
        f"Check if complex geometries in {path.name}/{layer} (> {subdivide_coords} "
        "coords)"
    )
    complexgeom_df = gfo.read_file(path, sql_stmt=complexgeom_sql, sql_dialect="SQLITE")
    if len(complexgeom_df) <= 0:
        return None

    logger.info("Subdivide needed: complex geometries found")

    # Do subdivide using python function, because all spatialite options didn't
    # seem to work.
    # Check out commits in https://github.com/geofileops/geofileops/pull/433
    def subdivide(geom, num_coords_max):
        if geom is None or geom.is_empty:
            return geom

        if isinstance(geom, shapely.geometry.base.BaseMultipartGeometry):
            # Simple single geometry
            result = shapely.get_parts(
                pygeoops.subdivide(geom, num_coords_max=num_coords_max)
            )
        else:
            geom = shapely.get_parts(geom)
            if len(geom) == 1:
                # There was only one geometry in the multigeometry
                result = shapely.get_parts(
                    pygeoops.subdivide(geom[0], num_coords_max=num_coords_max)
                )
            else:
                to_subdivide = shapely.get_num_coordinates(geom) > num_coords_max
                if np.any(to_subdivide):
                    subdivided = np.concatenate(
                        [
                            shapely.get_parts(
                                pygeoops.subdivide(g, num_coords_max=num_coords_max)
                            )
                            for g in geom[to_subdivide]
                        ]
                    )
                    result = np.concatenate([subdivided, geom[~to_subdivide]])
                else:
                    result = geom

        if result is None:
            return None
        if not hasattr(result, "__len__"):
            return result
        if len(result) == 1:
            return result[0]

        # Explode because
        #   - they will be exploded anyway by spatialite.ST_Collect
        #   - spatialite.ST_AsBinary and/or spatialite.ST_GeomFromWkb don't seem
        #     to handle nested collections well.
        return shapely.geometrycollections(result)

    def subdivide_vectorized(geom, num_coords_max):
        if geom is None:
            return None

        if not hasattr(geom, "__len__"):
            return subdivide(geom, num_coords_max)

        to_subdivide = shapely.get_num_coordinates(geom) > num_coords_max
        geom[to_subdivide] = np.array(
            [subdivide(g, num_coords_max=num_coords_max) for g in geom[to_subdivide]]
        )

        return geom

    # Keep the fid column if needed
    columns = ["fid"] if keep_fid else []

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _geoops_gpd.apply_vectorized(
        input_path=path,
        input_layer=layer,
        output_path=output_path,
        output_layer=layer,
        func=lambda geom: subdivide_vectorized(geom, num_coords_max=subdivide_coords),
        operation_name=f"{operation_prefix}subdivide",
        columns=columns,
        explodecollections=True,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        parallelization_config=_geoops_gpd.ParallelizationConfig(
            bytes_per_row=2000, max_rows_per_batch=50000
        ),
    )
    if keep_fid:
        sql_create_index = f'CREATE INDEX "IDX_{layer}_fid_1" ON "{layer}"(fid_1)'
        fileops.execute_sql(output_path, sql_stmt=sql_create_index)

    return output_path


def export_by_location(
    input_path: Path,
    input_to_compare_with_path: Path,
    output_path: Path,
    spatial_relations_query: str,
    min_area_intersect: Optional[float] = None,
    area_inters_column_name: Optional[str] = None,
    input_layer: Optional[str] = None,
    input_columns: Optional[list[str]] = None,
    input_to_compare_with_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 10000,
    force: bool = False,
):
    # Because there might be extra preparation of the 2nd layer before going ahead
    # with the real calculation, do some additional init + checks here...
    if subdivide_coords < 0:
        raise ValueError("subdivide_coords < 0 is not allowed")

    operation_name = "export_by_location"
    logger = logging.getLogger(f"geofileops.{operation_name}")
    if output_path.exists():
        if force is False:
            logger.info(f"Stop, output exists already {output_path}")
            return
        else:
            gfo.remove(output_path)

    start_time = datetime.now()

    # Prepare sql template for this operation
    input1_layer_rtree = "rtree_{input1_layer}_{input1_geometrycolumn}"
    input2_layer_rtree = "rtree_{input2_layer}_{input2_geometrycolumn}"

    # Prepare spatial relation column and filter
    (
        spatial_relation_column,
        spatial_relation_filter,
        true_for_disjoint,
    ) = _prepare_filter_by_location_fields(spatial_relations_query)

    # Subdivide the 2nd layer if applicable to speed up further processing.
    tmp_dir = _io_util.create_tempdir(f"geofileops/{operation_name}")
    input_to_compare_with_subdivided_path = _subdivide_layer(
        path=input_to_compare_with_path,
        layer=input_to_compare_with_layer,
        output_path=tmp_dir / "subdivided/input_to_compare_with_layer.gpkg",
        subdivide_coords=subdivide_coords,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        operation_prefix=f"{operation_name}/",
    )
    if input_to_compare_with_subdivided_path is not None:
        input_to_compare_with_path = input_to_compare_with_subdivided_path

    # Different query if intersecting features need to be unioned...
    if (
        true_for_disjoint is False
        and area_inters_column_name is None
        and min_area_intersect is None
    ):
        # No union needed.
        sql_template = f"""
            WITH layer1_intersecting_filtered AS (
              SELECT layer1.{{input1_geometrycolumn}} AS geom
                    {{layer1_columns_prefix_alias_str}}
                FROM {{input1_databasename}}."{{input1_layer}}" layer1
               WHERE 1=1
                 {{batch_filter}}
                 AND EXISTS (
                      SELECT 1 FROM (
                        SELECT 1
                              {spatial_relation_column}
                          FROM {{input2_databasename}}."{{input2_layer}}" layer2
                          JOIN {{input2_databasename}}."{input2_layer_rtree}" layer2tree
                            ON layer2.fid = layer2tree.id
                         WHERE ST_MinX(layer1.{{input1_geometrycolumn}}) <= layer2tree.maxx
                           AND ST_MaxX(layer1.{{input1_geometrycolumn}}) >= layer2tree.minx
                           AND ST_MinY(layer1.{{input1_geometrycolumn}}) <= layer2tree.maxy
                           AND ST_MaxY(layer1.{{input1_geometrycolumn}}) >= layer2tree.miny
                           --LIMIT -1 OFFSET 0
                        ) sub_filter
                       WHERE {spatial_relation_filter}
                      )
            )
            SELECT sub.geom
                  {{layer1_columns_from_subselect_str}}
                  {{layer2_columns_from_subselect_str}}
              FROM layer1_intersecting_filtered sub
        """  # noqa: E501

        # If disjoint is True according to the query, include features that don't match
        # the spatial index.
        if true_for_disjoint:
            sql_template = f"""
                {sql_template}
                UNION ALL
                SELECT layer1.{{input1_geometrycolumn}} AS geom
                      {{layer1_columns_prefix_alias_str}}
                      {{layer2_columns_prefix_alias_null_str}}
                  FROM {{input1_databasename}}."{{input1_layer}}" layer1
                  WHERE 1=1
                   {{batch_filter}}
                   AND NOT EXISTS (
                        SELECT 1
                          FROM {{input2_databasename}}."{{input2_layer}}" layer2
                          JOIN {{input2_databasename}}."{input2_layer_rtree}" layer2tree
                            ON layer2.fid = layer2tree.id
                         WHERE ST_MinX(layer1.{{input1_geometrycolumn}}) <= layer2tree.maxx
                           AND ST_MaxX(layer1.{{input1_geometrycolumn}}) >= layer2tree.minx
                           AND ST_MinY(layer1.{{input1_geometrycolumn}}) <= layer2tree.maxy
                           AND ST_MaxY(layer1.{{input1_geometrycolumn}}) >= layer2tree.miny
                       )
        """  # noqa: E501
    else:
        # Union needed to calculate intersection area or because spatial_relation_query
        # returns True for disjoint features.

        # Prepare area calculation is relevant
        area_inters_column_expression = ""
        if area_inters_column_name is not None or min_area_intersect is not None:
            if area_inters_column_name is None:
                area_inters_column_name = "area_inters"
            area_inters_column_expression = (
                f",ST_area(ST_intersection(geom, geom2)) AS {area_inters_column_name}"
            )

        (
            spatial_relation_column,
            spatial_relation_filter,
            true_for_disjoint,
        ) = _prepare_filter_by_location_fields(
            spatial_relations_query, geom1="geom", geom2="geom2", subquery_alias="sub"
        )

        # Optimize special case: geom2 is already filtered on intersects in the query,
        # so for "intersects is True" we can avoid calculating intersects again:
        if spatial_relations_query.lower() == "intersects is true":
            spatial_relation_column = ""
            spatial_relation_filter = "geom2 IS NOT NULL"

        if true_for_disjoint:
            spatial_relation_filter = f"geom2 IS NULL OR ({spatial_relation_filter})"
        area_inters_column = (
            f",{area_inters_column_name}" if area_inters_column_name is not None else ""
        )
        sql_template = f"""
            SELECT sub.geom
                  {{layer1_columns_from_subselect_str}}
                  {area_inters_column}
              FROM (
                SELECT sub_union.*
                      {spatial_relation_column}
                      {area_inters_column_expression}
                  FROM (
                    SELECT layer1.*
                          ,(SELECT ST_Union(layer2_sub.{{input2_geometrycolumn}}) AS geom2
                              FROM {{input1_databasename}}."{input1_layer_rtree}" layer1tree
                              JOIN {{input2_databasename}}."{{input2_layer}}" layer2_sub
                              JOIN {{input2_databasename}}."{input2_layer_rtree}" layer2tree
                                ON layer2_sub.rowid = layer2tree.id
                             WHERE layer1tree.id = layer1.rowid
                               AND layer1tree.minx <= layer2tree.maxx
                               AND layer1tree.maxx >= layer2tree.minx
                               AND layer1tree.miny <= layer2tree.maxy
                               AND layer1tree.maxy >= layer2tree.miny
                               AND ST_intersects(
                                        layer1.{{input1_geometrycolumn}},
                                        layer2_sub.{{input2_geometrycolumn}}
                                   ) = 1
                             LIMIT -1 OFFSET 0
                           ) AS geom2
                      FROM {{input1_databasename}}."{{input1_layer}}" layer1
                     WHERE 1=1
                       {{batch_filter}}
                     LIMIT -1 OFFSET 0
                ) sub_union
              ) sub
             WHERE {spatial_relation_filter}
        """  # noqa: E501

        # Filter on intersect area if necessary
        if min_area_intersect is not None:
            sql_template = f"""
                SELECT * FROM
                  ( {sql_template}
                     LIMIT -1 OFFSET 0
                  ) sub_area
                WHERE sub_area.{area_inters_column_name} >= {min_area_intersect}
            """

    # Go!
    input_layer_info = gfo.get_layerinfo(input_path, input_layer)
    _two_layer_vector_operation(
        input1_path=input_path,
        input2_path=input_to_compare_with_path,
        output_path=output_path,
        sql_template=sql_template,
        operation_name=operation_name,
        input1_layer=input_layer,
        input1_columns=input_columns,
        input1_columns_prefix="",
        input2_layer=input_to_compare_with_layer,
        input2_columns=[],
        input2_columns_prefix="",
        output_layer=output_layer,
        explodecollections=False,
        force_output_geometrytype=input_layer_info.geometrytype,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
        tmp_dir=tmp_dir,
    )

    # Print time taken
    logger.info(f"Ready, full export_by_location took {datetime.now()-start_time}")


def export_by_distance(
    input_to_select_from_path: Path,
    input_to_compare_with_path: Path,
    output_path: Path,
    max_distance: float,
    input1_layer: Optional[str] = None,
    input1_columns: Optional[list[str]] = None,
    input2_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    # Prepare sql template for this operation
    input1_layer_rtree = "rtree_{input1_layer}_{input1_geometrycolumn}"
    input2_layer_rtree = "rtree_{input2_layer}_{input2_geometrycolumn}"
    sql_template = f"""
        SELECT geom
              {{layer1_columns_prefix_alias_str}}
          FROM {{input1_databasename}}."{{input1_layer}}" layer1
          JOIN {{input1_databasename}}."{input1_layer_rtree}" layer1tree
            ON layer1.fid = layer1tree.id
         WHERE 1=1
               {{batch_filter}}
               AND EXISTS (
                    SELECT 1
                      FROM {{input2_databasename}}."{{input2_layer}}" layer2
                      JOIN {{input2_databasename}}."{input2_layer_rtree}" layer2tree
                        ON layer2.fid = layer2tree.id
                     WHERE (layer1tree.minx-{max_distance}) <= layer2tree.maxx
                       AND (layer1tree.maxx+{max_distance}) >= layer2tree.minx
                       AND (layer1tree.miny-{max_distance}) <= layer2tree.maxy
                       AND (layer1tree.maxy+{max_distance}) >= layer2tree.miny
                       AND ST_distance(
                            layer1.{{input1_geometrycolumn}},
                            layer2.{{input2_geometrycolumn}}) <= {max_distance})
    """

    input_layer_info = gfo.get_layerinfo(input_to_select_from_path, input1_layer)

    # Go!
    return _two_layer_vector_operation(
        input1_path=input_to_select_from_path,
        input2_path=input_to_compare_with_path,
        output_path=output_path,
        sql_template=sql_template,
        operation_name="export_by_distance",
        input1_layer=input1_layer,
        input1_columns=input1_columns,
        input1_columns_prefix="",
        input2_layer=input2_layer,
        input2_columns=[],
        input2_columns_prefix="",
        output_layer=output_layer,
        explodecollections=False,
        force_output_geometrytype=input_layer_info.geometrytype,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def intersection(  # noqa: D417
    input1_path: Path,
    input2_path: Path,
    output_path: Path,
    overlay_self: bool,
    input1_layer: Optional[str] = None,
    input1_columns: Optional[list[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[list[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 7500,
    force: bool = False,
    output_with_spatial_index: Optional[bool] = None,
    operation_prefix: str = "",
    input1_subdivided_path: Optional[Path] = None,
    input2_subdivided_path: Optional[Path] = None,
):
    """Calculate the intersection between two layers.

    Only arguments specific to the internal difference operation are documented here.
    For the other arguments, check out the corresponding function in geoops.py.

    Args:
        output_with_spatial_index (Optional[bool], optional): Controls whether the
            output file is created with a spatial index. True to create one, False not
            to create one, None to apply the GDAL standard behaviour. Defaults to None.
        operation_prefix (str, optional): When this function is called from a compounded
            spatial operation, the name of this operation can be specified to show
            clearer progress messages,... Defaults to "".
        input1_subdivided_path (Path | None, optional): If a Path to a file,
            the subdivided version of input1 can be found here. If a Path to root
            (Path("/")), input1 was tested, but it does not need subdividing. If None,
            input1 still needs to be subdivided. Defaults to None.
        input2_subdivided_path (Path | None, optional): If a Path to a file,
            the subdivided version of input1 can be found here. If a Path to root
            (Path("/")), input2 was tested, but it does not need subdividing. If None,
            input2 still needs to be subdivided. Defaults to None.
    """
    # Because there might be extra preparation of the input layers before going ahead
    # with the real calculation, do some additional init + checks here...
    start_time = datetime.now()
    if subdivide_coords < 0:
        raise ValueError("subdivide_coords < 0 is not allowed")

    operation_name = f"{operation_prefix}intersection"
    logger = logging.getLogger(f"geofileops.{operation_name}")

    input1_layer, input2_layer, output_layer = _validate_params(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        input1_layer=input1_layer,
        input2_layer=input2_layer,
        output_layer=output_layer,
        operation_name=operation_name,
    )
    if _io_util.output_exists(path=output_path, remove_if_exists=force):
        return

    # In the query, important to only extract the geometry types that are expected
    input1_layer_info = gfo.get_layerinfo(input1_path, input1_layer)
    input2_layer_info = gfo.get_layerinfo(input2_path, input2_layer)
    primitivetype_to_extract = PrimitiveType(
        min(
            input1_layer_info.geometrytype.to_primitivetype.value,
            input2_layer_info.geometrytype.to_primitivetype.value,
        )
    )

    # Force MULTI variant if explodecollections is False to avoid ugly warnings/issues.
    if explodecollections:
        force_output_geometrytype = primitivetype_to_extract.to_singletype
    else:
        force_output_geometrytype = primitivetype_to_extract.to_multitype

    # Subdivide input1 layer if needed to speed up further processing.
    tempdir = _io_util.create_tempdir(f"geofileops/{operation_name}")

    if input1_subdivided_path is None:
        # input1_subdivided_path is None: try to subdivide.
        input1_subdivided_path = _subdivide_layer(
            path=input1_path,
            layer=input1_layer,
            output_path=tempdir / "subdivided/input1_layer.gpkg",
            subdivide_coords=subdivide_coords,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix=f"{operation_name}/",
        )
    elif input1_subdivided_path == Path("/"):
        # input1_subdivided_path is Path("/"): input1 doesn't contain complex geoms.
        input1_subdivided_path = None

    # Subdivide input2 layer as well if needed.
    if overlay_self:
        # If we are self-overlaying, input2 is the same as input1, so we can reuse the
        # result of subdividing input1.
        input2_subdivided_path = input1_subdivided_path
    elif input2_subdivided_path is None:
        input2_subdivided_path = _subdivide_layer(
            path=input2_path,
            layer=input2_layer,
            output_path=tempdir / "subdivided/input2_layer.gpkg",
            subdivide_coords=subdivide_coords,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix=f"{operation_name}/",
        )
    elif input2_subdivided_path == Path("/"):
        # input2_subdivided_path is Path("/"): input2 doesn't contain complex geoms.
        input2_subdivided_path = None

    # If we are doing a self overlay, we need to filter out rows with the same rowid
    where_clause_self = "1=1"
    if overlay_self:
        if input1_subdivided_path is None:
            where_clause_self = "layer1.rowid <> layer2.rowid"
        else:
            # Filter out the same rowids using the original fids!
            where_clause_self = "layer1_subdiv.fid_1 <> layer2_subdiv.fid_1"

    # Prepare sql template for this operation
    #
    # Remarks:
    # - ST_Intersects is fine, but ST_Touches slows down. Especially when the data
    #   contains huge geoms, time doubles or worse. The filter on sub.geom IS NOT NULL
    #   removes rows without intersection anyway.
    # - use "LIMIT -1 OFFSET 0" to avoid the subquery flattening. Flattening e.g.
    #   "geom IS NOT NULL" leads to geom operation to be calculated twice!
    input1_layer_rtree = "rtree_{input1_layer}_{input1_geometrycolumn}"
    input2_layer_rtree = "rtree_{input2_layer}_{input2_geometrycolumn}"

    if input1_subdivided_path is None and input2_subdivided_path is None:
        # No subdividing happened, so we can do a simple intersection
        sql_template = f"""
            SELECT sub.geom
                 {{layer1_columns_from_subselect_str}}
                 {{layer2_columns_from_subselect_str}}
              FROM
                ( SELECT ST_CollectionExtract(
                           ST_Intersection(
                                layer1.{{input1_geometrycolumn}},
                                layer2.{{input2_geometrycolumn}}),
                                {primitivetype_to_extract.value}) AS geom
                        {{layer1_columns_prefix_alias_str}}
                        {{layer2_columns_prefix_alias_str}}
                    FROM {{input1_databasename}}."{{input1_layer}}" layer1
                    JOIN {{input1_databasename}}."{input1_layer_rtree}" layer1tree
                      ON layer1.fid = layer1tree.id
                    JOIN {{input2_databasename}}."{{input2_layer}}" layer2
                    JOIN {{input2_databasename}}."{input2_layer_rtree}" layer2tree
                      ON layer2.fid = layer2tree.id
                   WHERE {where_clause_self}
                     {{batch_filter}}
                     AND layer1tree.minx <= layer2tree.maxx
                     AND layer1tree.maxx >= layer2tree.minx
                     AND layer1tree.miny <= layer2tree.maxy
                     AND layer1tree.maxy >= layer2tree.miny
                     AND ST_Intersects(
                            layer1.{{input1_geometrycolumn}},
                            layer2.{{input2_geometrycolumn}}) = 1
                     --AND ST_Touches(
                     --       layer1.{{input1_geometrycolumn}},
                     --       layer2.{{input2_geometrycolumn}}) = 0
                   LIMIT -1 OFFSET 0
                ) sub
             WHERE sub.geom IS NOT NULL
        """
    else:
        # At lease one input layer was subdivided, so we need to union the result of the
        # different partial intersections.

        # Depending on which input layers were actually subdivided, we need to adjust
        # the sql
        if input1_subdivided_path is None:
            # input1 layer was not subdivided, so use the original input1 layer
            input1_subdiv_databasename = "{input1_databasename}"
            input1_subdiv_fid_orig = "fid"
            input1_subdiv_geometrycolumn = "{input1_geometrycolumn}"
            input1_subdiv_layer_rtree = input1_layer_rtree
        else:
            input1_subdiv_databasename = "{input1_subdiv_databasename}"
            input1_subdiv_fid_orig = "fid_1"
            input1_subdiv_geometrycolumn = "{input1_subdiv_geometrycolumn}"
            input1_subdiv_layer_rtree = (
                "rtree_{input1_layer}_{input1_subdiv_geometrycolumn}"
            )

        if input2_subdivided_path is None:
            # input2 layer was not subdivided, so use the original input2 layer
            input2_subdiv_databasename = "{input2_databasename}"
            input2_subdiv_fid_orig = "fid"
            input2_subdiv_geometrycolumn = "{input2_geometrycolumn}"
            input2_subdiv_layer_rtree = input2_layer_rtree
        else:
            input2_subdiv_databasename = "{input2_subdiv_databasename}"
            input2_subdiv_fid_orig = "fid_1"
            input2_subdiv_geometrycolumn = "{input2_subdiv_geometrycolumn}"
            input2_subdiv_layer_rtree = (
                "rtree_{input2_layer}_{input2_subdiv_geometrycolumn}"
            )

        sql_template = f"""
            SELECT intersections.geom
                  {{layer1_columns_prefix_alias_str}}
                  {{layer2_columns_prefix_alias_str}}
              FROM (
                SELECT sub.layer1_fid_orig
                      ,sub.layer2_fid_orig
                      ,ST_Union(geom) AS geom
                  FROM (
                    SELECT layer1_subdiv.{input1_subdiv_fid_orig} AS layer1_fid_orig
                          ,layer2_subdiv.{input2_subdiv_fid_orig} AS layer2_fid_orig
                          ,ST_CollectionExtract(
                             ST_Intersection(
                                  layer1_subdiv.{input1_subdiv_geometrycolumn},
                                  layer2_subdiv.{input2_subdiv_geometrycolumn}),
                                  {primitivetype_to_extract.value}) AS geom
                      FROM {input1_subdiv_databasename}."{{input1_layer}}" layer1_subdiv
                      JOIN {input1_subdiv_databasename}."{input1_subdiv_layer_rtree}" layer1tree
                        ON layer1_subdiv.fid = layer1tree.id
                      JOIN {input2_subdiv_databasename}."{{input2_layer}}" layer2_subdiv
                      JOIN {input2_subdiv_databasename}."{input2_subdiv_layer_rtree}" layer2tree
                        ON layer2_subdiv.fid = layer2tree.id
                     WHERE {where_clause_self}
                       {{batch_filter}}
                       AND layer1tree.minx <= layer2tree.maxx
                       AND layer1tree.maxx >= layer2tree.minx
                       AND layer1tree.miny <= layer2tree.maxy
                       AND layer1tree.maxy >= layer2tree.miny
                       AND ST_Intersects(
                              layer1_subdiv.{input1_subdiv_geometrycolumn},
                              layer2_subdiv.{input2_subdiv_geometrycolumn}) = 1
                       --AND ST_Touches(
                       --       layer1_subdiv.{input1_subdiv_geometrycolumn},
                       --       layer2_subdiv.{input2_subdiv_geometrycolumn}) = 0
                     LIMIT -1 OFFSET 0
                  ) sub
               WHERE sub.geom IS NOT NULL
               GROUP BY sub.layer1_fid_orig, sub.layer2_fid_orig
              ) intersections
              JOIN {{input1_databasename}}."{{input1_layer}}" layer1
                   ON layer1.fid = intersections.layer1_fid_orig
              JOIN {{input2_databasename}}."{{input2_layer}}" layer2
                   ON layer2.fid = intersections.layer2_fid_orig
        """  # noqa: E501

    # Go!
    _two_layer_vector_operation(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        sql_template=sql_template,
        operation_name=f"{operation_prefix}intersection",
        input1_layer=input1_layer,
        input1_columns=input1_columns,
        input1_columns_prefix=input1_columns_prefix,
        input2_layer=input2_layer,
        input2_columns=input2_columns,
        input2_columns_prefix=input2_columns_prefix,
        output_layer=output_layer,
        explodecollections=explodecollections,
        force_output_geometrytype=force_output_geometrytype,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
        input1_subdivided_path=input1_subdivided_path,
        input2_subdivided_path=input2_subdivided_path,
        output_with_spatial_index=output_with_spatial_index,
    )

    # Print time taken
    logger.info(f"Ready, full intersection took {datetime.now()-start_time}")


def join_by_location(
    input1_path: Path,
    input2_path: Path,
    output_path: Path,
    spatial_relations_query: str = "intersects is True",
    discard_nonmatching: bool = True,
    min_area_intersect: Optional[float] = None,
    area_inters_column_name: Optional[str] = None,
    input1_layer: Optional[str] = None,
    input1_columns: Optional[list[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[list[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    # Prepare sql template for this operation
    # Prepare intersection area columns/filter
    area_inters_column_expression = ""
    area_inters_column_in_output = ""
    area_inters_column_0_in_output = ""
    area_inters_filter = ""
    if area_inters_column_name is not None or min_area_intersect is not None:
        if area_inters_column_name is not None:
            area_inters_column_name_touse = area_inters_column_name
            area_inters_column_in_output = f',"{area_inters_column_name}"'
            area_inters_column_0_in_output = f',0 AS "{area_inters_column_name}"'
        else:
            area_inters_column_name_touse = "area_inters"
        area_inters_column_expression = (
            ",ST_area(ST_intersection(sub_filter.geom, sub_filter.l2_geom)) "
            f'AS "{area_inters_column_name_touse}"'
        )
        if min_area_intersect is not None:
            area_inters_filter = (
                f'WHERE sub_area."{area_inters_column_name_touse}" '
                f">= {min_area_intersect}"
            )

    # Prepare spatial relation column and filter
    # As the query is used as the join criterium, it should not evaluate to True for
    # disjoint features. So specify avoid_disjoint=True.
    (
        spatial_relation_column,
        spatial_relation_filter,
        _,
    ) = _prepare_filter_by_location_fields(spatial_relations_query, avoid_disjoint=True)

    # Prepare sql template
    #
    # Remark: use "LIMIT -1 OFFSET 0" to avoid that the sqlite query optimizer
    #     "flattens" the subquery, as that makes checking the spatial
    #     relations (using ST_RelateMatch) very slow!
    input1_layer_rtree = "rtree_{input1_layer}_{input1_geometrycolumn}"
    input2_layer_rtree = "rtree_{input2_layer}_{input2_geometrycolumn}"
    sql_template = f"""
        WITH layer1_relations_filtered AS (
          SELECT sub_area.*
            FROM (
              SELECT sub_filter.*
                    {area_inters_column_expression}
                FROM (
                  SELECT layer1.{{input1_geometrycolumn}} AS geom
                        ,layer1.fid l1_fid
                        ,layer2.{{input2_geometrycolumn}} AS l2_geom
                        {{layer1_columns_prefix_alias_str}}
                        {{layer2_columns_prefix_alias_str}}
                        {spatial_relation_column}
                    FROM {{input1_databasename}}."{{input1_layer}}" layer1
                    JOIN {{input1_databasename}}."{input1_layer_rtree}" layer1tree
                      ON layer1.fid = layer1tree.id
                    JOIN {{input2_databasename}}."{{input2_layer}}" layer2
                    JOIN {{input2_databasename}}."{input2_layer_rtree}" layer2tree
                      ON layer2.fid = layer2tree.id
                   WHERE 1=1
                     {{batch_filter}}
                     AND layer1tree.minx <= layer2tree.maxx
                     AND layer1tree.maxx >= layer2tree.minx
                     AND layer1tree.miny <= layer2tree.maxy
                     AND layer1tree.maxy >= layer2tree.miny
                   LIMIT -1 OFFSET 0
                  ) sub_filter
               WHERE {spatial_relation_filter}
               LIMIT -1 OFFSET 0
              ) sub_area
           {area_inters_filter}
           LIMIT -1 OFFSET 0
          )
        SELECT sub.geom
              {{layer1_columns_from_subselect_str}}
              {{layer2_columns_from_subselect_str}}
              {area_inters_column_in_output}
          FROM layer1_relations_filtered sub
    """

    # If a left join is asked, add all features from layer1 that weren't
    # matched.
    if discard_nonmatching is False:
        sql_template = f"""
            {sql_template}
            UNION ALL
            SELECT layer1.{{input1_geometrycolumn}} AS geom
                  {{layer1_columns_prefix_alias_str}}
                  {{layer2_columns_prefix_alias_null_str}}
                  {area_inters_column_0_in_output}
              FROM {{input1_databasename}}."{{input1_layer}}" layer1
             WHERE 1=1
               {{batch_filter}}
               AND layer1.fid NOT IN (
                   SELECT l1_fid FROM layer1_relations_filtered)
        """

    # Go!
    input1_layer_info = gfo.get_layerinfo(input1_path, input1_layer)
    return _two_layer_vector_operation(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        sql_template=sql_template,
        operation_name="join_by_location",
        input1_layer=input1_layer,
        input1_columns=input1_columns,
        input1_columns_prefix=input1_columns_prefix,
        input2_layer=input2_layer,
        input2_columns=input2_columns,
        input2_columns_prefix=input2_columns_prefix,
        output_layer=output_layer,
        explodecollections=explodecollections,
        force_output_geometrytype=input1_layer_info.geometrytype,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def _prepare_filter_by_location_fields(
    query: str,
    geom1: str = "layer1.{input1_geometrycolumn}",
    geom2: str = "layer2.{input2_geometrycolumn}",
    subquery_alias: str = "sub_filter",
    avoid_disjoint: bool = False,
) -> tuple[str, str, bool]:
    """Prepare the fields needed to prepare a select to filter by location.

    Args:
        query (str): the spatial relations query that should be filtered on.
        geom1 (str): the 1st geom in the spatial_relation_column.
        geom2 (str): the 2nd geom in the spatial_relation_column.
        subquery_alias (str): the alias tha will be used for the subquery to filter on.
            Defaults to "sub_filter".
        avoid_disjoint (bool): avoid that the query evaluates disjoint featurs to True.
            If it does, "intersects is True" is added to the input query.

    Returns:
        Tuple[str, str, bool]: returns a tuple with the following values:
            - spatial_relation_column: the string to use as column to filter on
            - spatial_relation_filter: the string to use as filter
            - true_for_disjoint: True if the query returns True for disjoint features.
                  If `avoid_disjoint` is True, `includes_disjoint` is always False.
    """
    # Add a specific optimisation for "intersects is True" as it is the most used
    # filtering and it is very optimised in GEOS.
    if query.lower() == "intersects is true":
        spatial_relation_column = (
            f',ST_intersects({geom1}, {geom2}) AS "GFO_$TEMP$_SPATIAL_RELATION"'
        )
        spatial_relation_filter = f'{subquery_alias}."GFO_$TEMP$_SPATIAL_RELATION" = 1'
        true_for_disjoint = False

        return (spatial_relation_column, spatial_relation_filter, true_for_disjoint)

    # It is a more complex query, so some more processing needed
    spatial_relations_filter = _prepare_spatial_relations_filter(query)
    spatial_relation_column = (
        ',ST_relate({input1}, {input2}) AS "GFO_$TEMP$_SPATIAL_RELATION"'
    )
    spatial_relation_filter = spatial_relations_filter.format(
        spatial_relation=f'{subquery_alias}."GFO_$TEMP$_SPATIAL_RELATION"'
    )

    # Determine if the spatial_relations_query returns True for disjoint features
    spatial_relation_column_disjoint = spatial_relation_column.format(
        input1="ST_GeomFromText('POLYGON((0 0, 0 1, 1 1, 1 0, 0 0))')",
        input2="ST_GeomFromText('POLYGON((5 0, 5 1, 6 1, 6 0, 5 0))')",
    )
    test_path = Path(__file__).resolve().parent / "test.gpkg"
    sql_stmt = f"""
        SELECT * FROM (
            SELECT NULL AS ignore
                  {spatial_relation_column_disjoint}
            ) {subquery_alias}
         WHERE {spatial_relation_filter}
    """
    df = fileops.read_file(test_path, sql_stmt=sql_stmt)
    true_for_disjoint = True if len(df) > 0 else False

    if true_for_disjoint and avoid_disjoint:
        # Avoid the query evaluating to True for disjoint features by adding
        # "intersects is True"
        query = f"({query}) and intersects is True"
        spatial_relations_filter = _prepare_spatial_relations_filter(query)
        spatial_relation_filter = spatial_relations_filter.format(
            spatial_relation=f'{subquery_alias}."GFO_$TEMP$_SPATIAL_RELATION"'
        )
        true_for_disjoint = False

        warnings.warn(
            "The spatial relation query specified evaluated to True for disjoint "
            f"features. To avoid this, 'intersects is True' was added: {query}",
            stacklevel=2,
        )

    # Fill out input columns of the spatial_relation_column
    spatial_relation_column = spatial_relation_column.format(input1=geom1, input2=geom2)

    return (spatial_relation_column, spatial_relation_filter, true_for_disjoint)


def _prepare_spatial_relations_filter(query: str) -> str:
    named_spatial_relations = {
        "disjoint": ["FF*FF****"],
        "equals": ["TFFF*FFF*"],
        "touches": ["FT*******", "F**T*****", "F***T****"],
        "within": ["T*F**F***"],
        "overlaps": ["T*T***T**", "1*T***T**"],
        "crosses": ["T*T******", "T*****T**", "0********"],
        "intersects": ["T********", "*T*******", "***T*****", "****T****"],
        "contains": ["T*****FF*"],
        "covers": ["T*****FF*", "*T****FF*", "***T**FF*", "****T*FF*"],
        "coveredby": ["T*F**F***", "*TF**F***", "**FT*F***", "**F*TF***"],
    }

    # Parse query and replace things that need to be replaced
    import re

    query_tokens = re.split("([ =()])", query)

    query_tokens_prepared = []
    nb_unclosed_brackets = 0
    for token in query_tokens:
        if token == "":
            continue
        elif token in [" ", "\n", "\t", "and", "or"]:
            query_tokens_prepared.append(token)
        elif token == "(":
            nb_unclosed_brackets += 1
            query_tokens_prepared.append(token)
        elif token == ")":
            nb_unclosed_brackets -= 1
            query_tokens_prepared.append(token)
        elif token == "is":
            query_tokens_prepared.append("=")
        elif token == "True":
            query_tokens_prepared.append("1")
        elif token == "False":
            query_tokens_prepared.append("0")
        elif token in named_spatial_relations:
            match_list = []
            for spatial_relation in named_spatial_relations[token]:
                match = (
                    f"ST_RelateMatch({{spatial_relation}}, '{spatial_relation}') = 1"
                )
                match_list.append(match)
            query_tokens_prepared.append(f"({' or '.join(match_list)})")
        elif len(token) == 9 and re.fullmatch("^[FT012*]+$", token) is not None:
            token_prepared = f"ST_RelateMatch({{spatial_relation}}, '{token}')"
            query_tokens_prepared.append(token_prepared)
        else:
            raise ValueError(
                f"Unexpected token in query (query is case sensitive!): {token}"
            )

    # If there are unclosed brackets, raise
    if nb_unclosed_brackets > 0:
        raise ValueError(f"not all brackets are closed in query {query}")
    elif nb_unclosed_brackets < 0:
        raise ValueError(f"more closing brackets than opening ones in query {query}")

    result = f"({''.join(query_tokens_prepared)})"
    return result


def join_nearest(
    input1_path: Path,
    input2_path: Path,
    output_path: Path,
    nb_nearest: int,
    distance: Optional[float],
    expand: Optional[bool],
    input1_layer: Optional[str] = None,
    input1_columns: Optional[list[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[list[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    # Init some things...
    # Because there is preprocessing done in this function, check output path
    # here already
    logger = logging.getLogger("geofileops.join_nearest")
    if output_path.exists() and force is False:
        logger.info(f"Stop, output exists already {output_path}")
        return
    if input1_layer is None:
        input1_layer = gfo.get_only_layer(input1_path)
    if input2_layer is None:
        input2_layer = gfo.get_only_layer(input2_path)

    # If spatialite >= 5.1, check some more parameters
    if SPATIALITE_GTE_51:
        if distance is None:
            raise ValueError("distance is mandatory with spatialite >= 5.1")
        if expand is None:
            raise ValueError("expand is mandatory with spatialite >= 5.1")
        expand_int = 1 if expand else False
    elif expand is not None and not expand:
        raise ValueError("expand=False is not supported with spatialite < 5.1")

    # Prepare input files
    # To use knn index, the input layers need to be in sqlite file format
    # (not a .gpkg!), so prepare this
    if input1_path == input2_path and gfo.get_driver(input1_path) == "SQLite":
        # Input files already ok...
        input1_tmp_path = input1_path
        input1_tmp_layer = input1_layer
        input2_tmp_path = input2_path
        input2_tmp_layer = input2_layer
    else:
        # Put input2 layer in sqlite gfo...
        tempdir = _io_util.create_tempdir("geofileops/join_nearest")
        input1_tmp_path = tempdir / "both_input_layers.sqlite"
        input1_tmp_layer = "input1_layer"
        gfo.copy_layer(
            src=input1_path,
            src_layer=input1_layer,
            dst=input1_tmp_path,
            dst_layer=input1_tmp_layer,
            preserve_fid=True,
        )

        # Add input2 layer to sqlite gfo...
        input2_tmp_path = input1_tmp_path
        input2_tmp_layer = "input2_layer"
        gfo.append_to(
            src=input2_path,
            src_layer=input2_layer,
            dst=input2_tmp_path,
            dst_layer=input2_tmp_layer,
            preserve_fid=True,
        )

    # Remark: the 2 input layers need to be in one file!
    if SPATIALITE_GTE_51:
        sql_template = f"""
            SELECT layer1.{{input1_geometrycolumn}} as geom
                  {{layer1_columns_prefix_alias_str}}
                  {{layer2_columns_prefix_alias_str}}
                  ,k.pos, k.distance_m AS distance, k.distance_crs
              FROM "{{input1_layer}}" layer1
              JOIN knn2 k
              JOIN "{{input2_layer}}" layer2 ON layer2.rowid = k.fid
             WHERE f_table_name = '{{input2_layer}}'
               AND f_geometry_column = '{{input2_geometrycolumn}}'
               AND ref_geometry = ST_Centroid(layer1.{{input1_geometrycolumn}})
               AND radius = {distance}
               AND max_items = {nb_nearest}
               AND expand = {expand_int}
               {{batch_filter}}
        """
    else:
        sql_template = f"""
            SELECT layer1.{{input1_geometrycolumn}} as geom
                  {{layer1_columns_prefix_alias_str}}
                  {{layer2_columns_prefix_alias_str}}
                  ,k.pos, k.distance
              FROM {{input1_databasename}}."{{input1_layer}}" layer1
              JOIN {{input2_databasename}}.knn k
              JOIN {{input2_databasename}}."{{input2_layer}}" layer2
                ON layer2.rowid = k.fid
             WHERE k.f_table_name = '{{input2_layer}}'
               AND k.f_geometry_column = '{{input2_geometrycolumn}}'
               AND k.ref_geometry = layer1.{{input1_geometrycolumn}}
               AND k.max_items = {nb_nearest}
               {{batch_filter}}
        """

    input1_layer_info = gfo.get_layerinfo(input1_path, input1_layer)

    # Go!
    return _two_layer_vector_operation(
        input1_path=input1_tmp_path,
        input2_path=input2_tmp_path,
        output_path=output_path,
        sql_template=sql_template,
        operation_name="join_nearest",
        input1_layer=input1_tmp_layer,
        input1_columns=input1_columns,
        input1_columns_prefix=input1_columns_prefix,
        input2_layer=input2_tmp_layer,
        input2_columns=input2_columns,
        input2_columns_prefix=input2_columns_prefix,
        output_layer=output_layer,
        force_output_geometrytype=input1_layer_info.geometrytype,
        explodecollections=explodecollections,
        gridsize=0.0,
        where_post=None,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
        use_ogr=True,
    )


def select_two_layers(
    input1_path: Path,
    input2_path: Path,
    output_path: Path,
    sql_stmt: str,
    input1_layer: Optional[str] = None,
    input1_columns: Optional[list[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[list[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    force_output_geometrytype: Optional[GeometryType] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = 1,
    batchsize: int = -1,
    force: bool = False,
    operation_prefix: str = "",
    output_with_spatial_index: Optional[bool] = None,
):
    # Go!
    return _two_layer_vector_operation(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        sql_template=sql_stmt,
        operation_name=f"{operation_prefix}select_two_layers",
        input1_layer=input1_layer,
        input1_columns=input1_columns,
        input1_columns_prefix=input1_columns_prefix,
        input2_layer=input2_layer,
        input2_columns=input2_columns,
        input2_columns_prefix=input2_columns_prefix,
        output_layer=output_layer,
        explodecollections=explodecollections,
        force_output_geometrytype=force_output_geometrytype,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
        output_with_spatial_index=output_with_spatial_index,
    )


def identity(
    input1_path: Path,
    input2_path: Path,
    output_path: Path,
    overlay_self: bool,
    input1_layer: Optional[str] = None,
    input1_columns: Optional[list[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[list[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = 1,
    batchsize: int = -1,
    subdivide_coords: int = 2000,
    force: bool = False,
):
    # An identity is the combination of the results of an "intersection" of input1 and
    # input2 and an difference of input2 with input1.

    # Because the calculations of the intermediate results will be towards temp files,
    # we need to do some additional init + checks here...
    start_time = datetime.now()
    if subdivide_coords < 0:
        raise ValueError("subdivide_coords < 0 is not allowed")

    logger = logging.getLogger("geofileops.identity")

    input1_layer, input2_layer, output_layer = _validate_params(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        input1_layer=input1_layer,
        input2_layer=input2_layer,
        output_layer=output_layer,
        operation_name="identity",
    )
    if _io_util.output_exists(path=output_path, remove_if_exists=force):
        return

    tempdir = _io_util.create_tempdir("geofileops/identity")
    try:
        # Prepare the input files
        logger.info("Step 1 of 4: prepare input files")
        input1_subdivided_path = _subdivide_layer(
            path=input1_path,
            layer=input1_layer,
            output_path=tempdir / "subdivided/input1_layer.gpkg",
            subdivide_coords=subdivide_coords,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix="identity/",
        )
        if input1_subdivided_path is None:
            # Hardcoded optimization: root means that no subdivide was needed
            input1_subdivided_path = Path("/")

        if overlay_self:
            # If overlay_self is True, input1 and input2 are the same
            input2_subdivided_path: Optional[Path] = input1_subdivided_path
        else:
            input2_subdivided_path = _subdivide_layer(
                path=input2_path,
                layer=input2_layer,
                output_path=tempdir / "subdivided/input2_layer.gpkg",
                subdivide_coords=subdivide_coords,
                nb_parallel=nb_parallel,
                batchsize=batchsize,
                operation_prefix="identity/",
            )
            if input2_subdivided_path is None:
                # Hardcoded optimization: root means that no subdivide was needed
                input2_subdivided_path = Path("/")

        # Calculate intersection of input1 with input2 to a temporary output file
        logger.info("Step 2 of 4: intersection")
        intersection_output_path = tempdir / "intersection_output.gpkg"
        intersection(
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=intersection_output_path,
            overlay_self=overlay_self,
            input1_layer=input1_layer,
            input1_columns=input1_columns,
            input1_columns_prefix=input1_columns_prefix,
            input2_layer=input2_layer,
            input2_columns=input2_columns,
            input2_columns_prefix=input2_columns_prefix,
            output_layer=output_layer,
            explodecollections=explodecollections,
            gridsize=gridsize,
            where_post=where_post,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            force=force,
            output_with_spatial_index=False,
            operation_prefix="identity/",
            input1_subdivided_path=input1_subdivided_path,
            input2_subdivided_path=input2_subdivided_path,
        )

        # Now difference input1 from input2 to another temporary output gfo...
        logger.info("Step 3 of 4: difference")
        difference_output_path = tempdir / "difference_output.gpkg"
        difference(
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=difference_output_path,
            overlay_self=overlay_self,
            input1_layer=input1_layer,
            input1_columns=input1_columns,
            input_columns_prefix=input1_columns_prefix,
            input2_layer=input2_layer,
            output_layer=output_layer,
            explodecollections=explodecollections,
            gridsize=gridsize,
            where_post=where_post,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            subdivide_coords=subdivide_coords,
            force=force,
            output_with_spatial_index=False,
            operation_prefix="identity/",
            input1_subdivided_path=input1_subdivided_path,
            input2_subdivided_path=input2_subdivided_path,
        )

        # Now append
        logger.info("Step 4 of 4: finalize")
        # Note: append will never create an index on an already existing layer.
        _append_to_nolock(
            src=difference_output_path,
            dst=intersection_output_path,
            src_layer=output_layer,
            dst_layer=output_layer,
        )

        # Convert or add spatial index
        tmp_output_path = intersection_output_path
        if intersection_output_path.suffix != output_path.suffix:
            # Output file should be in different format, so convert
            tmp_output_path = tempdir / output_path.name
            gfo.copy_layer(src=intersection_output_path, dst=tmp_output_path)
        elif GeofileInfo(tmp_output_path).default_spatial_index:
            gfo.create_spatial_index(path=tmp_output_path, layer=output_layer)

        # Now we are ready to move the result to the final spot...
        gfo.move(tmp_output_path, output_path)

    finally:
        if ConfigOptions.remove_temp_files:
            shutil.rmtree(tempdir, ignore_errors=True)

    logger.info(f"Ready, full identity took {datetime.now()-start_time}")


def symmetric_difference(
    input1_path: Path,
    input2_path: Path,
    output_path: Path,
    overlay_self: bool,
    input1_layer: Optional[str] = None,
    input1_columns: Optional[list[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[list[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 2000,
    force: bool = False,
):
    # A symmetric difference can be simulated by doing an difference of input1
    # and input2 and then append the result of an difference of input2 with
    # input1...

    # Because both difference calculations will be towards temp files,
    # we need to do some additional init + checks here...
    start_time = datetime.now()
    if subdivide_coords < 0:
        raise ValueError("subdivide_coords < 0 is not allowed")

    logger = logging.getLogger("geofileops.symmetric_difference")
    logger.info(
        f"Start, with input1: {input1_path}, "
        f"input2: {input2_path}, output: {output_path}"
    )

    input1_layer, input2_layer, output_layer = _validate_params(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        input1_layer=input1_layer,
        input2_layer=input2_layer,
        output_layer=output_layer,
        operation_name="symmetric_difference",
    )
    if _io_util.output_exists(path=output_path, remove_if_exists=force):
        return

    tempdir = _io_util.create_tempdir("geofileops/symmdiff")
    try:
        # Prepare the input files
        logger.info("Step 1 of 4: prepare input files")
        input1_subdivided_path = _subdivide_layer(
            path=input1_path,
            layer=input1_layer,
            output_path=tempdir / "subdivided/input1_layer.gpkg",
            subdivide_coords=subdivide_coords,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix="symmetric_difference/",
        )
        if input1_subdivided_path is None:
            # Hardcoded optimization: root means that no subdivide was needed
            input1_subdivided_path = Path("/")

        if overlay_self:
            # With overlay_self, input2 is the same as input1
            input2_subdivided_path: Optional[Path] = input1_subdivided_path
        else:
            input2_subdivided_path = _subdivide_layer(
                path=input2_path,
                layer=input2_layer,
                output_path=tempdir / "subdivided/input2_layer.gpkg",
                subdivide_coords=subdivide_coords,
                nb_parallel=nb_parallel,
                batchsize=batchsize,
                operation_prefix="symmetric_difference/",
            )
            if input2_subdivided_path is None:
                # Hardcoded optimization: root means that no subdivide was needed
                input2_subdivided_path = Path("/")

        # Difference input2 from input1 to a temporary output file
        logger.info("Step 2 of 4: difference 1")
        diff1_output_path = tempdir / "layer1_diff_layer2_output.gpkg"
        difference(
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=diff1_output_path,
            overlay_self=overlay_self,
            input1_layer=input1_layer,
            input1_columns=input1_columns,
            input_columns_prefix=input1_columns_prefix,
            input2_layer=input2_layer,
            output_layer=output_layer,
            explodecollections=explodecollections,
            gridsize=gridsize,
            where_post=where_post,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            subdivide_coords=subdivide_coords,
            force=force,
            output_with_spatial_index=False,
            operation_prefix="symmetric_difference/",
            input1_subdivided_path=input1_subdivided_path,
            input2_subdivided_path=input2_subdivided_path,
        )

        if input2_columns is None or len(input2_columns) > 0:
            input2_info = gfo.get_layerinfo(input2_path)
            columns_to_add = (
                input2_columns if input2_columns is not None else input2_info.columns
            )
            for column in columns_to_add:
                gfo.add_column(
                    diff1_output_path,
                    name=f"{input2_columns_prefix}{column}",
                    type=input2_info.columns[column].gdal_type,
                )

        # Now difference input1 from input2 to another temporary output file
        logger.info("Step 3 of 4: difference 2")
        diff2_output_path = tempdir / "layer2_diff_layer1_output.gpkg"
        difference(
            input1_path=input2_path,
            input2_path=input1_path,
            output_path=diff2_output_path,
            overlay_self=overlay_self,
            input1_layer=input2_layer,
            input1_columns=input2_columns,
            input_columns_prefix=input2_columns_prefix,
            input2_layer=input1_layer,
            output_layer=output_layer,
            explodecollections=explodecollections,
            gridsize=gridsize,
            where_post=where_post,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            subdivide_coords=subdivide_coords,
            force=force,
            output_with_spatial_index=False,
            operation_prefix="symmetric_difference/",
        )

        # Now append
        logger.info("Step 4 of 4: finalize")
        # Note: append will never create an index on an already existing layer.
        _append_to_nolock(
            src=diff2_output_path,
            dst=diff1_output_path,
            src_layer=output_layer,
            dst_layer=output_layer,
        )

        # Convert or add spatial index
        tmp_output_path = diff1_output_path
        if diff1_output_path.suffix != output_path.suffix:
            # Output file should be in diffent format, so convert
            tmp_output_path = tempdir / output_path.name
            gfo.copy_layer(src=diff1_output_path, dst=tmp_output_path)
        elif GeofileInfo(tmp_output_path).default_spatial_index:
            gfo.create_spatial_index(path=tmp_output_path, layer=output_layer)

        # Now we are ready to move the result to the final spot...
        gfo.move(tmp_output_path, output_path)

    finally:
        if ConfigOptions.remove_temp_files:
            shutil.rmtree(tempdir, ignore_errors=True)

    logger.info(f"Ready, full symmetric_difference took {datetime.now()-start_time}")


def union(
    input1_path: Path,
    input2_path: Path,
    output_path: Path,
    overlay_self: bool,
    input1_layer: Optional[str] = None,
    input1_columns: Optional[list[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[list[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 2000,
    force: bool = False,
):
    # A union is the combination of the results of an intersection of input1 and input2,
    # the result of an difference of input2 with input1 and the difference of input1
    # with input2.

    # Because the calculations of the intermediate results will be towards temp files,
    # we need to do some additional init + checks here...
    if subdivide_coords < 0:
        raise ValueError("subdivide_coords < 0 is not allowed")

    operation_name = "union"
    logger = logging.getLogger(f"geofileops.{operation_name}")

    input1_layer, input2_layer, output_layer = _validate_params(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        input1_layer=input1_layer,
        input2_layer=input2_layer,
        output_layer=output_layer,
        operation_name=operation_name,
    )
    if _io_util.output_exists(path=output_path, remove_if_exists=force):
        return

    start_time = datetime.now()
    tempdir = _io_util.create_tempdir("geofileops/union")
    try:
        # First apply intersection of input1 with input2 to a temporary output file...
        logger.info("Step 1 of 4: intersection")
        intersection_output_path = tempdir / "intersection_output.gpkg"
        intersection(
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=intersection_output_path,
            overlay_self=overlay_self,
            input1_layer=input1_layer,
            input1_columns=input1_columns,
            input1_columns_prefix=input1_columns_prefix,
            input2_layer=input2_layer,
            input2_columns=input2_columns,
            input2_columns_prefix=input2_columns_prefix,
            output_layer=output_layer,
            explodecollections=explodecollections,
            gridsize=gridsize,
            where_post=where_post,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            force=force,
            output_with_spatial_index=False,
            operation_prefix="union/",
        )

        # Difference input1 from input2 to another temporary output gfo.
        logger.info("Step 2 of 4: difference of input 1 from input 2")
        diff1_output_path = tempdir / "diff_input1_from_input2_output.gpkg"
        difference(
            input1_path=input2_path,
            input2_path=input1_path,
            output_path=diff1_output_path,
            overlay_self=overlay_self,
            input1_layer=input2_layer,
            input1_columns=input2_columns,
            input_columns_prefix=input2_columns_prefix,
            input2_layer=input1_layer,
            output_layer=output_layer,
            explodecollections=explodecollections,
            gridsize=gridsize,
            where_post=where_post,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            subdivide_coords=subdivide_coords,
            force=force,
            output_with_spatial_index=False,
            operation_prefix="union/",
        )
        # Note: append will never create an index on an already existing layer.
        _append_to_nolock(
            src=diff1_output_path,
            dst=intersection_output_path,
            src_layer=output_layer,
            dst_layer=output_layer,
        )
        gfo.remove(diff1_output_path)

        # Difference input1 from input2 to and add to temporary output file.
        logger.info("Step 3 of 4: difference input 2 from input 1")
        diff2_output_path = tempdir / "diff_input2_from_input1_output.gpkg"

        difference(
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=diff2_output_path,
            overlay_self=overlay_self,
            input1_layer=input1_layer,
            input1_columns=input1_columns,
            input_columns_prefix=input1_columns_prefix,
            input2_layer=input2_layer,
            output_layer=output_layer,
            explodecollections=explodecollections,
            gridsize=gridsize,
            where_post=where_post,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            subdivide_coords=subdivide_coords,
            force=force,
            output_with_spatial_index=False,
            operation_prefix="union/",
        )
        _append_to_nolock(
            src=diff2_output_path,
            dst=intersection_output_path,
            src_layer=output_layer,
            dst_layer=output_layer,
        )
        gfo.remove(diff2_output_path)

        # Convert or add spatial index
        logger.info("Step 4 of 4: finalize")

        tmp_output_path = intersection_output_path
        if intersection_output_path.suffix != output_path.suffix:
            # Output file should be in different format, so convert
            tmp_output_path = tempdir / output_path.name
            gfo.copy_layer(src=intersection_output_path, dst=tmp_output_path)
        elif GeofileInfo(tmp_output_path).default_spatial_index:
            gfo.create_spatial_index(path=tmp_output_path, layer=output_layer)

        # Now we are ready to move the result to the final spot...
        gfo.move(tmp_output_path, output_path)

    finally:
        if ConfigOptions.remove_temp_files:
            shutil.rmtree(tempdir, ignore_errors=True)

    logger.info(f"Ready, full union took {datetime.now()-start_time}")


def _two_layer_vector_operation(
    input1_path: Path,
    input2_path: Path,
    output_path: Path,
    sql_template: str,
    operation_name: str,
    input1_layer: Optional[str],
    input1_columns: Optional[list[str]],
    input1_columns_prefix: str,
    input2_layer: Optional[str],
    input2_columns: Optional[list[str]],
    input2_columns_prefix: str,
    output_layer: Optional[str],
    explodecollections: bool,
    force_output_geometrytype: Optional[GeometryType],
    gridsize: float,
    where_post: Optional[str],
    nb_parallel: int,
    batchsize: int,
    force: bool,
    input1_subdivided_path: Optional[Path] = None,
    input2_subdivided_path: Optional[Path] = None,
    use_ogr: bool = False,
    output_with_spatial_index: Optional[bool] = None,
    tmp_dir: Optional[Path] = None,
):
    """Executes an operation that needs 2 input files.

    Args:
        input1_path (str): the file to export features from
        input2_path (str): the file to check intersections with
        output_path (str): output file
                input1_layer (str, optional): input layer name. Optional if the
            file only contains one layer. Defaults to None.
        operation_name (str): name of the operation to be used in logging.
        sql_template (str): the SELECT sql statement to be executed.
        input1_layer (str): input1 layer name.
        input1_columns (List[str]): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased even if input1_columns_prefix is "", eg. to
            "fid_1".
        input1_columns_prefix (str): prefix to use in the column aliases.
        input2_layer (str): input2 layer name.
        input2_columns (List[str]): columns to select. If None is specified,
            all columns are selected. As explained for input1_columns, it is also
            possible to specify "fid".
        input2_columns_prefix (str): prefix to use in the column aliases.
        output_layer (str): [description]. Defaults to None.
        explodecollections (bool, optional): Explode collecions in output.
            Defaults to False.
        force_output_geometrytype (GeometryType, optional): Defaults to None.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): sql filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): [description]. Defaults to -1.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): [description]. Defaults to False.
        input1_subdivided_path (Path, optional): [description]
        input2_subdivided_path (Path, optional): [description]
        use_ogr (bool, optional): If True, ogr is used to do the processing,
            In this case different input files (input1_path, input2_path) are
            NOT supported. If False, sqlite3 is used directly.
            Defaults to False.
        output_with_spatial_index (bool, optional): True to create output file with
            spatial index. None to use the GDAL default. Defaults to None.
        tmp_dir (Path, optional): If None, a new temp dir will be created. if not None,
            the temp dir specified will be used. In both cases the tmp_dir will be
            removed after the operation if ConfigOptions.remove_temp_files is not False!

    Raises:
        ValueError: [description]

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    # Init
    logger = logging.getLogger(f"geofileops.{operation_name}")

    if isinstance(input1_columns, str):
        # If a string is passed, convert to list
        input1_columns = [input1_columns]
    if isinstance(input2_columns, str):
        # If a string is passed, convert to list
        input2_columns = [input2_columns]

    input1_layer, input2_layer, output_layer = _validate_params(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        input1_layer=input1_layer,
        input2_layer=input2_layer,
        output_layer=output_layer,
        operation_name=operation_name,
    )
    if use_ogr and input1_path != input2_path:
        raise ValueError(
            f"{operation_name}: if use_ogr True, input1_path should equal input2_path!"
        )
    if _io_util.output_exists(path=output_path, remove_if_exists=force):
        return

    if output_with_spatial_index is None:
        output_with_spatial_index = GeofileInfo(output_path).default_spatial_index

    # Check if spatialite is properly installed to execute this query
    _sqlite_util.spatialite_version_info()

    # Init layer info
    start_time = datetime.now()
    if tmp_dir is None:
        tmp_dir = _io_util.create_tempdir(f"geofileops/{operation_name}")

    # Check if crs are the same in the input layers + use it (if there is one)
    output_crs = _check_crs(input1_path, input1_layer, input2_path, input2_layer)

    # Prepare tmp output filename
    tmp_output_path = tmp_dir / output_path.name
    tmp_output_path.parent.mkdir(exist_ok=True, parents=True)
    gfo.remove(tmp_output_path, missing_ok=True)

    try:
        # Prepare tmp files/batches
        # -------------------------
        logger.debug(f"Prepare input (params), tempdir: {tmp_dir}")
        input1_path, input1_layer, input2_path, input2_layer = (
            _convert_to_spatialite_based(  # type: ignore[assignment]
                input1_path=input1_path,
                input1_layer=input1_layer,
                tempdir=tmp_dir,
                input2_path=input2_path,
                input2_layer=input2_layer,
            )
        )

        if input1_subdivided_path is not None:
            input1_layer_alias = "layer1_subdiv"
            filter_column = "fid_1"
        elif input2_subdivided_path is not None:
            input1_layer_alias = "layer1_subdiv"
            filter_column = "fid"
        else:
            input1_layer_alias = "layer1"
            filter_column = "rowid"

        processing_params = _prepare_processing_params(
            input1_path=input1_path,
            input1_subdivided_path=input1_subdivided_path,
            input1_layer=input1_layer,
            input1_layer_alias=input1_layer_alias,
            filter_column=filter_column,
            input2_path=input2_path,
            input2_layer=input2_layer,
            tempdir=tmp_dir,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
        )
        if processing_params is None or processing_params.batches is None:
            return

        # Do some checks on the placeholders
        sql_template_placeholders = [
            name for _, name, _, _ in string.Formatter().parse(sql_template) if name
        ]

        # Warn no if "{input*_databasename}". placeholders present
        if "input1_databasename" not in sql_template_placeholders:
            logger.warning(
                'A placeholder "{input1_databasename}". is recommended '
                "as prefix for the input1 layer/rtree/tables used in sql_stmt."
            )
        if "input2_databasename" not in sql_template_placeholders:
            logger.warning(
                'A placeholder "{input2_databasename}". is recommended '
                "as prefix for the input2 layer/rtree/tables used in sql_stmt."
            )

        # If multiple batches, mandatory "batch_filter" placeholder in sql_template
        nb_batches = len(processing_params.batches)
        if nb_batches > 1:
            if "batch_filter" not in sql_template_placeholders:
                raise ValueError(
                    "Number batches > 1 requires a batch_filter placeholder in "
                    f"sql_template {sql_template}"
                )

        # Prepare column names,... to format the select
        # ---------------------------------------------
        # Format column strings for use in select
        input1_layerinfo = gfo.get_layerinfo(
            input1_path, input1_layer, raise_on_nogeom=False
        )
        input1_col_strs = _ogr_sql_util.ColumnFormatter(
            columns_asked=input1_columns,
            columns_in_layer=input1_layerinfo.columns,
            fid_column=input1_layerinfo.fid_column,
            table_alias="layer1",
            column_alias_prefix=input1_columns_prefix,
        )
        assert input2_path is not None
        input2_layerinfo = gfo.get_layerinfo(
            input2_path,
            input2_layer,
            raise_on_nogeom=False,
        )
        input2_col_strs = _ogr_sql_util.ColumnFormatter(
            columns_asked=input2_columns,
            columns_in_layer=input2_layerinfo.columns,
            fid_column=input2_layerinfo.fid_column,
            table_alias="layer2",
            column_alias_prefix=input2_columns_prefix,
        )

        input1_subdiv_geometrycolumn = None
        if input1_subdivided_path is not None:
            input1_subdiv_info = gfo.get_layerinfo(input1_subdivided_path)
            input1_subdiv_geometrycolumn = input1_subdiv_info.geometrycolumn

        input2_subdiv_geometrycolumn = None
        if input2_subdivided_path is not None:
            input2_subdiv_info = gfo.get_layerinfo(input2_subdivided_path)
            input2_subdiv_geometrycolumn = input2_subdiv_info.geometrycolumn

        # Check input crs'es
        if input1_layerinfo.crs != input2_layerinfo.crs:
            logger.warning(
                f"input1 has a different crs than input2: \n\tinput1: "
                f"{input1_layerinfo.crs} \n\tinput2: {input2_layerinfo.crs}"
            )

        # Prepare the database names to fill out in the sql_template
        input_db_placeholders, input_db_names = _prepare_input_db_names(
            {
                "input1_databasename": input1_path,
                "input2_databasename": input2_path,
                "input1_subdiv_databasename": input1_subdivided_path,
                "input2_subdiv_databasename": input2_subdivided_path,
            },
            use_ogr=use_ogr,
        )

        # Fill out sql_template as much as possible already
        # -------------------------------------------------
        # Keep input1_tmp_layer and input2_tmp_layer for backwards compatibility
        sql_template = sql_template.format(
            **input_db_placeholders,
            layer1_columns_from_subselect_str=input1_col_strs.from_subselect(),
            layer1_columns_prefix_alias_str=input1_col_strs.prefixed_aliased(),
            layer1_columns_prefix_str=input1_col_strs.prefixed(),
            input1_layer=input1_layer,
            input1_tmp_layer=input1_layer,
            input1_geometrycolumn=input1_layerinfo.geometrycolumn,
            input1_subdiv_geometrycolumn=input1_subdiv_geometrycolumn,
            layer2_columns_from_subselect_str=input2_col_strs.from_subselect(),
            layer2_columns_prefix_alias_str=input2_col_strs.prefixed_aliased(),
            layer2_columns_prefix_str=input2_col_strs.prefixed(),
            layer2_columns_prefix_alias_null_str=input2_col_strs.null_aliased(),
            input2_layer=input2_layer,
            input2_tmp_layer=input2_layer,
            input2_geometrycolumn=input2_layerinfo.geometrycolumn,
            input2_subdiv_geometrycolumn=input2_subdiv_geometrycolumn,
            batch_filter="{batch_filter}",
        )

        # Determine column names and types based on sql statement
        column_datatypes = None
        # Use first batch_filter to improve performance
        sql_stmt = sql_template.format(
            batch_filter=processing_params.batches[0]["batch_filter"]
        )

        column_datatypes = _sqlite_util.get_columns(
            sql_stmt=sql_stmt, input_databases=input_db_names
        )

        # Apply gridsize if it is specified
        if gridsize != 0.0:
            if SPATIALITE_GTE_51:
                # Spatialite >= 5.1 available, so we can try ST_ReducePrecision first,
                # which should be faster.
                # ST_ReducePrecision seems to crash on EMPTY geometry, so check
                # ST_IsEmpty not being 0 (result can be -1, 0 or 1).
                gridsize_op = f"""
                    IIF(sub_gridsize.geom IS NULL OR ST_IsEmpty(sub_gridsize.geom) <> 0,
                        NULL,
                        IFNULL(
                            ST_ReducePrecision(sub_gridsize.geom, {gridsize}),
                            ST_GeomFromWKB(GFO_ReducePrecision(
                                ST_AsBinary(sub_gridsize.geom), {gridsize}
                            ))
                        )
                    )
                """
            else:
                gridsize_op = (
                    "ST_GeomFromWKB(GFO_ReducePrecision("
                    f"ST_AsBinary(sub_gridsize.geom), {gridsize}))"
                )

            # All columns need to be specified
            # Remark:
            # - use "LIMIT -1 OFFSET 0" to avoid the subquery flattening. Flattening
            #   "geom IS NOT NULL" leads to GFO_Difference_Collection calculated double!
            cols = [col for col in column_datatypes if col.lower() != "geom"]
            columns_to_select = _ogr_sql_util.columns_quoted(cols)
            sql_template = f"""
                SELECT * FROM
                  ( SELECT {gridsize_op} AS geom
                          {columns_to_select}
                      FROM ( {sql_template}
                              LIMIT -1 OFFSET 0
                      ) sub_gridsize
                     LIMIT -1 OFFSET 0
                  ) sub_gridsize2
                 WHERE sub_gridsize2.geom IS NOT NULL
            """

        # Prepare/apply where_post parameter
        if where_post is not None and not explodecollections:
            # explodecollections is not True, so we can add where_post to sql_stmt.
            # If explodecollections would be True, we need to wait to apply the
            # where_post till after explodecollections is applied, so when appending the
            # partial results to the output file.
            sql_template = f"""
                SELECT * FROM
                    ( {sql_template}
                      LIMIT -1 OFFSET 0
                    )
                 WHERE {where_post}
            """
            # where_post has been applied already so set to None.
            where_post = None

        # Calculate
        # ---------
        # Processing in threads is 2x faster for small datasets (on Windows)
        calculate_in_threads = True if input1_layerinfo.featurecount <= 100 else False
        logger.info(
            f"Start processing ({processing_params.nb_parallel} "
            f"parallel workers, batch size: {processing_params.batchsize})"
        )
        with _processing_util.PooledExecutorFactory(
            threadpool=calculate_in_threads,
            max_workers=processing_params.nb_parallel,
            initializer=_processing_util.initialize_worker(),
        ) as calculate_pool:
            # Start looping
            batches: dict[int, dict] = {}
            future_to_batch_id = {}
            for batch_id in processing_params.batches:
                batches[batch_id] = {}
                batches[batch_id]["layer"] = output_layer

                tmp_partial_output_path = (
                    tmp_dir / f"{output_path.stem}_{batch_id}.gpkg"
                )
                batches[batch_id]["tmp_partial_output_path"] = tmp_partial_output_path

                # Fill out final things in sql_template
                sql_stmt = sql_template.format(
                    input1_databasename="{input1_databasename}",
                    input2_databasename="{input2_databasename}",
                    input3_databasename="{input3_databasename}",
                    input4_databasename="{input4_databasename}",
                    batch_filter=processing_params.batches[batch_id]["batch_filter"],
                )
                batches[batch_id]["sqlite_stmt"] = sql_stmt

                # calculate_two_layers doesn't support explodecollections in one step:
                # there is an extra layer copy involved.
                # Normally explodecollections can be deferred to the appending of the
                # partial files, but if explodecollections and there is a where_post to
                # be applied, it needs to be applied now already. Otherwise the
                # where_post in the append of partial files later on won't give correct
                # results!
                explodecollections_now = False
                output_geometrytype_now = force_output_geometrytype
                if explodecollections and where_post is not None:
                    explodecollections_now = True
                if (
                    force_output_geometrytype is not None
                    and explodecollections
                    and not explodecollections_now
                ):
                    # convert geometrytype to multitype to avoid ogr warnings
                    output_geometrytype_now = force_output_geometrytype.to_multitype

                # Remark: this temp file doesn't need spatial index
                future = calculate_pool.submit(
                    _calculate_two_layers,
                    input_databases=input_db_names,
                    output_path=tmp_partial_output_path,
                    sql_stmt=sql_stmt,
                    output_layer=output_layer,
                    explodecollections=explodecollections_now,
                    force_output_geometrytype=output_geometrytype_now,
                    output_crs=output_crs,
                    use_ogr=use_ogr,
                    create_spatial_index=False,
                    column_datatypes=column_datatypes,
                )
                future_to_batch_id[future] = batch_id

            # Loop till all parallel processes are ready, but process each one
            # that is ready already
            nb_done = 0
            _general_util.report_progress(
                start_time,
                nb_done,
                nb_batches,
                operation_name,
                processing_params.nb_parallel,
            )
            for future in futures.as_completed(future_to_batch_id):
                try:
                    # Get the result
                    result = future.result()
                    if result is not None:
                        logger.debug(f"{result}")
                except Exception as ex:
                    batch_id = future_to_batch_id[future]
                    error = str(ex).partition("\n")[0]
                    message = f"Error <{error}> executing {batches[batch_id]}"
                    logger.exception(message)
                    raise Exception(message) from ex

                # If the calculate gave results, copy/append to output
                batch_id = future_to_batch_id[future]
                tmp_partial_output_path = batches[batch_id]["tmp_partial_output_path"]
                nb_done += 1

                # Normally all partial files should exist, but to be sure...
                if not tmp_partial_output_path.exists():
                    logger.warning(f"Result file {tmp_partial_output_path} not found")
                    continue

                # If there is only one tmp_partial file and it is already ok as
                # output file, just rename/move it.
                if (
                    nb_batches == 1
                    and not explodecollections
                    and force_output_geometrytype is None
                    and where_post is None
                    and tmp_partial_output_path.suffix.lower()
                    == tmp_output_path.suffix.lower()
                ):
                    gfo.move(tmp_partial_output_path, tmp_output_path)
                else:
                    # If there is only one batch, it is faster to create the spatial
                    # index immediately
                    create_spatial_index = (
                        True if nb_batches == 1 and output_with_spatial_index else False
                    )

                    fileops._append_to_nolock(
                        src=tmp_partial_output_path,
                        dst=tmp_output_path,
                        explodecollections=explodecollections,
                        force_output_geometrytype=force_output_geometrytype,
                        where=where_post,
                        create_spatial_index=create_spatial_index,
                        preserve_fid=False,
                    )
                    gfo.remove(tmp_partial_output_path)

                # Log the progress and prediction speed
                _general_util.report_progress(
                    start_time=start_time,
                    nb_done=nb_done,
                    nb_todo=nb_batches,
                    operation=operation_name,
                    nb_parallel=processing_params.nb_parallel,
                )

        # Round up and clean up
        # Now create spatial index and move to output location
        if tmp_output_path.exists():
            if output_with_spatial_index:
                gfo.create_spatial_index(
                    path=tmp_output_path,
                    layer=output_layer,
                    exist_ok=True,
                    no_geom_ok=True,
                )
            if tmp_output_path != output_path:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                gfo.move(tmp_output_path, output_path)
        else:
            logger.debug("Result was empty!")

        logger.info(f"Ready, took {datetime.now()-start_time}")

    except Exception:
        gfo.remove(output_path, missing_ok=True)
        gfo.remove(tmp_output_path, missing_ok=True)
        raise
    finally:
        if ConfigOptions.remove_temp_files:
            shutil.rmtree(tmp_dir, ignore_errors=True)


def _validate_params(
    input1_path: Path,
    input2_path: Path,
    output_path: Path,
    input1_layer: Optional[str],
    input2_layer: Optional[str],
    output_layer: Optional[str],
    operation_name: str,
) -> tuple[str, str, str]:
    """Validate the input parameters, return the layer names.

    Args:
        input1_path (Path): _description_
        input2_path (Path): _description_
        output_path (Path): _description_
        input1_layer (Optional[str]): _description_
        input2_layer (Optional[str]): _description_
        output_layer (Optional[str]): _description_
        operation_name (str): _description_

    Raises:
        ValueError: when an invalid parameter was passed.

    Returns:
        tuple[str, str, str]: a tuple with the layer names: input1_layer,
            input2_layer, output_layer
    """
    if not input1_path.exists():
        raise ValueError(f"{operation_name}: input1_path doesn't exist: {input1_path}")
    if not input2_path.exists():
        raise ValueError(f"{operation_name}: input2_path doesn't exist: {input2_path}")
    if output_path in (input1_path, input2_path):
        raise ValueError(
            f"{operation_name}: output_path must not equal one of input paths"
        )

    # Get layer names
    if input1_layer is None:
        input1_layer = gfo.get_only_layer(input1_path)
    if input2_layer is None:
        input2_layer = gfo.get_only_layer(input2_path)
    if output_layer is None:
        output_layer = gfo.get_default_layer(output_path)

    return input1_layer, input2_layer, output_layer


def _prepare_input_db_names(
    input_paths: dict[str, Optional[Path]], use_ogr: bool
) -> tuple[dict, dict]:
    placeholders_to_name: dict[str, Optional[str]] = {}
    names_to_path: dict[str, Path] = {}
    for index, (placeholder, path) in enumerate(input_paths.items()):
        # If path is already in input_databases, reuse the db_name
        db_name = None
        for name, cur_path in names_to_path.items():
            if cur_path == path:
                db_name = name
                break

        if db_name is None and path is not None:
            if use_ogr:
                # use_ogr needs main as dbname
                db_name = "main"
            else:
                db_name = f"input{index + 1}"

        placeholders_to_name[placeholder] = db_name
        if db_name is not None and path is not None:
            names_to_path[db_name] = path

    return placeholders_to_name, names_to_path


def _check_crs(
    input1_path: Path, input1_layer: str, input2_path: Path, input2_layer: str
) -> int:
    input1_info = gfo.get_layerinfo(input1_path, input1_layer, raise_on_nogeom=False)
    input2_info = None
    if input2_path is not None:
        input2_info = gfo.get_layerinfo(
            input2_path, input2_layer, raise_on_nogeom=False
        )
    crs_epsg = -1
    if input1_info.crs is not None:
        crs_epsg1 = input1_info.crs.to_epsg()
        if crs_epsg1 is not None:
            crs_epsg = crs_epsg1
        # If input 2 also has a crs, check if it is the same.
        if (
            input2_info is not None
            and input2_info.crs is not None
            and crs_epsg1 != input2_info.crs.to_epsg()
        ):
            warnings.warn(
                "input1 layer doesn't have the same crs as input2 layer: "
                f"{input1_info.crs} vs {input2_info.crs}",
                stacklevel=5,
            )
    elif input2_info is not None and input2_info.crs is not None:
        crs_epsg2 = input2_info.crs.to_epsg()
        if crs_epsg2 is not None:
            crs_epsg = crs_epsg2

    return crs_epsg


def _calculate_two_layers(
    input_databases: dict[str, Path],
    output_path: Path,
    sql_stmt: str,
    output_layer: str,
    explodecollections: bool,
    force_output_geometrytype: Optional[GeometryType],
    output_crs: int,
    create_spatial_index: bool,
    column_datatypes: dict,
    use_ogr: bool,
):
    if not use_ogr:
        # If explodecollections, write first to tmp file, then apply explodecollections
        # to the final output file.
        output_tmp_path = output_path
        if explodecollections:
            output_name = f"{output_path.stem}_tmp{output_path.suffix}"
            output_tmp_path = output_path.parent / output_name

        _sqlite_util.create_table_as_sql(
            input_databases=input_databases,
            output_path=output_tmp_path,
            sql_stmt=sql_stmt,
            output_layer=output_layer,
            output_geometrytype=force_output_geometrytype,
            output_crs=output_crs,
            create_spatial_index=create_spatial_index,
            profile=_sqlite_util.SqliteProfile.SPEED,
            column_datatypes=column_datatypes,
        )

        if explodecollections:
            _ogr_util.vector_translate(
                input_path=output_tmp_path,
                input_layers=output_layer,
                output_path=output_path,
                output_layer=output_layer,
                explodecollections=explodecollections,
                force_output_geometrytype=force_output_geometrytype,
                options={"LAYER_CREATION.SPATIAL_INDEX": create_spatial_index},
                preserve_fid=False,
            )
            gfo.remove(output_tmp_path)
    else:
        # Use ogr to run the query
        #   * input2 path (= using attach) doesn't seem to work at time of writing
        if len(input_databases) != 1:
            raise ValueError("use_ogr=True only supports one input file")

        _ogr_util.vector_translate(
            input_path=next(iter(input_databases.values())),
            output_path=output_path,
            sql_stmt=sql_stmt,
            output_layer=output_layer,
            explodecollections=explodecollections,
            force_output_geometrytype=force_output_geometrytype,
            options={"LAYER_CREATION.SPATIAL_INDEX": create_spatial_index},
        )


class ProcessingParams:
    def __init__(
        self,
        nb_parallel: int,
        batches: dict,
        batchsize: int,
    ):
        self.nb_parallel = nb_parallel
        self.batches = batches
        self.batchsize = batchsize

    def to_json(self, path: Path):
        prepared = _general_util.prepare_for_serialize(vars(self))
        with open(path, "w") as file:
            file.write(json.dumps(prepared, indent=4, sort_keys=True))


def _convert_to_spatialite_based(
    input1_path: Path,
    input1_layer: str,
    tempdir: Path,
    input2_path: Optional[Path] = None,
    input2_layer: Optional[str] = None,
) -> tuple[Path, str, Optional[Path], Optional[str]]:
    """Prepare input files for the calculation.

    The input files should be spatialite based, and should be of the same type: either
    both GPKG, or both SQLite.
    """
    input1_info = _geofileinfo.get_geofileinfo(input1_path)
    input2_info = (
        None if input2_path is None else _geofileinfo.get_geofileinfo(input2_path)
    )

    # If input1 is spatialite based and compatible with input2, no conversion.
    if input1_info.is_spatialite_based and (
        input1_info.driver == "GPKG"
        or input2_info is None
        or input2_info.driver == input2_info.driver
    ):
        if input1_info.driver == "GPKG":
            # HasSpatialindex doesn't work for spatialite files.
            gfo.create_spatial_index(
                input1_path, input1_layer, exist_ok=True, no_geom_ok=True
            )
    else:
        # input1 is not spatialite compatible, so convert it.
        # If input2 is "Sqlite", convert input1 to SQLite as well.
        suffix = ".gpkg"
        if input2_info is not None and input2_info.driver == "SQLite":
            suffix = ".sqlite"
        input1_tmp_path = tempdir / f"{input1_path.stem}{suffix}"
        gfo.copy_layer(
            src=input1_path,
            src_layer=input1_layer,
            dst=input1_tmp_path,
            dst_layer=input1_layer,
            preserve_fid=True,
        )
        input1_path = input1_tmp_path
        input1_info = _geofileinfo.get_geofileinfo(input1_path)
        if input1_info.driver == "SQLite":
            # In sqlite, the layer name is sometimes changed...
            input1_layer = gfo.get_only_layer(input1_path)

    # If input2 is spatialite_based and compatible with input1, no conversion.
    if input2_path is not None and input2_info is not None:
        if input2_info.is_spatialite_based and input2_info.driver == input1_info.driver:
            if input2_info.driver == "GPKG":
                # HasSpatialindex doesn't work for spatialite files.
                gfo.create_spatial_index(
                    input2_path, input2_layer, exist_ok=True, no_geom_ok=True
                )
        else:
            # input2 is not spatialite compatible, so convert it.
            # If input1 is "Sqlite", convert input2 to SQLite as well.
            suffix = ".gpkg"
            if input1_info is not None and input1_info.driver == "SQLite":
                suffix = ".sqlite"
            input2_tmp_path = tempdir / f"{input2_path.stem}{suffix}"

            # Make sure the copy is taken to a separate file.
            if input2_tmp_path.exists():
                input2_tmp_path = tempdir / f"{input2_path.stem}2{suffix}"
            gfo.copy_layer(
                src=input2_path,
                src_layer=input2_layer,
                dst=input2_tmp_path,
                dst_layer=input2_layer,
                preserve_fid=True,
            )
            input2_path = input2_tmp_path
            input2_info = _geofileinfo.get_geofileinfo(input2_path)
            if input2_info.driver == "SQLite":
                # In sqlite, the layer name is sometimes changed...
                input2_layer = gfo.get_only_layer(input2_path)

    return input1_path, input1_layer, input2_path, input2_layer


def _prepare_processing_params(
    input1_path: Path,
    input1_layer: str,
    tempdir: Path,
    nb_parallel: int,
    batchsize: int = -1,
    input1_layer_alias: Optional[str] = None,
    filter_column: str = "rowid",
    input1_subdivided_path: Optional[Path] = None,
    input2_path: Optional[Path] = None,
    input2_layer: Optional[str] = None,
) -> Optional[ProcessingParams]:
    # Prepare batches to process
    layer1_info = gfo.get_layerinfo(
        input1_subdivided_path or input1_path, input1_layer, raise_on_nogeom=False
    )
    nb_rows_input_layer = layer1_info.featurecount

    # Determine optimal number of batches
    nb_parallel, nb_batches = _determine_nb_batches(
        nb_rows_input_layer=nb_rows_input_layer,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        is_twolayer_operation=input2_path is not None,
    )

    # Check number of batches + appoint nb rows to batches
    batches: dict[int, dict] = {}
    if nb_batches == 1:
        # If only one batch, no filtering is needed
        batches[0] = {}
        batches[0]["input1_path"] = input1_path
        batches[0]["input1_layer"] = input1_layer
        batches[0]["input2_path"] = input2_path
        batches[0]["input2_layer"] = input2_layer
        batches[0]["batch_filter"] = ""

    else:
        if input1_subdivided_path is not None:
            # input1 is subdivided, so determine batches based on the fid_1
            nb_rows_per_batch = round(nb_rows_input_layer / (nb_batches))
            # Remark: ROW_NUMBER() is one-based!
            sql_stmt = f"""
                SELECT DISTINCT fid_1 AS start_id FROM (
                    SELECT ROW_NUMBER() OVER (ORDER BY fid_1) AS rownumber, *
                      FROM "{layer1_info.name}"
                    )
                 WHERE (rownumber = 1 OR rownumber % {nb_rows_per_batch} = 0)
            """
            batch_info_df = gfo.read_file(
                path=input1_subdivided_path, sql_stmt=sql_stmt, sql_dialect="SQLITE"
            )

            batch_info_df.reset_index(names=["batch_id"], inplace=True)
            nb_batches = len(batch_info_df)

        else:
            # Determine the min_rowid and max_rowid
            # Remark: SELECT MIN(rowid), MAX(rowid) ... is a lot slower than UNION ALL!
            sql_stmt = f"""
                SELECT MIN(rowid) minmax_rowid FROM "{layer1_info.name}"
                UNION ALL
                SELECT MAX(rowid) minmax_rowid FROM "{layer1_info.name}"
            """
            batch_info_df = gfo.read_file(
                path=input1_path, sql_stmt=sql_stmt, sql_dialect="SQLITE"
            )
            min_rowid = pd.to_numeric(batch_info_df["minmax_rowid"][0]).item()
            max_rowid = pd.to_numeric(batch_info_df["minmax_rowid"][1]).item()

            # Determine the exact batches to use
            if ((max_rowid - min_rowid) / nb_rows_input_layer) < 1.1:
                # If the rowid's are quite consecutive, use an imperfect, but
                # fast distribution in batches
                batch_info_list = []
                start_id = min_rowid
                offset_per_batch = round((max_rowid - min_rowid) / nb_batches)
                for batch_id in range(nb_batches):
                    batch_info_list.append((batch_id, start_id))
                    start_id += offset_per_batch

                batch_info_df = pd.DataFrame(
                    batch_info_list, columns=["batch_id", "start_id"]
                )
            else:
                # The rowids are not consecutive, so determine the optimal rowid
                # ranges for each batch so each batch has same number of elements
                # Remark: - this might take some seconds for larger datasets!
                #         - (batch_id - 1) AS id to make the id zero-based
                sql_stmt = f"""
                    SELECT (batch_id - 1) AS batch_id
                        ,MIN(rowid) AS start_id
                    FROM
                        ( SELECT rowid
                                ,NTILE({nb_batches}) OVER (ORDER BY rowid) batch_id
                            FROM "{layer1_info.name}"
                        )
                    GROUP BY batch_id;
                """
                batch_info_df = gfo.read_file(path=input1_path, sql_stmt=sql_stmt)

        # Prepare the layer alias to use in the batch filter
        layer_alias_d = ""
        if input1_layer_alias is not None:
            layer_alias_d = f"{input1_layer_alias}."

        # The end_id is the start_id of the next batch - 1
        batch_info_df["end_id"] = batch_info_df["start_id"].shift(-1) - 1

        # Now loop over all batch ranges to build up the necessary filters
        for batch_id, start_id, end_id in batch_info_df.itertuples(index=False):
            # The batch filter
            batch_filter = f"{layer_alias_d}{filter_column} >= {int(start_id)}"
            if not np.isnan(end_id).item():
                # There is an end_id specified, so add it to the filter
                batch_filter += f" AND {layer_alias_d}{filter_column} <= {int(end_id)}"
            batch_filter = f"AND ({batch_filter}) "

            # Fill out the batch properties
            batches[batch_id] = {
                "input1_path": input1_path,
                "input1_layer": input1_layer,
                "input2_path": input2_path,
                "input2_layer": input2_layer,
                "batch_filter": batch_filter,
            }

    # No use starting more processes than the number of batches...
    nb_parallel = min(len(batches), nb_parallel)

    returnvalue = ProcessingParams(
        nb_parallel=nb_parallel,
        batches=batches,
        batchsize=int(nb_rows_input_layer / len(batches)),
    )
    returnvalue.to_json(tempdir / "processing_params.json")
    return returnvalue


def _determine_nb_batches(
    nb_rows_input_layer: int,
    nb_parallel: int,
    batchsize: int,
    is_twolayer_operation: bool,
    cpu_count: Optional[int] = None,
) -> tuple[int, int]:
    """Determine an optimal number of batches and parallel workers.

    Args:
        nb_rows_input_layer (int): number of input rows
        nb_parallel (int): recommended number of workers
        batchsize (int): recommended number of rows per batch
        is_twolayer_operation (bool): True if optimization for a two layer operation,
            False if it involves a single layer operation.
        cpu_count (int, optional): the number of CPU's available. If None, this is
            determined automatically if needed.

    Returns:
        Tuple[int, int]: Tuple of (nb_parallel, nb_batches)
    """
    # If no or 1 input rows or if 1 parallel worker is asked
    # Remark: especially for 'select' operation, if nb_parallel is 1 nb_batches should
    # be 1 (select might give wrong results)
    if nb_rows_input_layer <= 1 or nb_parallel == 1:
        return (1, 1)

    if cpu_count is None:
        cpu_count = multiprocessing.cpu_count()

    # Determine the optimal number of parallel workers
    if nb_parallel == -1:
        # If no batch size specified, put at least 100 rows in a batch
        if batchsize <= 0:
            min_rows_per_batch = 100
        else:
            # If batchsize is specified, use the batch size
            min_rows_per_batch = batchsize

        max_parallel = max(int(nb_rows_input_layer / min_rows_per_batch), 1)
        nb_parallel = min(cpu_count, max_parallel)

    # Determine optimal number of batches
    if nb_parallel > 1:
        # Limit number of rows processed in parallel to limit memory use
        if batchsize > 0:
            max_rows_parallel = batchsize * nb_parallel
        else:
            max_rows_parallel = 1000000
            if is_twolayer_operation:
                max_rows_parallel = 200000

        # Adapt number of batches to max_rows_parallel
        if nb_rows_input_layer > max_rows_parallel:
            # If more rows than can be handled simultanously in parallel
            nb_batches = math.ceil(
                nb_rows_input_layer / (max_rows_parallel / nb_parallel)
            )
            # Round up to the nearest multiple of nb_parallel
            nb_batches = math.ceil(nb_batches / nb_parallel) * nb_parallel
        elif batchsize > 0:
            # If a batchsize is specified, try to honer it
            nb_batches = nb_parallel
        else:
            nb_batches = nb_parallel

            # If no batchsize specified and 2 layer processing, add some batches to
            # reduce impact of possible unbalanced batches on total processing time.
            if is_twolayer_operation:
                nb_batches *= 2

    elif batchsize > 0:
        nb_batches = math.ceil(nb_rows_input_layer / batchsize)

    else:
        nb_batches = 1

    # If more batches than rows, limit nb batches
    nb_batches = min(nb_batches, nb_rows_input_layer)
    # If more parallel than number of batches, limit nb_parallel
    nb_parallel = min(nb_parallel, nb_batches)

    return (nb_parallel, nb_batches)


def dissolve_singlethread(
    input_path: Path,
    output_path: Path,
    groupby_columns: Union[str, Iterable[str], None] = None,
    agg_columns: Optional[dict] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = False,
    where_post: Optional[str] = None,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    force: bool = False,
):
    """Remark: this is not a parallelized version!!!"""
    # Init
    logger = logging.getLogger("geofileops.dissolve")
    start_time = datetime.now()

    # Check input params
    if not input_path.exists():
        raise ValueError(f"input_path doesn't exist: {input_path}")
    if input_path == output_path:
        raise ValueError("output_path must not equal input_path")
    if where_post is not None and where_post == "":
        where_post = None

    # Check layer names
    if input_layer is None:
        input_layer = gfo.get_only_layer(input_path)
    if output_layer is None:
        output_layer = gfo.get_default_layer(output_path)

    # Use get_layerinfo to check if the layer definition is OK
    input_layerinfo = gfo.get_layerinfo(input_path, input_layer)
    fid_column = (
        input_layerinfo.fid_column if input_layerinfo.fid_column != "" else "rowid"
    )

    # Prepare some lists for later use
    columns_available = list(input_layerinfo.columns) + ["fid"]
    columns_available_upper = [column.upper() for column in columns_available]
    groupby_columns_upper_dict = {}
    if groupby_columns is not None:
        groupby_columns_upper_dict = {col.upper(): col for col in groupby_columns}

    # Prepare the strings regarding groupby_columns to use in the select statement.
    if groupby_columns is not None:
        # Standardize parameter to simplify the rest of the code
        if isinstance(groupby_columns, str):
            # If a string is passed, convert to list
            groupby_columns = [groupby_columns]

        # Check if all groupby columns exist
        for column in groupby_columns:
            if column.upper() not in columns_available_upper:
                raise ValueError(f"column in groupby_columns not in input: {column}")

        # Because the query uses a subselect, the groupby columns need to be prefixed.
        columns_prefixed = [f'layer."{column}"' for column in groupby_columns]
        groupby_columns_for_groupby_str = ", ".join(columns_prefixed)
        columns_prefixed_aliased = [
            f'layer."{column}" "{column}"' for column in groupby_columns
        ]
        groupby_columns_for_select_str = f", {', '.join(columns_prefixed_aliased)}"
    else:
        # Even if no groupby is provided, we still need to use a groupby clause,
        # otherwise ST_union doesn't seem to work.
        groupby_columns_for_groupby_str = "'1'"
        groupby_columns_for_select_str = ""

    # Prepare the strings regarding agg_columns to use in the select statement.
    agg_columns_str = ""
    if agg_columns is not None:
        # Validate the dict structure, so we can assume everything is OK further on
        _parameter_helper.validate_agg_columns(agg_columns)

        # Start preparation of agg_columns_str
        if "json" in agg_columns:
            # Determine the columns to be put in json
            columns = []
            if agg_columns["json"] is None:
                # If columns specified is None: all columns not in groupby_columns
                for column in input_layerinfo.columns:
                    if column.upper() not in groupby_columns_upper_dict:
                        columns.append(column)
            else:
                for column in agg_columns["json"]:
                    columns.append(column)
            json_columns = [f"'{column}', layer.\"{column}\"" for column in columns]

            # The fid should be added as well, but make name unique
            fid_orig_column = "fid_orig"
            for idx in range(99999):
                if idx != 0:
                    fid_orig_column = f"fid_orig{idx}"
                if fid_orig_column not in columns:
                    break
            json_columns.append(f"'{fid_orig_column}', layer.\"{fid_column}\"")

            # Now we are ready to prepare final str
            agg_columns_str = (
                f", json_group_array(json_object({', '.join(json_columns)})) as json"
            )
        elif "columns" in agg_columns:
            for agg_column in agg_columns["columns"]:
                # Init
                distinct_str = ""
                extra_param_str = ""

                # Prepare aggregation keyword
                if agg_column["agg"].lower() in [
                    "count",
                    "sum",
                    "min",
                    "max",
                    "median",
                ]:
                    aggregation_str = agg_column["agg"]
                elif agg_column["agg"].lower() in ["mean", "avg"]:
                    aggregation_str = "avg"
                elif agg_column["agg"].lower() == "concat":
                    aggregation_str = "group_concat"
                    if "sep" in agg_column:
                        extra_param_str = f", '{agg_column['sep']}'"
                else:
                    raise ValueError(f"aggregation {agg_column['agg']} not supported!")

                # If distinct is specified, add the distinct keyword
                if "distinct" in agg_column and agg_column["distinct"] is True:
                    distinct_str = "DISTINCT "

                # Prepare column name string
                column = agg_column["column"]
                if column.upper() not in columns_available_upper:
                    raise ValueError(f"{column} not available in: {columns_available}")
                if column.upper() == "FID":
                    column_str = f'layer."{fid_column}"'
                else:
                    column_str = f'layer."{column}"'

                # Now put everything together
                agg_columns_str += (
                    f", {aggregation_str}({distinct_str}{column_str}{extra_param_str}) "
                    f'AS "{agg_column["as"]}"'
                )

    # Check output path
    if _io_util.output_exists(path=output_path, remove_if_exists=force):
        return

    # Now prepare the sql statement
    # Remark: calculating the area in the enclosing selects halves the processing time

    # The operation to run on the geometry
    operation = f"ST_union(layer.{input_layerinfo.geometrycolumn})"

    # If the input is a linestring, also apply st_linemerge(), otherwise the individual
    # lines are just concatenated together and common points are not removed, resulting
    # in the original seperate lines again if explodecollections is True.
    if input_layerinfo.geometrytype.to_primitivetype == PrimitiveType.LINESTRING:
        operation = f"ST_LineMerge({operation})"

    # If the output file results in no rows gdal needs force_output_geometrytype to be
    # able to create an empty output file with the right geometry type.
    if explodecollections:
        force_output_geometrytype = input_layerinfo.geometrytype.to_singletype
    else:
        force_output_geometrytype = input_layerinfo.geometrytype.to_multitype

    # Apply tolerance gridsize on result
    if gridsize != 0.0:
        operation = _format_apply_gridsize_operation(
            geometrycolumn=operation,
            gridsize=gridsize,
            force_output_geometrytype=force_output_geometrytype,
        )

    # Now the sql query can be assembled
    sql_stmt = f"""
        SELECT {operation} AS geom
              {groupby_columns_for_select_str}
              {agg_columns_str}
          FROM "{input_layer}" layer
         GROUP BY {groupby_columns_for_groupby_str}
    """

    # If empty/null geometries don't need to be kept, filter them away
    if not keep_empty_geoms:
        sql_stmt = f"""
            SELECT * FROM
                ( {sql_stmt}
                )
             WHERE geom IS NOT NULL
        """

    # Prepare/apply where_post parameter
    if where_post is not None and not explodecollections:
        # explodecollections is not True, so we can add where_post to sql_stmt.
        # If explodecollections would be True, we need to wait to apply the
        # where_post till after explodecollections is applied, so when appending
        # the partial results to the output file.
        where_post = where_post.format(geometrycolumn="geom")
        sql_stmt = f"""
            SELECT * FROM
                ( {sql_stmt}
                )
             WHERE {where_post}
        """
        # where_post has been applied already so set to None.
        where_post = None

    # When null geometries are being kept, we need to make sure the geom in the
    # first row is not NULL because of a bug in gdal, so add ORDER BY as last step.
    #   -> https://github.com/geofileops/geofileops/issues/308
    if keep_empty_geoms:
        sql_stmt = f"""
            SELECT * FROM
                ( {sql_stmt}
                )
             ORDER BY geom IS NULL
        """

    # Now we can really start
    tempdir = _io_util.create_tempdir("geofileops/dissolve_singlethread")
    try:
        suffix = output_path.suffix
        options = {}
        if where_post is not None:
            # where_post needs to be applied still, so no spatial index needed
            options["LAYER_CREATION.SPATIAL_INDEX"] = False
            suffix = ".gpkg"
        tmp_output_path = tempdir / f"output_tmp{suffix}"

        _ogr_util.vector_translate(
            input_path=input_path,
            output_path=tmp_output_path,
            output_layer=output_layer,
            sql_stmt=sql_stmt,
            sql_dialect="SQLITE",
            force_output_geometrytype=force_output_geometrytype,
            explodecollections=explodecollections,
            options=options,
        )

        # We still need to apply the where_post filter
        if where_post is not None:
            tmp_output_where_path = tempdir / f"output_tmp2_where{output_path.suffix}"
            tmp_output_info = gfo.get_layerinfo(tmp_output_path)
            where_post = where_post.format(
                geometrycolumn=tmp_output_info.geometrycolumn
            )
            sql_stmt = f"""
                SELECT * FROM "{output_layer}"
                 WHERE {where_post}
            """
            _ogr_util.vector_translate(
                input_path=tmp_output_path,
                output_path=tmp_output_where_path,
                output_layer=output_layer,
                force_output_geometrytype=force_output_geometrytype,
                sql_stmt=sql_stmt,
                sql_dialect="SQLITE",
            )
            tmp_output_path = tmp_output_where_path

        # Now we are ready to move the result to the final spot...
        gfo.move(tmp_output_path, output_path)

    finally:
        if ConfigOptions.remove_temp_files:
            shutil.rmtree(tempdir, ignore_errors=True)

    logger.info(f"Ready, took {datetime.now()-start_time}")


def _format_apply_gridsize_operation(
    geometrycolumn: str, gridsize: float, force_output_geometrytype: GeometryType
) -> str:
    if SPATIALITE_GTE_51:
        # ST_ReducePrecision and GeosMakeValid only available for spatialite >= 5.1
        # Retry with applying makevalid.
        # It is not possible to return the original geometry if error stays after
        # makevalid, because spatialite functions return NULL for failures as well as
        # when the result is correctly NULL, so not possible to make the distinction.
        # ST_ReducePrecision seems to crash on EMPTY geometry, so check ST_IsEmpty not
        # being 0 (result can be -1, 0 or 1).
        gridsize_op = f"""
            IIF({geometrycolumn} IS NULL OR ST_IsEmpty({geometrycolumn}) <> 0,
                NULL,
                IFNULL(
                    ST_ReducePrecision({geometrycolumn}, {gridsize}),
                    ST_ReducePrecision(GeosMakeValid({geometrycolumn}, 0), {gridsize})
                )
            )
        """
    else:
        # Apply snaptogrid, but this results in invalid geometries, so also
        # Makevalid.
        gridsize_op = f"ST_MakeValid(SnapToGrid({geometrycolumn}, {gridsize}))"

        # SnapToGrid + ST_MakeValid can result in collapsed (pieces of)
        # geometries, so finally apply collectionextract as well.
        if force_output_geometrytype is None:
            warnings.warn(
                "a gridsize is specified but no force_output_geometrytype, "
                "this can result in inconsistent geometries in the output",
                stacklevel=3,
            )
        else:
            primitivetypeid = force_output_geometrytype.to_primitivetype.value
            gridsize_op = f"ST_CollectionExtract({gridsize_op}, {primitivetypeid})"

    return gridsize_op
