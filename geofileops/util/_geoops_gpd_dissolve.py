"""Module containing the implementation of Geofile operations using GeoPandas."""

import copy
import logging
import logging.config
import multiprocessing
import sqlite3
import time
import uuid
import warnings
from collections.abc import Iterable
from concurrent import futures
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pygeoops
import shapely
import shapely.geometry as sh_geom
from pygeoops import GeometryType, PrimitiveType
from pyproj import Transformer
from shapely.geometry.base import BaseGeometry

import geofileops as gfo
from geofileops import LayerInfo, fileops
from geofileops.helpers import _general_helper, _parameter_helper
from geofileops.helpers._options import ConfigOptions
from geofileops.util import (
    _general_util,
    _geoops_sql,
    _io_util,
    _ogr_sql_util,
    _ogr_util,
    _processing_util,
)
from geofileops.util._geoops_gpd import (
    ParallelizationConfig as _GpdParallelizationConfig,
)
from geofileops.util._geoops_gpd import (
    _determine_nb_batches as _gpd_determine_nb_batches,
)
from geofileops.util._geopath_util import GeoPath

# Don't show this geopandas warning...
warnings.filterwarnings("ignore", "GeoSeries.isna", UserWarning)

logger = logging.getLogger(__name__)


def dissolve(  # noqa: D417
    input_path: Path,
    output_path: Path,
    groupby_columns: list[str] | str | None = None,
    agg_columns: dict | None = None,
    explodecollections: bool = True,
    tiles_path: Path | None = None,
    nb_squarish_tiles: int = 1,
    input_layer: str | LayerInfo | None = None,
    output_layer: str | None = None,
    gridsize: float = 0.0,
    where_post: str | None = None,
    nb_parallel: int | None = None,
    batchsize: int = -1,
    force: bool = False,
    operation_prefix: str = "",
    tmp_basedir: Path | None = None,
) -> None:
    """Function that applies a dissolve.

    End user documentation can be found in module geoops!

    Remark: keep_empty_geoms is not implemented because this is not so easy because
    (for polygon dissolve) the batches are location based, and null/empty geometries
    don't have a location. It could be implemented, but as long as nobody needs it...

    The attribute data aggregation logic is a bit more complex to be able to process
    per tile and in multiple passed for large datasets:
      - Note that a geometry that lies on the edge of 2 (or more) tiles will be split up
        on the tile boundary(ies) and each part will be further treated in the
        respective tile.
      - To be able to correctly perform attribute aggregations, they can only be
        determined after all tiles and passes have been finished, as the information
        from multiple tiles over multiple passes might have to be combined.
      - Polygon column and JSON aggregations copy source attributes once; geometry
        passes carry FIDs rather than serialized attribute values.
      - Multi-tile runs map temporary geometry IDs to source FIDs across workers
        and passes.
      - Finalization joins attributes by FID and groups by dissolve keys and tile.
      - Distinct FIDs prevent recounting features split across processing tiles.
      - JSON strings are built at finalization and include source FIDs.

    Only arguments specific to the internal dissolve operation are documented here.
    For the other arguments, check out the corresponding function in geoops.py.

    Args:
        tmp_basedir (Optional[Path], optional): The directory to create the temporary
            directory in for this operation call. If None, it is created in the default
            geofileops temporary directory. Useful to keep all temporary files for an
            operation that uses multiple steps in one temporary directory.
            Defaults to None.
    """
    # Init and validate input parameters
    # ----------------------------------
    operation_name = f"{operation_prefix}dissolve"
    logger = logging.getLogger(f"geofileops.{operation_name}")

    # Check if we need to calculate anyway
    if _io_util.output_exists(path=output_path, remove_if_exists=force):
        return

    # Standardize parameter to simplify the rest of the code
    if groupby_columns is not None:
        if isinstance(groupby_columns, str):
            # If a string is passed, convert to list
            groupby_columns = [groupby_columns]
        elif len(groupby_columns) == 0:
            # If an empty list of geometry columns is passed, convert it to None
            groupby_columns = None
    source_groupby_columns = list(groupby_columns or [])

    if input_path == output_path:
        raise ValueError("output_path must not equal input_path")
    if not input_path.exists():
        raise FileNotFoundError(f"input_path not found: {input_path}")

    if not isinstance(input_layer, LayerInfo):
        input_layer = gfo.get_layerinfo(input_path, input_layer)

    if input_layer.geometrytype.to_primitivetype in [
        PrimitiveType.POINT,
        PrimitiveType.LINESTRING,
    ] and (tiles_path is not None or nb_squarish_tiles > 1):
        raise ValueError(
            f"Dissolve to tiles is not supported for {input_layer.geometrytype}"
            ", so tiles_path should be None and nb_squarish_tiles should be 1)"
        )

    if output_layer is None:
        output_layer = gfo.get_default_layer(output_path)

    # Check columns in groupby_columns
    columns_available = [*list(input_layer.columns), "fid"]
    if groupby_columns is not None:
        columns_in_layer_upper = [column.upper() for column in columns_available]
        for column in groupby_columns:
            if column.upper() not in columns_in_layer_upper:
                raise ValueError(
                    f"column in groupby_columns not available in layer: {column}"
                )
        columns_available = _general_util.align_casing_list(
            columns_available, groupby_columns, raise_on_missing=False
        )

    if agg_columns is not None:
        # Check agg_columns param
        # Validate the dict structure, so we can assume everything is OK further on
        _parameter_helper.validate_agg_columns(agg_columns)

        # First take a deep copy, as values can be changed further on to treat columns
        # case insensitive
        agg_columns = copy.deepcopy(agg_columns)
        if "json" in agg_columns:
            if agg_columns["json"] is None:
                agg_columns["json"] = [
                    c for c in columns_available if c.lower() not in ("index", "fid")
                ]
            else:
                # Align casing of column names to data
                agg_columns["json"] = _general_util.align_casing_list(
                    agg_columns["json"], columns_available
                )
        elif "columns" in agg_columns:
            # Loop through all rows
            for agg_column in agg_columns["columns"]:
                # Check if column exists + set casing same as in data
                agg_column["column"] = _general_util.align_casing(
                    agg_column["column"], columns_available
                )

    dissolved_id_column = None

    # Check what we need to do in an error occurs
    on_data_error = ConfigOptions.get_on_data_error

    # Warn about low memory availability if needed
    _general_helper.warn_if_low_mem(called_from=operation_name)

    # Now start dissolving
    # --------------------
    # Empty or Line and point layers are:
    #   * not so large (memory-wise)
    #   * aren't computationally heavy
    # Additionally line layers are a pain to handle correctly because of
    # rounding issues at the borders of tiles... so just dissolve them in one go.
    if input_layer.featurecount == 0 or input_layer.geometrytype.to_primitivetype in [
        PrimitiveType.POINT,
        PrimitiveType.LINESTRING,
    ]:
        _geoops_sql.dissolve_singlethread(
            input_path=input_path,
            output_path=output_path,
            explodecollections=explodecollections,
            groupby_columns=groupby_columns,
            agg_columns=agg_columns,
            input_layer=input_layer,
            output_layer=output_layer,
            gridsize=gridsize,
            keep_empty_geoms=False,
            where_post=where_post,
            force=force,
            tmp_basedir=tmp_basedir,
        )

    elif input_layer.geometrytype.to_primitivetype is PrimitiveType.POLYGON:
        start_time = datetime.now()

        # Prepare where_post
        if where_post is not None:
            if where_post == "":
                where_post = None
            else:
                # Set geometrycolumn to "geom", because temp files are saved as gpkg.
                where_post = where_post.format(geometrycolumn="geom")

        # If a tiles_path is specified, read those tiles...
        result_tiles_gdf = None
        if tiles_path is not None:
            result_tiles_gdf = gfo.read_file(tiles_path)
            if nb_parallel == -1:
                nb_cpu = multiprocessing.cpu_count()
                nb_parallel = nb_cpu  # int(1.25 * nb_cpu)
                logger.debug(f"{nb_cpu=}, {nb_parallel=}")
        else:
            # Else, create a grid based on the number of tiles wanted as result
            # Use a margin of 1 meter around the bounds
            margin = 1.0
            if input_layer.crs is not None and not input_layer.crs.is_projected:
                # If geographic crs, 1 degree = 111 km or 111000 m
                margin /= 111000
            bounds = input_layer.total_bounds
            bounds = (
                bounds[0] - margin,
                bounds[1] - margin,
                bounds[2] + margin,
                bounds[3] + margin,
            )
            result_tiles_gdf = gpd.GeoDataFrame(
                geometry=pygeoops.create_grid2(bounds, nb_squarish_tiles),
                crs=input_layer.crs,
            )

        # Apply gridsize tolerance on tiles, otherwise the border polygons can't be
        # unioned properly because gaps appear after rounding coordinates.
        if gridsize != 0.0:
            result_tiles_gdf.geometry = shapely.set_precision(
                result_tiles_gdf.geometry, grid_size=gridsize
            )
        if len(result_tiles_gdf) > 1:
            gfo.to_file(
                result_tiles_gdf,
                output_path.parent / f"{output_path.stem}_tiles.gpkg",
            )

        # If a tiled result is asked, add tile_id to group on for the result
        if len(result_tiles_gdf) > 1:
            result_tiles_gdf["tile_id"] = result_tiles_gdf.reset_index().index
        if agg_columns is not None and len(result_tiles_gdf) > 1:
            existing_columns = set(input_layer.columns)
            dissolved_id_column = _ogr_sql_util.get_unique_columnname(
                "__gfo_dissolved_id", existing_columns
            )

        # The dissolve for polygons is done in several passes, and after the first
        # pass, only the 'onborder' features are further dissolved, as the
        # 'notonborder' features are already OK.
        with _general_helper.create_gfo_tmp_dir(operation_name, tmp_basedir) as tmp_dir:
            if output_layer is None:
                output_layer = gfo.get_default_layer(output_path)
            output_tmp_path = tmp_dir / "output_tmp.gpkg"
            prev_nb_batches = None
            last_pass = False
            pass_id = 1
            geoindex_column = "__tmp_geoindex_column__"

            logger.info(f"Start, with input {input_path}")
            input_pass_path = input_path
            input_pass_layer = input_layer
            while True:
                # Get info of the current file that needs to be dissolved
                nb_rows_total = input_pass_layer.featurecount

                # Calculate the best number of parallel processes and batches for
                # the available resources for the current pass
                # Limit the nb of rows per batch, as dissolve slows down with more rows.
                nb_parallel, nb_batches = _gpd_determine_nb_batches(
                    nb_rows_total=nb_rows_total,
                    nb_parallel=nb_parallel,
                    batchsize=batchsize,
                    parallelization_config=_GpdParallelizationConfig(
                        max_rows_per_batch=10000
                    ),
                )

                # If the ideal number of batches is close to the nb. result tiles asked,
                # dissolve towards the asked result!
                # If not, a temporary result is created using smaller tiles
                if nb_batches <= len(result_tiles_gdf) * 1.1:
                    tiles_gdf = result_tiles_gdf
                    last_pass = True
                    nb_parallel = min(len(result_tiles_gdf), nb_parallel)
                elif len(result_tiles_gdf) == 1:
                    # Create a grid based on the ideal number of batches, but make
                    # sure the number is smaller than the maximum...
                    nb_squarish_tiles_max = None
                    if prev_nb_batches is not None:
                        nb_squarish_tiles_max = max(prev_nb_batches - 1, 1)
                        nb_batches = min(nb_batches, nb_squarish_tiles_max)
                    grid_total_bounds = (
                        input_pass_layer.total_bounds[0] - 0.000001,
                        input_pass_layer.total_bounds[1] - 0.000001,
                        input_pass_layer.total_bounds[2] + 0.000001,
                        input_pass_layer.total_bounds[3] + 0.000001,
                    )
                    tiles_gdf = gpd.GeoDataFrame(
                        geometry=pygeoops.create_grid2(
                            total_bounds=grid_total_bounds,
                            nb_squarish_tiles=nb_batches,
                            nb_squarish_tiles_max=nb_squarish_tiles_max,
                        ),
                        crs=input_pass_layer.crs,
                    )
                else:
                    # If a grid is specified already, add extra columns/rows instead of
                    # creating new one...
                    tiles_gdf = pygeoops.split_tiles(result_tiles_gdf, nb_batches)

                # Apply gridsize tolerance on tiles, otherwise the border polygons can't
                # be unioned properly because gaps appear after rounding coordinates.
                if gridsize != 0.0:
                    tiles_gdf.geometry = shapely.set_precision(
                        tiles_gdf.geometry, grid_size=gridsize
                    )
                gfo.to_file(tiles_gdf, tmp_dir / f"output_{pass_id}_tiles.gpkg")

                # If the number of tiles ends up as 1, it is the last pass anyway...
                if len(tiles_gdf) == 1:
                    last_pass = True

                # If we are not in the last pass, onborder parcels will need extra
                # processing still in further passes, so are saved in a seperate
                # gfo. The notonborder rows are final immediately
                if last_pass is not True:
                    output_tmp_onborder_path = (
                        tmp_dir / f"output_{pass_id}_onborder.gpkg"
                    )
                else:
                    output_tmp_onborder_path = output_tmp_path

                # Now go!
                logger.info(
                    f"Start pass {pass_id} to {len(tiles_gdf)} tiles "
                    f"(batch size: {int(nb_rows_total / len(tiles_gdf))})"
                )
                pass_start = datetime.now()
                _dissolve_polygons_pass(
                    input_path=input_pass_path,
                    output_notonborder_path=output_tmp_path,
                    output_onborder_path=output_tmp_onborder_path,
                    explodecollections=explodecollections,
                    groupby_columns=groupby_columns,
                    tiles_gdf=tiles_gdf,
                    input_layer=input_pass_layer,
                    output_layer=output_layer,
                    gridsize=gridsize,
                    keep_empty_geoms=False,
                    nb_parallel=nb_parallel,
                    geoindex_column=geoindex_column,
                    dissolved_id_column=dissolved_id_column,
                    on_data_error=on_data_error,
                )
                logger.info(f"Pass {pass_id} ready, took {datetime.now() - pass_start}")

                # If this was the last pass, if the last pass didn't have any onborder
                # polygons as result, we are ready dissolving.
                if last_pass or not output_tmp_onborder_path.exists():
                    break

                # Prepare the next pass
                prev_nb_batches = len(tiles_gdf)
                input_pass_path = output_tmp_onborder_path
                input_pass_layer = gfo.get_layerinfo(input_pass_path)
                pass_id += 1

            # Calculation ready! Now finalise output!
            logger.info("Finalize result")
            # If there is a result on border, append it to the rest
            if (
                str(output_tmp_onborder_path) != str(output_tmp_path)
                and output_tmp_onborder_path.exists()
            ):
                gfo.copy_layer(
                    output_tmp_onborder_path,
                    output_tmp_path,
                    dst_layer=output_layer,
                    write_mode="append",
                    preserve_fid=False,
                )

            # If there is a result...
            if output_tmp_path.exists():
                # If aggregation columns are specified, copy them to the temp output
                # geopackage for easy joining later
                if agg_columns is not None:
                    _copy_aggregation_attributes(
                        input_path=input_path,
                        output_path=output_tmp_path,
                        input_layer=input_layer,
                        agg_columns=agg_columns,
                        groupby_columns=source_groupby_columns,
                    )

                # If tiled output asked, add "tile_id" to groupby_columns
                has_output_tile_id = len(result_tiles_gdf) > 1
                if has_output_tile_id:
                    if groupby_columns is None:
                        groupby_columns = ["tile_id"]
                    else:
                        groupby_columns = list(groupby_columns).copy()
                        groupby_columns.append("tile_id")

                # Prepare strings to use in select based on groupby_columns
                if groupby_columns is not None:
                    groupby_prefixed_list = [
                        f'{{prefix}}"{column}"' for column in groupby_columns
                    ]
                    groupby_select_prefixed_str = (
                        f", {', '.join(groupby_prefixed_list)}"
                    )
                    groupby_groupby_prefixed_str = (
                        f"GROUP BY {', '.join(groupby_prefixed_list)}"
                    )

                    # Using IS for comparison is equivalent to using = for non-null
                    # values, but it also correctly handles nulls.
                    groupby_filter_list = [
                        f' AND geo_data."{column}" IS json_data."{column}"'
                        for column in groupby_columns
                    ]
                    groupby_filter_str = " ".join(groupby_filter_list)
                else:
                    groupby_select_prefixed_str = ""
                    groupby_groupby_prefixed_str = ""
                    groupby_filter_str = ""

                # Prepare strings to use in select based on agg_columns
                agg_columns_str = ""
                json_agg_columns_str = ""
                if agg_columns is not None:
                    if dissolved_id_column is not None:
                        json_rows_value_str = "source_fids.original_fid AS original_fid"
                        if has_output_tile_id:
                            json_rows_value_str += (
                                ', layer_for_json."tile_id" AS tile_id'
                            )
                        quoted_id_column = dissolved_id_column.replace('"', '""')
                        json_rows_join_str = (
                            'JOIN "__gfo_dissolve_attributes" attributes '
                            'ON attributes."original_fid" = json_rows.original_fid'
                        )
                        json_rows_expand_str = (
                            'JOIN "__gfo_dissolve_source_fids" source_fids '
                            f"ON source_fids.dissolved_id = "
                            f'layer_for_json."{quoted_id_column}"'
                        )
                        attribute_groupby_columns = [
                            f'attributes."{column}"'
                            for column in source_groupby_columns
                        ]
                        if has_output_tile_id:
                            attribute_groupby_columns.append('json_rows."tile_id"')
                        json_rows_groupby_select_str = ""
                    else:
                        attribute_groupby_columns = [
                            f'attributes."{column}"'
                            for column in source_groupby_columns
                        ]

                    json_groupby_select_str = (
                        ", ".join(attribute_groupby_columns) or "1"
                    )
                    json_rows_groupby_clause_str = (
                        f"GROUP BY {', '.join(attribute_groupby_columns)}"
                        if attribute_groupby_columns
                        else ""
                    )

                    if "json" in agg_columns:
                        agg_columns_str = ", json_data.json"
                        json_fid_key = "fid_orig"
                        json_columns = agg_columns["json"]
                        for suffix in range(1, 100000):
                            if json_fid_key not in json_columns:
                                break
                            json_fid_key = f"fid_orig{suffix}"
                        json_object_fields = [
                            f"'{json_fid_key}', attributes.\"original_fid\""
                        ]
                        for column in json_columns:
                            quoted_column = column.replace('"', '""')
                            quoted_json_key = column.replace("'", "''")
                            json_object_fields.append(
                                f"'{quoted_json_key}', attributes.\"{quoted_column}\""
                            )
                        json_row_str = (
                            f"(json_object({', '.join(json_object_fields)}) || '')"
                        )
                        json_agg_columns_str = (
                            f", json_group_array({json_row_str}) AS json"
                        )
                    elif "columns" in agg_columns:
                        for agg_column in agg_columns["columns"]:
                            # Init
                            distinct_str = ""
                            extra_param_str = ""

                            # Prepare aggregation keyword.
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
                                raise ValueError(
                                    f"aggregation {agg_column['agg']} is not supported"
                                )

                            # If distinct is specified, add the distinct keyword
                            if (
                                "distinct" in agg_column
                                and agg_column["distinct"] is True
                            ):
                                distinct_str = "DISTINCT "

                            # Prepare column expressions for the outer and inner query.
                            quoted_column = agg_column["column"].replace('"', '""')
                            column_str = f'attributes."{quoted_column}"'

                            agg_columns_str += f', json_data."{agg_column["as"]}"'
                            json_agg_columns_str += (
                                f", {aggregation_str}({distinct_str}"
                                f"{column_str}"
                                f'{extra_param_str}) AS "{agg_column["as"]}"'
                            )

                # Prepare SQL statement for final output file if one is needed.

                # All tiles are already dissolved to groups, but now the results from
                # all tiles could still need to be grouped/collected together.
                if agg_columns is None:
                    # If there are no aggregation columns, things are not too
                    # complicated.
                    if explodecollections:
                        # As explodecollections is also true, no grouping nor collecting
                        # needed.
                        sql_stmt = f"""
                            SELECT {{geometrycolumn}}
                                  {groupby_select_prefixed_str.format(prefix="layer.")}
                              FROM "{{input_layer}}" layer
                             ORDER BY layer.{geoindex_column}
                        """
                    else:
                        # No explodecollections, so collect to one geometry
                        # (per groupby if applicable).
                        sql_stmt = f"""
                            SELECT ST_Collect({{geometrycolumn}}) AS {{geometrycolumn}}
                                  {groupby_select_prefixed_str.format(prefix="layer.")}
                              FROM "{{input_layer}}" layer
                              {groupby_groupby_prefixed_str.format(prefix="layer.")}
                             ORDER BY MIN(layer.{geoindex_column})
                        """
                else:
                    # If agg_columns specified, postprocessing is a bit more
                    # complicated.
                    if dissolved_id_column is None:
                        json_agg_sql_stmt = f"""
                            SELECT {json_groupby_select_str}
                                  {json_agg_columns_str}
                              FROM "__gfo_dissolve_attributes" attributes
                              {json_rows_groupby_clause_str}
                        """
                    else:
                        json_agg_sql_stmt = f"""
                            SELECT {json_groupby_select_str}
                                  {json_agg_columns_str}
                              FROM (
                                SELECT DISTINCT
                                    {json_rows_value_str}
                                       {json_rows_groupby_select_str}
                                  FROM "{{input_layer}}" layer_for_json
                                 {json_rows_expand_str}
                               ) json_rows
                                {json_rows_join_str}
                              {json_rows_groupby_clause_str}
                        """
                    sql_stmt = f"""
                        SELECT geo_data.{{geometrycolumn}}
                              {groupby_select_prefixed_str.format(prefix="geo_data.")}
                              {agg_columns_str}
                          FROM (
                            SELECT ST_Collect(layer_geo.{{geometrycolumn}}
                                   ) AS {{geometrycolumn}}
                                  {groupby_select_prefixed_str.format(prefix="layer_geo.")}
                                  ,MIN(layer_geo.{geoindex_column}) as {geoindex_column}
                              FROM "{{input_layer}}" layer_geo
                              {groupby_groupby_prefixed_str.format(prefix="layer_geo.")}
                            ) geo_data
                          JOIN (
                            {json_agg_sql_stmt}
                          ) json_data
                         WHERE 1=1
                            {groupby_filter_str}
                          ORDER BY geo_data.{geoindex_column}
                    """

                # Apply where_post parameter if needed/possible
                if where_post is not None and not explodecollections:
                    # explodecollections is not True, so we can add it to sql_stmt.
                    # If explodecollections would be True, we need to wait to apply the
                    # where_post till after explodecollections is applied to be sure it
                    # gives correct results.
                    where_post = where_post.format(geometrycolumn="geom")
                    sql_stmt = f"""
                        SELECT * FROM
                            ( {sql_stmt}
                            )
                         WHERE {where_post}
                    """
                    # where_post has been applied already so set to None.
                    where_post = None

                # Execute the prepared sql statement
                output_geometrytype = (
                    input_layer.geometrytype.to_singletype
                    if explodecollections
                    else input_layer.geometrytype.to_multitype
                )
                sql_stmt = sql_stmt.format(
                    geometrycolumn="geom", input_layer=output_layer
                )

                options = {}
                if where_post is None:
                    name = GeoPath(output_path).name_nozip
                else:
                    # where_post still needs to be ran, so no index + to gpkg
                    name = "output_tmp2_final.gpkg"
                    options["LAYER_CREATION.SPATIAL_INDEX"] = False
                output_tmp_final_path = tmp_dir / name

                if groupby_columns:
                    # Create a groupby index if groupby columns are specified.
                    # For an input file of 16 GB adding the groupby index (of 1.5 GB)
                    # reduced temp space used by SQLite to 12 GB instead of 26 GB.
                    groupby_columns_sql = ", ".join(
                        f'"{column}"' for column in groupby_columns
                    )
                    fileops.execute_sql(
                        output_tmp_path,
                        sql_stmt=(
                            'CREATE INDEX IF NOT EXISTS "groupby_idx" '
                            f'ON "{output_layer}" ({groupby_columns_sql})'
                        ),
                        sql_dialect="SQLITE",
                    )

                _ogr_util.vector_translate(
                    input_path=output_tmp_path,
                    output_path=output_tmp_final_path,
                    output_layer=output_layer,
                    sql_stmt=sql_stmt,
                    sql_dialect="SQLITE",
                    force_output_geometrytype=output_geometrytype,
                    explodecollections=explodecollections,
                    options=options,
                )

                # We still need to apply the where_post filter
                if where_post is not None:
                    name = f"output_tmp3_where_{GeoPath(output_path).suffix_full}"
                    output_tmp_local_path = tmp_dir / name
                    tmp_info = gfo.get_layerinfo(output_tmp_final_path, output_layer)
                    where_post = where_post.format(
                        geometrycolumn=tmp_info.geometrycolumn
                    )
                    sql_stmt = f"""
                        SELECT * FROM "{output_layer}"
                         WHERE {where_post}
                    """
                    sql_stmt = sql_stmt.format(geometrycolumn=tmp_info.geometrycolumn)
                    _ogr_util.vector_translate(
                        input_path=output_tmp_final_path,
                        output_path=output_tmp_local_path,
                        output_layer=output_layer,
                        force_output_geometrytype=output_geometrytype,
                        sql_stmt=sql_stmt,
                        sql_dialect="SQLITE",
                    )
                    output_tmp_final_path = output_tmp_local_path

                # Zip if needed
                if (
                    output_path.suffix.lower() == ".zip"
                    and output_tmp_final_path.suffix.lower() != ".zip"
                ):
                    zipped_path = Path(f"{output_tmp_final_path.as_posix()}.zip")
                    fileops.zip_geofile(output_tmp_final_path, zipped_path)
                    output_tmp_final_path = zipped_path

                # Now we are ready to move the result to the final spot...
                gfo.move(output_tmp_final_path, output_path)

        logger.info(f"Ready, full dissolve took {datetime.now() - start_time}")

    else:
        raise NotImplementedError(
            f"Unsupported input geometrytype: {input_layer.geometrytype}"
        )


