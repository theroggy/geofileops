# -*- coding: utf-8 -*-
"""
Tests for operations that are executed using a sql statement on one layer.
"""

from pathlib import Path
import sys

import geopandas as gpd

# Add path so the local geofileops packages are found 
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import geofileops as gfo
from geofileops import GeometryType
from geofileops.util import geofileops_sql
from geofileops.util import geometry_util
import test_helper

def get_nb_parallel() -> int:
    # The number of parallel processes to use for these tests.
    return 2

def get_batchsize() -> int:
    return 5

def test_buffer(tmpdir):
    # Init
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    test_inputs = []
    test_inputs.append({
            "input_path": test_helper.TestFiles.polygons_parcels_gpkg,
            "geometrytype": GeometryType.MULTIPOLYGON})
    test_inputs.append({
            "input_path": test_helper.TestFiles.points_gpkg,
            "geometrytype": GeometryType.MULTIPOINT})
    test_inputs.append({
            "input_path": test_helper.TestFiles.linestrings_rows_of_trees_gpkg,
            "geometrytype": GeometryType.MULTILINESTRING})

    # Prepare test data + run tests
    for suffix in test_helper.get_test_suffix_list():
        # Buffer on not-projected data is weird, so not tested (at the moment)  
        for crs_epsg in test_helper.get_test_crs_epsg_list():
            for test_input in test_inputs: 
                # If test input file is in wrong format, convert it
                input_path = test_helper.prepare_test_file(
                        path=test_input['input_path'],
                        tmp_dir=tmp_dir,
                        suffix=suffix,
                        crs_epsg=crs_epsg)

                # Now run test
                output_path = tmp_dir / f"{input_path.stem}-output{suffix}"
                print(f"Run test for suffix {suffix}, crs_epsg {crs_epsg}, geometrytype {test_input['geometrytype']}")
                basetest_buffer(input_path, output_path, test_input['geometrytype'])

def basetest_buffer(
        input_path: Path, 
        output_path: Path, 
        input_geometry_type: GeometryType):

    ### Init ###    
    layerinfo_input = gfo.get_layerinfo(input_path)
    assert layerinfo_input.crs is not None
    distance = 1
    if layerinfo_input.crs.is_projected is False:
        # 1 degree = 111 km or 111000 m
        distance /= 111000

    ### Test positive buffer ###
    gfo.buffer(
            input_path=input_path,
            output_path=output_path,
            distance=distance,
            nb_parallel=get_nb_parallel(),
            batchsize=get_batchsize())

    # Now check if the output file is correctly created
    assert output_path.exists() == True
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_input.featurecount == layerinfo_output.featurecount
    assert len(layerinfo_output.columns) == len(layerinfo_input.columns)
    
    # Check geometry type
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON 

    # Read result for some more detailed checks
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None

    ### Test buffer to existing output path ###
    assert output_path.exists() is True
    mtime_orig = output_path.stat().st_mtime
    gfo.buffer(
            input_path=input_path,
            output_path=output_path,
            distance=distance,
            nb_parallel=get_nb_parallel())
    assert output_path.stat().st_mtime == mtime_orig

    # With force=True
    gfo.buffer(
            input_path=input_path,
            output_path=output_path,
            distance=distance,
            nb_parallel=get_nb_parallel(),
            force=True)
    assert output_path.stat().st_mtime != mtime_orig

    ### Test negative buffer ###
    distance = -10
    if layerinfo_input.crs.is_projected is False:
        # 1 degree = 111 km or 111000 m
        distance /= 111000

    output_path = output_path.parent / f"{output_path.stem}_m10m{output_path.suffix}"
    gfo.buffer(
            input_path=input_path,
            output_path=output_path,
            distance=distance,
            nb_parallel=get_nb_parallel())

    # Now check if the output file is correctly created
    if input_geometry_type in [GeometryType.MULTIPOINT, GeometryType.MULTILINESTRING]:
        # A Negative buffer of points or linestrings doesn't give a result.
        assert output_path.exists() == False
    else:    
        # A Negative buffer of polygons gives a result for large polygons.
        assert output_path.exists() == True
        layerinfo_output = gfo.get_layerinfo(output_path)
        assert len(layerinfo_output.columns) == len(layerinfo_input.columns) 
        if layerinfo_input.crs.is_projected is True:
            # 7 polygons disappear because of the negative buffer
            assert layerinfo_output.featurecount == layerinfo_input.featurecount - 7
        else:
            assert layerinfo_output.featurecount == layerinfo_input.featurecount - 4
        
        # Check geometry type
        assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

        # Read result for some more detailed checks
        output_gdf = gfo.read_file(output_path)
        assert output_gdf['geometry'][0] is not None
    
    ### Test negative buffer with explodecollections ###
    output_path = output_path.parent / f"{output_path.stem}_m10m_explode{output_path.suffix}"
    gfo.buffer(
            input_path=input_path,
            output_path=output_path,
            distance=distance,
            explodecollections=True,
            nb_parallel=get_nb_parallel())

    # Now check if the output file is correctly created
    if input_geometry_type in [GeometryType.MULTIPOINT, GeometryType.MULTILINESTRING]:
        # A Negative buffer of points or linestrings doesn't give a result.
        assert output_path.exists() == False
    else:    
        # A Negative buffer of polygons gives a result for large polygons
        assert output_path.exists() == True
        layerinfo_output = gfo.get_layerinfo(output_path)
        assert len(layerinfo_output.columns) == len(layerinfo_input.columns) 

        if layerinfo_input.crs.is_projected is True:
            # 6 polygons disappear because of the negative buffer, 3 polygons are 
            # split in 2 because of the negative buffer and/or explodecollections=True.
            assert layerinfo_output.featurecount == layerinfo_input.featurecount - 7 + 3
        else:
            assert layerinfo_output.featurecount == layerinfo_input.featurecount - 3 + 3

        # Check geometry type
        assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

        # Read result for some more detailed checks
        output_gdf = gfo.read_file(output_path)
        assert output_gdf['geometry'][0] is not None

