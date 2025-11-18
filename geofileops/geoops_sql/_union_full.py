"""Module with union_full geooperations."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Literal, TypeAlias, get_args

import geofileops as gfo
from geofileops import GeometryType, LayerInfo, fileops
from geofileops.helpers import _general_helper
from geofileops.helpers._parameter_helper import validate_params_single_layer
from geofileops.util import _geoops_sql, _io_util, _ogr_sql_util
from geofileops.util._geoops_sql import (
    _subdivide_layer,
    delete_duplicate_geometries,
    difference,
    intersection,
    join_by_location,
    select,
)

UnionFullSelfTypes: TypeAlias = Literal["COLUMNS", "LISTS", "ROWS"]


def union_full_self(
    input_path: Path,
    output_path: Path,
    intersections_as: UnionFullSelfTypes,
    input_layer: str | LayerInfo | None = None,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 2000,
    force: bool = False,
    output_with_spatial_index: bool | None = None,
) -> None:
    # Because the calculations of the intermediate results will be towards temp files,
    # we need to do some additional init + checks here...
    if subdivide_coords < 0:
        raise ValueError("subdivide_coords < 0 is not allowed")
    if intersections_as not in get_args(UnionFullSelfTypes):
        raise ValueError(
            f"intersections_as should be one of {get_args(UnionFullSelfTypes)}"
        )

    operation_name = "union_full_self"
    logger = logging.getLogger(f"geofileops.{operation_name}")

    if _io_util.output_exists(path=output_path, remove_if_exists=force):
        return

    input_layer, output_layer = validate_params_single_layer(
        input_path=input_path,
        output_path=output_path,
        input_layer=input_layer,
        output_layer=output_layer,
        operation_name=operation_name,
    )

    # Determine output_geometrytype
    force_output_geometrytype = input_layer.geometrytype
    if explodecollections:
        force_output_geometrytype = force_output_geometrytype.to_singletype
    elif force_output_geometrytype is not GeometryType.POINT:
        # If explodecollections is False and the input type is not point, force the
        # output type to multi, because difference can cause eg. polygons to be split to
        # multipolygons.
        force_output_geometrytype = force_output_geometrytype.to_multitype

    start_time = datetime.now()
    with _general_helper.create_gfo_tmp_dir(operation_name) as tmp_dir:
        # Prepare the input files
        logger.info("Step 1 of 4: prepare input file")
        input_subdivided_path = _subdivide_layer(
            path=input_path,
            layer=input_layer,
            output_path=tmp_dir / "subdivided/input_layer.gpkg",
            subdivide_coords=subdivide_coords,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix=f"{operation_name}/",
            tmp_basedir=tmp_dir,
        )
        if input_subdivided_path is None:
            # Hardcoded optimization: root means that no subdivide was needed
            input_subdivided_path = Path("/")

        # Loop until all intersections are gone...
        logger.info("Step 2 of 4: create a 'flat union' layer without intersections")
        non_intersecting_path = tmp_dir / "union_self_non_intersecting.gpkg"
        if intersections_as == "COLUMNS":
            columns_pass = list(input_layer.columns) if columns is None else columns
        else:
            columns_pass = []

        pass_id = 1
        input_path_pass = input_path
        input_layer_pass: str | LayerInfo = input_layer
        input_subdivided_cur_path: Path | None = input_subdivided_path
        while True:
            logger.info(f"  -> create 'flat union' layer, pass {pass_id}")
            if pass_id == 1:
                # In the first pass, include the original fid column
                input1_columns = columns_pass
                input2_columns = input1_columns
                input1_columns_prefix = f"i{pass_id}_"
                input2_columns_prefix = f"i{pass_id + 1}_"

            elif pass_id == 2:
                # In the 2nd pass, we need to include the original fid column
                input1_columns = None  # all columns
                input2_columns = [
                    f"i{pass_id}_{col}" for col in columns_pass
                ]  # only the "right" columns
                input1_columns_prefix = ""
                input2_columns_prefix = f"i{pass_id + 1}_"

                # From the 2nd pass on, we cannot use the subdivided input anymore
                input_subdivided_cur_path = None

                # From the 2nd pass on, input_pass_layer becomes the output layer
                input_layer_pass = output_layer

            else:
                # In the next passes, no use to keep columns anymore
                input1_columns = []
                input2_columns = []

            # Parts of geometries that don't intersect in the input layer are ready for
            # the output.
            # Remark: subdivide_coords=0, because the input is already subdivided.
            diff_output_path = tmp_dir / f"diff_output_{pass_id}.gpkg"
            difference(
                input1_path=input_path_pass,
                input2_path=input_path_pass,
                output_path=diff_output_path,
                overlay_self=True,
                input1_layer=input_layer_pass,
                input1_columns=input1_columns,
                input_columns_prefix=input1_columns_prefix,
                input2_layer=input_layer_pass,
                output_layer=output_layer,
                explodecollections=explodecollections,
                gridsize=gridsize,
                where_post=where_post,
                nb_parallel=nb_parallel,
                batchsize=batchsize,
                subdivide_coords=0,
                force=force,
                output_with_spatial_index=False,
                operation_prefix=f"{operation_name}/",
                tmp_basedir=tmp_dir,
                input1_subdivided_path=input_subdivided_cur_path,
                input2_subdivided_path=input_subdivided_cur_path,
            )

            if pass_id == 1:
                # First pass, so we can just rename
                gfo.move(diff_output_path, non_intersecting_path)
            else:
                # Append
                fileops.copy_layer(
                    src=diff_output_path,
                    dst=non_intersecting_path,
                    src_layer=output_layer,
                    dst_layer=output_layer,
                    write_mode="append_add_fields",
                    force_output_geometrytype=force_output_geometrytype,
                )

            # Determine the parts of geometries in the input layer that intersect.
            # Remark: subdivide_coords=0, because the input is already subdivided.
            intersection_output_path = tmp_dir / f"intersection_output_{pass_id}.gpkg"
            intersection(
                input1_path=input_path_pass,
                input2_path=input_path_pass,
                output_path=intersection_output_path,
                overlay_self=True,
                include_duplicates=False,
                input1_layer=input_layer_pass,
                input1_columns=input1_columns,
                input1_columns_prefix=input1_columns_prefix,
                input2_layer=input_layer_pass,
                input2_columns=input2_columns,
                input2_columns_prefix=input2_columns_prefix,
                output_layer=output_layer,
                explodecollections=explodecollections,
                gridsize=gridsize,
                where_post=None,
                nb_parallel=nb_parallel,
                batchsize=batchsize,
                subdivide_coords=0,
                force=force,
                output_with_spatial_index=False,
                operation_prefix=f"{operation_name}/",
                tmp_basedir=tmp_dir,
                input1_subdivided_path=input_subdivided_cur_path,
                input2_subdivided_path=input_subdivided_cur_path,
            )

            # If the intersection output is empty, we are ready...
            inters_info = gfo.get_layerinfo(path=intersection_output_path)
            if inters_info.featurecount == 0:
                attributes_in_flat_union = True if pass_id <= 2 else False
                break

            # Delete duplicates from the intersections before starting next pass.
            deldups_path = tmp_dir / f"{intersection_output_path.stem}_no-dups.gpkg"
            delete_duplicate_geometries(
                input_path=intersection_output_path,
                output_path=deldups_path,
                input_layer=output_layer,
                output_layer=output_layer,
                columns=None,
                priority_column=None,
                priority_ascending=True,
                explodecollections=explodecollections,
                keep_empty_geoms=False,
                where_post=None,
                nb_parallel=nb_parallel,
                batchsize=batchsize,
                force=force,
                operation_prefix=f"{operation_name}/",
                tmp_basedir=tmp_dir,
            )
            intersection_output_path = deldups_path

            # Init for the next pass
            # if intersection_output_prev_path is not None:
            #    gfo.remove(intersection_output_prev_path)
            input_path_pass = intersection_output_path
            pass_id += 1

        logger.info("Step 3 of 4: combine the attributes with the 'flat union' layer")
        if intersections_as == "COLUMNS" and columns == []:
            # No output attribute columns needed -> ready
            output_tmp_path = non_intersecting_path

        elif intersections_as == "COLUMNS" and attributes_in_flat_union:
            # If the attributes are already in the result of the "flat union", not
            # needed to join them.
            output_tmp_path = non_intersecting_path

        else:
            # Join the "flat union" with the original input layer to:
            #   - add the attributes of the input layer
            #   - duplicate the polygon parts as many times as they overlap in the
            #     input layer
            union_multirow_path = tmp_dir / "union_multirow.gpkg"
            join_by_location(
                input1_path=non_intersecting_path,
                input2_path=input_path,
                output_path=union_multirow_path,
                spatial_relations_query="intersects is True and touches is False",
                input1_layer=output_layer,
                input2_layer=input_layer,
                output_layer=output_layer,
                input1_columns=["fid"],
                input2_columns=columns,
                input1_columns_prefix="union_",
                input2_columns_prefix="",
                explodecollections=explodecollections,
                gridsize=gridsize,
                where_post=where_post,
                nb_parallel=nb_parallel,
                batchsize=batchsize,
                force=False,
                output_with_spatial_index=False,
                operation_prefix=f"{operation_name}/",
                tmp_basedir=tmp_dir,
            )
            output_tmp_path = union_multirow_path

            if intersections_as in ("COLUMNS", "LISTS"):
                columns_local = (
                    list(input_layer.columns) if columns is None else columns
                )
                sql_stmt = _get_union_full_attr_sql_stmt(
                    union_multirow_path=output_tmp_path,
                    intersections_as=intersections_as,
                    columns=columns_local,
                )
                select_output_path = tmp_dir / "union_with_attributes.gpkg"
                select(
                    input_path=output_tmp_path,
                    output_path=select_output_path,
                    sql_stmt=sql_stmt,
                    input_layer=output_layer,
                    output_layer=output_layer,
                    preserve_fid=False,
                    explodecollections=explodecollections,
                    nb_parallel=nb_parallel,
                    batchsize=batchsize,
                    operation_prefix=f"{operation_name}/",
                    batch_filter_column="union_fid",
                    tmp_basedir=tmp_dir,
                )
                output_tmp_path = select_output_path

        # Convert or add spatial index
        logger.info("Step 4 of 4: finalize")

        _geoops_sql._finalize_output(
            output_tmp_path=output_tmp_path,
            output_path=output_path,
            output_layer=output_layer,
            output_with_spatial_index=output_with_spatial_index,
        )

    logger.info(f"Ready, full {operation_name} took {datetime.now() - start_time}")


def _get_union_full_attr_sql_stmt(
    union_multirow_path: Path,
    intersections_as: UnionFullSelfTypes | str,
    columns: list[str],
) -> str:
    """Create a sql statement to aggregate attributes based on a multi-row-union file.

    The file should include a "union_fid" column to group on.

    Args:
        union_multirow_path (Path): path to the union file with multiple rows per
            intersection
        intersections_as (str): type of union_full_self
        columns (List[str]): list of columns to aggregate

    Returns:
        str: sql statement
    """
    if intersections_as == "LISTS":
        if len(columns) > 0:
            columns_list = []
            for col in columns:
                if col.lower() == "fid":
                    # The fid column will be aliased already in union_multirow_path!
                    alias = _ogr_sql_util.get_unique_fid_alias(col, columns)
                    column_str = f'json_group_array("{alias}") AS "{alias}"'
                else:
                    column_str = f'json_group_array("{col}") AS "{col}"'
                columns_list.append(column_str)

            columns_str = f", {', '.join(columns_list)}"

        else:
            columns_str = ""

        # An index on union_fid does not speed this up/decrease memory usage
        sql_stmt = f"""
            SELECT layer.{{geometrycolumn}}
                  ,COUNT(*) AS nb_intersecting
                  {columns_str}
              FROM "{{input_layer}}" layer
             WHERE 1=1
               {{batch_filter}}
             GROUP BY union_fid
        """

    elif intersections_as == "COLUMNS":
        # An index on union_fid does not speed up/decrease memory usage for
        # following queries
        if len(columns) > 0:
            # First determine the maximum number of intersections
            sql_stmt_max = """
                SELECT MAX(counts.count) AS max_intersections
                  FROM  ( SELECT COUNT(*) AS count
                            FROM "{input_layer}" layer
                           GROUP BY union_fid
                        ) counts
            """
            df = fileops.read_file(union_multirow_path, sql_stmt=sql_stmt_max)
            max_intersections = df.iloc[0]["max_intersections"]

            # Now create the columns for in the select
            columns_list = []
            for i_id in range(1, max_intersections + 1):
                for input_col in columns:
                    if input_col.lower() == "fid":
                        input_col = "fid_1"
                        col_alias = f"i{i_id}_fid"
                    else:
                        col_alias = f"i{i_id}_{input_col}"
                    columns_list.append(
                        f'MIN(CASE WHEN rn = {i_id + 1} THEN "{input_col}" END'
                        f') AS "{col_alias}"'
                    )

            columns_str = f", {', '.join(columns_list)}"

        else:
            columns_str = ""

        sql_stmt = f"""
            SELECT data.{{geometrycolumn}}
                  {columns_str}
              FROM (
                SELECT layer.{{geometrycolumn}}
                      ,layer.union_fid
                      {{columns_to_select_str}}
                      ,row_number() OVER (PARTITION BY union_fid) AS rn
                  FROM "{{input_layer}}" layer
                 WHERE 1=1
                   {{batch_filter}}
                ) data
             WHERE 1=1
             GROUP BY data.union_fid
        """

    else:
        raise ValueError(f"Unsupported union_type: {intersections_as}")

    return sql_stmt
