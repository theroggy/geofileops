"""
Tests for functionalities in geoseries_util.
"""

import geopandas as gpd
from pygeoops import GeometryType
import pytest
import shapely
import shapely.geometry as sh_geom

import geofileops as gfo
import geofileops._compat as compat
from geofileops.util import _geoseries_util
from tests import test_helper


def test_get_geometrytypes():
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
    # None and empty geometries are by default ignored in get_geometrytypes
    test_geometrytypes = _geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_geometrytypes) == 5

    test_gdf = gpd.GeoDataFrame(
        geometry=[
            None,
            sh_geom.Point(),
            sh_geom.LineString(),
            sh_geom.Polygon(),
            test_helper.TestData.point,
        ]
    )
    # None and empty geometries are by default ignored in get_geometrytypes
    test_geometrytypes = _geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_geometrytypes) == 1
    assert GeometryType.POINT in test_geometrytypes

    # Empty geometries are counted with ignore_empty_geometries=False.
    test_gdf = gpd.GeoDataFrame(
        geometry=[
            None,
            sh_geom.Point(),
            sh_geom.LineString(),
            sh_geom.Polygon(),
            test_helper.TestData.point,
        ]
    )
    test_geometrytypes = _geoseries_util.get_geometrytypes(
        test_gdf.geometry, ignore_empty_geometries=False
    )
    # In shapely 2, empty geometries get the correct type, in shapely 1 they were always
    # of type geometrycollection
    if compat.SHAPELY_GTE_20:
        assert len(test_geometrytypes) == 3
        assert GeometryType.POINT in test_geometrytypes
        assert GeometryType.LINESTRING in test_geometrytypes
        assert GeometryType.POLYGON in test_geometrytypes
        assert GeometryType.GEOMETRYCOLLECTION not in test_geometrytypes
    else:
        assert len(test_geometrytypes) == 2


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
    test_gdf_geometrytypes = _geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_gdf_geometrytypes) == 2
    test_result_gdf = test_gdf.copy()
    assert isinstance(test_result_gdf, gpd.GeoDataFrame)
    test_result_gdf.geometry = _geoseries_util.harmonize_geometrytypes(
        test_result_gdf.geometry
    )
    test_result_geometrytypes = _geoseries_util.get_geometrytypes(
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
        geometry=[
            None,
            sh_geom.LineString(),
            test_helper.TestData.linestring,
            test_helper.TestData.multilinestring,
            test_helper.TestData.linestring,
            test_helper.TestData.multilinestring,
        ]
    )
    test_gdf_geometrytypes = _geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_gdf_geometrytypes) == 2
    test_result_gdf = test_gdf.copy()
    assert isinstance(test_result_gdf, gpd.GeoDataFrame)
    test_result_gdf.geometry = _geoseries_util.harmonize_geometrytypes(
        test_result_gdf.geometry
    )
    test_result_geometrytypes = _geoseries_util.get_geometrytypes(
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
        geometry=[
            test_helper.TestData.polygon_with_island,
            None,
            sh_geom.Polygon(),
            test_helper.TestData.polygon_with_island,
            test_helper.TestData.multipolygon,
        ]
    )
    test_gdf_geometrytypes = _geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_gdf_geometrytypes) == 2
    # Filter the gdf a bit to test that the indexes are retained properly in
    test_gdf = test_gdf.iloc[[1, 2, 3, 4]]
    test_result_gdf = test_gdf.copy()
    assert isinstance(test_result_gdf, gpd.GeoDataFrame)
    test_result_gdf.geometry = _geoseries_util.harmonize_geometrytypes(
        test_result_gdf.geometry
    )
    test_result_geometrytypes = _geoseries_util.get_geometrytypes(
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
    test_geometrytypes = _geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_geometrytypes) == 5
    test_result_gdf = test_gdf.copy()
    assert isinstance(test_result_gdf, gpd.GeoDataFrame)
    test_result_gdf.geometry = _geoseries_util.harmonize_geometrytypes(
        test_result_gdf.geometry
    )
    test_result_geometrytypes = _geoseries_util.get_geometrytypes(
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
        geometry=[
            sh_geom.Polygon(),
            test_helper.TestData.point,
            test_helper.TestData.multipoint,
            test_helper.TestData.polygon_with_island,
            test_helper.TestData.polygon_no_islands,
            test_helper.TestData.multipolygon,
            test_helper.TestData.geometrycollection,
        ]
    )
    result = _geoseries_util.is_valid_reason(test_gdf.geometry)

    assert len(result) == len(test_gdf)
    assert result.unique() == "Valid Geometry"

    # Test if indexes are retained
    # ----------------------------
    test_filtered_gdf = test_gdf[3:-1]
    assert isinstance(test_filtered_gdf.geometry, gpd.GeoSeries)
    result = _geoseries_util.is_valid_reason(test_filtered_gdf.geometry)

    assert len(result) == len(test_filtered_gdf)
    assert result.unique() == "Valid Geometry"
    assert result.index.to_list() == test_filtered_gdf.index.to_list()

    # Test with None
    # --------------
    test_gdf = gpd.GeoDataFrame(geometry=[None])
    result = _geoseries_util.is_valid_reason(test_gdf.geometry)

    # is_valid_reason returns None for None geometries
    assert result[0] is None

    # Test with invalid data
    # ----------------------
    # Prepare test data
    path = test_helper.get_testfile("polygon-invalid")
    gdf = gfo.read_file(path)
    result = _geoseries_util.is_valid_reason(gdf.geometry)

    assert len(result) == len(gdf)
    assert result[0].startswith("Ring Self-intersection")


poly_gridsize_error = shapely.from_wkt(
    "Polygon ((26352.5 175096.6, 26352.6 175096.6, 26352.6 175096.7, "
    "26352.5 175096.7, 26352.5 175096.6),(26352.528000000002 175096.676, "
    "26352.528369565214 175096.67489130437, 26352.528140495866 175096.67619834712, "
    "26352.52785714286 175096.67714285714, 26352.53 175096.66, "
    "26352.528000000002 175096.676))"
)
poly_ok = shapely.from_wkt(
    "Polygon ((26352.5 175096.7, 26352.66895 175096.76895, 26352.6 175096.6, "
    "26352.5 175096.6, 26352.5 175096.7))"
)


@pytest.mark.parametrize("raise_on_topoerror", [True, False])
@pytest.mark.parametrize(
    "geometry, exp_geometry",
    [
        (
            [poly_gridsize_error, poly_ok],
            [poly_gridsize_error, shapely.set_precision(poly_ok, grid_size=0.01)],
        ),
        (poly_gridsize_error, poly_gridsize_error),
    ],
)
def test_set_precision(geometry, exp_geometry, raise_on_topoerror):
    # The only currently known test case only works with geos 3.12
    if shapely.geos_version != (3, 12, 0):
        pytest.skip()

    grid_size = 0.01

    if raise_on_topoerror:
        with pytest.raises(Exception, match="TopologyException: Ring edge missing at"):
            # raise_on_topoerror is default False
            result = _geoseries_util.set_precision(geometry, grid_size=grid_size)
        return

    result = _geoseries_util.set_precision(
        geometry, grid_size=grid_size, raise_on_topoerror=raise_on_topoerror
    )

    # Check result
    if hasattr(geometry, "__len__"):
        assert result.tolist() == exp_geometry
    else:
        assert result == exp_geometry
