"""Shared helpers for DuckDB-backed geometry operations."""

from __future__ import annotations

import importlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from geofileops import fileops
from geofileops.helpers._options import ConfigOptions
from geofileops.util._general_util import MissingRuntimeDependencyError

if TYPE_CHECKING:
    from pathlib import Path

    import duckdb


@dataclass
class DuckDBSource:
    relation: str
    geometry_column: str
    attribute_columns: list[str]
    is_geoparquet: bool


def should_use_duckdb(input_paths: list[Path], output_path: Path) -> bool:
    """Resolve the SQL backend using the configured option and file formats."""
    backend = ConfigOptions.get_geoops_sql_backend
    geoparquet_paths = [*input_paths, output_path]
    has_geoparquet = any(
        path.suffix.lower() in {".parquet", ".geoparquet"} for path in geoparquet_paths
    )

    if backend == "sqlite":
        if has_geoparquet:
            raise ValueError(
                "The SQLite backend cannot process GeoParquet paths; use the "
                "automatic or DuckDB backend."
            )
        return False
    elif backend == "duckdb":
        return True

    return has_geoparquet


def create_connection() -> duckdb.DuckDBPyConnection:
    """Create a DuckDB connection with the preinstalled Spatial extension loaded."""
    try:
        duckdb_module = importlib.import_module("duckdb")
    except ImportError as ex:
        raise MissingRuntimeDependencyError(
            "The DuckDB backend requires the optional DuckDB dependency. Install it "
            "with `pip install geofileops[duckdb]`."
        ) from ex

    connection = duckdb_module.connect()
    try:
        connection.execute("LOAD spatial")
    except Exception as ex:
        connection.close()
        raise MissingRuntimeDependencyError(
            "The DuckDB Spatial extension must be installed before using the DuckDB "
            "backend. Provision it in DuckDB with `INSTALL spatial`, then retry."
        ) from ex

    return connection


def get_source(
    connection: duckdb.DuckDBPyConnection,
    input_path: Path,
    input_layer: str | None = None,
) -> DuckDBSource:
    """Build a DuckDB relation and resolve its primary geometry column."""
    path_sql = quote_sql_string(input_path.as_posix())
    is_geoparquet = input_path.suffix.lower() in {".parquet", ".geoparquet"}

    if is_geoparquet:
        metadata_rows = connection.execute(
            f"SELECT key, value FROM parquet_kv_metadata({path_sql})"
        ).fetchall()
        geo_metadata = next(
            (value for key, value in metadata_rows if key == b"geo"), None
        )
        if geo_metadata is None:
            raise ValueError(f"Input is not a GeoParquet file: {input_path}")
        geometry_column = json.loads(geo_metadata)["primary_column"]
        relation = f"read_parquet({path_sql})"
    else:
        if input_layer is None:
            input_layer = fileops.get_only_layer(input_path)
        layer_sql = quote_sql_string(input_layer)
        relation = f"ST_Read({path_sql}, layer={layer_sql})"
        geometry_column = ""

    schema = connection.execute(f"DESCRIBE SELECT * FROM {relation}").fetchall()
    schema_by_name = {column[0]: column[1] for column in schema}
    if not is_geoparquet:
        geometry_columns = [
            name
            for name, data_type in schema_by_name.items()
            if data_type.upper().startswith("GEOMETRY")
        ]
        if len(geometry_columns) != 1:
            raise ValueError(
                f"Expected one geometry column in {input_path}, found "
                f"{geometry_columns}"
            )
        geometry_column = geometry_columns[0]
    elif geometry_column not in schema_by_name:
        raise ValueError(
            f"GeoParquet primary geometry column {geometry_column!r} was not found "
            f"in {input_path}"
        )

    attribute_columns = [
        name
        for name, data_type in schema_by_name.items()
        if name != geometry_column
        and not data_type.upper().startswith("GEOMETRY")
        and (is_geoparquet or name.lower() != "fid")
    ]
    return DuckDBSource(
        relation=relation,
        geometry_column=geometry_column,
        attribute_columns=attribute_columns,
        is_geoparquet=is_geoparquet,
    )


def quote_identifier(identifier: str) -> str:
    return f'"{identifier.replace(chr(34), chr(34) * 2)}"'


def quote_sql_string(value: str) -> str:
    return f"'{value.replace(chr(39), chr(39) * 2)}'"
