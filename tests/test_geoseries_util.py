# -*- coding: utf-8 -*-
"""
Tests for functionalities in geoseries_util.
"""

import geopandas as gpd
import pytest
import shapely.geometry as sh_geom

import geofileops as gfo
import geofileops._compat as compat
from geofileops.util import geoseries_util
from geofileops.util.geometry_util import GeometryType, PrimitiveType, SimplifyAlgorithm
from tests import test_helper


def test_get_geometrytypes():
    test_gdf = gpd.GeoDataFrame(
        geometry=[  # type: ignore
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
    # None and empty geometries are by default ignored in get_geometrytypes
    test_geometrytypes = geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_geometrytypes) == 5

    test_gdf = gpd.GeoDataFrame(
        geometry=[  # type: ignore
            None,
            sh_geom.Point(),
            sh_geom.LineString(),
            sh_geom.Polygon(),
            test_helper.TestData.point,
        ]
    )
    # None and empty geometries are by default ignored in get_geometrytypes
    test_geometrytypes = geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_geometrytypes) == 1
    assert GeometryType.POINT in test_geometrytypes

    # Empty geometries are counted with ignore_empty_geometries=False.
    test_gdf = gpd.GeoDataFrame(
        geometry=[  # type: ignore
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
    # In shapely 2, empty geometries get the correct type, in shapely 1 they were always
    # of type geometrycollection
    if compat.SHAPELY_GE_20:
        assert len(test_geometrytypes) == 3
        assert GeometryType.POINT in test_geometrytypes
        assert GeometryType.LINESTRING in test_geometrytypes
        assert GeometryType.POLYGON in test_geometrytypes
        assert GeometryType.GEOMETRYCOLLECTION not in test_geometrytypes
    else:
        assert len(test_geometrytypes) == 2


def test_geometry_collection_extract():
    # Test for gdf with all types of geometrytypes, extract!
    test_gdf = gpd.GeoDataFrame(
        geometry=[  # type: ignore
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
    assert isinstance(test_result_gdf, gpd.GeoDataFrame)
    test_result_gdf.geometry = geoseries_util.geometry_collection_extract(
        test_result_gdf.geometry, PrimitiveType.POLYGON
    )
    test_result_geometrytypes = geoseries_util.get_geometrytypes(
        test_result_gdf.geometry
    )
    assert len(test_result_geometrytypes) == 2
    for index, geom in test_result_gdf.items():
        assert geom is not None


def test_harmonize_geometrytypes():
    # Test for gdf with None + point + multipoint -> all multipoint
    test_gdf = gpd.GeoDataFrame(
        geometry=[  # type: ignore
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
    assert isinstance(test_result_gdf, gpd.GeoDataFrame)
    test_result_gdf.geometry = geoseries_util.harmonize_geometrytypes(
        test_result_gdf.geometry
    )
    test_result_geometrytypes = geoseries_util.get_geometrytypes(
        test_result_gdf.geometry
    )
    assert len(test_result_geometrytypes) == 1
    assert test_result_geometrytypes[0] == GeometryType.MULTIPOINT
    for index, geom in test_result_gdf.geometry.items():
        if index in [0, 1]:
            assert geom is None
        else:
            assert geom is not None

    # Test for gdf with linestring + multilinestring -> all multilinestring
    test_gdf = gpd.GeoDataFrame(
        geometry=[  # type: ignore
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
    assert isinstance(test_result_gdf, gpd.GeoDataFrame)
    test_result_gdf.geometry = geoseries_util.harmonize_geometrytypes(
        test_result_gdf.geometry
    )
    test_result_geometrytypes = geoseries_util.get_geometrytypes(
        test_result_gdf.geometry
    )
    assert len(test_result_geometrytypes) == 1
    assert test_result_geometrytypes[0] == GeometryType.MULTILINESTRING
    for index, geom in test_result_gdf.geometry.items():
        if index in [0, 1]:
            assert geom is None
        else:
            assert geom is not None

    # Test for gdf with polygon + multipolygon -> all multipolygon
    test_gdf = gpd.GeoDataFrame(
        geometry=[  # type: ignore
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
    assert isinstance(test_result_gdf, gpd.GeoDataFrame)
    test_result_gdf.geometry = geoseries_util.harmonize_geometrytypes(
        test_result_gdf.geometry
    )
    test_result_geometrytypes = geoseries_util.get_geometrytypes(
        test_result_gdf.geometry
    )
    assert len(test_result_geometrytypes) == 1
    assert test_result_geometrytypes[0] == GeometryType.MULTIPOLYGON
    for index, geom in test_result_gdf.geometry.items():
        if index in [1, 2]:
            assert geom is None
        else:
            assert geom is not None

    # Test for gdf with all types of geometrytypes -> no harmonization possible
    test_gdf = gpd.GeoDataFrame(
        geometry=[  # type: ignore
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
    assert isinstance(test_result_gdf, gpd.GeoDataFrame)
    test_result_gdf.geometry = geoseries_util.harmonize_geometrytypes(
        test_result_gdf.geometry
    )
    test_result_geometrytypes = geoseries_util.get_geometrytypes(
        test_result_gdf.geometry
    )
    assert len(test_result_geometrytypes) == 5
    for index, geom in test_result_gdf.geometry.items():
        if index in [0]:
            # Only None is None, empty geometry is not changed!
            assert geom is None
        else:
            assert geom is not None


def test_is_valid_reason(tmp_path):
    # Test with valid data + Empty geometry
    # -------------------------------------
    test_gdf = gpd.GeoDataFrame(
        geometry=[  # type: ignore
            sh_geom.Polygon(),
            test_helper.TestData.point,
            test_helper.TestData.multipoint,
            test_helper.TestData.polygon_with_island,
            test_helper.TestData.polygon_no_islands,
            test_helper.TestData.multipolygon,
            test_helper.TestData.geometrycollection,
        ]
    )
    result = geoseries_util.is_valid_reason(test_gdf.geometry)

    assert len(result) == len(test_gdf)
    assert result.unique() == "Valid Geometry"

    # Test if indexas are retained
    # ----------------------------
    test_filtered_gdf = test_gdf[3:-1]
    assert isinstance(test_filtered_gdf.geometry, gpd.GeoSeries)
    result = geoseries_util.is_valid_reason(test_filtered_gdf.geometry)

    assert len(result) == len(test_filtered_gdf)
    assert result.unique() == "Valid Geometry"
    assert result.index.to_list() == test_filtered_gdf.index.to_list()

    # Test with None
    # --------------
    test_gdf = gpd.GeoDataFrame(geometry=[None])  # type: ignore
    result = geoseries_util.is_valid_reason(test_gdf.geometry)

    # is_valid_reason returns None for None geometries
    assert result[0] is None

    # Test with invalid data
    # ----------------------
    # Prepare test data
    path = test_helper.get_testfile("polygon-invalid")
    gdf = gfo.read_file(path)
    result = geoseries_util.is_valid_reason(gdf.geometry)

    assert len(result) == len(gdf)
    assert result[0].startswith("Ring Self-intersection")


def test_polygons_to_lines():
    # Test with polygons
    test_geoseries = gpd.GeoSeries(
        data=[
            None,
            sh_geom.Polygon(),
            test_helper.TestData.multipolygon,
            test_helper.TestData.polygon_with_island,
            test_helper.TestData.polygon_no_islands,
            test_helper.TestData.multipolygon,
        ]
    )
    lines_series = geoseries_util.polygons_to_lines(test_geoseries)
    assert len(lines_series) == 9


@pytest.mark.parametrize(
    "algorithm", [SimplifyAlgorithm.RAMER_DOUGLAS_PEUCKER, SimplifyAlgorithm.LANG]
)
def test_simplify_ext(algorithm):
    input_path = test_helper.get_testfile("polygon-parcel")
    input_gdf = gfo.read_file(input_path)
    result_geoseries = geoseries_util.simplify_ext(
        input_gdf.geometry, tolerance=1, algorithm=algorithm
    )

    assert len(result_geoseries) == len(input_gdf.geometry)
    assert len(result_geoseries[1].exterior.coords) < len(
        input_gdf.geometry[1].geoms[0].exterior.coords
    )


@pytest.mark.parametrize(
    "algorithm", [SimplifyAlgorithm.RAMER_DOUGLAS_PEUCKER, SimplifyAlgorithm.LANG]
)
def test_simplify_topo_ext(algorithm):
    # Skip test if simplification is not available
    _ = pytest.importorskip("simplification")

    input_path = test_helper.get_testfile("polygon-parcel")
    input_gdf = gfo.read_file(input_path)
    result_geoseries = geoseries_util.simplify_topo_ext(
        input_gdf.geometry, tolerance=1, algorithm=algorithm
    )

    assert len(result_geoseries) == len(input_gdf.geometry)
    assert len(result_geoseries[1].geoms[0].exterior.coords) < len(
        input_gdf.geometry[1].geoms[0].exterior.coords
    )
