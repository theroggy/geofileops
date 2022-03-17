# -*- coding: utf-8 -*-
"""
Tests for operations using GeoPandas.
"""

import inspect
from pathlib import Path
import sys

import geopandas as gpd
import shapely.geometry as sh_geom

# Add path so the local geofileops packages are found 
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import geofileops as gfo
from geofileops import GeometryType
from geofileops.util import geofileops_gpd
from geofileops.util import geometry_util
from geofileops.util import io_util
import test_helper

def get_nb_parallel() -> int:
    # The number of parallel processes to use for these tests.
    return 2

def get_batchsize() -> int:
    return 5

def test_get_parallelization_params():
    parallelization_params = geofileops_gpd.get_parallelization_params(500000)
    assert parallelization_params is not None

def test_apply(tmpdir):
    # Init
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Prepare test data + test
    for suffix in test_helper.get_test_suffix_list():
        for crs_epsg in test_helper.get_test_crs_epsg_list():

            # Write test file in the right format + crs
            print(f"Run test for suffix {suffix} and crs_epsg {crs_epsg}")
            test_gdf = gpd.GeoDataFrame(
                    geometry=[
                            test_helper.TestData.polygon_small_island, 
                            test_helper.TestData.polygon_with_island, 
                            None], 
                    crs=test_helper.TestData.crs_epsg)
            # Reproject if needed
            if test_helper.TestData.crs_epsg != crs_epsg:
                test_gdf = test_gdf.to_crs(epsg=crs_epsg)
                assert isinstance(test_gdf, gpd.GeoDataFrame)
            input_path = tmp_dir / f"polygons_small_holes_{crs_epsg}{suffix}"
            gfo.to_file(test_gdf, input_path)
            output_path = tmp_dir / f"{input_path.stem}-output{suffix}"

            # Now run test
            basetest_apply(input_path, output_path)

def basetest_apply(
        input_path: Path,
        output_path: Path):
    ### Init ###
    input_layerinfo = gfo.get_layerinfo(input_path)
    
    ### Test apply with only_geom_input = True ###
    gfo.apply(
            input_path=input_path,
            output_path=output_path,
            func=lambda geom: geometry_util.remove_inner_rings(
                    geometry=geom,
                    min_area_to_keep=2,
                    crs=input_layerinfo.crs),
            only_geom_input=True,
            nb_parallel=get_nb_parallel())

    # Now check if the output file is correctly created
    assert output_path.exists() == True
    output_layerinfo = gfo.get_layerinfo(output_path)
    # The row with the None geometry will be removed
    assert input_layerinfo.featurecount == (output_layerinfo.featurecount + 1)
    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON 

    # Read result for some more detailed checks
    output_gdf = gfo.read_file(output_path)

    # In the 1st polygon the island should be removed 
    output_geometry = output_gdf['geometry'][0]
    assert output_geometry is not None
    if isinstance(output_geometry, sh_geom.MultiPolygon):
        assert len(output_geometry.geoms) == 1
        output_geometry = output_geometry.geoms[0]
    assert isinstance(output_geometry, sh_geom.Polygon)
    assert len(output_geometry.interiors) == 0

    # In the 2nd polygon the island is too large, so should still be there 
    output_geometry = output_gdf['geometry'][1]
    assert output_geometry is not None
    if isinstance(output_geometry, sh_geom.MultiPolygon):
        assert len(output_geometry.geoms) == 1
        output_geometry = output_geometry.geoms[0]
    assert isinstance(output_geometry, sh_geom.Polygon)
    assert len(output_geometry.interiors) == 1

    ### Test apply with only_geom_input = False ###
    output_path = io_util.with_stem(output_path, f"{output_path.stem}_2")
    gfo.apply(
            input_path=input_path,
            output_path=output_path,
            func=lambda row: geometry_util.remove_inner_rings(
                    row.geometry,
                    min_area_to_keep=2,
                    crs=input_layerinfo.crs),
            only_geom_input=False,
            nb_parallel=get_nb_parallel())

    # Now check if the output file is correctly created
    assert output_path.exists() == True
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert input_layerinfo.featurecount == (output_layerinfo.featurecount + 1)
    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON 

    # Read result for some more detailed checks
    output_gdf = gfo.read_file(output_path)
    for index in range(0, 2):
        output_geometry = output_gdf['geometry'][index]
        assert output_geometry is not None
        if isinstance(output_geometry, sh_geom.MultiPolygon):
            assert len(output_geometry.geoms) == 1
            output_geometry = output_geometry.geoms[0]
        assert isinstance(output_geometry, sh_geom.Polygon)
        
        if index == 0:
            # In the 1st polygon the island must be removed 
            assert len(output_geometry.interiors) == 0
        elif index == 1:
            # In the 2nd polygon the island is larger, so should be there 
            assert len(output_geometry.interiors) == 1

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
    
    ### Test polygon buffer with square endcaps ###
    output_path = output_path.parent / f"{output_path.stem}_endcap_join{output_path.suffix}"
    gfo.buffer(
            input_path=input_path,
            output_path=output_path,
            distance=distance,
            endcap_style=geometry_util.BufferEndCapStyle.SQUARE,
            join_style=geometry_util.BufferJoinStyle.MITRE,
            nb_parallel=get_nb_parallel())

    # Now check if the output file is correctly created
    assert output_path.exists() == True
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_input.featurecount == layerinfo_output.featurecount
    assert len(layerinfo_output.columns) == len(layerinfo_input.columns)
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON 

    # Read result for some more detailed checks
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None
    area_square_buffer = sum(output_gdf.area)
    assert area_square_buffer > area_default_buffer

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