def _dissolve_group_key(row: pd.Series, groupby_columns: list[str] | None) -> tuple:
    key = []
    for column in groupby_columns or []:
        value = row[column]
        if pd.isna(value):
            value = None
        elif isinstance(value, np.generic):
            value = value.item()
        key.append(value)
    return tuple(key)


def _copy_aggregation_attributes(
    input_path: Path,
    output_path: Path,
    input_layer: LayerInfo,
    agg_columns: dict,
    groupby_columns: list[str],
) -> None:
    """Copy source attributes once into the temporary dissolve GeoPackage."""
    if "columns" in agg_columns:
        aggregation_columns = {
            agg_column["column"] for agg_column in agg_columns["columns"]
        }
    else:
        aggregation_columns = set(agg_columns["json"])
    attribute_columns = sorted(aggregation_columns | set(groupby_columns))

    def quote_identifier(identifier: str) -> str:
        return f'"{identifier.replace(chr(34), chr(34) * 2)}"'

    attributes_table = quote_identifier("__gfo_dissolve_attributes")
    orig_fid_columns = quote_identifier("original_fid")
    if input_path.suffix.lower() != ".gpkg":
        attribute_columns_sql = ", ".join(
            quote_identifier(column) for column in attribute_columns
        )
        sql_stmt = (
            f"SELECT FID AS {orig_fid_columns}, {attribute_columns_sql} "
            f"FROM {quote_identifier(input_layer.name)}"
        )
        gfo.copy_layer(
            src=input_path,
            dst=output_path,
            dst_layer="__gfo_dissolve_attributes",
            write_mode="add_layer",
            sql_stmt=sql_stmt,
            sql_dialect="OGRSQL",
            force_output_geometrytype="NONE",
            create_spatial_index=False,
        )
    else:
        fid_column = quote_identifier(input_layer.fid_column)
        source_table = quote_identifier(input_layer.name)
        attribute_columns_sql = ", ".join(
            quote_identifier(column) for column in attribute_columns
        )

        connection = sqlite3.connect(output_path)
        try:
            connection.execute("ATTACH DATABASE ? AS source_data", (str(input_path),))
            connection.execute(
                f"CREATE TABLE {attributes_table} AS "
                f"SELECT {fid_column} AS {orig_fid_columns}, "
                f"{attribute_columns_sql} "
                f"FROM source_data.{source_table}"
            )
            connection.execute(
                f'CREATE UNIQUE INDEX "idx_gfo_dissolve_attributes_original_fid" '
                f"ON {attributes_table} ({orig_fid_columns})"
            )
            connection.commit()
        finally:
            connection.close()


