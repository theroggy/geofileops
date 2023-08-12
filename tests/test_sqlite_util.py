"""
Tests for functionalities in ogr_util.
"""

from pathlib import Path

import pytest

import geofileops as gfo
from geofileops.util import _sqlite_util as sqlite_util
from tests import test_helper


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
    assert gfo.has_spatial_index(test_path)
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
