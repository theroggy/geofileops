# -*- coding: utf-8 -*-
"""
Tests for functionalities in ogr_util.
"""

from pathlib import Path
import sys

# Add path so the local geofileops packages are found 
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from geofileops.util import sqlite_util
from geofileops import GeometryType
import test_helper

def test_exec_spatialite_sql(tmpdir):
    tmpdir = Path(tmpdir)
    output_path = tmpdir / 'output.gpkg'
    input1_path = test_helper.TestFiles.polygons_parcels_gpkg
    input2_path = test_helper.TestFiles.polygons_zones_gpkg

    sql_stmt = f'''
            SELECT CastToMulti(ST_CollectionExtract(
                       ST_Intersection(layer1.geom, layer2.geometry), 3)) as geom
                  ,ST_area(layer1.geom) AS area_intersect
                  ,layer1.HFDTLT
                  ,layer2.naam
              FROM {{input1_databasename}}."parcels" layer1
              JOIN {{input1_databasename}}."rtree_parcels_geom" layer1tree ON layer1.fid = layer1tree.id
              JOIN {{input2_databasename}}."zones" layer2
              JOIN {{input2_databasename}}."rtree_zones_geometry" layer2tree ON layer2.fid = layer2tree.id
             WHERE 1=1
               AND layer1.rowid > 0 AND layer1.rowid < 10
               AND layer1tree.minx <= layer2tree.maxx AND layer1tree.maxx >= layer2tree.minx
               AND layer1tree.miny <= layer2tree.maxy AND layer1tree.maxy >= layer2tree.miny
               AND ST_Intersects(layer1.geom, layer2.geometry) = 1
               AND ST_Touches(layer1.geom, layer2.geometry) = 0
            '''

    sqlite_util.create_table_as_sql(
            input1_path=input1_path,
            input1_layer='parcels',
            input2_path=input2_path,
            output_path=output_path,
            output_layer=output_path.stem,
            output_geometrytype=GeometryType.MULTIPOLYGON,
            sql_stmt=sql_stmt,
            profile=sqlite_util.SqliteProfile.SPEED)
    
if __name__ == '__main__':
    # Init
    tmpdir = test_helper.init_test_for_debug(Path(__file__).stem)

    # Test functions to run...
    #test_get_gdal_to_use()
    test_exec_spatialite_sql(tmpdir)