def _read_dissolve_source_fids(
    input_path: Path, dissolved_ids: Iterable[str]
) -> dict[str, set[int]]:
    """Read source FIDs associated with dissolved geometry IDs."""
    source_fids_by_dissolved_id: dict[str, set[int]] = {}
    dissolved_ids = list(dissolved_ids)
    if len(dissolved_ids) == 0:
        return source_fids_by_dissolved_id

    connection = sqlite3.connect(input_path)
    try:
        connection.execute(
            "CREATE TEMP TABLE requested_dissolved_ids (dissolved_id TEXT)"
        )
        connection.executemany(
            "INSERT INTO requested_dissolved_ids VALUES (?)",
            ((dissolved_id,) for dissolved_id in dissolved_ids),
        )
        for dissolved_id, original_fid in connection.execute(
            """
            SELECT source_fids.dissolved_id, source_fids.original_fid
              FROM __gfo_dissolve_source_fids source_fids
              JOIN requested_dissolved_ids requested
                ON requested.dissolved_id = source_fids.dissolved_id
            """
        ):
            source_fids_by_dissolved_id.setdefault(dissolved_id, set()).add(
                original_fid
            )
    finally:
        connection.close()
    return source_fids_by_dissolved_id


def _write_dissolve_source_fids(
    output_path: Path,
    output_gdf: gpd.GeoDataFrame,
    dissolved_id_column: str,
    source_fids_by_dissolved_id: dict[str, set[int]],
) -> None:
    """Persist dissolved-ID-to-source-FID relations in a worker GeoPackage."""
    dissolved_ids = output_gdf[dissolved_id_column].dropna().unique()
    records = [
        (dissolved_id, original_fid)
        for dissolved_id in dissolved_ids
        for original_fid in source_fids_by_dissolved_id[dissolved_id]
    ]
    if not records:
        return

    connection = sqlite3.connect(output_path)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS __gfo_dissolve_source_fids (
                dissolved_id TEXT NOT NULL,
                original_fid INTEGER NOT NULL,
                PRIMARY KEY (dissolved_id, original_fid)
            )
            """
        )
        connection.executemany(
            "INSERT OR IGNORE INTO __gfo_dissolve_source_fids VALUES (?, ?)", records
        )
        connection.commit()
    finally:
        connection.close()


def _append_dissolve_source_fids(
    source_path: Path, destination_path: Path, layer_name: str | None
) -> None:
    """Append a worker's dissolved-ID-to-source-FID relations to a shared GeoPackage."""
    connection = sqlite3.connect(destination_path)
    try:
        connection.execute("ATTACH DATABASE ? AS source_data", (str(source_path),))
        source_has_relation = connection.execute(
            """
            SELECT 1 FROM source_data.sqlite_master
             WHERE type='table' AND name='__gfo_dissolve_source_fids'
            """
        ).fetchone()
        if source_has_relation is None:
            if layer_name is None:
                raise RuntimeError(
                    "Layer name required to validate an empty source-FID relation"
                )
            quoted_layer = layer_name.replace('"', '""')
            row_count = connection.execute(
                f'SELECT count(*) FROM source_data."{quoted_layer}"'
            ).fetchone()[0]
            if row_count > 0:
                raise RuntimeError(
                    f"Missing dissolve source-FID relation table in {source_path}"
                )
            return

        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS __gfo_dissolve_source_fids (
                dissolved_id TEXT NOT NULL,
                original_fid INTEGER NOT NULL,
                PRIMARY KEY (dissolved_id, original_fid)
            )
            """
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO __gfo_dissolve_source_fids
            SELECT dissolved_id, original_fid
              FROM source_data.__gfo_dissolve_source_fids
            """
        )
        connection.commit()
    finally:
        connection.close()


