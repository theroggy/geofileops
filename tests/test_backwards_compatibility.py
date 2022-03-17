# -*- coding: utf-8 -*-
"""
Test if backwards compatibility for old API still works.
"""

from pathlib import Path
import sys

# Add path so the local geofileops packages are found 
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from geofileops import geofileops
from geofileops import geofile
from geofileops.util import vector_util
import test_helper

def test_old_geofileops_api(tmpdir):
    tmp_dir = Path(tmpdir)
    input_path = test_helper.TestFiles.polygons_parcels_gpkg
    output_path = tmp_dir / f"{input_path.stem}-output.gpkg"
    
    geofileops.buffer(input_path=input_path, output_path=output_path, distance=1)
    assert output_path.exists() is True
    
    input_gdf = geofile.read_file(path=input_path)
    assert len(input_gdf) > 0

def test_old_vector_util_api():
    # Test from geometry_util
    numberpoints = vector_util.numberpoints(test_helper.TestData.point)
    assert numberpoints == 1

    # Test from grid_util
    grid_gdf = vector_util.create_grid2(
            total_bounds=(40000.0, 160000.0, 45000.0, 210000.0), 
            nb_squarish_tiles=100,
            crs='epsg:31370')
    assert len(grid_gdf) == 96

if __name__ == '__main__':
    # Init
    tmpdir = test_helper.init_test_for_debug(Path(__file__).stem)

    # Test functions to run...
    test_old_geofileops_api(tmpdir)
