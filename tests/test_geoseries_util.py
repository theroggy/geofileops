# -*- coding: utf-8 -*-
"""
Tests for functionalities in geoseries_util.
"""

from pathlib import Path
import sys

import geopandas as gpd
import shapely.geometry as sh_geom

# Add path so the local geofileops packages are found
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from geofileops.util import geoseries_util
from geofileops.util.geometry_util import GeometryType, PrimitiveType
from tests import test_helper


def test_get_geometrytypes():
    # None and empty geometries are by default ignored in get_geometrytypes
    test_gdf = gpd.GeoDataFrame(
        geometry=[
            None,
            sh_geom.Point(),
            sh_geom.LineString(),
            sh_geom.Polygon(),
            test_helper.TestData.point,
            test_helper.TestData.multipoint,
            test_helper.TestData.polygon_with_island,
            test_helper.TestData.polygon_no_islands,
            test_helper.TestData.multipolygon,
            test_helper.TestData.geometrycollection,
        ]
    )
    test_geometrytypes = geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_geometrytypes) == 5

    # None and empty geometries are by default ignored in get_geometrytypes
    test_gdf = gpd.GeoDataFrame(
        geometry=[
            None,
            sh_geom.Point(),
            sh_geom.LineString(),
            sh_geom.Polygon(),
            test_helper.TestData.point,
        ]
    )
    test_geometrytypes = geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_geometrytypes) == 1
    assert GeometryType.POINT in test_geometrytypes

    # Empty geometries are counted with ignore_empty_geometries=False, but
    # are always treated as GeometryCollection in GeoPandas.
    test_gdf = gpd.GeoDataFrame(
        geometry=[
            None,
            sh_geom.Point(),
            sh_geom.LineString(),
            sh_geom.Polygon(),
            test_helper.TestData.point,
        ]
    )
    test_geometrytypes = geoseries_util.get_geometrytypes(
        test_gdf.geometry, ignore_empty_geometries=False
    )
    assert len(test_geometrytypes) == 2
    assert GeometryType.POINT in test_geometrytypes
    assert GeometryType.GEOMETRYCOLLECTION in test_geometrytypes


def test_geometry_collection_extract():
    # Test for gdf with all types of geometrytypes, extract!
    test_gdf = gpd.GeoDataFrame(
        geometry=[
            test_helper.TestData.point,
            test_helper.TestData.multipoint,
            test_helper.TestData.polygon_with_island,
            test_helper.TestData.polygon_no_islands,
            test_helper.TestData.multipolygon,
            test_helper.TestData.geometrycollection,
        ]
    )
    test_geometrytypes = geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_geometrytypes) == 5
    test_result_gdf = test_gdf.copy()
    test_result_gdf.geometry = geoseries_util.geometry_collection_extract(
        test_result_gdf.geometry, PrimitiveType.POLYGON
    )
    test_result_geometrytypes = geoseries_util.get_geometrytypes(
        test_result_gdf.geometry
    )
    assert len(test_result_geometrytypes) == 2
    for index, geom in test_result_gdf.iteritems():
        assert geom is not None


