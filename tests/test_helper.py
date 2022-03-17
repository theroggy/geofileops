# -*- coding: utf-8 -*-
"""
Helper functions for all tests.
"""

import logging
from pathlib import Path
import tempfile
from typing import List, Optional
import sys

import geopandas as gpd
import shapely.geometry as sh_geom

# Add path so the local geofileops packages are found 
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import geofileops as gfo

class TestData:
    crs_epsg = 31370
    point = sh_geom.Point((0, 0))
    multipoint = sh_geom.MultiPoint([(0, 0), (10, 10), (20, 20)])
    linestring = sh_geom.LineString([(0, 0), (10, 10), (20, 20)])
    multilinestring = sh_geom.MultiLineString(
            [linestring.coords, [(100, 100), (110, 110), (120, 120)]])
    polygon_with_island = sh_geom.Polygon(
            shell=[(0, 0), (0, 10), (1, 10), (10, 10), (10, 0), (0, 0)], 
            holes=[[(2, 2), (2, 8), (8, 8), (8, 2), (2, 2)]])
    polygon_no_islands = sh_geom.Polygon(shell=[(100, 100), (100, 110), (110, 110), (110, 100), (100, 100)])
    polygon_with_island2 = sh_geom.Polygon(
            shell=[(20, 20), (20, 30), (21, 30), (30, 30), (30, 20), (20,20)], 
            holes=[[(22, 22), (22, 28), (28, 28), (28, 22), (22, 22)]])
    multipolygon = sh_geom.MultiPolygon([polygon_no_islands, polygon_with_island2])
    geometrycollection = sh_geom.GeometryCollection([
            point, multipoint, linestring, multilinestring, polygon_with_island, multipolygon])
    polygon_small_island = sh_geom.Polygon(
            shell=[(40, 40), (40, 50), (41, 50), (50, 50), (50, 40), (40, 40)], 
            holes=[[(42, 42), (42, 43), (43, 43), (43, 42), (42, 42)]])
    
class TestFiles:
    testdata_dir = Path(__file__).resolve().parent / 'data'

    BEFL_kbl_gpkg = testdata_dir / 'BEFL_kbl.gpkg'

    linestrings_rows_of_trees_gpkg = testdata_dir / 'linestrings_rows_of_trees.gpkg'
    linestrings_watercourses_gpkg = testdata_dir / 'linestrings_watercourses.gpkg'

    polygons_no_rows_gpkg = testdata_dir / 'polygons_no_rows.gpkg'
    polygons_overlappingcircles_all_gpkg = testdata_dir / 'polygons_overlappingcircles_all.gpkg'
    polygons_overlappingcircles_one_gpkg = testdata_dir / 'polygons_overlappingcircles_one.gpkg'
    polygons_overlappingcircles_twothree_gpkg = testdata_dir / 'polygons_overlappingcircles_two+three.gpkg'
    polygons_parcels_gpkg = testdata_dir / 'polygons_parcels-2020.gpkg'
    polygons_invalid_geometries_gpkg = testdata_dir / 'polygons_invalid_geometries.gpkg'
    polygons_simplify_onborder_testcase_gpkg = testdata_dir / 'polygons_simplify_onborder_testcase.gpkg'
    polygons_twolayers_gpkg = testdata_dir / 'polygons_twolayers.gpkg'
    polygons_zones_gpkg = testdata_dir / 'polygons_zones.gpkg'
    
    points_gpkg = testdata_dir / 'points.gpkg'

def create_tempdir(
        base_dirname: str,
        parent_dir: Optional[Path] = None) -> Path:
    # Parent
    if parent_dir is None:
        parent_dir = Path(tempfile.gettempdir())

    for i in range(1, 999999):
        try:
            tempdir = parent_dir / f"{base_dirname}_{i:06d}"
            tempdir.mkdir(parents=True)
            return Path(tempdir)
        except FileExistsError:
            continue

    raise Exception(f"Wasn't able to create a temporary dir with basedir: {parent_dir / base_dirname}") 

def get_testdata_dir() -> Path:
    return Path(__file__).resolve().parent / 'data'

def get_test_crs_epsg_list() -> List[int]:
    return [31370, 4326]

def get_test_suffix_list() -> List[str]:
    return [".gpkg", ".shp"]

def init_test_for_debug(test_module_name: str) -> Path:
    # Init logging
    logging.basicConfig(
            format="%(asctime)s.%(msecs)03d|%(levelname)s|%(name)s|%(message)s", 
            datefmt="%H:%M:%S", level=logging.INFO)

    # Prepare tmpdir
    tmp_basedir = Path(tempfile.gettempdir()) / "geofileops_test_debug" / test_module_name
    tmpdir = create_tempdir(parent_dir=tmp_basedir, base_dirname='debugrun')
    
    """
    if tmpdir.exists():
        shutil.rmtree(tmpdir)
    tmpdir.mkdir(parents=True, exist_ok=True)
    """

    return tmpdir

def prepare_test_file(
        path: Path,
        tmp_dir: Path,
        suffix: str,
        crs_epsg: Optional[int] = None) -> Path:

    # If sufixx the same, copy to tmp_dir, if not, convert
    new_path = tmp_dir / f"{path.stem}{suffix}"
    if path.suffix == suffix:    
        gfo.copy(path, new_path)
    else:
        gfo.convert(path, new_path)
    path = new_path

    # If crs_epsg specified and test input file in wrong crs_epsg, reproject
    if crs_epsg is not None:
        input_layerinfo = gfo.get_layerinfo(path)
        assert input_layerinfo.crs is not None
        if input_layerinfo.crs.to_epsg() != crs_epsg:
            new_path = tmp_dir / f"{path.stem}_{crs_epsg}{suffix}"
            if new_path.exists() is False:
                test_gdf = gfo.read_file(path)
                test_gdf = test_gdf.to_crs(crs_epsg)
                assert isinstance(test_gdf, gpd.GeoDataFrame)
                gfo.to_file(test_gdf, new_path)
            path = new_path

    return path