def basetest_convexhull(input_path, output_path):
    layerinfo_orig = gfo.get_layerinfo(input_path)
    geofileops_gpd.convexhull(
            input_path=input_path,
            output_path=output_path,
            nb_parallel=get_nb_parallel())

    # Now check if the output file is correctly created
    assert output_path.exists() == True
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_orig.featurecount == layerinfo_output.featurecount
    assert len(layerinfo_orig.columns) == len(layerinfo_output.columns)
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON 

    # Read result for some more detailed checks
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None

def test_dissolve_linestrings_nogroupby(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for suffix in test_helper.get_test_suffix_list():
        for crs_epsg in test_helper.get_test_crs_epsg_list():
            # If test input file is in wrong format, convert it
            input_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.linestrings_watercourses_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)

            # Now run test
            output_path = tmp_dir / f"{input_path.stem}-output{suffix}"
            print(f"Run test for suffix {suffix}, crs_epsg {crs_epsg}")
            basetest_dissolve_linestrings_nogroupby(input_path, output_path)

def basetest_dissolve_linestrings_nogroupby(input_path, output_basepath):
    # Apply dissolve with explodecollections
    output_path = (output_basepath.parent / 
            f"{output_basepath.stem}_expl{output_basepath.suffix}")
    gfo.dissolve(
            input_path=input_path,
            output_path=output_path,
            explodecollections=True,
            nb_parallel=get_nb_parallel(),
            batchsize=5)

    # Check if the result file is correctly created
    assert output_path.exists() == True
    layerinfo_orig = gfo.get_layerinfo(input_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == 85
    assert layerinfo_output.geometrytype in [GeometryType.LINESTRING, GeometryType.MULTILINESTRING]
    assert len(layerinfo_output.columns) >= 0

    # Now check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == layerinfo_output.featurecount
    assert output_gdf['geometry'][0] is not None

    # Apply dissolve without explodecollections
    output_path = (output_basepath.parent / 
            f"{output_basepath.stem}_noexpl{output_basepath.suffix}")
    # explodecollections=False only supported if 
    gfo.dissolve(
            input_path=input_path,
            output_path=output_path,
            explodecollections=False,
            nb_parallel=get_nb_parallel(),
            batchsize=5)

    # Check if the result file is correctly created
    assert output_path.exists() == True
    layerinfo_orig = gfo.get_layerinfo(input_path)
    
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == 1
    assert layerinfo_output.geometrytype is layerinfo_orig.geometrytype
    assert len(layerinfo_output.columns) >= 0

    # Now check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == layerinfo_output.featurecount
    assert output_gdf['geometry'][0] is not None

def test_dissolve_polygons_groupby(tmpdir):
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
            basetest_dissolve_polygons_groupby(input_path, output_path)

def basetest_dissolve_polygons_groupby(
        input_path: Path, 
        output_basepath: Path):
    # Init
    layerinfo_input = gfo.get_layerinfo(input_path)

    ### Test dissolve polygons with groupby + without explodecollections ###
    output_path = output_basepath.parent / f"{output_basepath.stem}_group{output_basepath.suffix}"
    gfo.dissolve(
            input_path=input_path,
            output_path=output_path,
            groupby_columns=['GEWASGROEP'],
            explodecollections=False,
            nb_parallel=get_nb_parallel(),
            batchsize=get_batchsize())

    # Now check if the tmp file is correctly created
    assert output_path.exists() == True
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == 6
    assert len(layerinfo_output.columns) == 1
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == layerinfo_output.featurecount
    assert output_gdf['geometry'][0] is not None

    ### Test dissolve polygons with explodecollections ###
    output_path = output_basepath.parent / f"{output_basepath.stem}_group_explode{output_basepath.suffix}"
    gfo.dissolve(
            input_path=input_path,
            output_path=output_path,
            groupby_columns=['GEWASGROEP'],
            explodecollections=True,
            nb_parallel=get_nb_parallel(),
            batchsize=get_batchsize())

    # Now check if the tmp file is correctly created
    assert output_path.exists() == True
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == 25
    assert len(layerinfo_output.columns) == 1

    # Check geometry type
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON 

    # Now check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == layerinfo_output.featurecount
    assert output_gdf['geometry'][0] is not None

    ### Test dissolve polygons with explodecollections + all columns ###
    output_path = output_basepath.parent / f"{output_basepath.stem}_group_explode_allcolumns{output_basepath.suffix}"
    gfo.dissolve(
            input_path=input_path,
            output_path=output_path,
            groupby_columns=['GEWASGROEP'],
            columns=None,
            explodecollections=True,
            nb_parallel=get_nb_parallel(),
            batchsize=get_batchsize())

    # Now check if the tmp file is correctly created
    assert output_path.exists() == True
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == 25
    assert len(layerinfo_output.columns) == len(layerinfo_input.columns)

    # Check geometry type
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON 

    # Now check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == layerinfo_output.featurecount
    assert output_gdf['geometry'][0] is not None

    ### Test dissolve polygons with specified output layer ###
    # A different output layer is not supported for shapefile!!!
    try:
        output_path = output_basepath.parent / f"{output_basepath.stem}_group_outputlayer{output_basepath.suffix}"
        gfo.dissolve(
                input_path=input_path,
                output_path=output_path,
                groupby_columns=['GEWASGROEP'],
                output_layer='banana',
                explodecollections=True,
                nb_parallel=get_nb_parallel(),
                batchsize=get_batchsize())
    except Exception as ex:
        # A different output_layer is not supported for shapefile, so normal 
        # that an exception is thrown!
        assert output_path.suffix.lower() == '.shp'

    # Now check if the tmp file is correctly created
    if output_path.suffix.lower() != '.shp':
        assert output_path.exists() == True
        layerinfo_output = gfo.get_layerinfo(output_path)
        assert layerinfo_output.featurecount == 25
        assert len(layerinfo_output.columns) == 1
        assert layerinfo_output.name == 'banana'

        # Check geometry type
        assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

        # Now check the contents of the result file
        input_gdf = gfo.read_file(input_path)
        output_gdf = gfo.read_file(output_path)
        assert input_gdf.crs == output_gdf.crs
        assert len(output_gdf) == layerinfo_output.featurecount
        assert output_gdf['geometry'][0] is not None

def test_dissolve_polygons_nogroupby(tmpdir):
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
            basetest_dissolve_polygons_groupby(input_path, output_path)

def basetest_dissolve_polygons_nogroupby(
        input_path: Path, 
        output_basepath: Path):
    # Init
    layerinfo_input = gfo.get_layerinfo(input_path)
    
    ### Test dissolve polygons with explodecollections=True (= default) ###
    output_path = output_basepath.parent / f"{output_basepath.stem}_defaults{output_basepath.suffix}"
    gfo.dissolve(
            input_path=input_path,
            output_path=output_path,
            explodecollections=True,
            nb_parallel=get_nb_parallel(),
            batchsize=get_batchsize(),
            force=True)

    # Now check if the result file is correctly created
    assert output_path.exists() == True
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == 23
    if output_basepath.suffix == '.shp':
        # Shapefile always has an FID field
        # TODO: think about whether this should also be the case for geopackage??? 
        assert len(layerinfo_output.columns) == 1
    else:
        assert len(layerinfo_output.columns) == 0

    # Check geometry type
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON 

    # Now check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == layerinfo_output.featurecount
    assert output_gdf['geometry'][0] is not None

    ### Test dissolve to existing output path ###
    assert output_path.exists() is True
    mtime_orig = output_path.stat().st_mtime
    gfo.dissolve(
            input_path=input_path,
            output_path=output_path,
            explodecollections=True,
            nb_parallel=get_nb_parallel())
    assert output_path.stat().st_mtime == mtime_orig

    # With force=True
    gfo.dissolve(
            input_path=input_path,
            output_path=output_path,
            explodecollections=True,
            nb_parallel=get_nb_parallel(),
            force=True)
    assert output_path.stat().st_mtime == mtime_orig


    ### Test dissolve polygons with explodecollections=False ###
    output_path = output_basepath.parent / f"{output_basepath.stem}_defaults{output_basepath.suffix}"
    gfo.dissolve(
            input_path=input_path,
            output_path=output_path,
            explodecollections=False,
            nb_parallel=get_nb_parallel(),
            batchsize=get_batchsize(),
            force=True)

    # Now check if the result file is correctly created
    assert output_path.exists() == True
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == 1
    if output_basepath.suffix == '.shp':
        # Shapefile always has an FID field
        # TODO: think about whether this should also be the case for geopackage??? 
        assert len(layerinfo_output.columns) == 1
    else:
        assert len(layerinfo_output.columns) == 0

    # Check geometry type
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON 

    # Now check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == layerinfo_output.featurecount
    assert output_gdf['geometry'][0] is not None

    ### Test dissolve polygons, with output_layer ###
    # A different output layer is not supported for shapefile!!!
    try:
        output_path = output_basepath.parent / f"{output_basepath.stem}_outputlayer{output_basepath.suffix}"
        gfo.dissolve(
                input_path=input_path,
                output_path=output_path,
                output_layer='banana',
                explodecollections=True,
                nb_parallel=get_nb_parallel(),
                batchsize=get_batchsize(),
                force=True)
    except Exception as ex:
        # A different output_layer is not supported for shapefile, so normal 
        # that an exception is thrown!
        assert output_path.suffix.lower() == '.shp'

    # Now check if the result file is correctly created
    if output_path.suffix.lower() != '.shp':
        assert output_path.exists() == True
        layerinfo_output = gfo.get_layerinfo(output_path)
        assert layerinfo_output.featurecount == 23
        assert len(layerinfo_output.columns) == 0
        if output_basepath.suffix == '.shp':
            # Shapefile doesn't support specifying an output_layer
            assert layerinfo_output.name == output_path.stem
        else:
            assert layerinfo_output.name == 'banana'

        # Check geometry type
        assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON 

        # Now check the contents of the result file
        input_gdf = gfo.read_file(input_path)
        output_gdf = gfo.read_file(output_path)
        assert input_gdf.crs == output_gdf.crs
        assert len(output_gdf) == layerinfo_output.featurecount
        assert output_gdf['geometry'][0] is not None

def test_dissolve_multisinglepolygons(tmpdir):
    # Init
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Prepare test data + test
    for suffix in test_helper.get_test_suffix_list():
        for crs_epsg in test_helper.get_test_crs_epsg_list():

            # Write test file in the right format + crs
            print(f"Run test for suffix {suffix} and crs_epsg {crs_epsg}")
            test_gdf = gpd.GeoDataFrame(
                    geometry=[
                            test_helper.TestData.polygon_with_island, 
                            test_helper.TestData.multipolygon], 
                    crs=test_helper.TestData.crs_epsg)
            # Reproject if needed
            if test_helper.TestData.crs_epsg != crs_epsg:
                test_gdf = test_gdf.to_crs(epsg=crs_epsg)
                assert isinstance(test_gdf, gpd.GeoDataFrame)
            input_path = tmp_dir / f"polygons_{crs_epsg}{suffix}"
            gfo.to_file(test_gdf, input_path)
            output_path = tmp_dir / f"{input_path.stem}-output{suffix}"

            # Now run test
            basetest_dissolve_multisinglepolygons(input_path, output_path)

def basetest_dissolve_multisinglepolygons(
        input_path: Path,
        output_path: Path):
    # Test to check if it is handled well that a file that results in single 
    # and multipolygons during dissolve is treated correctly, as geopackage 
    # doesn't support single and multi-polygons in one layer.
    gfo.dissolve(
            input_path=input_path,
            output_path=output_path,
            explodecollections=True,
            nb_squarish_tiles=2,
            nb_parallel=get_nb_parallel(),
            batchsize=get_batchsize(),
            force=True)

    # Now check if the result file is correctly created
    assert output_path.exists() == True
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == 3
    if output_path.suffix == '.shp':
        # Shapefile always has an FID field
        # TODO: think about whether this should also be the case for geopackage??? 
        assert len(layerinfo_output.columns) == 1
    else:
        assert len(layerinfo_output.columns) == 0
    
    # Check geometry type
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON 

    # Now check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == layerinfo_output.featurecount
    assert output_gdf['geometry'][0] is not None

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
        output_basepath: Path, 
        expected_output_geometrytype: GeometryType):

    ### Init ###
    layerinfo_orig = gfo.get_layerinfo(input_path)
    assert layerinfo_orig.crs is not None
    if layerinfo_orig.crs.is_projected:
        tolerance = 5
    else:
        # 1 degree = 111 km or 111000 m
        tolerance = 5/111000

    ### Test default algorithm, rdp ###
    output_path = io_util.with_stem(output_basepath, f"{output_basepath.stem}_rdp")
    gfo.simplify(
            input_path=input_path,
            output_path=output_path,
            tolerance=tolerance,
            nb_parallel=get_nb_parallel())

    # Now check if the tmp file is correctly created
    assert output_path.exists() == True
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_orig.featurecount == layerinfo_output.featurecount
    assert len(layerinfo_orig.columns) == len(layerinfo_output.columns)

    # Check geometry type
    assert layerinfo_output.geometrytype == expected_output_geometrytype

    # Now check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == layerinfo_output.featurecount
    assert output_gdf['geometry'][0] is not None

    ### Test vw (visvalingam-whyatt) algorithm ###
    output_path = io_util.with_stem(output_basepath, f"{output_basepath.stem}_vw")
    gfo.simplify(
            input_path=input_path,
            output_path=output_path,
            tolerance=tolerance,
            algorithm=geometry_util.SimplifyAlgorithm.VISVALINGAM_WHYATT,
            nb_parallel=get_nb_parallel())

    # Now check if the tmp file is correctly created
    assert output_path.exists() == True
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_orig.featurecount == layerinfo_output.featurecount
    assert len(layerinfo_orig.columns) == len(layerinfo_output.columns)

    # Check geometry type
    assert layerinfo_output.geometrytype == expected_output_geometrytype

    # Now check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == layerinfo_output.featurecount
    assert output_gdf['geometry'][0] is not None

    ### Test lang algorithm ###
    output_path = io_util.with_stem(output_basepath, f"{output_basepath.stem}_lang")
    gfo.simplify(
            input_path=input_path,
            output_path=output_path,
            tolerance=tolerance,
            algorithm=geometry_util.SimplifyAlgorithm.LANG,
            lookahead=8,
            nb_parallel=get_nb_parallel())

    # Now check if the tmp file is correctly created
    assert output_path.exists() == True
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_orig.featurecount == layerinfo_output.featurecount
    assert len(layerinfo_orig.columns) == len(layerinfo_output.columns)

    # Check geometry type
    assert layerinfo_output.geometrytype == expected_output_geometrytype

    # Now check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == layerinfo_output.featurecount
    assert output_gdf['geometry'][0] is not None

if __name__ == '__main__':
    # Init
    tmpdir = test_helper.init_test_for_debug(Path(__file__).stem)

    # Run
    #test_get_parallelization_params()
    test_apply(tmpdir / "apply")
    #test_buffer(tmpdir / "buffer")
    #test_buffer_ext(tmpdir / "buffer_ext")
    #test_dissolve_linestrings_nogroupby(tmpdir / "dissolve_linestrings_nogroupby")
    #test_dissolve_polygons_groupby(tmpdir / "dissolve_polygons_groupby")
    #test_dissolve_polygons_nogroupby(tmpdir / "dissolve_polygons_nogroupby")
    #test_dissolve_multisinglepolygons(tmpdir / "dissolve_multisinglepolygons")
    #test_simplify(tmpdir / "simplify")
