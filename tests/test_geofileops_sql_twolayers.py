# -*- coding: utf-8 -*-
"""
Tests for operations that are executed using a sql statement on two layers.
"""

from pathlib import Path
import sys

# Add path so the local geofileops packages are found 
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import geofileops as gfo
from geofileops import GeometryType, PrimitiveType
from geofileops.util import io_util
import test_helper

def test_erase(tmpdir):
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

                # If test input file is in wrong format, convert it
                erase_path = test_helper.prepare_test_file(
                        path=test_helper.TestFiles.polygons_zones_gpkg,
                        tmp_dir=tmp_dir,
                        suffix=suffix,
                        crs_epsg=crs_epsg)
            
                # Now run test
                output_path = tmp_dir / f"{input_path.stem}-output{suffix}"
                print(f"Run test for suffix {suffix}, crs_epsg {crs_epsg}, geometrytype {test_input['geometrytype']}")
                basetest_erase(input_path, erase_path, output_path, test_input['geometrytype'])

def basetest_erase(
        input_path: Path,
        erase_path: Path, 
        output_path: Path,
        expected_output_geometrytype: GeometryType):

    ### Do standard operation ###
    gfo.erase(
            input_path=input_path, 
            erase_path=erase_path,
            output_path=output_path)

    # Now check if the tmp file is correctly created
    assert output_path.exists() == True
    layerinfo_orig = gfo.get_layerinfo(input_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert len(layerinfo_orig.columns) == len(layerinfo_output.columns)

    # Checks depending on geometry type
    assert layerinfo_output.geometrytype == expected_output_geometrytype
    if expected_output_geometrytype == GeometryType.MULTIPOLYGON:
        assert layerinfo_output.featurecount == 37
    elif expected_output_geometrytype == GeometryType.MULTIPOINT:
        assert layerinfo_output.featurecount == 47
    elif expected_output_geometrytype == GeometryType.MULTILINESTRING:
        assert layerinfo_output.featurecount == 12
    else:
        raise Exception(f"Unsupported expected_output_geometrytype: {expected_output_geometrytype}")

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None

    ### Do operation with explodecollections=True ###
    output_path = io_util.with_stem(output_path, f"{output_path.stem}_exploded")
    gfo.erase(
            input_path=input_path, 
            erase_path=erase_path,
            output_path=output_path,
            explodecollections=True)

    # Now check if the tmp file is correctly created
    assert output_path.exists() == True
    layerinfo_orig = gfo.get_layerinfo(input_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert len(layerinfo_orig.columns) == len(layerinfo_output.columns)

    # Checks depending on geometry type
    assert layerinfo_output.geometrytype == expected_output_geometrytype
    if expected_output_geometrytype == GeometryType.MULTIPOLYGON:
        assert layerinfo_output.featurecount == 40
    elif expected_output_geometrytype == GeometryType.MULTIPOINT:
        assert layerinfo_output.featurecount == 47
    elif expected_output_geometrytype == GeometryType.MULTILINESTRING:
        assert layerinfo_output.featurecount == 13
    else:
        raise Exception(f"Unsupported expected_output_geometrytype: {expected_output_geometrytype}")

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None
        
def test_export_by_location(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for suffix in test_helper.get_test_suffix_list():
        for crs_epsg in test_helper.get_test_crs_epsg_list():
            # If test input file is in wrong format, convert it
            input_to_select_from_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_parcels_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)

            # If test input file is in wrong format, convert it
            input_to_compare_with_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_zones_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)
        
            # Now run test
            output_path = tmp_dir / f"{input_to_select_from_path.stem}-output{suffix}"
            print(f"Run test for suffix {suffix}, crs_epsg {crs_epsg}")
            basetest_export_by_location(input_to_select_from_path, input_to_compare_with_path, output_path)

def basetest_export_by_location(
        input_to_select_from_path: Path, 
        input_to_compare_with_path: Path, 
        output_path: Path):

    gfo.export_by_location(
            input_to_select_from_path=input_to_select_from_path,
            input_to_compare_with_path=input_to_compare_with_path,
            output_path=output_path)

    # Now check if the tmp file is correctly created
    assert output_path.exists() == True
    layerinfo_orig = gfo.get_layerinfo(input_to_select_from_path)
    layerinfo_output = gfo.get_layerinfo(input_to_select_from_path)
    assert layerinfo_orig.featurecount == layerinfo_output.featurecount
    assert len(layerinfo_orig.columns) == len(layerinfo_output.columns)

    # Check geometry type
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON 

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None

def test_export_by_distance(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for suffix in test_helper.get_test_suffix_list():
        for crs_epsg in test_helper.get_test_crs_epsg_list():
            # If test input file is in wrong format, convert it
            input_to_select_from_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_parcels_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)

            # If test input file is in wrong format, convert it
            input_to_compare_with_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_zones_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)
        
            # Now run test
            output_path = tmp_dir / f"{input_to_select_from_path.stem}-output{suffix}"
            print(f"Run test for suffix {suffix}, crs_epsg {crs_epsg}")
            basetest_export_by_distance(
                    input_to_select_from_path, 
                    input_to_compare_with_path, 
                    output_path)

