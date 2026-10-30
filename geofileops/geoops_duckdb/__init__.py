"""DuckDB-backed implementations of geometry operations."""

from geofileops.geoops_duckdb._common import should_use_duckdb
from geofileops.geoops_duckdb._single_layer import buffer, convexhull

__all__ = ["buffer", "convexhull", "should_use_duckdb"]
