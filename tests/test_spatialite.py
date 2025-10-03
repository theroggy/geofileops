"""
Tests for functionalities in ogr_util.
"""

import pytest
import shapely.geometry as sh_geom

import geofileops as gfo
from tests import test_helper


@pytest.mark.parametrize(
    "descr, sql",
    [
        (
            "1_geos_basic",
            "SELECT ST_Buffer(ST_GeomFromText('POINT (5 5)'), 5) AS geom",
        ),
        (
            "2_geos_advanced",
            "SELECT ST_ConcaveHull(ST_GeomFromText('POINT (5 5)')) geom",
        ),
        (
            "3_geos_3100",
            "SELECT GeosMakeValid(ST_GeomFromText('POINT (5 5)')) AS geom",
        ),
        (
            "4_geos_3110",
            """
            SELECT HilbertCode(
                       ST_GeomFromText('POINT (5 5)'),
                       ST_GeomFromText('POLYGON ((0 0, 0 10, 10 10, 10 0, 0 0))'),
                       5
                   ) AS geom
            """,
        ),
    ],
)
def test_geos_functions(descr, sql):
    """Test some geos functions available via spatialite."""
    test_path = test_helper.get_testfile(testfile="polygon-parcel")
    gfo.read_file(test_path, sql_stmt=sql)


@pytest.mark.skipif(
    not test_helper.RUNS_LOCAL,
    reason="Don't this run on CI: just to document this behaviour.",
)
def test_st_difference_null(tmp_path):
    """
    ST_difference returns NULL when 2nd argument is NULL.

    This is the normal treatment of NULL values: `SELECT (1-NULL)` also results in NULL.

    In several spatial operations IIF statements are used to handle this situation.
    """
    input_path = test_helper.get_testfile(testfile="polygon-parcel")

    sql_stmt = """
        SELECT *
          FROM "{input_layer}"
         WHERE ST_difference({geometrycolumn}, NULL) IS NULL
    """
    output_path = tmp_path / "output.gpkg"
    gfo.select(input_path, output_path, sql_stmt=sql_stmt)

    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert len(input_gdf) == len(output_gdf)


@pytest.mark.skipif(
    not test_helper.RUNS_LOCAL,
    reason="Don't this run on CI: just to document this behaviour.",
)
@pytest.mark.parametrize("ogr_type", ["WKB", "WKT"])
def test_nested_collections(ogr_type):
    """
    A multi-geometry in a GeometryCollection is "flattened" by spatialite, which should
    not happen. For wkb's in some cases the result is even

    Bug report: https://groups.google.com/g/spatialite-users/c/GW-Ed0SL81Y
    """
    # Prepare test data
    input_path = test_helper.get_testfile(testfile="polygon-parcel")
    collection = sh_geom.GeometryCollection(
        [test_helper.TestData.multipolygon, test_helper.TestData.polygon_no_islands]
    )

    # Test
    if ogr_type == "WKT":
        sql_stmt = f"SELECT ST_GeomFromText('{collection.wkt}')"
    elif ogr_type == "WKB":
        sql_stmt = f"SELECT ST_GeomFromWKB(x'{collection.wkb_hex}')"

    test_gdf = gfo.read_file(input_path, sql_stmt=sql_stmt)
    if ogr_type == "WKT":
        # Due to a bug in spatialite this isn't equal even though it should be equal.
        pytest.xfail("Spatialite: Multi-geom in WKT GeometryCollection is flattened")
        assert test_gdf.geometry[0].wkt == collection.wkt
    elif ogr_type == "WKB":
        # Due to a worse bug in spatialite the wkb version is parsed to a POINT.
        pytest.xfail("Spatialite: Multi-geom in WKB GeometryCollection becomes Point")
        assert test_gdf.geometry[0].wkt == "GEOMETRYCOLLECTION (POINT (0 0))"
        assert test_gdf.geometry[0].wkt == collection.wkt