def _dissolve_polygons_pass(
    input_path: Path,
    output_notonborder_path: Path,
    output_onborder_path: Path,
    explodecollections: bool,
    groupby_columns: Iterable[str] | None,
    tiles_gdf: gpd.GeoDataFrame,
    input_layer: str | LayerInfo | None,
    output_layer: str | None,
    gridsize: float,
    keep_empty_geoms: bool,
    nb_parallel: int,
    geoindex_column: str,
    dissolved_id_column: str | None,
    on_data_error: str = "raise",
) -> None:
    start_time = datetime.now()
    if not isinstance(input_layer, LayerInfo):
        input_layer = gfo.get_layerinfo(input_path, input_layer)

    # Make sure the input file has a spatial index
    tmp_dir = output_onborder_path.parent
    # If it is not a .gpkg.zip that already has a spatial index, unzip the file if it is
    # zipped and create a spatial index on it if it doesn't have one.
    if not (
        input_path.name.lower().endswith(".gpkg.zip")
        and fileops.has_spatial_index(input_path)
    ):
        if GeoPath(input_path).is_multi_suffix:
            # Unzip, as we can't create a spatial index on a zipped file
            unzipped_dir = tmp_dir / "input_unzipped"
            input_path = fileops.unzip_geofile(input_path, unzipped_dir)
        gfo.create_spatial_index(input_path, layer=input_layer, exist_ok=True)

    # Start calculation in parallel# Start processing
    worker_type = _general_helper.worker_type_to_use(input_layer.featurecount)
    with _processing_util.PooledExecutorFactory(
        worker_type=worker_type,
        max_workers=nb_parallel,
        initializer=_processing_util.initialize_worker,
        initargs=(worker_type,),
    ) as calculate_pool:
        batches: dict[int, dict] = {}
        nb_batches = len(tiles_gdf)
        nb_batches_done = 0
        future_to_batch_id = {}
        nb_rows_done = 0
        for batch_id, tile_row in enumerate(tiles_gdf.itertuples()):
            batches[batch_id] = {}
            batches[batch_id]["layer"] = output_layer
            batches[batch_id]["bounds"] = tile_row.geometry.bounds

            # Output each batch to a seperate temporary file, otherwise there
            # are timeout issues when processing large files
            suffix = output_notonborder_path.suffix
            name = f"{output_notonborder_path.stem}_{batch_id}{suffix}"
            output_notonborder_tmp_partial_path = tmp_dir / name
            batches[batch_id]["output_notonborder_tmp_partial_path"] = (
                output_notonborder_tmp_partial_path
            )
            name = f"{output_onborder_path.stem}_{batch_id}{suffix}"
            output_onborder_tmp_partial_path = tmp_dir / name
            batches[batch_id]["output_onborder_tmp_partial_path"] = (
                output_onborder_tmp_partial_path
            )

            # Get tile_id if present
            tile_id = tile_row.tile_id if "tile_id" in tile_row._fields else None

            future = calculate_pool.submit(
                _dissolve_polygons,
                input_path=input_path,
                output_notonborder_path=output_notonborder_tmp_partial_path,
                output_onborder_path=output_onborder_tmp_partial_path,
                explodecollections=explodecollections,
                groupby_columns=groupby_columns,
                input_geometrytype=input_layer.geometrytype,
                input_layer=input_layer,
                output_layer=output_layer,
                bbox=tile_row.geometry.bounds,
                tile_id=tile_id,
                gridsize=gridsize,
                keep_empty_geoms=keep_empty_geoms,
                geoindex_column=geoindex_column,
                dissolved_id_column=dissolved_id_column,
                on_data_error=on_data_error,
            )
            future_to_batch_id[future] = batch_id

        # Loop till all parallel processes are ready, but process each one
        # that is ready already
        _general_util.report_progress(
            start_time, nb_batches_done, nb_batches, "dissolve"
        )
        # Warn about low memory availability if needed
        _general_helper.warn_if_low_mem(called_from="dissolve, loop")

        for future in futures.as_completed(future_to_batch_id):
            try:
                # If the calculate gave results
                nb_batches_done += 1
                batch_id = future_to_batch_id[future]
                result = future.result()

                if result is not None:
                    nb_rows_done += result["nb_rows_done"]
                    if result["nb_rows_done"] > 0 and result["total_time"] > 0:
                        rows_per_sec = round(
                            result["nb_rows_done"] / result["total_time"]
                        )
                        logger.debug(
                            f"Batch {batch_id} processed {result['nb_rows_done']} rows "
                            f"({rows_per_sec}/sec)"
                        )
                        if "perfstring" in result:
                            logger.debug(f"Perfstring: {result['perfstring']}")

                    # Start copy of the result to a common file
                    batch_id = future_to_batch_id[future]

                    # If calculate gave notonborder results, append to output
                    output_notonborder_tmp_partial_path = batches[batch_id][
                        "output_notonborder_tmp_partial_path"
                    ]
                    if (
                        output_notonborder_tmp_partial_path.exists()
                        and output_notonborder_tmp_partial_path.stat().st_size > 0
                    ):
                        if not output_notonborder_path.exists():
                            fileops.move(
                                src=output_notonborder_tmp_partial_path,
                                dst=output_notonborder_path,
                            )
                        else:
                            fileops.copy_layer(
                                src=output_notonborder_tmp_partial_path,
                                dst=output_notonborder_path,
                                src_layer=output_layer,
                                dst_layer=output_layer,
                                write_mode="append",
                                create_spatial_index=False,
                                preserve_fid=False,
                            )
                            if dissolved_id_column is not None:
                                _append_dissolve_source_fids(
                                    output_notonborder_tmp_partial_path,
                                    output_notonborder_path,
                                    output_layer,
                                )
                            gfo.remove(output_notonborder_tmp_partial_path)

                    # If calculate gave onborder results, append to output
                    output_onborder_tmp_partial_path = batches[batch_id][
                        "output_onborder_tmp_partial_path"
                    ]
                    if (
                        output_onborder_tmp_partial_path.exists()
                        and output_onborder_tmp_partial_path.stat().st_size > 0
                    ):
                        if not output_onborder_path.exists():
                            fileops.move(
                                src=output_onborder_tmp_partial_path,
                                dst=output_onborder_path,
                            )
                        else:
                            fileops.copy_layer(
                                src=output_onborder_tmp_partial_path,
                                dst=output_onborder_path,
                                src_layer=output_layer,
                                dst_layer=output_layer,
                                write_mode="append",
                                create_spatial_index=False,
                                preserve_fid=False,
                            )
                            if dissolved_id_column is not None:
                                _append_dissolve_source_fids(
                                    output_onborder_tmp_partial_path,
                                    output_onborder_path,
                                    output_layer,
                                )
                            gfo.remove(output_onborder_tmp_partial_path)

            except Exception as ex:  # pragma: no cover
                batch_id = future_to_batch_id[future]
                message = f"Error executing {batches[batch_id]}: {ex}"
                logger.exception(message)
                calculate_pool.shutdown()
                raise RuntimeError(message) from ex

            # Log the progress and prediction speed
            _general_util.report_progress(
                start_time, nb_batches_done, nb_batches, "dissolve"
            )


