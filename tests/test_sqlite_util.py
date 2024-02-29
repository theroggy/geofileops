"""
Tests for functionalities in ogr_util.
"""

import logging
from pathlib import Path

import pytest

from geofileops import fileops
import geofileops as gfo
from geofileops.util import _sqlite_util as sqlite_util
from geofileops.util._geofileinfo import GeofileInfo
from tests import test_helper
from tests.test_helper import assert_geodataframe_equal


@pytest.mark.parametrize("create_spatial_index", [(True), (False)])
def test_create_table_as_sql(tmp_path, create_spatial_index):
    output_path = tmp_path / "output.gpkg"
    input1_path = test_helper.get_testfile(testfile="polygon-parcel", dst_dir=tmp_path)
    input2_path = test_helper.get_testfile(testfile="polygon-zone", dst_dir=tmp_path)

    sql_stmt = """
            SELECT CastToMulti(ST_CollectionExtract(
                       ST_Intersection(layer1.geom, layer2.geometry), 3)) as geom
                  ,ST_area(layer1.geom) AS area_intersect
                  ,layer1.HFDTLT
                  ,layer2.naam
              FROM {input1_databasename}."parcels" layer1
              JOIN {input1_databasename}."rtree_parcels_geom" layer1tree
                ON layer1.fid = layer1tree.id
              JOIN {input2_databasename}."zones" layer2
              JOIN {input2_databasename}."rtree_zones_geometry" layer2tree
                ON layer2.fid = layer2tree.id
             WHERE 1=1
               AND layer1.rowid > 0 AND layer1.rowid < 10
               AND layer1tree.minx <= layer2tree.maxx
               AND layer1tree.maxx >= layer2tree.minx
               AND layer1tree.miny <= layer2tree.maxy
               AND layer1tree.maxy >= layer2tree.miny
               AND ST_Intersects(layer1.geom, layer2.geometry) = 1
               AND ST_Touches(layer1.geom, layer2.geometry) = 0
            """

    sqlite_util.create_table_as_sql(
        input1_path=input1_path,
        input1_layer="parcels",
        input2_path=input2_path,
        input2_layer="zones",
        output_path=output_path,
        output_layer=output_path.stem,
        output_geometrytype=gfo.GeometryType.MULTIPOLYGON,
        sql_stmt=sql_stmt,
        profile=sqlite_util.SqliteProfile.SPEED,
        create_spatial_index=create_spatial_index,
    )

    assert output_path.exists()
    assert gfo.has_spatial_index(output_path) is create_spatial_index
    output_info = gfo.get_layerinfo(output_path)
    assert output_info.featurecount == 7

    # The gpkg created by spatialite by default include some triggers that have errors
    # and were removed from the gpkg spec but not removed in spatialite.
    # These operations give errors if the triggers are still there.
    gfo.drop_column(output_path, column_name="naam")
    gfo.rename_layer(output_path, layer=output_path.stem, new_layer="test_layername")


@pytest.mark.parametrize(
    "kwargs, expected_error",
    [
        ({"append": True}, "append=True nor update=True are implemented."),
        ({"update": True}, "append=True nor update=True are implemented."),
        (
            {"input1_path": Path("input1.sqlite")},
            "output_path and both input paths must have the same suffix!",
        ),
        (
            {"input2_path": Path("input2.sqlite")},
            "output_path and both input paths must have the same suffix!",
        ),
        (
            {"output_path": Path("output.sqlite")},
            "output_path and both input paths must have the same suffix!",
        ),
    ],
)
def test_create_table_as_sql_invalidparams(kwargs, expected_error):
    # Set default values for kwargs that are not specified:
    if "input1_path" not in kwargs:
        kwargs["input1_path"] = Path("input1.gpkg")
    if "input1_layer" not in kwargs:
        kwargs["input1_layer"] = "input1_layer"
    if "input2_path" not in kwargs:
        kwargs["input2_path"] = Path("input2.gpkg")
    if "input2_layer" not in kwargs:
        kwargs["input2_layer"] = "input2_layer"
    if "output_path" not in kwargs:
        kwargs["output_path"] = Path("output.gpkg")
    if "output_layer" not in kwargs:
        kwargs["output_layer"] = "output_layer"
    if "sql_stmt" not in kwargs:
        kwargs["sql_stmt"] = "SELECTje"
    if "output_geometrytype" not in kwargs:
        kwargs["output_geometrytype"] = None

    with pytest.raises(ValueError, match=expected_error):
        sqlite_util.create_table_as_sql(**kwargs)


