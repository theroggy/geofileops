# -*- coding: utf-8 -*-
"""
Tests for functionalities in ogr_util.
"""

from pathlib import Path
import sys

# Add path so the local geofileops packages are found
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from geofileops.util import _sqlite_util
from geofileops import GeometryType
from tests import test_helper


def test_exec_spatialite_sql(tmp_path):
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

    _sqlite_util.create_table_as_sql(
        input1_path=input1_path,
        input1_layer="parcels",
        input2_path=input2_path,
        output_path=output_path,
        output_layer=output_path.stem,
        output_geometrytype=GeometryType.MULTIPOLYGON,
        sql_stmt=sql_stmt,
        profile=_sqlite_util.SqliteProfile.SPEED,
    )
