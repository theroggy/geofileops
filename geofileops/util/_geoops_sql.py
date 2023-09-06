"""
Module containing the implementation of Geofile operations using a sql statement.
"""

from concurrent import futures
from datetime import datetime
import json
import logging
import logging.config
import math
import multiprocessing
from pathlib import Path
import shutil
import string
from typing import Dict, Iterable, List, Literal, Optional, Union
import warnings

import pandas as pd

import geofileops as gfo
from geofileops import GeofileType, GeometryType, PrimitiveType
from geofileops import fileops
from geofileops.fileops import _append_to_nolock
from geofileops.util import _general_util
from geofileops.util import _io_util
from geofileops.util import _ogr_sql_util
from geofileops.util import _ogr_util
from geofileops.helpers import _parameter_helper
from geofileops.util import _processing_util
from geofileops.util import _sqlite_util

################################################################################
# Some init
################################################################################

logger = logging.getLogger(__name__)

################################################################################
# Operations on one layer
################################################################################


def buffer(
    input_path: Path,
    output_path: Path,
    distance: float,
    quadrantsegments: int = 5,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = True,
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
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = False,  # Should become True
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
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    keep_empty_geoms: bool = True,
    where_post: Optional[str] = None,
    force: bool = False,
):
    # The query as written doesn't give correct results when parallellized,
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
    columns: Optional[List[str]] = None,
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
    if validate_attribute_data:
        try:
            input_geofiletype = GeofileType(input_path)
            if input_geofiletype.is_spatialite_based:
                _sqlite_util.test_data_integrity(path=input_path)
                logger.debug("test_data_integrity was succesfull")
        except Exception:
            logger.exception(
                f"nb_invalid_geoms: {nb_invalid_geoms} + some attributes could not be "
                "read!"
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
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    force_output_geometrytype: Optional[GeometryType] = None,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = True,
    where_post: Optional[str] = None,
    validate_attribute_data: bool = False,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    # If output file exists already, either clean up or return...
    operation_name = "makevalid"
    if not force and output_path.exists():
        logger.info(f"Stop {operation_name}: output exists already {output_path}")
        return

    # Init + prepare sql template for this operation
    # ----------------------------------------------
    operation = "{geometrycolumn}"

    # If the precision needs to be reduced, snap to grid
    if gridsize != 0.0:
        operation = f"ST_SnapToGrid({operation}, {gridsize})"

    # Prepare sql template for this operation
    operation = f"ST_MakeValid({operation})"

    # Determine output_geometrytype if it wasn't specified. Otherwise makevalid results
    # in column type 'GEOMETRY'/'UNKNOWN(ANY)'
    input_layerinfo = gfo.get_layerinfo(input_path, input_layer)
    if force_output_geometrytype is None:
        force_output_geometrytype = input_layerinfo.geometrytype

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
        gridsize=0.0,
        keep_empty_geoms=keep_empty_geoms,
        where_post=where_post,
        sql_dialect="SQLITE",
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )

    # If asked and output is spatialite based, check if all data can be read
    if validate_attribute_data:
        output_geofiletype = GeofileType(input_path)
        if output_geofiletype.is_spatialite_based:
            _sqlite_util.test_data_integrity(path=input_path)


