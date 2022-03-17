# -*- coding: utf-8 -*-
"""
Tests for functionalities in vector_util.
"""

from pathlib import Path
import sys

# Add path so the local geofileops packages are found 
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import geofileops as gfo
from geofileops.util import grid_util
import test_helper

def test_create_grid2():
    # Test for small number of cells
    for i in range(1, 10):
        grid_gdf = grid_util.create_grid2(
                total_bounds=(40000.0, 160000.0, 45000.0, 210000.0), 
                nb_squarish_tiles=i,
                crs='epsg:31370')
        assert len(grid_gdf) == i
    
    # Test for larger number of cells
    grid_gdf = grid_util.create_grid2(
            total_bounds=(40000.0, 160000.0, 45000.0, 210000.0), 
            nb_squarish_tiles=100,
            crs='epsg:31370')
    assert len(grid_gdf) == 96

def test_split_tiles():
    input_tiles_path = test_helper.TestFiles.BEFL_kbl_gpkg
    input_tiles = gfo.read_file(input_tiles_path)
    nb_tiles_wanted = len(input_tiles) * 8
    result = grid_util.split_tiles(
            input_tiles=input_tiles,
            nb_tiles_wanted=nb_tiles_wanted)

    #geogfo.to_file(result, r"C:\temp\BEFL_kbl_split.gpkg")

    assert len(result) == len(input_tiles) * 8

if __name__ == '__main__':
    # Init
    tmpdir = test_helper.init_test_for_debug(Path(__file__).stem)

    test_create_grid2()
    test_split_tiles()
    