def _dissolve_polygons(
    input_path: Path,
    output_notonborder_path: Path,
    output_onborder_path: Path,
    explodecollections: bool,
    groupby_columns: Iterable[str] | None,
    input_geometrytype: GeometryType,
    input_layer: str | LayerInfo | None,
    output_layer: str | None,
    bbox: tuple[float, float, float, float],
    tile_id: int | None,
    gridsize: float,
    keep_empty_geoms: bool,
    geoindex_column: str | None,
    dissolved_id_column: str | None,
    on_data_error: str = "raise",
) -> dict:
    # Init
    perfinfo: dict[str, float] = {}
    start_time = datetime.now()
    return_info = {
        "input_path": input_path,
        "output_notonborder_path": output_notonborder_path,
        "output_onborder_path": output_onborder_path,
        "bbox": bbox,
        "tile_id": tile_id,
        "gridsize": gridsize,
        "nb_rows_done": 0,
        "total_time": 0,
        "perfinfo": "",
    }

    # Read all records that are in the bbox
    retry_count = 0
    start_read = datetime.now()
    source_fids_by_group: dict[tuple, set[int]] = {}
    groupby_columns = list(groupby_columns) if groupby_columns is not None else None
    while True:
        try:
            columns_to_read: set[str] = set()
            if not isinstance(input_layer, LayerInfo):
                input_layer = gfo.get_layerinfo(input_path, input_layer)
            if groupby_columns is not None:
                columns_to_read.update(groupby_columns)
            fid_as_index = dissolved_id_column is not None
            has_dissolved_id = (
                dissolved_id_column is not None
                and dissolved_id_column in input_layer.columns
            )
            if dissolved_id_column is not None and has_dissolved_id:
                columns_to_read.add(dissolved_id_column)

            input_gdf = gfo.read_file(
                path=input_path,
                layer=input_layer.name,
                bbox=bbox,
                columns=columns_to_read,
                fid_as_index=fid_as_index,
            )

            if dissolved_id_column is not None:
                if has_dissolved_id:
                    source_fids_by_dissolved_id = _read_dissolve_source_fids(
                        input_path,
                        input_gdf[dissolved_id_column].dropna().astype(str).unique(),
                    )
                    for _, row in input_gdf.iterrows():
                        group_key = _dissolve_group_key(row, groupby_columns)
                        source_fids = source_fids_by_dissolved_id.get(
                            str(row[dissolved_id_column]), set()
                        )
                        source_fids_by_group.setdefault(group_key, set()).update(
                            source_fids
                        )
                else:
                    for source_fid, row in input_gdf.iterrows():
                        group_key = _dissolve_group_key(row, groupby_columns)
                        source_fids_by_group.setdefault(group_key, set()).add(
                            int(source_fid)
                        )

            break
        except Exception as ex:  # pragma: no cover
            if str(ex) == "database is locked":
                if retry_count < 10:
                    retry_count += 1
                    time.sleep(1)
                else:
                    raise Exception("retried 10 times, database still locked") from ex
            else:
                raise ex

    # Check result
    perfinfo["time_read"] = (datetime.now() - start_read).total_seconds()
    return_info["nb_rows_done"] = len(input_gdf)
    if return_info["nb_rows_done"] == 0:
        message = f"dissolve_polygons: no input geometries found in {input_path}"
        logger.info(message)
        return_info["message"] = message
        return_info["total_time"] = (datetime.now() - start_time).total_seconds()
        return return_info

    # Now the real processing
    start_dissolve = datetime.now()
    try:
        diss_gdf = _dissolve(
            df=input_gdf,
            by=groupby_columns,
            aggfunc="first",
            as_index=False,
            dropna=False,
            grid_size=gridsize,
        )
    except Exception as ex:  # pragma: no cover
        # If a GEOS exception occurs, check on_data_error on how to proceed.
        if on_data_error == "warn":
            message = f"Error processing tile, ENTIRE TILE LOST!!!: {ex}"
            warnings.warn(message, UserWarning, stacklevel=3)

            # Return
            return_info["perfinfo"] = perfinfo
            return_info["message"] = message
            return return_info
        else:
            raise ex

    perfinfo["time_dissolve"] = (datetime.now() - start_dissolve).total_seconds()

    output_source_fids_by_dissolved_id: dict[str, set[int]] = {}
    if dissolved_id_column is not None:
        dissolved_ids = [uuid.uuid4().hex for _ in range(len(diss_gdf))]
        diss_gdf[dissolved_id_column] = dissolved_ids
        for _, row in diss_gdf.iterrows():
            dissolved_id = row[dissolved_id_column]
            group_key = _dissolve_group_key(row, groupby_columns)
            output_source_fids_by_dissolved_id[dissolved_id] = source_fids_by_group[
                group_key
            ]

    if "index" in diss_gdf.columns and (
        groupby_columns is None or "index" not in groupby_columns
    ):
        diss_gdf.drop("index", axis=1, inplace=True)

    # If explodecollections is True and For polygons, explode multi-geometries.
    # If needed they will be 'collected' afterwards to multipolygons again.
    if explodecollections is True or input_geometrytype in [
        GeometryType.POLYGON,
        GeometryType.MULTIPOLYGON,
    ]:
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
        start_clip = datetime.now()
        bbox_gdf = gpd.GeoDataFrame(geometry=[sh_geom.box(*bbox)], crs=input_gdf.crs)

        # keep_geom_type=True gave sometimes error, and still does in 0.9.0
        # so use own implementation of keep_geom_type
        diss_gdf = gpd.clip(diss_gdf, bbox_gdf)  # , keep_geom_type=True)

        # Only keep geometries of the primitive type specified after clip...
        diss_gdf.geometry = pygeoops.collection_extract(
            diss_gdf.geometry, primitivetype=input_geometrytype.to_primitivetype
        )

        perfinfo["time_clip"] = (datetime.now() - start_clip).total_seconds()

    # Set empty geometries to None
    assert isinstance(diss_gdf.geometry, gpd.GeoSeries)
    diss_gdf.loc[diss_gdf.geometry.is_empty, diss_gdf.geometry.name] = None

    if not keep_empty_geoms:
        # Remove rows where geom is None
        diss_gdf = diss_gdf[~diss_gdf.geometry.isna()]

    # If there is no result, return
    if len(diss_gdf) == 0:
        message = f"Result is empty for {input_path}"
        return_info["message"] = message
        return_info["perfinfo"] = perfinfo
        return_info["total_time"] = (datetime.now() - start_time).total_seconds()
        return return_info

    # Split up in onborder and notonborder geometries
    if str(output_notonborder_path) == str(output_onborder_path):
        # If tiles don't need to be merged afterwards, treat everything as notonborder.
        onborder_gdf = None
        notonborder_gdf = diss_gdf
    else:
        # If not, save the polygons on the border seperately
        bbox_lines = shapely.get_parts(
            shapely.boundary(sh_geom.box(bbox[0], bbox[1], bbox[2], bbox[3]))
        )
        bbox_lines_gdf = gpd.GeoDataFrame(geometry=bbox_lines, crs=input_gdf.crs)
        onborder_gdf = gpd.sjoin(diss_gdf, bbox_lines_gdf, predicate="intersects")
        onborder_gdf.drop("index_right", axis=1, inplace=True)

        notonborder_gdf = diss_gdf[~diss_gdf.index.isin(onborder_gdf.index)].copy()

    # Save the result to destination file(s)
    start_to_file = datetime.now()

    # If explodecollections is False, force multitype to avoid warnings when some
    # batches contain singletype and some contain multitype geometries.
    force_multitype = not explodecollections
    if onborder_gdf is not None and len(onborder_gdf) > 0:
        gfo.to_file(
            onborder_gdf,
            output_onborder_path,
            layer=output_layer,
            force_multitype=force_multitype,
            create_spatial_index=False,
        )
        if dissolved_id_column is not None:
            assert dissolved_id_column is not None
            _write_dissolve_source_fids(
                output_onborder_path,
                onborder_gdf,
                dissolved_id_column,
                output_source_fids_by_dissolved_id,
            )

    if len(notonborder_gdf) > 0:
        # Add tile_id to the notonborder_gdf if relevant
        if tile_id is not None:
            notonborder_gdf["tile_id"] = tile_id

        # Add geoindex_column to the notonborder_gdf if asked
        if geoindex_column is not None:
            crs = notonborder_gdf.crs
            if crs is not None and crs.area_of_use is not None:
                transformer = Transformer.from_crs(
                    crs.geodetic_crs, crs, always_xy=True
                )
                crs_bounds = transformer.transform_bounds(*crs.area_of_use.bounds)
                notonborder_gdf[geoindex_column] = notonborder_gdf.hilbert_distance(
                    crs_bounds
                )
            else:
                # Use representative point x coordinate as fallback.
                notonborder_gdf[geoindex_column] = shapely.get_x(
                    notonborder_gdf.geometry.representative_point()
                )

        gfo.to_file(
            notonborder_gdf,
            output_notonborder_path,
            layer=output_layer,
            force_multitype=force_multitype,
            index=False,
            create_spatial_index=False,
        )
        if dissolved_id_column is not None:
            assert dissolved_id_column is not None
            _write_dissolve_source_fids(
                output_notonborder_path,
                notonborder_gdf,
                dissolved_id_column,
                output_source_fids_by_dissolved_id,
            )

    perfinfo["time_to_file"] = (datetime.now() - start_to_file).total_seconds()

    # Finalise...
    message = (
        f"dissolve_polygons: ready in {datetime.now() - start_time} on {input_path}"
    )
    logger.debug(message)

    # Collect perfinfo
    total_perf_time = 0.0
    perfstring = ""
    for perfcode, perfvalue in perfinfo.items():
        total_perf_time += perfvalue
        perfstring += f"{perfcode}: {perfvalue:.2f}, "
    return_info["total_time"] = (datetime.now() - start_time).total_seconds()
    perfinfo["unaccounted"] = (
        return_info["total_time"] - total_perf_time  # type: ignore[operator]
    )
    perfstring += f"unaccounted: {perfinfo['unaccounted']:.2f}"

    # Return
    return_info["perfinfo"] = perfinfo
    return_info["perfstring"] = perfstring
    return_info["message"] = message
    return return_info