def test_harmonize_geometrytypes():
    # Test for gdf with None + point + multipoint -> all multipoint
    test_gdf = gpd.GeoDataFrame(
        geometry=[
            None,
            sh_geom.Point(),
            test_helper.TestData.point,
            test_helper.TestData.multipoint,
            test_helper.TestData.point,
            test_helper.TestData.multipoint,
        ]
    )
    test_gdf_geometrytypes = geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_gdf_geometrytypes) == 2
    test_result_gdf = test_gdf.copy()
    test_result_gdf.geometry = geoseries_util.harmonize_geometrytypes(
        test_result_gdf.geometry
    )
    test_result_geometrytypes = geoseries_util.get_geometrytypes(
        test_result_gdf.geometry
    )
    assert len(test_result_geometrytypes) == 1
    assert test_result_geometrytypes[0] == GeometryType.MULTIPOINT
    for index, geom in test_result_gdf.geometry.iteritems():
        if index in [0, 1]:
            assert geom is None
        else:
            assert geom is not None

    # Test for gdf with linestring + multilinestring -> all multilinestring
    test_gdf = gpd.GeoDataFrame(
        geometry=[
            None,
            sh_geom.LineString(),
            test_helper.TestData.linestring,
            test_helper.TestData.multilinestring,
            test_helper.TestData.linestring,
            test_helper.TestData.multilinestring,
        ]
    )
    test_gdf_geometrytypes = geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_gdf_geometrytypes) == 2
    test_result_gdf = test_gdf.copy()
    test_result_gdf.geometry = geoseries_util.harmonize_geometrytypes(
        test_result_gdf.geometry
    )
    test_result_geometrytypes = geoseries_util.get_geometrytypes(
        test_result_gdf.geometry
    )
    assert len(test_result_geometrytypes) == 1
    assert test_result_geometrytypes[0] == GeometryType.MULTILINESTRING
    for index, geom in test_result_gdf.geometry.iteritems():
        if index in [0, 1]:
            assert geom is None
        else:
            assert geom is not None

    # Test for gdf with polygon + multipolygon -> all multipolygon
    test_gdf = gpd.GeoDataFrame(
        geometry=[
            test_helper.TestData.polygon_with_island,
            None,
            sh_geom.Polygon(),
            test_helper.TestData.polygon_with_island,
            test_helper.TestData.multipolygon,
        ]
    )
    test_gdf_geometrytypes = geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_gdf_geometrytypes) == 2
    # Filter the gdf a bit to test that the indexes are retained properly in
    test_gdf = test_gdf.iloc[[1, 2, 3, 4]]  # type: ignore
    test_result_gdf = test_gdf.copy()
    test_result_gdf.geometry = geoseries_util.harmonize_geometrytypes(
        test_result_gdf.geometry
    )
    test_result_geometrytypes = geoseries_util.get_geometrytypes(
        test_result_gdf.geometry
    )
    assert len(test_result_geometrytypes) == 1
    assert test_result_geometrytypes[0] == GeometryType.MULTIPOLYGON
    for index, geom in test_result_gdf.geometry.iteritems():
        if index in [1, 2]:
            assert geom is None
        else:
            assert geom is not None

    # Test for gdf with all types of geometrytypes -> no harmonization possible
    test_gdf = gpd.GeoDataFrame(
        geometry=[
            None,
            sh_geom.Polygon(),
            test_helper.TestData.point,
            test_helper.TestData.multipoint,
            test_helper.TestData.polygon_with_island,
            test_helper.TestData.polygon_no_islands,
            test_helper.TestData.multipolygon,
            test_helper.TestData.geometrycollection,
        ]
    )
    test_geometrytypes = geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_geometrytypes) == 5
    test_result_gdf = test_gdf.copy()
    test_result_gdf.geometry = geoseries_util.harmonize_geometrytypes(
        test_result_gdf.geometry
    )
    test_result_geometrytypes = geoseries_util.get_geometrytypes(
        test_result_gdf.geometry
    )
    assert len(test_result_geometrytypes) == 5
    for index, geom in test_result_gdf.geometry.iteritems():
        if index in [0]:
            # Only None is None, empty geometry is not changed!
            assert geom is None
        else:
            assert geom is not None


def test_polygons_to_lines():
    # Test with polygons
    test_gdf = gpd.GeoDataFrame(
        geometry=[
            None,
            sh_geom.Polygon(),
            test_helper.TestData.multipolygon,
            test_helper.TestData.polygon_with_island,
            test_helper.TestData.polygon_no_islands,
            test_helper.TestData.multipolygon,
        ]
    )
    lines_series = geoseries_util.polygons_to_lines(test_gdf.geometry)
    assert len(lines_series) == 9