def basetest_export_by_distance(
        input_to_select_from_path: Path, 
        input_to_compare_with_path: Path, 
        output_path: Path):

    gfo.export_by_distance(
            input_to_select_from_path=input_to_select_from_path,
            input_to_compare_with_path=input_to_compare_with_path,
            max_distance=10,
            output_path=output_path)

    # Now check if the tmp file is correctly created
    assert output_path.exists() == True
    layerinfo_orig = gfo.get_layerinfo(input_to_select_from_path)
    layerinfo_output = gfo.get_layerinfo(input_to_select_from_path)
    assert layerinfo_orig.featurecount == layerinfo_output.featurecount
    assert len(layerinfo_orig.columns) == len(layerinfo_output.columns)

    # Check geometry type
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON 

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None

def test_intersect(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for suffix in test_helper.get_test_suffix_list():
        for crs_epsg in test_helper.get_test_crs_epsg_list():
            # If test input file is in wrong format, convert it
            input1_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_parcels_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)

            # If test input file is in wrong format, convert it
            input2_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_zones_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)
        
            # Now run test
            output_path = tmp_dir / f"{input1_path.stem}-output{suffix}"
            print(f"Run test for suffix {suffix}, crs_epsg {crs_epsg}")
            basetest_intersect(input1_path, input2_path, output_path)
    
def basetest_intersect(
        input1_path: Path, 
        input2_path: Path, 
        output_path: Path):

    # Do operation
    gfo.intersect(
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=output_path,
            nb_parallel=2)

    # Now check if the tmp file is correctly created
    assert output_path.exists() == True
    layerinfo_input1 = gfo.get_layerinfo(input1_path)
    layerinfo_input2 = gfo.get_layerinfo(input2_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == 28
    assert (len(layerinfo_input1.columns) + len(layerinfo_input2.columns)) == len(layerinfo_output.columns)
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON 
    
    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None

def test_join_by_location(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for suffix in test_helper.get_test_suffix_list():
        for crs_epsg in test_helper.get_test_crs_epsg_list():
            # If test input file is in wrong format, convert it
            input1_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_parcels_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)

            # If test input file is in wrong format, convert it
            input2_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_zones_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)
        
            # Now run test
            output_path = tmp_dir / f"{input1_path.stem}-output{suffix}"
            print(f"Run test for suffix {suffix}, crs_epsg {crs_epsg}")
            basetest_join_by_location(input1_path, input2_path, output_path)
    
def basetest_join_by_location(
        input1_path: Path, 
        input2_path: Path,
        output_path: Path):
        
    ### Test 1: inner join, intersect
    gfo.join_by_location(
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=output_path,
            discard_nonmatching=True,
            force=True)

    # Now check if the output file is correctly created
    assert output_path.exists() == True
    layerinfo_input1 = gfo.get_layerinfo(input1_path)
    layerinfo_input2 = gfo.get_layerinfo(input2_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == 28
    if input1_path.suffix == ".shp":
        assert (len(layerinfo_input1.columns) + len(layerinfo_input2.columns)) == len(layerinfo_output.columns)
    else:
        assert (len(layerinfo_input1.columns) + len(layerinfo_input2.columns) + 1) == len(layerinfo_output.columns)
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON 

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None

    ### Test 2: left outer join, intersect
    gfo.join_by_location(
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=output_path,
            discard_nonmatching=False,
            force=True)

    # Now check if the output file is correctly created
    assert output_path.exists() == True
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == 48
    if input1_path.suffix == ".shp":
        assert (len(layerinfo_input1.columns) + len(layerinfo_input2.columns)) == len(layerinfo_output.columns)
    else:
        assert (len(layerinfo_input1.columns) + len(layerinfo_input2.columns) + 1) == len(layerinfo_output.columns)
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None

def test_join_nearest(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for suffix in test_helper.get_test_suffix_list():
        for crs_epsg in test_helper.get_test_crs_epsg_list():
            # If test input file is in wrong format, convert it
            input1_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_parcels_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)

            # If test input file is in wrong format, convert it
            input2_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_zones_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)
        
            # Now run test
            output_path = tmp_dir / f"{input1_path.stem}-output{suffix}"
            print(f"Run test for suffix {suffix}, crs_epsg {crs_epsg}")
            basetest_join_nearest(input1_path, input2_path, output_path)
    