def test_execute_sql(tmp_path):
    test_path = test_helper.get_testfile(testfile="polygon-parcel", dst_dir=tmp_path)
    exp_spatial_index = GeofileInfo(test_path).default_spatial_index
    assert gfo.has_spatial_index(test_path) is exp_spatial_index
    info_input = gfo.get_layerinfo(test_path)
    nb_deleted = 0

    # Execute one statement
    sql_stmt = "DELETE FROM parcels WHERE rowid = (SELECT MIN(rowid) FROM parcels)"
    sqlite_util.execute_sql(test_path, sql_stmt=sql_stmt)
    nb_deleted += 1
    info = gfo.get_layerinfo(test_path)
    assert info.featurecount == info_input.featurecount - nb_deleted

    # Execute a list of statements
    sqlite_util.execute_sql(test_path, sql_stmt=[sql_stmt, sql_stmt])
    nb_deleted += 2
    info = gfo.get_layerinfo(test_path)
    assert info.featurecount == info_input.featurecount - nb_deleted


def test_get_columns():
    # Prepare test data
    input1_path = test_helper.get_testfile("polygon-parcel")
    input2_path = test_helper.get_testfile("polygon-zone")

    input1_info = gfo.get_layerinfo(input1_path)
    input2_info = gfo.get_layerinfo(input2_path)
    # Also include an identical column name aliasing a constant, is special case that
    # was a bug (https://github.com/geofileops/geofileops/pull/477).
    sql_stmt = f"""
        SELECT layer1.OIDN, layer1.UIDN, layer1.datum, layer2.naam, 'test' AS naam
          FROM {{input1_databasename}}."{input1_info.name}" layer1
          CROSS JOIN {{input2_databasename}}."{input2_info.name}" layer2
         WHERE 1=1
    """

    # Set logging level to DEBUG so the explain plan logging code path is touched.
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)

    # Run test
    columns = sqlite_util.get_columns(
        sql_stmt=sql_stmt, input1_path=input1_path, input2_path=input2_path
    )

    assert len(columns) == 5


def test_create_table_as_sql_single_input(tmp_path):
    input_path = test_helper.get_testfile(testfile="polygon-parcel", dst_dir=tmp_path)
    output_path = tmp_path / "output.gpkg"
    distance = 10
    resolution = 5

    # Prepare expected result
    expected_gdf = fileops.read_file(input_path, columns=["HFDTLT"])
    expected_gdf.geometry = expected_gdf.geometry.buffer(
        distance, resolution=resolution
    )

    sql_stmt = f"""
        SELECT ST_buffer(layer.geom, {distance}, {resolution}) as geom
              ,layer.HFDTLT
          FROM "parcels" layer
    """
    sqlite_util.create_table_as_sql(
        input1_path=input_path,
        input1_layer="parcels",
        input2_path=None,
        input2_layer=None,
        output_path=output_path,
        output_layer=None,
        output_geometrytype=None,
        sql_stmt=sql_stmt,
    )

    assert output_path.exists()
    output_gdf = fileops.read_file(output_path)

    # EMPTY geometry becomes NULL/None...
    expected_gdf.loc[expected_gdf.geometry.is_empty, "geometry"] = None
    assert_geodataframe_equal(output_gdf, expected_gdf)