def _dissolve(
    df: gpd.GeoDataFrame,
    by: str | Iterable[str] | None = None,
    aggfunc: str | dict | None = "first",
    as_index: bool = True,
    level: int | Iterable[int] | str | Iterable[str] | None = None,
    sort: bool = True,
    observed: bool = False,
    dropna: bool = True,
    grid_size: float = 0.0,
) -> gpd.GeoDataFrame:
    """Dissolve geometries within `groupby` into single observation.

    This is accomplished by applying the `unary_union` method
    to all geometries within a groupself.
    Observations associated with each `groupby` group will be aggregated
    using the `aggfunc`.

    Parameters
    ----------
    by : str or list-like, default None
        Column(s) whose values define groups to be dissolved. If None,
        whole GeoDataFrame is considered a single group.
    aggfunc : function, string or dict, default "first"
        Aggregation function for manipulation of data associated
        with each group. Passed to pandas `groupby.agg` method.
    as_index : boolean, default True
        If true, groupby columns become index of result.
    level : int or str or sequence of int or sequence of str, default None
        If the axis is a MultiIndex (hierarchical), group by a
        particular level or levels.
    sort : bool, default True
        Sort group keys. Get better performance by turning this off.
        Note this does not influence the order of observations within
        each group. Groupby preserves the order of rows within each group.
    observed : bool, default False
        This only applies if any of the groupers are Categoricals.
        If True: only show observed values for categorical groupers.
        If False: show all values for categorical groupers.
    dropna : bool, default True
        If True, and if group keys contain NA values, NA values
        together with row/column will be dropped. If False, NA
        values will also be treated as the key in groups.
        This parameter is not supported for pandas < 1.1.0.
        A warning will be emitted for earlier pandas versions
        if a non-default value is given for this parameter.

    Returns:
    -------
    GeoDataFrame

    Examples:
    --------
    >>> from shapely.geometry import Point
    >>> d = {
    ...     "col1": ["name1", "name2", "name1"],
    ...     "geometry": [Point(1, 2), Point(2, 1), Point(0, 1)],
    ... }
    >>> gdf = geopandas.GeoDataFrame(d, crs=4326)
    >>> gdf
        col1                 geometry
    0  name1  POINT (1.00000 2.00000)
    1  name2  POINT (2.00000 1.00000)
    2  name1  POINT (0.00000 1.00000)
    >>> dissolved = gdf.dissolve('col1')
    >>> dissolved  # doctest: +SKIP
                                                geometry
    col1
    name1  MULTIPOINT (0.00000 1.00000, 1.00000 2.00000)
    name2                        POINT (2.00000 1.00000)

    See Also:
    --------
    GeoDataFrame.explode : explode multi-part geometries into single geometries
    """
    if by is None and level is None:
        by_local = np.zeros(len(df), dtype="int64")
    else:
        by_local = by  # type: ignore[assignment]

    groupby_kwargs = {
        "by": by_local,
        "level": level,
        "sort": sort,
        "observed": observed,
        "dropna": dropna,
    }
    """
    if not compat.PANDAS_GE_11:
        groupby_kwargs.pop("dropna")

        if not dropna:  # If they passed a non-default dropna value
            warnings.warn("dropna kwarg is not supported for pandas < 1.1.0")
    """

    # Process non-spatial component
    data = pd.DataFrame(df.drop(columns=df.geometry.name))

    agg_data = data.groupby(**groupby_kwargs).agg(aggfunc)  # type: ignore[call-overload]
    # Check if all columns were properly aggregated
    columns_to_agg = [column for column in data.columns if column not in by_local]
    if len(columns_to_agg) != len(agg_data.columns):
        dropped_columns = [
            column for column in columns_to_agg if column not in agg_data.columns
        ]
        raise ValueError(
            f"Column(s) {dropped_columns} are not supported for aggregation, stop"
        )

    # Process spatial component
    def merge_geometries(block) -> BaseGeometry:  # noqa: ANN001
        return shapely.union_all(block, grid_size=grid_size)

    g = df.groupby(group_keys=False, **groupby_kwargs)[df.geometry.name].agg(
        merge_geometries
    )

    # Aggregate
    aggregated_geometry = gpd.GeoDataFrame(
        data=g, geometry=df.geometry.name, crs=df.crs
    )
    # Recombine
    aggregated = aggregated_geometry.join(agg_data)

    # Reset if requested
    if not as_index:
        aggregated = aggregated.reset_index()

    # Make sure output types of grouped columns are the same as input types.
    # E.g. object columns become float if all values are None.
    if by is not None:
        if isinstance(by, str):
            if by in aggregated.columns and df[by].dtype != aggregated[by].dtype:
                aggregated[by] = aggregated[by].astype(df[by].dtype)
        elif isinstance(by, Iterable):
            for col in by:
                if col in aggregated.columns and df[col].dtype != aggregated[col].dtype:
                    aggregated[col] = aggregated[col].astype(df[col].dtype)

    return aggregated
