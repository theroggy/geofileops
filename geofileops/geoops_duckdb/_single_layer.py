"""DuckDB-backed single-layer geometry operations."""

import shutil
from collections.abc import Callable
from pathlib import Path

from geofileops import fileops
from geofileops.geoops_duckdb._common import (
    create_connection,
    get_source,
    quote_identifier,
    quote_sql_string,
)
from geofileops.helpers import _general_helper
from geofileops.util import _io_util
from geofileops.util._geometry_util import BufferEndCapStyle, BufferJoinStyle
from geofileops.util._geopath_util import GeoPath


def buffer(
    input_path: Path,
    output_path: Path,
    distance: float,
    quadrantsegments: int = 5,
    *,
    endcap_style: BufferEndCapStyle = BufferEndCapStyle.ROUND,
    join_style: BufferJoinStyle = BufferJoinStyle.ROUND,
    mitre_limit: float = 5.0,
    single_sided: bool = False,
    input_layer: str | None = None,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = False,
    where_post: str | None = None,
    nb_parallel: int | None = None,
    batchsize: int = -1,
    force: bool = False,
) -> None:
    """Buffer every geometry using DuckDB Spatial."""
    if single_sided:
        raise NotImplementedError(
            "The DuckDB backend does not support single-sided buffers."
        )

    cap_style = {
        BufferEndCapStyle.ROUND: "CAP_ROUND",
        BufferEndCapStyle.FLAT: "CAP_FLAT",
        BufferEndCapStyle.SQUARE: "CAP_SQUARE",
    }[endcap_style]
    join_style_sql = {
        BufferJoinStyle.ROUND: "JOIN_ROUND",
        BufferJoinStyle.MITRE: "JOIN_MITRE",
        BufferJoinStyle.BEVEL: "JOIN_BEVEL",
    }[join_style]

    def buffer_geometry(geometry: str) -> str:
        result = (
            f"ST_Buffer({geometry}, {distance}, {quadrantsegments}, "
            f"'{cap_style}', '{join_style_sql}', {mitre_limit})"
        )
        if distance < 0:
            result = f"ST_CollectionExtract({result}, 3)"
        if not explodecollections:
            result = f"ST_Multi({result})"
        return result

    return _run_single_layer_operation(
        operation_name="buffer",
        geometry_operation=buffer_geometry,
        input_path=input_path,
        output_path=output_path,
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def convexhull(
    input_path: Path,
    output_path: Path,
    *,
    input_layer: str | None = None,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = False,
    where_post: str | None = None,
    nb_parallel: int | None = None,
    batchsize: int = -1,
    force: bool = False,
) -> None:
    """Calculate the convex hull of every feature using DuckDB Spatial."""
    return _run_single_layer_operation(
        operation_name="convexhull",
        geometry_operation=lambda geometry: f"ST_ConvexHull({geometry})",
        input_path=input_path,
        output_path=output_path,
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def _run_single_layer_operation(
    *,
    operation_name: str,
    geometry_operation: Callable[[str], str],
    input_path: Path,
    output_path: Path,
    input_layer: str | None,
    output_layer: str | None,
    columns: list[str] | None,
    explodecollections: bool,
    gridsize: float,
    keep_empty_geoms: bool,
    where_post: str | None,
    nb_parallel: int | None,
    batchsize: int,
    force: bool,
) -> None:
    output_suffix = GeoPath(output_path).suffix_full.lower()
    is_parquet_output = output_suffix in {".parquet", ".geoparquet"}
    if not is_parquet_output and output_suffix != ".gpkg":
        raise ValueError(
            f"The DuckDB {operation_name} implementation currently supports "
            "GeoParquet and GeoPackage output."
        )

    if _io_util.output_exists(path=output_path, remove_if_exists=False):
        if not force:
            return
        if is_parquet_output:
            output_path.unlink()
        else:
            _io_util.output_exists(path=output_path, remove_if_exists=True)
    if input_path == output_path:
        raise ValueError(f"{operation_name}: output_path must not equal input_path")
    if not input_path.exists():
        raise FileNotFoundError(f"{operation_name}: input_path not found: {input_path}")

    with _general_helper.create_gfo_tmp_dir(f"duckdb_{operation_name}") as tmp_dir:
        tmp_output_path = tmp_dir / output_path.name
        connection = create_connection()
        try:
            if nb_parallel is not None and nb_parallel > 0:
                connection.execute(f"SET threads = {nb_parallel}")

            source = get_source(connection, input_path, input_layer)
            if columns is None:
                columns_to_select = source.attribute_columns
            else:
                columns_asked = [columns] if isinstance(columns, str) else columns
                columns_by_lower = {
                    column.lower(): column for column in source.attribute_columns
                }
                missing_columns = [
                    column
                    for column in columns_asked
                    if column.lower() not in columns_by_lower
                ]
                if missing_columns:
                    raise ValueError(f"columns not found in input: {missing_columns}")
                columns_to_select = [
                    columns_by_lower[column.lower()] for column in columns_asked
                ]

            if not is_parquet_output and any(
                column.lower() == "fid" for column in columns_to_select
            ):
                raise ValueError(
                    "Selecting the input FID into a GeoPackage output is not yet "
                    "supported by the DuckDB backend."
                )

            geometry_column_sql = quote_identifier(source.geometry_column)
            geometry_result = geometry_operation(geometry_column_sql)
            if gridsize != 0.0:
                geometry_result = f"ST_ReducePrecision({geometry_result}, {gridsize})"
            if explodecollections:
                geometry_result = f"UNNEST(ST_Dump({geometry_result})).geom"

            selected_columns = [
                *(quote_identifier(column) for column in columns_to_select),
                f"{geometry_result} AS {geometry_column_sql}",
            ]
            query = f"SELECT {', '.join(selected_columns)} FROM {source.relation}"
            filters = []
            if not keep_empty_geoms:
                filters.extend(
                    [
                        f"{geometry_column_sql} IS NOT NULL",
                        f"NOT ST_IsEmpty({geometry_column_sql})",
                    ]
                )
            if where_post:
                filters.append(f"({where_post})")
            if filters:
                query = f"SELECT * FROM ({query}) result WHERE {' AND '.join(filters)}"

            output_sql = quote_sql_string(tmp_output_path.as_posix())
            if is_parquet_output:
                copy_options = "(FORMAT PARQUET)"
            else:
                output_layer = output_layer or output_path.stem
                layer_sql = quote_sql_string(output_layer)
                copy_options = f"(FORMAT GDAL, DRIVER 'GPKG', LAYER_NAME {layer_sql})"
            connection.execute(f"COPY ({query}) TO {output_sql} {copy_options}")
        except Exception as ex:
            if isinstance(ex, (ValueError, FileNotFoundError)):
                raise
            raise RuntimeError(f"DuckDB {operation_name} failed: {ex}") from ex
        finally:
            connection.close()

        if is_parquet_output:
            shutil.move(str(tmp_output_path), output_path)
        else:
            fileops.move(tmp_output_path, output_path)

    _ = batchsize