def basetest_join_nearest(
        input1_path: Path, 
        input2_path: Path,
        output_path: Path):
        
    ### Test 1: inner join, intersect
    nb_nearest = 2
    gfo.join_nearest(
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=output_path,
            nb_nearest=nb_nearest,
            force=True)

    # Now check if the output file is correctly created
    assert output_path.exists() == True
    layerinfo_input1 = gfo.get_layerinfo(input1_path)
    layerinfo_input2 = gfo.get_layerinfo(input2_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == nb_nearest * layerinfo_input1.featurecount
    assert (len(layerinfo_input1.columns) + len(layerinfo_input2.columns) + 2) == len(layerinfo_output.columns)

    # Check geometry type
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON 

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None

def test_select_two_layers(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for suffix in test_helper.get_test_suffix_list():
        for crs_epsg in test_helper.get_test_crs_epsg_list():
            # If test input file is in wrong format, convert it
            input1_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_parcels_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)

            # If test input file is in wrong format, convert it
            input2_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_zones_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)
        
            # Now run test
            output_path = tmp_dir / f"{input1_path.stem}-output{suffix}"
            print(f"Run test for suffix {suffix}, crs_epsg {crs_epsg}")
            basetest_select_two_layers(input1_path, input2_path, output_path)
    
def basetest_select_two_layers(
        input1_path: Path, 
        input2_path: Path, 
        output_path: Path):

    # Prepare query to execute. At the moment this is just the query for the 
    # intersect() operation.
    input1_layer_info = gfo.get_layerinfo(input1_path)
    input2_layer_info = gfo.get_layerinfo(input2_path)
    primitivetype_to_extract = PrimitiveType(min(
            input1_layer_info.geometrytype.to_primitivetype.value, 
            input2_layer_info.geometrytype.to_primitivetype.value))
    sql_stmt = f'''
            SELECT ST_CollectionExtract(
                    ST_Intersection(layer1.{{input1_geometrycolumn}}, layer2.{{input2_geometrycolumn}}), 
                    {primitivetype_to_extract.value}) as geom
                    {{layer1_columns_prefix_alias_str}}
                    {{layer2_columns_prefix_alias_str}}
                    ,CASE 
                        WHEN layer2.naam = 'zone1' THEN 'in_zone1'
                        ELSE 'niet_in_zone1'
                        END AS category
                FROM {{input1_databasename}}."{{input1_layer}}" layer1
                JOIN {{input1_databasename}}."rtree_{{input1_layer}}_{{input1_geometrycolumn}}" layer1tree ON layer1.fid = layer1tree.id
                JOIN {{input2_databasename}}."{{input2_layer}}" layer2
                JOIN {{input2_databasename}}."rtree_{{input2_layer}}_{{input2_geometrycolumn}}" layer2tree ON layer2.fid = layer2tree.id
            WHERE 1=1
                {{batch_filter}}
                AND layer1tree.minx <= layer2tree.maxx AND layer1tree.maxx >= layer2tree.minx
                AND layer1tree.miny <= layer2tree.maxy AND layer1tree.maxy >= layer2tree.miny
                AND ST_Intersects(layer1.{{input1_geometrycolumn}}, layer2.{{input2_geometrycolumn}}) = 1
                AND ST_Touches(layer1.{{input1_geometrycolumn}}, layer2.{{input2_geometrycolumn}}) = 0
            '''
    gfo.select_two_layers(
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=output_path,
            sql_stmt=sql_stmt)

    # Now check if the tmp file is correctly created
    assert output_path.exists() == True
    layerinfo_input1 = gfo.get_layerinfo(input1_path)
    layerinfo_input2 = gfo.get_layerinfo(input2_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == 28
    assert (len(layerinfo_input1.columns) + len(layerinfo_input2.columns) + 1) == len(layerinfo_output.columns)
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None

def test_split(tmpdir):
   # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for suffix in test_helper.get_test_suffix_list():
        for crs_epsg in test_helper.get_test_crs_epsg_list():
            # If test input file is in wrong format, convert it
            input1_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_parcels_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)

            # If test input file is in wrong format, convert it
            input2_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_zones_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)
        
            # Now run test
            output_path = tmp_dir / f"{input1_path.stem}-output{suffix}"
            print(f"Run test for suffix {suffix}, crs_epsg {crs_epsg}")
            basetest_split_layers(input1_path, input2_path, output_path)
    