def select(
    input_path: Path,
    output_path: Path,
    sql_stmt: str,
    sql_dialect: Optional[Literal["SQLITE", "OGRSQL"]] = "SQLITE",
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    force_output_geometrytype: Optional[GeometryType] = None,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = True,
    nb_parallel: int = 1,
    batchsize: int = -1,
    force: bool = False,
):
    # Check if output exists already here, to avoid to much logging to be written
    if output_path.exists():
        if force is False:
            logger.info(f"Stop select: output exists already {output_path}")
            return
    logger.debug(f"  -> select to execute:\n{sql_stmt}")

    # If no output geometrytype is specified, use the geometrytype of the input layer
    if force_output_geometrytype is None:
        force_output_geometrytype = gfo.get_layerinfo(
            input_path, input_layer, raise_on_nogeom=False
        ).geometrytype
        logger.info(
            "No force_output_geometrytype specified, so defaults to input layer "
            f"geometrytype: {force_output_geometrytype}"
        )

    # Go!
    return _single_layer_vector_operation(
        input_path=input_path,
        output_path=output_path,
        sql_template=sql_stmt,
        geom_selected=None,
        operation_name="select",
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
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = True,
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
    columns: Optional[List[str]],
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
    # Init
    start_time = datetime.now()

    # Check/clean input parameters...
    if not input_path.exists():
        raise ValueError(f"{operation_name}: input_path doesn't exist: {input_path}")
    if input_path == output_path:
        raise ValueError(f"{operation_name}: output_path must not equal input_path")
    if where_post is not None and where_post == "":
        where_post = None

    # Check/get layer names
    if input_layer is None:
        input_layer = gfo.get_only_layer(input_path)
    if output_layer is None:
        output_layer = gfo.get_default_layer(output_path)

    # If output file exists already, either clean up or return...
    if output_path.exists():
        if force is False:
            logger.info(f"Stop {operation_name}: output exists already {output_path}")
            return
        else:
            gfo.remove(output_path)

    # Determine if fid can be preserved
    preserve_fid = False
    if not explodecollections and GeofileType(output_path) == GeofileType.GPKG:
        preserve_fid = True

    # Calculate
    tempdir = _io_util.create_tempdir(f"geofileops/{operation_name.replace(' ', '_')}")
    try:
        # If gridsize != 0.0 or if geom_selected is None we need an sqlite file to be
        # able to determine the columns later on.
        convert_to_spatialite_based = (
            True if gridsize != 0.0 or geom_selected is None else False
        )
        processing_params = _prepare_processing_params(
            input1_path=input_path,
            input1_layer=input_layer,
            input1_layer_alias="layer",
            tempdir=tempdir,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            convert_to_spatialite_based=convert_to_spatialite_based,
        )
        # If None is returned, just stop.
        if processing_params is None or processing_params.batches is None:
            return

        # Get layer info of the input layer to use
        assert processing_params.input1_path is not None
        input_layerinfo = gfo.get_layerinfo(
            processing_params.input1_path, input_layer, raise_on_nogeom=False
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
            input_layer=processing_params.input1_layer,
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
                    input1_path=processing_params.input1_path,
                )
                geom_selected = input_layerinfo.geometrycolumn in cols

        # Fill out/add to the sql_template what is already possible
        # ---------------------------------------------------------

        # Add snaptogrid around sql_template if gridsize specified
        if geom_selected and gridsize != 0.0:
            # Apply snaptogrid, but this results in invalid geometries, so also
            # ST_Makevalid. It can also result in collapsed (pieces of)
            # geometries, so also collectionextract.
            gridsize_op = (
                "ST_MakeValid(SnapToGrid("
                f"    sub_gridsize.{input_layerinfo.geometrycolumn}, {gridsize}))"
            )
            if force_output_geometrytype is None:
                warnings.warn(
                    "a gridsize is specified but no force_output_geometrytype, this "
                    "can result in inconsistent geometries in the output",
                    stacklevel=2,
                )
            else:
                primitivetypeid = force_output_geometrytype.to_primitivetype.value
                gridsize_op = f"ST_CollectionExtract({gridsize_op}, {primitivetypeid})"

            # Get all columns of the sql_template
            sql_tmp = sql_template.format(batch_filter="")
            cols = _sqlite_util.get_columns(
                sql_stmt=sql_tmp, input1_path=processing_params.input1_path
            )
            attributes = [
                col for col in cols if col.lower() != input_layerinfo.geometrycolumn
            ]
            columns_to_select = _ogr_sql_util.columns_quoted(attributes)
            sql_template = f"""
                SELECT {gridsize_op} AS {input_layerinfo.geometrycolumn}
                      {columns_to_select}
                  FROM ( {sql_template}
                    ) sub_gridsize
            """

        # If empty/null geometries don't need to be kept, filter them away
        if geom_selected and not keep_empty_geoms:
            sql_template = f"""
                SELECT * FROM
                    ( {sql_template}
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
                    )
                 ORDER BY {input_layerinfo.geometrycolumn} IS NULL
            """

        # Fill out geometrycolumn again as there might have popped up extra ones
        sql_template = sql_template.format(
            geometrycolumn=input_layerinfo.geometrycolumn,
            batch_filter="{batch_filter}",
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
            batches: Dict[int, dict] = {}
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
                create_spatial_index = False
                if nb_batches == 1:
                    create_spatial_index = True
                translate_info = _ogr_util.VectorTranslateInfo(
                    input_path=processing_params.batches[batch_id]["path"],
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
                start_time, nb_done, nb_batches, operation_name, nb_parallel=nb_parallel
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
                    nb_batches,
                    operation_name,
                    nb_parallel=nb_parallel,
                )

        # Round up and clean up
        # Now create spatial index and move to output location
        if tmp_output_path.exists():
            if (
                gfo.get_layerinfo(
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
            GeofileType(tmp_output_path) == GeofileType.ESRIShapefile
            and tmp_output_path.with_suffix(".dbf").exists()
        ):
            # If the output shapefile doesn't have a geometry column, the .shp file
            # doesn't exist but the .dbf does
            output_path.parent.mkdir(parents=True, exist_ok=True)
            gfo.move(
                tmp_output_path.with_suffix(".dbf"), output_path.with_suffix(".dbf")
            )
        else:
            logger.debug(f"Result of {operation_name} was empty!")

    finally:
        # Clean tmp dir
        shutil.rmtree(tempdir, ignore_errors=True)

    logger.info(f"Processing ready, took {datetime.now()-start_time}!")


################################################################################
# Operations on two layers
################################################################################


def clip(
    input_path: Path,
    clip_path: Path,
    output_path: Path,
    input_layer: Optional[str] = None,
    input_columns: Optional[List[str]] = None,
    clip_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
    input_columns_prefix: str = "",
    output_with_spatial_index: bool = True,
):
    # Init
    # In the query, important to only extract the geometry types that are expected
    input_layer_info = gfo.get_layerinfo(input_path, input_layer)
    primitivetypeid = input_layer_info.geometrytype.to_primitivetype.value

    # If the input type is not point, force the output type to multi,
    # because erase clip cause eg. polygons to be split to multipolygons...
    force_output_geometrytype = input_layer_info.geometrytype
    if force_output_geometrytype is not GeometryType.POINT:
        force_output_geometrytype = input_layer_info.geometrytype.to_multitype

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
                 AND ST_Touches(
                        layer1.{{input1_geometrycolumn}},
                        layer2.{{input2_geometrycolumn}}) = 0
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


def erase(
    input_path: Path,
    erase_path: Path,
    output_path: Path,
    input_layer: Optional[str] = None,
    input_columns: Optional[List[str]] = None,
    erase_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 1000,
    force: bool = False,
    input_columns_prefix: str = "",
    output_with_spatial_index: bool = True,
):
    # Init
    input_layer_info = gfo.get_layerinfo(input_path, input_layer)

    # If the input type is not point, force the output type to multi,
    # because erase can cause eg. polygons to be split to multipolygons...
    force_output_geometrytype = input_layer_info.geometrytype
    if force_output_geometrytype is not GeometryType.POINT:
        force_output_geometrytype = input_layer_info.geometrytype.to_multitype

    # Prepare sql template for this operation
    # - WHERE geom IS NOT NULL to avoid rows with a NULL geom, they give issues in
    #   later operations
    # - use "LIMIT -1 OFFSET 0" to avoid the subquery flattening. Flattening e.g.
    #   "geom IS NOT NULL" leads to GFO_Difference_Collection calculated double!
    # - ST_Intersects and ST_Touches slow down a lot when the data contains huge geoms
    # - Calculate difference in correlated subquery in SELECT clause reduces memory
    #   usage by a factor 10 compared with a WITH with GROUP BY. The WITH with a GROUP
    #   BY on layer1.rowid was a few % faster, but this is not worth it. E.g. for one
    #   test file 4-7 GB per process versus 70-700 MB). For another: crash.
    # - Check if the result of GFO_Difference_Collection is empty (NULL) using IFNULL,
    #   and if this ois the case set to 'DIFF_EMPTY'. This way we can make the
    #   distinction whether the subquery is finding a row (no match with spatial index)
    #   or if the difference results in an empty/NULL geometry.
    #   Tried to return EMPTY GEOMETRY from GFO_Difference_Collection, but it didn't
    #   work to use spatialite's ST_IsEmpty(geom) = 0 to filter on this for an unclear
    #   reason.
    # - Using ST_Subdivide instead of GFO_Subdivide is 10 * slower, not sure why. Maybe
    #   the result of that function isn't cached?
    # - First checking ST_NPoints before GFO_Subdivide provides another 20% speed up.
    # - Not relevant anymore, but ST_difference(geometry , NULL) gives NULL as result
    input1_layer_rtree = "rtree_{input1_layer}_{input1_geometrycolumn}"
    input2_layer_rtree = "rtree_{input2_layer}_{input2_geometrycolumn}"

    sql_template = f"""
        SELECT * FROM (
          SELECT IFNULL(
                   ( SELECT IFNULL(
                                ST_GeomFromWKB(GFO_Difference_Collection(
                                    ST_AsBinary(layer1_sub.{{input1_geometrycolumn}}),
                                    ST_AsBinary(ST_Collect(layer2_sub.geom_divided)),
                                    1,
                                    {subdivide_coords}
                                )),
                                'DIFF_EMPTY'
                            ) AS diff_geom
                       FROM {{input1_databasename}}."{{input1_layer}}" layer1_sub
                       JOIN {{input1_databasename}}."{input1_layer_rtree}" layer1tree
                         ON layer1_sub.rowid = layer1tree.id
                       JOIN (SELECT layer2_sub2.rowid
                                   ,IIF(
                                      ST_NPoints(layer2_sub2.{{input2_geometrycolumn}})
                                          < {subdivide_coords},
                                      layer2_sub2.{{input2_geometrycolumn}},
                                      ST_GeomFromWKB(GFO_Subdivide(
                                          ST_AsBinary(
                                              layer2_sub2.{{input2_geometrycolumn}}),
                                          {subdivide_coords}))
                                    ) AS geom_divided
                             FROM {{input2_databasename}}."{{input2_layer}}" layer2_sub2
                             LIMIT -1 OFFSET 0
                         ) layer2_sub
                       JOIN {{input2_databasename}}."{input2_layer_rtree}" layer2tree
                         ON layer2_sub.rowid = layer2tree.id
                      WHERE 1=1
                        AND layer1_sub.rowid = layer1.rowid
                        AND layer1tree.minx <= layer2tree.maxx
                        AND layer1tree.maxx >= layer2tree.minx
                        AND layer1tree.miny <= layer2tree.maxy
                        AND layer1tree.maxy >= layer2tree.miny
                      GROUP BY layer1_sub.rowid
                      LIMIT -1 OFFSET 0
                   ),
                   layer1.{{input1_geometrycolumn}}
                 ) AS geom
                {{layer1_columns_prefix_alias_str}}
            FROM {{input1_databasename}}."{{input1_layer}}" layer1
           WHERE 1=1
             {{batch_filter}}
           LIMIT -1 OFFSET 0
          )
         WHERE geom IS NOT NULL
           AND geom <> 'DIFF_EMPTY'
    """

    # Go!
    return _two_layer_vector_operation(
        input1_path=input_path,
        input2_path=erase_path,
        output_path=output_path,
        sql_template=sql_template,
        operation_name="erase",
        input1_layer=input_layer,
        input1_columns=input_columns,
        input1_columns_prefix=input_columns_prefix,
        input2_layer=erase_layer,
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
    )


def export_by_location(
    input_path: Path,
    input_to_compare_with_path: Path,
    output_path: Path,
    min_area_intersect: Optional[float] = None,
    area_inters_column_name: Optional[str] = None,
    input_layer: Optional[str] = None,
    input_columns: Optional[List[str]] = None,
    input_to_compare_with_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    # Prepare sql template for this operation
    # TODO: test performance difference between the following two queries
    input1_layer_rtree = "rtree_{input1_layer}_{input1_geometrycolumn}"
    input2_layer_rtree = "rtree_{input2_layer}_{input2_geometrycolumn}"

    # If intersect area needs to be calculated, other query needed
    if area_inters_column_name is None and min_area_intersect is None:
        sql_template = f"""
            SELECT layer1.{{input1_geometrycolumn}} AS geom
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
                   WHERE layer1tree.minx <= layer2tree.maxx
                     AND layer1tree.maxx >= layer2tree.minx
                     AND layer1tree.miny <= layer2tree.maxy
                     AND layer1tree.maxy >= layer2tree.miny
                     AND ST_intersects(layer1.{{input1_geometrycolumn}},
                                       layer2.{{input2_geometrycolumn}}) = 1
                     AND ST_touches(layer1.{{input1_geometrycolumn}},
                                    layer2.{{input2_geometrycolumn}}) = 0)
            """
    else:
        # Intersect area needs to be calculated
        if area_inters_column_name is None:
            area_inters_column_name = "area_inters"
        area_inters_column_expression = f"""
            ,ST_area(ST_intersection(
                    ST_union(layer1.{{input1_geometrycolumn}}),
                    ST_union(layer2.{{input2_geometrycolumn}})
                )) AS {area_inters_column_name}
        """

        # Prepare sql template with intersect area calculation
        sql_template = f"""
            SELECT ST_union(layer1.{{input1_geometrycolumn}}) as geom
                  {{layer1_columns_prefix_str}}
                  {area_inters_column_expression}
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
               AND ST_Intersects(layer1.{{input1_geometrycolumn}},
                                 layer2.{{input2_geometrycolumn}}) = 1
               AND ST_Touches(layer1.{{input1_geometrycolumn}},
                              layer2.{{input2_geometrycolumn}}) = 0
             GROUP BY layer1.rowid {{layer1_columns_prefix_str}}
        """

        # Filter on intersect area if necessary
        if min_area_intersect is not None:
            sql_template = f"""
                SELECT sub.* FROM
                  ( {sql_template}
                     LIMIT -1 OFFSET 0
                  ) sub
                WHERE sub.{area_inters_column_name} >= {min_area_intersect}
            """

    # Go!
    input_layer_info = gfo.get_layerinfo(input_path, input_layer)
    return _two_layer_vector_operation(
        input1_path=input_path,
        input2_path=input_to_compare_with_path,
        output_path=output_path,
        sql_template=sql_template,
        operation_name="export_by_location",
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
    )


def export_by_distance(
    input_to_select_from_path: Path,
    input_to_compare_with_path: Path,
    output_path: Path,
    max_distance: float,
    input1_layer: Optional[str] = None,
    input1_columns: Optional[List[str]] = None,
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


def intersection(
    input1_path: Path,
    input2_path: Path,
    output_path: Path,
    input1_layer: Optional[str] = None,
    input1_columns: Optional[List[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[List[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    # In the query, important to only extract the geometry types that are expected
    # TODO: test for geometrycollection, line, point,...
    input1_layer_info = gfo.get_layerinfo(input1_path, input1_layer)
    input2_layer_info = gfo.get_layerinfo(input2_path, input2_layer)
    primitivetype_to_extract = PrimitiveType(
        min(
            input1_layer_info.geometrytype.to_primitivetype.value,
            input2_layer_info.geometrytype.to_primitivetype.value,
        )
    )

    # For the output file, if output is going to be polygon or linestring, force
    # MULTI variant to avoid ugly warnings
    force_output_geometrytype = primitivetype_to_extract.to_multitype

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
               LIMIT -1 OFFSET 0
            ) sub
         WHERE sub.geom IS NOT NULL
    """

    # Go!
    return _two_layer_vector_operation(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        sql_template=sql_template,
        operation_name="intersection",
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
    )


def join_by_location(
    input1_path: Path,
    input2_path: Path,
    output_path: Path,
    spatial_relations_query: str = "intersects is True",
    discard_nonmatching: bool = True,
    min_area_intersect: Optional[float] = None,
    area_inters_column_name: Optional[str] = None,
    input1_layer: Optional[str] = None,
    input1_columns: Optional[List[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[List[str]] = None,
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
            f'as "{area_inters_column_name_touse}"'
        )
        if min_area_intersect is not None:
            area_inters_filter = (
                f'WHERE sub_area."{area_inters_column_name_touse}" '
                f">= {min_area_intersect}"
            )

    # Prepare spatial relations filter
    if spatial_relations_query != "intersects is True":
        # joining should only be possible on features that at least have an
        # interaction! So, add "intersects is True" to query to avoid errors!
        spatial_relations_query = f"({spatial_relations_query}) and intersects is True"
    spatial_relations_filter = _prepare_spatial_relations_filter(
        spatial_relations_query
    )

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
                  SELECT layer1.{{input1_geometrycolumn}} as geom
                        ,layer1.fid l1_fid
                        ,layer2.{{input2_geometrycolumn}} as l2_geom
                        {{layer1_columns_prefix_alias_str}}
                        {{layer2_columns_prefix_alias_str}}
                        ,ST_relate(layer1.{{input1_geometrycolumn}},
                                   layer2.{{input2_geometrycolumn}}) as spatial_relation
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
               WHERE {spatial_relations_filter.format(
                    spatial_relation="sub_filter.spatial_relation")}
               LIMIT -1 OFFSET 0
              ) sub_area
           {area_inters_filter}
          )
        SELECT sub.geom
              {{layer1_columns_from_subselect_str}}
              {{layer2_columns_from_subselect_str}}
              ,sub.spatial_relation
              {area_inters_column_in_output}
          FROM layer1_relations_filtered sub
    """

    # If a left join is asked, add all features from layer1 that weren't
    # matched.
    if discard_nonmatching is False:
        sql_template = f"""
            {sql_template}
            UNION ALL
            SELECT layer1.{{input1_geometrycolumn}} as geom
                  {{layer1_columns_prefix_alias_str}}
                  {{layer2_columns_prefix_alias_null_str}}
                  ,NULL as spatial_relation
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


def _prepare_spatial_relations_filter(query: str) -> str:
    named_spatial_relations = {
        # "disjoint": ["FF*FF****"],
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
    input1_layer: Optional[str] = None,
    input1_columns: Optional[List[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[List[str]] = None,
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
    if output_path.exists() and force is False:
        logger.info(f"Stop join_nearest: output exists already {output_path}")
        return
    if input1_layer is None:
        input1_layer = gfo.get_only_layer(input1_path)
    if input2_layer is None:
        input2_layer = gfo.get_only_layer(input2_path)

    # Prepare input files
    # To use knn index, the input layers need to be in sqlite file format
    # (not a .gpkg!), so prepare this
    if input1_path == input2_path and GeofileType(input1_path) == GeofileType.SQLite:
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
    input1_columns: Optional[List[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[List[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    force_output_geometrytype: Optional[GeometryType] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = 1,
    batchsize: int = -1,
    force: bool = False,
):
    # Go!
    return _two_layer_vector_operation(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        sql_template=sql_stmt,
        operation_name="select_two_layers",
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
    )


def split(
    input1_path: Path,
    input2_path: Path,
    output_path: Path,
    input1_layer: Optional[str] = None,
    input1_columns: Optional[List[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[List[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = 1,
    batchsize: int = -1,
    subdivide_coords: int = 1000,
    force: bool = False,
    output_with_spatial_index: bool = True,
):
    # In the query, important to only extract the geometry types that are
    # expected, so the primitive type of input1_layer
    # TODO: test for geometrycollection, line, point,...
    input1_layer_info = gfo.get_layerinfo(input1_path, input1_layer)
    primitivetype_to_extract = input1_layer_info.geometrytype.to_primitivetype

    # For the output file, force MULTI variant to avoid ugly warnings
    force_output_geometrytype = primitivetype_to_extract.to_multitype

    # Prepare sql template for this operation
    # - WHERE geom IS NOT NULL to avoid rows with a NULL geom, they give issues in
    #   later operations
    # - use "LIMIT -1 OFFSET 0" to avoid the subquery flattening. Flattening e.g.
    #   "geom IS NOT NULL" leads to GFO_Difference_Collection calculated double!
    # - ST_Intersects is fine, but ST_Touches slows down. Especially when the data
    #   contains huge geoms, time doubles or worse.
    # - Calculate difference in correlated subquery in SELECT clause reduces memory
    #   usage by a factor 10 compared with a WITH with GROUP BY. The WITH with a GROUP
    #   BY on layer1.rowid was a few % faster, but this is not worth it. E.g. for one
    #   test file 4-7 GB per process versus 70-700 MB). For another: crash.
    # - Check if the result of GFO_Difference_Collection is empty (NULL) using IFNULL,
    #   and if this ois the case set to 'DIFF_EMPTY'. This way we can make the
    #   distinction whether the subquery is finding a row (no match with spatial index)
    #   or if the difference results in an empty/NULL geometry.
    #   Tried to return EMPTY GEOMETRY from GFO_Difference_Collection, but it didn't
    #   work to use spatialite's ST_IsEmpty(geom) = 0 to filter on this for an unclear
    #   reason.
    # - Using ST_Subdivide instead of GFO_Subdivide is 10 * slower, not sure why. Maybe
    #   the result of that function isn't cached?
    # - First checking ST_NPoints before GFO_Subdivide provides another 20% speed up.
    # - Not relevant anymore, but ST_difference(geometry , NULL) gives NULL as result
    input1_layer_rtree = "rtree_{input1_layer}_{input1_geometrycolumn}"
    input2_layer_rtree = "rtree_{input2_layer}_{input2_geometrycolumn}"

    sql_template = f"""
        SELECT * FROM (
          SELECT ST_CollectionExtract(
                      ST_intersection(layer1.{{input1_geometrycolumn}},
                                      layer2.{{input2_geometrycolumn}}),
                      {primitivetype_to_extract.value}) as geom
                {{layer1_columns_prefix_alias_str}}
                {{layer2_columns_prefix_alias_str}}
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
             AND ST_Intersects(layer1.{{input1_geometrycolumn}},
                               layer2.{{input2_geometrycolumn}}) = 1
             --AND ST_Touches(layer1.{{input1_geometrycolumn}},
             --               layer2.{{input2_geometrycolumn}}) = 0
          UNION ALL
          SELECT IFNULL(
                   ( SELECT IFNULL(
                                ST_GeomFromWKB(GFO_Difference_Collection(
                                    ST_AsBinary(layer1_sub.{{input1_geometrycolumn}}),
                                    ST_AsBinary(ST_Collect(layer2_sub.geom_divided)),
                                    1,
                                    {subdivide_coords}
                                )),
                                'DIFF_EMPTY'
                            ) AS diff_geom
                       FROM {{input1_databasename}}."{{input1_layer}}" layer1_sub
                       JOIN {{input1_databasename}}."{input1_layer_rtree}" layer1tree
                         ON layer1_sub.rowid = layer1tree.id
                       JOIN (SELECT layer2_sub2.rowid
                                   ,IIF(
                                      ST_NPoints(layer2_sub2.{{input2_geometrycolumn}})
                                          < {subdivide_coords},
                                      layer2_sub2.{{input2_geometrycolumn}},
                                      ST_GeomFromWKB(GFO_Subdivide(
                                          ST_AsBinary(
                                              layer2_sub2.{{input2_geometrycolumn}}),
                                          {subdivide_coords}))
                                    ) AS geom_divided
                             FROM {{input2_databasename}}."{{input2_layer}}" layer2_sub2
                             LIMIT -1 OFFSET 0
                         ) layer2_sub
                       JOIN {{input2_databasename}}."{input2_layer_rtree}" layer2tree
                         ON layer2_sub.rowid = layer2tree.id
                      WHERE 1=1
                        AND layer1_sub.rowid = layer1.rowid
                        AND layer1tree.minx <= layer2tree.maxx
                        AND layer1tree.maxx >= layer2tree.minx
                        AND layer1tree.miny <= layer2tree.maxy
                        AND layer1tree.maxy >= layer2tree.miny
                      GROUP BY layer1_sub.rowid
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
    """

    # Go!
    return _two_layer_vector_operation(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        sql_template=sql_template,
        operation_name="split",
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


def symmetric_difference(
    input1_path: Path,
    input2_path: Path,
    output_path: Path,
    input1_layer: Optional[str] = None,
    input1_columns: Optional[List[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[List[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 1000,
    force: bool = False,
):
    # A symmetric difference can be simulated by doing an "erase" of input1
    # and input2 and then append the result of an erase of input2 with
    # input1...

    # Because both erase calculations will be towards temp files,
    # we need to do some additional init + checks here...
    if force is False and output_path.exists():
        return
    if output_layer is None:
        output_layer = gfo.get_default_layer(output_path)

    tempdir = _io_util.create_tempdir("geofileops/symmdiff")
    try:
        # First erase input2 from input1 to a temporary output file
        erase1_output_path = tempdir / "layer1_erase_layer2_output.gpkg"
        erase(
            input_path=input1_path,
            erase_path=input2_path,
            output_path=erase1_output_path,
            input_layer=input1_layer,
            input_columns=input1_columns,
            input_columns_prefix=input1_columns_prefix,
            erase_layer=input2_layer,
            output_layer=output_layer,
            explodecollections=explodecollections,
            gridsize=gridsize,
            where_post=where_post,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            subdivide_coords=subdivide_coords,
            force=force,
            output_with_spatial_index=False,
        )

        if input2_columns is None or len(input2_columns) > 0:
            input2_info = gfo.get_layerinfo(input2_path)
            columns_to_add = (
                input2_columns if input2_columns is not None else input2_info.columns
            )
            for column in columns_to_add:
                gfo.add_column(
                    erase1_output_path,
                    name=f"{input2_columns_prefix}{column}",
                    type=input2_info.columns[column].gdal_type,
                )

        # Now erase input1 from input2 to another temporary output file
        erase2_output_path = tempdir / "layer2_erase_layer1_output.gpkg"
        erase(
            input_path=input2_path,
            erase_path=input1_path,
            output_path=erase2_output_path,
            input_layer=input2_layer,
            input_columns=input2_columns,
            input_columns_prefix=input2_columns_prefix,
            erase_layer=input1_layer,
            output_layer=output_layer,
            explodecollections=explodecollections,
            gridsize=gridsize,
            where_post=where_post,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            subdivide_coords=subdivide_coords,
            force=force,
            output_with_spatial_index=False,
        )

        # Now append
        _append_to_nolock(
            src=erase2_output_path,
            dst=erase1_output_path,
            src_layer=output_layer,
            dst_layer=output_layer,
        )

        # Convert or add spatial index
        tmp_output_path = erase1_output_path
        if erase1_output_path.suffix != output_path.suffix:
            # Output file should be in diffent format, so convert
            tmp_output_path = tempdir / output_path.name
            gfo.copy_layer(src=erase1_output_path, dst=tmp_output_path)
        else:
            # Create spatial index
            gfo.create_spatial_index(path=tmp_output_path, layer=output_layer)

        # Now we are ready to move the result to the final spot...
        if output_path.exists():
            gfo.remove(output_path)
        gfo.move(tmp_output_path, output_path)

    finally:
        shutil.rmtree(tempdir, ignore_errors=True)


def union(
    input1_path: Path,
    input2_path: Path,
    output_path: Path,
    input1_layer: Optional[str] = None,
    input1_columns: Optional[List[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[List[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 1000,
    force: bool = False,
):
    # A union can be simulated by doing a "split" of input1 and input2 and
    # then append the result of an erase of input2 with input1...

    # Because the calculations in split and erase will be towards temp files,
    # we need to do some additional init + checks here...
    if force is False and output_path.exists():
        return
    if output_layer is None:
        output_layer = gfo.get_default_layer(output_path)

    start_time = datetime.now()
    tempdir = _io_util.create_tempdir("geofileops/union")
    try:
        # First split input1 with input2 to a temporary output gfo...
        split_output_path = tempdir / "split_output.gpkg"
        split(
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=split_output_path,
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
            subdivide_coords=subdivide_coords,
            force=force,
            output_with_spatial_index=False,
        )

        # Now erase input1 from input2 to another temporary output gfo...
        erase_output_path = tempdir / "erase_output.gpkg"
        erase(
            input_path=input2_path,
            erase_path=input1_path,
            output_path=erase_output_path,
            input_layer=input2_layer,
            input_columns=input2_columns,
            input_columns_prefix=input2_columns_prefix,
            erase_layer=input1_layer,
            output_layer=output_layer,
            explodecollections=explodecollections,
            gridsize=gridsize,
            where_post=where_post,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            subdivide_coords=subdivide_coords,
            force=force,
            output_with_spatial_index=False,
        )

        # Now append
        _append_to_nolock(
            src=erase_output_path,
            dst=split_output_path,
            src_layer=output_layer,
            dst_layer=output_layer,
        )

        # Convert or add spatial index
        tmp_output_path = split_output_path
        if split_output_path.suffix != output_path.suffix:
            # Output file should be in different format, so convert
            tmp_output_path = tempdir / output_path.name
            gfo.copy_layer(src=split_output_path, dst=tmp_output_path)
        else:
            # Create spatial index
            gfo.create_spatial_index(path=tmp_output_path, layer=output_layer)

        # Now we are ready to move the result to the final spot...
        if output_path.exists():
            gfo.remove(output_path)
        gfo.move(tmp_output_path, output_path)

    finally:
        shutil.rmtree(tempdir, ignore_errors=True)

    logger.info(f"union ready, took {datetime.now()-start_time}!")


def _two_layer_vector_operation(
    input1_path: Path,
    input2_path: Path,
    output_path: Path,
    sql_template: str,
    operation_name: str,
    input1_layer: Optional[str],
    input1_columns: Optional[List[str]],
    input1_columns_prefix: str,
    input2_layer: Optional[str],
    input2_columns: Optional[List[str]],
    input2_columns_prefix: str,
    output_layer: Optional[str],
    explodecollections: bool,
    force_output_geometrytype: Optional[GeometryType],
    gridsize: float,
    where_post: Optional[str],
    nb_parallel: int,
    batchsize: int,
    force: bool,
    use_ogr: bool = False,
    output_with_spatial_index: bool = True,
):
    """
    Executes an operation that needs 2 input files.

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
        use_ogr (bool, optional): If True, ogr is used to do the processing,
            In this case different input files (input1_path, input2_path) are
            NOT supported. If False, sqlite3 is used directly.
            Defaults to False.
        output_with_spatial_index (bool, optional): True to create output file with
            spatial index. Defaults to True.

    Raises:
        ValueError: [description]

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    # Init
    if not input1_path.exists():
        raise ValueError(f"{operation_name}: input1_path doesn't exist: {input1_path}")
    if not input2_path.exists():
        raise ValueError(f"{operation_name}: input2_path doesn't exist: {input2_path}")
    if input1_path == output_path or input2_path == output_path:
        raise ValueError(
            f"{operation_name}: output_path must not equal one of input paths"
        )
    if use_ogr is True and input1_path != input2_path:
        raise ValueError(
            f"{operation_name}: if use_ogr True, input1_path should equal input2_path!"
        )
    if output_path.exists():
        if force is False:
            logger.info(f"Stop {operation_name}: output exists already {output_path}")
            return
        else:
            gfo.remove(output_path)

    # Check if spatialite is properly installed to execute this query
    _sqlite_util.check_runtimedependencies()

    # Init layer info
    start_time = datetime.now()
    if input1_layer is None:
        input1_layer = gfo.get_only_layer(input1_path)
    if input2_layer is None:
        input2_layer = gfo.get_only_layer(input2_path)
    if output_layer is None:
        output_layer = gfo.get_default_layer(output_path)
    tempdir = _io_util.create_tempdir(f"geofileops/{operation_name}")

    # Use get_layerinfo to check if the input files are valid
    gfo.get_layerinfo(input1_path, input1_layer)
    gfo.get_layerinfo(input2_path, input2_layer)

    # Prepare output filename
    tmp_output_path = tempdir / output_path.name
    tmp_output_path.parent.mkdir(exist_ok=True, parents=True)
    gfo.remove(tmp_output_path)

    try:
        # Prepare tmp files/batches
        # -------------------------
        logger.info(
            f"Prepare input (params) for {operation_name} with tempdir: {tempdir}"
        )
        processing_params = _prepare_processing_params(
            input1_path=input1_path,
            input1_layer=input1_layer,
            input1_layer_alias="layer1",
            input2_path=input2_path,
            input2_layer=input2_layer,
            tempdir=tempdir,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            convert_to_spatialite_based=True,
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
                'A placeholder "{input1_databasename}". is recommended as prefix for '
                "the input1 layer/rtree/tables used in sql_stmt."
            )
        if "input2_databasename" not in sql_template_placeholders:
            logger.warning(
                'A placeholder "{input2_databasename}". is recommended as prefix for '
                "the input2 layer/rtree/tables used in sql_stmt."
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
        assert processing_params.input1_path is not None
        input1_tmp_layerinfo = gfo.get_layerinfo(
            processing_params.input1_path, processing_params.input1_layer
        )
        input1_col_strs = _ogr_sql_util.ColumnFormatter(
            columns_asked=input1_columns,
            columns_in_layer=input1_tmp_layerinfo.columns,
            fid_column=input1_tmp_layerinfo.fid_column,
            table_alias="layer1",
            column_alias_prefix=input1_columns_prefix,
        )
        assert processing_params.input2_path is not None
        input2_tmp_layerinfo = gfo.get_layerinfo(
            processing_params.input2_path, processing_params.input2_layer
        )
        input2_col_strs = _ogr_sql_util.ColumnFormatter(
            columns_asked=input2_columns,
            columns_in_layer=input2_tmp_layerinfo.columns,
            fid_column=input2_tmp_layerinfo.fid_column,
            table_alias="layer2",
            column_alias_prefix=input2_columns_prefix,
        )

        # Check input crs'es
        if input1_tmp_layerinfo.crs != input2_tmp_layerinfo.crs:
            logger.warning(
                "input1 has a different crs than input2: \n\tinput1: "
                f"{input1_tmp_layerinfo.crs} \n\tinput2: {input2_tmp_layerinfo.crs}"
            )

        # Fill out sql_template as much as possible already
        # -------------------------------------------------
        # Keep input1_tmp_layer and input2_tmp_layer for backwards compatibility
        sql_template = sql_template.format(
            input1_databasename="{input1_databasename}",
            input2_databasename="{input2_databasename}",
            layer1_columns_from_subselect_str=input1_col_strs.from_subselect(),
            layer1_columns_prefix_alias_str=input1_col_strs.prefixed_aliased(),
            layer1_columns_prefix_str=input1_col_strs.prefixed(),
            input1_layer=processing_params.input1_layer,
            input1_tmp_layer=processing_params.input1_layer,
            input1_geometrycolumn=input1_tmp_layerinfo.geometrycolumn,
            layer2_columns_from_subselect_str=input2_col_strs.from_subselect(),
            layer2_columns_prefix_alias_str=input2_col_strs.prefixed_aliased(),
            layer2_columns_prefix_str=input2_col_strs.prefixed(),
            layer2_columns_prefix_alias_null_str=input2_col_strs.null_aliased(),
            input2_layer=processing_params.input2_layer,
            input2_tmp_layer=processing_params.input2_layer,
            input2_geometrycolumn=input2_tmp_layerinfo.geometrycolumn,
            batch_filter="{batch_filter}",
        )

        # Determine column names and types based on sql statement
        column_datatypes = None
        # Use first batch_filter to improve performance
        sql_stmt = sql_template.format(
            input1_databasename="{input1_databasename}",
            input2_databasename="{input2_databasename}",
            batch_filter=processing_params.batches[0]["batch_filter"],
        )
        column_datatypes = _sqlite_util.get_columns(
            sql_stmt=sql_stmt,
            input1_path=processing_params.input1_path,
            input2_path=processing_params.input2_path,
        )

        # Add snaptogrid around sql_template if gridsize specified
        if gridsize != 0.0:
            # Apply snaptogrid, but this results in invalid geometries, so also
            # ST_Makevalid. It can also result in collapsed (pieces of)
            # geometries, so also collectionextract.
            gridsize_op = f"ST_MakeValid(SnapToGrid(sub_gridsize.geom, {gridsize}))"
            if force_output_geometrytype is None:
                warnings.warn(
                    "a gridsize is specified but no force_output_geometrytype, this "
                    "can result in inconsistent geometries in the output",
                    stacklevel=2,
                )
            else:
                primitivetypeid = force_output_geometrytype.to_primitivetype.value
                gridsize_op = f"ST_CollectionExtract({gridsize_op}, {primitivetypeid})"

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
                SELECT {gridsize_op} AS geom
                        {columns_to_select}
                  FROM ( {sql_template}
                         LIMIT -1 OFFSET 0
                  ) sub_gridsize
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
        calculate_in_threads = (
            True if input1_tmp_layerinfo.featurecount <= 100 else False
        )
        logger.info(
            f"Start {operation_name} ({processing_params.nb_parallel} parallel workers)"
        )
        with _processing_util.PooledExecutorFactory(
            threadpool=calculate_in_threads,
            max_workers=processing_params.nb_parallel,
            initializer=_processing_util.initialize_worker(),
        ) as calculate_pool:
            # Start looping
            batches: Dict[int, dict] = {}
            future_to_batch_id = {}
            for batch_id in processing_params.batches:
                batches[batch_id] = {}
                batches[batch_id]["layer"] = output_layer

                tmp_partial_output_path = (
                    tempdir / f"{output_path.stem}_{batch_id}.gpkg"
                )
                batches[batch_id]["tmp_partial_output_path"] = tmp_partial_output_path

                # Fill out final things in sql_template
                sql_stmt = sql_template.format(
                    input1_databasename="{input1_databasename}",
                    input2_databasename="{input2_databasename}",
                    batch_filter=processing_params.batches[batch_id]["batch_filter"],
                )
                batches[batch_id]["sqlite_stmt"] = sql_stmt

                # If explodecollections and there is a where_post to be applied, we need
                # to apply explodecollections now already to be able to apply the
                # where_post in the append of partial files later on even though this
                # involves an extra copy of the result data under the hood in practice!
                explodecollections_now = False
                if explodecollections and where_post is not None:
                    explodecollections_now = True
                # Remark: this temp file doesn't need spatial index
                future = calculate_pool.submit(
                    calculate_two_layers,
                    input1_path=processing_params.batches[batch_id]["path"],
                    input1_layer=processing_params.batches[batch_id]["layer"],
                    input2_path=processing_params.input2_path,
                    output_path=tmp_partial_output_path,
                    sql_stmt=sql_stmt,
                    output_layer=output_layer,
                    explodecollections=explodecollections_now,
                    force_output_geometrytype=force_output_geometrytype,
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
                        logger.debug(result)
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
                    create_spatial_index = False
                    if nb_batches == 1 and output_with_spatial_index:
                        create_spatial_index = True

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
                    path=tmp_output_path, layer=output_layer, exist_ok=True
                )
            if tmp_output_path != output_path:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                gfo.move(tmp_output_path, output_path)
        else:
            logger.debug(f"Result of {operation_name} was empty!")

        logger.info(f"{operation_name} ready, took {datetime.now()-start_time}!")
    except Exception:
        gfo.remove(output_path, missing_ok=True)
        gfo.remove(tmp_output_path, missing_ok=True)
        raise
    finally:
        shutil.rmtree(tempdir, ignore_errors=True)


def calculate_two_layers(
    input1_path: Path,
    input1_layer: str,
    input2_path: Path,
    output_path: Path,
    sql_stmt: str,
    output_layer: str,
    explodecollections: bool,
    force_output_geometrytype: Optional[GeometryType],
    create_spatial_index: bool,
    column_datatypes: dict,
    use_ogr: bool,
):
    if use_ogr is False:
        # If explodecollections, write first to tmp file, then apply explodecollections
        # to the final output file.
        output_tmp_path = output_path
        if explodecollections:
            output_name = f"{output_path.stem}_tmp{output_path.suffix}"
            output_tmp_path = output_path.parent / output_name
        _sqlite_util.create_table_as_sql(
            input1_path=input1_path,
            input1_layer=input1_layer,
            input2_path=input2_path,
            output_path=output_tmp_path,
            sql_stmt=sql_stmt,
            output_layer=output_layer,
            output_geometrytype=force_output_geometrytype,
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
        #   * input2 path (= using attach) doesn't seem to work
        #   * ogr doesn't fill out database names, so do it now
        sql_stmt = sql_stmt.format(
            input1_databasename="main",
            input2_databasename="main",
        )

        _ogr_util.vector_translate(
            input_path=input1_path,
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
        input1_path: Optional[Path] = None,
        input1_layer: Optional[str] = None,
        input2_path: Optional[Path] = None,
        input2_layer: Optional[str] = None,
        nb_parallel: int = -1,
        batches: Optional[dict] = None,
    ):
        self.input1_path = input1_path
        self.input1_layer = input1_layer
        self.input2_path = input2_path
        self.input2_layer = input2_layer
        self.nb_parallel = nb_parallel
        self.batches = batches

    def to_json(self, path: Path):
        prepared = _general_util.prepare_for_serialize(vars(self))
        with open(path, "w") as file:
            file.write(json.dumps(prepared, indent=4, sort_keys=True))


def _prepare_processing_params(
    input1_path: Path,
    input1_layer: str,
    tempdir: Path,
    convert_to_spatialite_based: bool,
    nb_parallel: int,
    batchsize: int = -1,
    input1_layer_alias: Optional[str] = None,
    input2_path: Optional[Path] = None,
    input2_layer: Optional[str] = None,
) -> Optional[ProcessingParams]:
    # Init
    returnvalue = ProcessingParams(nb_parallel=nb_parallel)
    input1_layerinfo = gfo.get_layerinfo(
        input1_path, input1_layer, raise_on_nogeom=False
    )

    # Determine the optimal number of parallel processes + batches
    if returnvalue.nb_parallel == -1:
        # If no batch size specified, put at least 100 rows in a batch
        if batchsize <= 0:
            min_rows_per_batch = 100
        else:
            # If batchsize is specified, use the batch size
            min_rows_per_batch = batchsize

        max_parallel = max(int(input1_layerinfo.featurecount / min_rows_per_batch), 1)
        returnvalue.nb_parallel = min(multiprocessing.cpu_count(), max_parallel)

    # Determine optimal number of batches
    # Remark: especially for 'select' operation, if nb_parallel is 1
    #         nb_batches should be 1 (select might give wrong results)
    if returnvalue.nb_parallel > 1:
        # Limit number of rows processed in parallel to limit memory use
        if batchsize > 0:
            max_rows_parallel = batchsize * returnvalue.nb_parallel
        else:
            max_rows_parallel = 1000000
            if input2_path is not None:
                max_rows_parallel = 200000

        # Adapt number of batches to max_rows_parallel
        if input1_layerinfo.featurecount > max_rows_parallel:
            # If more rows than can be handled simultanously in parallel
            nb_batches = int(
                input1_layerinfo.featurecount
                / (max_rows_parallel / returnvalue.nb_parallel)
            )
        elif batchsize > 0:
            # If a batchsize is specified, try to honer it
            nb_batches = returnvalue.nb_parallel
        else:
            # If no batchsize specified and 2 layer processing, add some batches to
            # reduce impact of possible unbalanced batches on total processing time.
            nb_batches = returnvalue.nb_parallel
            if input2_path is not None:
                nb_batches = returnvalue.nb_parallel * 2

    elif batchsize > 0:
        nb_batches = math.ceil(input1_layerinfo.featurecount / batchsize)
    else:
        nb_batches = 1

    # Prepare input files for the calculation
    returnvalue.input1_layer = input1_layer
    returnvalue.input2_layer = input2_layer

    if convert_to_spatialite_based is False:
        returnvalue.input1_path = input1_path
        returnvalue.input2_path = input2_path
    else:
        # Check if the input files are of the correct geofiletype
        input1_geofiletype = GeofileType(input1_path)
        input2_geofiletype = None if input2_path is None else GeofileType(input2_path)

        # If input files are of the same format + are spatialite compatible,
        # just use them
        if input1_geofiletype.is_spatialite_based and (
            input2_geofiletype is None or input1_geofiletype == input2_geofiletype
        ):
            returnvalue.input1_path = input1_path
            if (
                input1_geofiletype == GeofileType.GPKG
                and input1_layerinfo.geometrycolumn is not None
            ):
                # HasSpatialindex doesn't work for spatialite file
                gfo.create_spatial_index(input1_path, input1_layer, exist_ok=True)
        else:
            # If not ok, copy the input layer to gpkg
            returnvalue.input1_path = tempdir / f"{input1_path.stem}.gpkg"
            gfo.copy_layer(
                src=input1_path,
                src_layer=input1_layer,
                dst=returnvalue.input1_path,
                dst_layer=returnvalue.input1_layer,
                preserve_fid=True,
            )

        if input2_path is not None and input2_geofiletype is not None:
            if (
                input2_geofiletype == input1_geofiletype
                and input2_geofiletype.is_spatialite_based
            ):
                returnvalue.input2_path = input2_path
                input2_layerinfo = gfo.get_layerinfo(
                    input2_path, input2_layer, raise_on_nogeom=False
                )
                if (
                    input2_geofiletype == GeofileType.GPKG
                    and input2_layerinfo.geometrycolumn is not None
                ):
                    # HasSpatialindex doesn't work for spatialite file
                    gfo.create_spatial_index(input2_path, input2_layer, exist_ok=True)
            else:
                # If not spatialite compatible, copy the input layer to gpkg
                returnvalue.input2_path = tempdir / f"{input2_path.stem}.gpkg"
                gfo.copy_layer(
                    src=input2_path,
                    src_layer=input2_layer,
                    dst=returnvalue.input2_path,
                    dst_layer=returnvalue.input2_layer,
                    preserve_fid=True,
                )

    # Prepare batches to process
    # Get column names and info
    layer1_info = gfo.get_layerinfo(
        returnvalue.input1_path, returnvalue.input1_layer, raise_on_nogeom=False
    )

    # Check number of batches + appoint nb rows to batches
    nb_rows_input_layer = layer1_info.featurecount
    if nb_batches > int(nb_rows_input_layer / 10):
        nb_batches = max(int(nb_rows_input_layer / 10), 1)

    batches: Dict[int, dict] = {}
    if nb_batches == 1:
        # If only one batch, no filtering is needed
        batches[0] = {}
        batches[0]["layer"] = returnvalue.input1_layer
        batches[0]["path"] = returnvalue.input1_path
        batches[0]["batch_filter"] = ""
    else:
        # Determine the min_rowid and max_rowid
        # Remark: SELECT MIN(rowid), MAX(rowid) FROM ... is a lot slower than UNION ALL!
        sql_stmt = f"""
            SELECT MIN(rowid) minmax_rowid FROM "{layer1_info.name}"
            UNION ALL
            SELECT MAX(rowid) minmax_rowid FROM "{layer1_info.name}"
        """
        batch_info_df = gfo.read_file(
            path=returnvalue.input1_path, sql_stmt=sql_stmt, sql_dialect="SQLITE"
        )
        min_rowid = pd.to_numeric(batch_info_df["minmax_rowid"][0]).item()
        max_rowid = pd.to_numeric(batch_info_df["minmax_rowid"][1]).item()

        # Determine the exact batches to use
        if ((max_rowid - min_rowid) / nb_rows_input_layer) < 1.1:
            # If the rowid's are quite consecutive, use an imperfect, but
            # fast distribution in batches
            batch_info_list = []
            nb_rows_per_batch = round(nb_rows_input_layer / nb_batches)
            offset = 0
            offset_per_batch = round((max_rowid - min_rowid) / nb_batches)
            for batch_id in range(nb_batches):
                start_rowid = offset
                if batch_id < (nb_batches - 1):
                    # End rowid for this batch is the next start_rowid - 1
                    end_rowid = offset + offset_per_batch - 1
                else:
                    # For the last batch, take the max_rowid so no rowid's are
                    # 'lost' due to rounding errors
                    end_rowid = max_rowid
                batch_info_list.append(
                    (batch_id, nb_rows_per_batch, start_rowid, end_rowid)
                )
                offset += offset_per_batch
            batch_info_df = pd.DataFrame(
                batch_info_list, columns=["id", "nb_rows", "start_rowid", "end_rowid"]
            )
        else:
            # The rowids are not consecutive, so determine the optimal rowid
            # ranges for each batch so each batch has same number of elements
            # Remark: - this might take some seconds for larger datasets!
            #         - (batch_id - 1) AS id to make the id zero-based
            sql_stmt = f"""
                SELECT (batch_id - 1) AS id
                      ,COUNT(*) AS nb_rows
                      ,MIN(rowid) AS start_rowid
                      ,MAX(rowid) AS end_rowid
                  FROM
                    ( SELECT rowid
                            ,NTILE({nb_batches}) OVER (ORDER BY rowid) batch_id
                        FROM "{layer1_info.name}"
                    )
                 GROUP BY batch_id;
            """
            batch_info_df = gfo.read_file(
                path=returnvalue.input1_path, sql_stmt=sql_stmt
            )

        # Prepare the layer alias to use in the batch filter
        layer_alias_d = ""
        if input1_layer_alias is not None:
            layer_alias_d = f"{input1_layer_alias}."

        # Now loop over all batch ranges to build up the necessary filters
        for batch_info in batch_info_df.itertuples():
            # Fill out the batch properties
            batches[batch_info.id] = {}
            batches[batch_info.id]["layer"] = returnvalue.input1_layer
            batches[batch_info.id]["path"] = returnvalue.input1_path

            # The batch filter
            if batch_info.id < nb_batches - 1:
                batches[batch_info.id]["batch_filter"] = (
                    f"AND ({layer_alias_d}rowid >= {batch_info.start_rowid} "
                    f"AND {layer_alias_d}rowid <= {batch_info.end_rowid}) "
                )
            else:
                batches[batch_info.id][
                    "batch_filter"
                ] = f"AND {layer_alias_d}rowid >= {batch_info.start_rowid} "

    # No use starting more processes than the number of batches...
    if len(batches) < returnvalue.nb_parallel:
        returnvalue.nb_parallel = len(batches)

    returnvalue.batches = batches
    returnvalue.to_json(tempdir / "processing_params.json")
    return returnvalue


def dissolve_singlethread(
    input_path: Path,
    output_path: Path,
    groupby_columns: Union[str, Iterable[str], None] = None,
    agg_columns: Optional[dict] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = True,
    where_post: Optional[str] = None,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    force: bool = False,
):
    """
    Remark: this is not a parallelized version!!!
    """
    # Init
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
            for idx in range(0, 99999):
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
    if output_path.exists():
        if force is False:
            logger.info(f"Stop dissolve: Output exists already {output_path}")
            return
        else:
            gfo.remove(output_path)

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
        # Apply snaptogrid, but this results in invalid geometries, so also
        # ST_Makevalid. It can also result in collapsed (pieces of)
        # geometries, so also collectionextract.
        operation = f"ST_MakeValid(SnapToGrid({operation}, {gridsize}))"
        primitivetypeid = force_output_geometrytype.to_primitivetype.value
        operation = f"ST_CollectionExtract({operation}, {primitivetypeid})"

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
        create_spatial_index = True
        suffix = output_path.suffix
        if where_post is not None:
            # where_post needs to be applied still, so no spatial index needed
            create_spatial_index = False
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
            options={"LAYER_CREATION.SPATIAL_INDEX": create_spatial_index},
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
                options={"LAYER_CREATION.SPATIAL_INDEX": True},
            )
            tmp_output_path = tmp_output_where_path

        # Now we are ready to move the result to the final spot...
        gfo.move(tmp_output_path, output_path)

    finally:
        shutil.rmtree(tempdir, ignore_errors=True)

    logger.info(f"Processing ready, took {datetime.now()-start_time}!")
