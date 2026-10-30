"""Tests for single-layer operations using the DuckDB backend."""

import geopandas as gpd
import pytest
from shapely import LineString, MultiPoint, Point

import geofileops as gfo
from geofileops.util import _geoops_sql as geoops_sql
from geofileops.util._geometry_util import BufferEndCapStyle, BufferJoinStyle
from tests.test_helper import assert_geodataframe_equal


@pytest.mark.parametrize("output_suffix", [".gpkg", ".parquet"])
def test_convexhull_geoparquet(tmp_path, monkeypatch, output_suffix):
    input_gdf = gpd.GeoDataFrame(
        {"value": [1, 2]},
        geometry=[Point(0, 0), Point(2, 3)],
        crs="EPSG:31370",
    )
    input_path = tmp_path / "input.parquet"
    input_gdf.to_parquet(input_path)
    output_path = tmp_path / f"output{output_suffix}"

    def fail_sqlite_runner(*_args, **_kwargs):
        raise AssertionError(
            "GeoParquet input should dispatch to DuckDB, not the SQLite runner"
        )

    monkeypatch.setattr(
        geoops_sql, "_single_layer_vector_operation", fail_sqlite_runner
    )
    gfo.convexhull(input_path=input_path, output_path=output_path)

    if output_suffix == ".parquet":
        result_gdf = gpd.read_parquet(output_path)
    else:
        result_gdf = gfo.read_file(output_path)
    expected_gdf = input_gdf.copy()
    expected_gdf.geometry = expected_gdf.geometry.convex_hull
    assert_geodataframe_equal(result_gdf, expected_gdf, sort_values=True)


def test_convexhull_forced_duckdb(tmp_path):
    input_gdf = gpd.GeoDataFrame(
        {"value": [1, 2]},
        geometry=[Point(0, 0), Point(2, 3)],
        crs="EPSG:31370",
    )
    input_path = tmp_path / "input.gpkg"
    output_path = tmp_path / "output.gpkg"
    gfo.to_file(input_gdf, input_path)

    with gfo.options.set_geoops_sql_backend("duckdb"):
        gfo.convexhull(input_path=input_path, output_path=output_path)

    result_gdf = gfo.read_file(output_path)
    expected_gdf = input_gdf.copy()
    expected_gdf.geometry = expected_gdf.geometry.convex_hull
    assert_geodataframe_equal(result_gdf, expected_gdf, sort_values=True)


@pytest.mark.parametrize("output_suffix", [".gpkg", ".parquet"])
def test_buffer_geoparquet(tmp_path, monkeypatch, output_suffix):
    input_gdf = gpd.GeoDataFrame(
        {"value": [1]},
        geometry=[Point(0, 0)],
        crs="EPSG:31370",
    )
    input_path = tmp_path / "input.parquet"
    input_gdf.to_parquet(input_path)
    output_path = tmp_path / f"buffered{output_suffix}"

    def fail_sqlite_runner(*_args, **_kwargs):
        raise AssertionError("GeoParquet input should dispatch to DuckDB")

    monkeypatch.setattr(geoops_sql, "buffer", fail_sqlite_runner)
    gfo.buffer(input_path=input_path, output_path=output_path, distance=1)

    if output_suffix == ".parquet":
        result_gdf = gpd.read_parquet(output_path)
    else:
        result_gdf = gfo.read_file(output_path)
    expected_gdf = input_gdf.copy()
    expected_gdf.geometry = expected_gdf.geometry.buffer(1, resolution=5)
    assert_geodataframe_equal(
        result_gdf,
        expected_gdf,
        normalize=True,
        promote_to_multi=True,
        sort_values=True,
    )


def test_buffer_forced_duckdb_styles(tmp_path):
    input_gdf = gpd.GeoDataFrame(
        {"value": [1]},
        geometry=[LineString([(0, 0), (2, 0), (2, 2)])],
        crs="EPSG:31370",
    )
    input_path = tmp_path / "input.gpkg"
    output_path = tmp_path / "buffered.gpkg"
    gfo.to_file(input_gdf, input_path)

    with gfo.options.set_geoops_sql_backend("duckdb"):
        gfo.buffer(
            input_path=input_path,
            output_path=output_path,
            distance=1,
            endcap_style=BufferEndCapStyle.FLAT,
            join_style=BufferJoinStyle.BEVEL,
        )

    result_gdf = gfo.read_file(output_path)
    expected_gdf = input_gdf.copy()
    expected_gdf.geometry = expected_gdf.geometry.buffer(
        1,
        resolution=5,
        cap_style=BufferEndCapStyle.FLAT.value,
        join_style=BufferJoinStyle.BEVEL.value,
    )
    assert_geodataframe_equal(
        result_gdf,
        expected_gdf,
        normalize=True,
        promote_to_multi=True,
        sort_values=True,
    )


def test_buffer_duckdb_rejects_single_sided(tmp_path):
    input_path = tmp_path / "input.gpkg"
    gfo.to_file(gpd.GeoDataFrame(geometry=[Point(0, 0)], crs="EPSG:31370"), input_path)

    with gfo.options.set_geoops_sql_backend("duckdb"):
        with pytest.raises(NotImplementedError, match="single-sided"):
            gfo.buffer(
                input_path=input_path,
                output_path=tmp_path / "buffered.gpkg",
                distance=1,
                single_sided=True,
            )


def test_buffer_explodecollections_duckdb(tmp_path):
    input_gdf = gpd.GeoDataFrame(
        {"value": [1]},
        geometry=[MultiPoint([(0, 0), (4, 0)])],
        crs="EPSG:31370",
    )
    input_path = tmp_path / "input.parquet"
    output_path = tmp_path / "buffered.parquet"
    input_gdf.to_parquet(input_path)

    gfo.buffer(
        input_path=input_path,
        output_path=output_path,
        distance=0.5,
        explodecollections=True,
    )

    result_gdf = gpd.read_parquet(output_path)
    expected_gdf = gpd.GeoDataFrame(
        {"value": [1, 1]},
        geometry=[
            Point(0, 0).buffer(0.5, resolution=5),
            Point(4, 0).buffer(0.5, resolution=5),
        ],
        crs=input_gdf.crs,
    )
    assert_geodataframe_equal(
        result_gdf, expected_gdf, normalize=True, sort_values=True
    )