def test_buffer_ext(tmpdir):    
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for suffix in test_helper.get_test_suffix_list():
        # Buffer on not-projected data is weird, so not tested (at the moment)  
        for crs_epsg in test_helper.get_test_crs_epsg_list():
            # If test input file is in wrong format, convert it
            input_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_parcels_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)

            # Now run test
            output_path = tmp_dir / f"{input_path.stem}-output{suffix}"
            print(f"Run test for suffix {suffix}, crs_epsg {crs_epsg}")
            basetest_buffer_ext(input_path, output_path)

def basetest_buffer_ext(input_path, output_path):

    ### Init ###    
    layerinfo_input = gfo.get_layerinfo(input_path)
    assert layerinfo_input.crs is not None
    distance = 1
    if layerinfo_input.crs.is_projected is False:
        # 1 degree = 111 km or 111000 m
        distance /= 111000

    ### Check if columns parameter works (case insensitive) ###
    columns = ['OIDN', 'uidn', 'HFDTLT', 'lblhfdtlt', 'GEWASGROEP', 'lengte', 'OPPERVL']
    gfo.buffer(
            input_path=input_path,
            columns=columns,
            output_path=output_path,
            distance=distance,
            nb_parallel=get_nb_parallel())

    # Now check if the tmp file is correctly created
    layerinfo_input = gfo.get_layerinfo(input_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_input.featurecount == layerinfo_output.featurecount
    assert 'OIDN' in layerinfo_output.columns
    assert 'UIDN' in layerinfo_output.columns
    assert len(layerinfo_output.columns) == len(columns)

    # Read result for some more detailed checks
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None
    area_default_buffer = sum(output_gdf.area)

    ### Check if ... parameter works ###
    # TODO: increase test coverage of other options...

def test_convexhull(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for suffix in test_helper.get_test_suffix_list():
        for crs_epsg in test_helper.get_test_crs_epsg_list():
            # If test input file is in wrong format, convert it
            input_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_parcels_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)

            # Now run test
            output_path = tmp_dir / f"{input_path.stem}-output{suffix}"
            print(f"Run test for suffix {suffix}, crs_epsg {crs_epsg}")
            basetest_convexhull(input_path, output_path)    

def basetest_convexhull(
        input_path: Path, 
        output_path: Path):
    
    # Do operation  
    gfo.convexhull(input_path=input_path, output_path=output_path)

    # Now check if the tmp file is correctly created
    assert output_path.exists() == True
    layerinfo_orig = gfo.get_layerinfo(input_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_orig.featurecount == layerinfo_output.featurecount
    assert len(layerinfo_orig.columns) == len(layerinfo_output.columns)

    # Check geometry type
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON 

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None

def test_delete_duplicate_geometries(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    test_gdf = gpd.GeoDataFrame(
            geometry=[
                    test_helper.TestData.polygon_with_island, 
                    test_helper.TestData.polygon_with_island,
                    test_helper.TestData.polygon_no_islands,
                    test_helper.TestData.polygon_no_islands,
                    test_helper.TestData.polygon_with_island2], 
            crs=test_helper.TestData.crs_epsg)
    suffix = ".gpkg"
    input_path = tmp_dir / f"input_test_data{suffix}"
    gfo.to_file(test_gdf, input_path)
    input_info = gfo.get_layerinfo(input_path)
    
    # Run test
    output_path = tmp_dir / f"{input_path.stem}-output{suffix}"
    print(f"Run test for suffix {suffix}")
    gfo.delete_duplicate_geometries(
            input_path=input_path,
            output_path=output_path)

    # Check result, 2 duplicates should be removed
    result_info = gfo.get_layerinfo(output_path)
    assert result_info.featurecount == input_info.featurecount - 2

def test_isvalid(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for suffix in [".gpkg"]: #test_helper.get_test_suffix_list():
        for crs_epsg in test_helper.get_test_crs_epsg_list():
            # If test input file is in wrong format, convert it
            input_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_invalid_geometries_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)

            # Now run test
            output_path = tmp_dir / f"{input_path.stem}-output{suffix}"
            print(f"Run test for suffix {suffix}, crs_epsg {crs_epsg}")
            basetest_isvalid(input_path, output_path)   
    
def basetest_isvalid(
        input_path: Path, 
        output_path: Path):
    
    # Do operation
    input_layerinfo = gfo.get_layerinfo(input_path)
    gfo.isvalid(input_path=input_path, output_path=output_path, nb_parallel=2)

    # Now check if the tmp file is correctly created
    assert output_path.exists() is True
    result_layerinfo = gfo.get_layerinfo(output_path)
    assert input_layerinfo.featurecount == result_layerinfo.featurecount
    assert len(input_layerinfo.columns) == len(result_layerinfo.columns) - 2

    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None
    assert output_gdf['isvalid'][0] == 0
    
    # Do operation, without specifying output path
    gfo.isvalid(input_path=input_path, nb_parallel=2)

    # Now check if the tmp file is correctly created
    output_auto_path = output_path.parent / f"{input_path.stem}_isvalid{output_path.suffix}"
    assert output_auto_path.exists() == True
    result_auto_layerinfo = gfo.get_layerinfo(output_auto_path)
    assert input_layerinfo.featurecount == result_auto_layerinfo.featurecount
    assert len(input_layerinfo.columns) == len(result_auto_layerinfo.columns) - 2

    output_auto_gdf = gfo.read_file(output_auto_path)
    assert output_auto_gdf['geometry'][0] is not None
    assert output_auto_gdf['isvalid'][0] == 0

def test_makevalid(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for suffix in test_helper.get_test_suffix_list():
        for crs_epsg in test_helper.get_test_crs_epsg_list():
            # If test input file is in wrong format, convert it
            input_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_invalid_geometries_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)

            # Now run test
            output_path = tmp_dir / f"{input_path.stem}-output{suffix}"
            print(f"Run test for suffix {suffix}, crs_epsg {crs_epsg}")
            basetest_makevalid(input_path, output_path)
           
def basetest_makevalid(
        input_path: Path, 
        output_path: Path):

    # Do operation
    gfo.makevalid(input_path=input_path, output_path=output_path, nb_parallel=2)

    # Now check if the output file is correctly created
    assert output_path.exists() == True
    layerinfo_orig = gfo.get_layerinfo(input_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_orig.featurecount == layerinfo_output.featurecount
    assert len(layerinfo_orig.columns) == len(layerinfo_output.columns)

    # Check geometry type
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON 

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None

    # Make sure the input file was not valid
    output_isvalid_path = output_path.parent / f"{output_path.stem}_is-valid{output_path.suffix}"
    isvalid = gfo.isvalid(input_path=input_path, output_path=output_isvalid_path)
    assert isvalid is False, "Input file should contain invalid features"

    # Check if the result file is valid
    output_new_isvalid_path = output_path.parent / f"{output_path.stem}_new_is-valid{output_path.suffix}"
    isvalid = gfo.isvalid(input_path=output_path, output_path=output_new_isvalid_path)
    assert isvalid == True, "Output file shouldn't contain invalid features"

def test_select(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for input_suffix in test_helper.get_test_suffix_list():
        for output_suffix in test_helper.get_test_suffix_list():
            for crs_epsg in test_helper.get_test_crs_epsg_list():
                # If test input file is in wrong format, convert it
                input_path = test_helper.prepare_test_file(
                        path=test_helper.TestFiles.polygons_parcels_gpkg,
                        tmp_dir=tmp_dir,
                        suffix=input_suffix,
                        crs_epsg=crs_epsg)

                # Now run test
                output_path = tmp_dir / f"{input_path.stem}-{input_suffix.replace('.', '')}-output{output_suffix}"
                print(f"Run test for input_suffix {input_suffix}, output_suffix {output_suffix}, crs_epsg {crs_epsg}")
                basetest_select(input_path, output_path)

def basetest_select(
        input_path: Path, 
        output_path: Path):

    # Run test
    layerinfo_input = gfo.get_layerinfo(input_path)
    sql_stmt = 'SELECT {geometrycolumn}, oidn, uidn FROM "{input_layer}"'
    gfo.select(
            input_path=input_path,
            output_path=output_path,
            sql_stmt=sql_stmt)

    # Now check if the tmp file is correctly created
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_input.featurecount == layerinfo_output.featurecount
    assert 'OIDN' in layerinfo_output.columns
    assert 'UIDN' in layerinfo_output.columns
    assert len(layerinfo_output.columns) == 2

    # Check geometry type
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON 

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None

def test_select_various_options(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for suffix in test_helper.get_test_suffix_list():
        for crs_epsg in test_helper.get_test_crs_epsg_list():
            # If test input file is in wrong format, convert it
            input_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_parcels_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)

            # Now run test
            output_path = tmp_dir / f"{input_path.stem}-output{suffix}"
            print(f"Run test for suffix {suffix}, crs_epsg {crs_epsg}")
            basetest_select(input_path, output_path)
    
def basetest_select_various_options(
        input_path: Path, 
        output_path: Path):

    ### Check if columns parameter works (case insensitive) ###
    columns = ['OIDN', 'uidn', 'HFDTLT', 'lblhfdtlt', 'GEWASGROEP', 'lengte', 'OPPERVL']
    layerinfo_input = gfo.get_layerinfo(input_path)
    sql_stmt = '''SELECT {geometrycolumn}
                        {columns_to_select_str} 
                    FROM "{input_layer}"'''
    gfo.select(
            input_path=input_path,
            output_path=output_path,
            columns=columns,
            sql_stmt=sql_stmt)

    # Now check if the tmp file is correctly created
    layerinfo_select = gfo.get_layerinfo(output_path)
    assert layerinfo_input.featurecount == layerinfo_select.featurecount
    assert 'OIDN' in layerinfo_select.columns
    assert 'UIDN' in layerinfo_select.columns
    assert len(layerinfo_select.columns) == len(columns)

    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None

    ### Check if ... parameter works ###
    # TODO: increase test coverage of other options...

def test_simplify(tmpdir):
    # Init
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    test_inputs = []
    test_inputs.append({
            "input_path": test_helper.TestFiles.polygons_parcels_gpkg,
            "geometrytype": GeometryType.MULTIPOLYGON})
    test_inputs.append({
            "input_path": test_helper.TestFiles.points_gpkg,
            "geometrytype": GeometryType.MULTIPOINT})
    test_inputs.append({
            "input_path": test_helper.TestFiles.linestrings_rows_of_trees_gpkg,
            "geometrytype": GeometryType.MULTILINESTRING})

    # Prepare test data + run tests
    for suffix in test_helper.get_test_suffix_list():
        for crs_epsg in test_helper.get_test_crs_epsg_list():
            for test_input in test_inputs: 
                # If test input file is in wrong format, convert it
                input_path = test_helper.prepare_test_file(
                        path=test_input['input_path'],
                        tmp_dir=tmp_dir,
                        suffix=suffix,
                        crs_epsg=crs_epsg)

                # Now run test
                output_path = tmp_dir / f"{input_path.stem}-output{suffix}"
                print(f"Run test for suffix {suffix}, crs_epsg {crs_epsg}, geometrytype {test_input['geometrytype']}")
                basetest_simplify(input_path, output_path, test_input['geometrytype'])
    
def basetest_simplify(
        input_path: Path, 
        output_path: Path,
        expected_output_geometrytype: GeometryType):

    ### Init ###
    layerinfo_orig = gfo.get_layerinfo(input_path)
    assert layerinfo_orig.crs is not None
    if layerinfo_orig.crs.is_projected:
        tolerance = 5
    else:
        # 1 degree = 111 km or 111000 m
        tolerance = 5/111000

    # Do operation
    geofileops_sql.simplify(
            input_path=input_path, 
            output_path=output_path,
            tolerance=tolerance)

    # Now check if the output file is correctly created
    assert output_path.exists() == True
    layerinfo_orig = gfo.get_layerinfo(input_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_orig.featurecount == layerinfo_output.featurecount
    assert len(layerinfo_orig.columns) == len(layerinfo_output.columns)

    # Check geometry type
    assert layerinfo_output.geometrytype == expected_output_geometrytype 

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None

if __name__ == '__main__':
    # Init
    tmpdir = test_helper.init_test_for_debug(Path(__file__).stem)

    # Single layer operations
    test_buffer(tmpdir / "buffer")
    #test_convexhull(tmpdir / "convexhull")
    #test_delete_duplicate_geometries(tmpdir / "delete_duplicate_geometries")
    #test_makevalid(tmpdir / "makevalid")
    #test_isvalid(tmpdir / "isvalid")
    #test_select(tmpdir / "select")
    #test_select_geos_version(tmpdir)
    #test_simplify(tmpdir / "simplify")
    