def basetest_split_layers(
        input1_path: Path, 
        input2_path: Path, 
        output_path: Path):

    # Do operation
    gfo.split(
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=output_path)

    # Now check if the tmp file is correctly created
    assert output_path.exists() == True
    layerinfo_input1 = gfo.get_layerinfo(input1_path)
    layerinfo_input2 = gfo.get_layerinfo(input2_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == 65
    assert (len(layerinfo_input1.columns) + len(layerinfo_input2.columns)) == len(layerinfo_output.columns)
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None

def test_union(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for suffix in test_helper.get_test_suffix_list():
        for crs_epsg in test_helper.get_test_crs_epsg_list():
            # If test input file is in wrong format, convert it
            input1_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_parcels_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)

            # If test input file is in wrong format, convert it
            input2_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_zones_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)
        
            # Now run test
            output_path = tmp_dir / f"{input1_path.stem}-output{suffix}"
            print(f"Run test for suffix {suffix}, crs_epsg {crs_epsg}")
            basetest_union(input1_path, input2_path, output_path)
    
def basetest_union(
        input1_path: Path, 
        input2_path: Path, 
        output_path: Path):

    # Do operation
    gfo.union(
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=output_path,
            verbose=True)

    # Now check if the tmp file is correctly created
    assert output_path.exists() == True
    layerinfo_input1 = gfo.get_layerinfo(input1_path)
    layerinfo_input2 = gfo.get_layerinfo(input2_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == 69
    assert (len(layerinfo_input1.columns) + len(layerinfo_input2.columns)) == len(layerinfo_output.columns)
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None

def test_union_circles(tmpdir):

    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    tmp_dir.mkdir(parents=True, exist_ok=True)
    for suffix in test_helper.get_test_suffix_list():
        for crs_epsg in test_helper.get_test_crs_epsg_list():
            # If test input file is in wrong format, convert it
            input1_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_overlappingcircles_one_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)

            # If test input file is in wrong format, convert it
            input2_path = test_helper.prepare_test_file(
                    path=test_helper.TestFiles.polygons_overlappingcircles_twothree_gpkg,
                    tmp_dir=tmp_dir,
                    suffix=suffix,
                    crs_epsg=crs_epsg)
        
            # Now run test
            output_path = tmp_dir / f"{input1_path.stem}-output{suffix}"
            print(f"Run test for suffix {suffix}, crs_epsg {crs_epsg}")
            basetest_union_circles(tmp_dir, input1_path, input2_path, output_path)
    
def basetest_union_circles(
        tmp_dir: Path,
        input1_path: Path,
        input2_path: Path,
        output_path: Path):
    
    ##### Also run some tests on basic data with circles #####
    ### Union the single circle towards the 2 circles ###
    gfo.union( 
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=output_path,
            verbose=True)

    # Now check if the tmp file is correctly created
    assert output_path.exists() == True
    layerinfo_input1 = gfo.get_layerinfo(input1_path)
    layerinfo_input2 = gfo.get_layerinfo(input2_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == 5
    assert (len(layerinfo_input1.columns) + len(layerinfo_input2.columns)) == len(layerinfo_output.columns)

    # Check geometry type
    assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None

    ### Union the two circles towards the single circle ###
    input1_path = test_helper.TestFiles.polygons_overlappingcircles_twothree_gpkg
    input2_path = test_helper.TestFiles.polygons_overlappingcircles_one_gpkg
    output_path = Path(tmp_dir) / f"{input1_path.stem}_union_{input2_path.stem}.gpkg"
    gfo.union( 
            input1_path=input1_path,
            input2_path=input2_path,
            output_path=output_path,
            verbose=True)

    # Now check if the tmp file is correctly created
    assert output_path.exists() == True
    layerinfo_input1 = gfo.get_layerinfo(input1_path)
    layerinfo_input2 = gfo.get_layerinfo(input2_path)
    layerinfo_output = gfo.get_layerinfo(output_path)
    assert layerinfo_output.featurecount == 5
    assert (len(layerinfo_input1.columns) + len(layerinfo_input2.columns)) == len(layerinfo_output.columns)

    # Check geometry type
    if output_path.suffix.lower() == '.shp':
        # For shapefiles the type stays POLYGON anyway 
        assert layerinfo_output.geometrytype == GeometryType.POLYGON 
    elif output_path.suffix.lower() == '.gpkg':
        assert layerinfo_output.geometrytype == GeometryType.MULTIPOLYGON

    # Now check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf['geometry'][0] is not None

if __name__ == '__main__':
    # Init
    tmpdir = test_helper.init_test_for_debug(Path(__file__).stem)

    # Two layer operations
    #test_erase(tmpdir)
    #test_export_by_distance(tmpdir)
    #test_export_by_location(tmpdir)
    #test_intersect(tmpdir)
    #test_join_by_location(tmpdir)
    #test_select_two_layers(tmpdir)
    #test_split(tmpdir)
    test_union(tmpdir)
    