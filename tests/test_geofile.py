# -*- coding: utf-8 -*-
"""
Tests for functionalities in geofileops.general.
"""

from pathlib import Path
import sys
from typing import Optional

import geopandas as gpd
import pandas as pd
import shapely.geometry as sh_geom

# Add path so the local geofileops packages are found 
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import geofileops as gfo
from geofileops.util import geoseries_util
from geofileops.util.geometry_util import GeometryType
from geofileops.util import io_util
import test_helper

def test_add_column(tmpdir):
    # First copy test file to tmpdir
    # Now add area column
    src = test_helper.TestFiles.polygons_parcels_gpkg
    tmppath = Path(tmpdir) / src.name
    gfo.copy(src, tmppath)

    # The area column shouldn't be in the test file yet
    layerinfo = gfo.get_layerinfo(path=tmppath, layer='parcels')
    assert 'AREA' not in layerinfo.columns
        
    ### Add area column ###
    #with test_helper.GdalBin(gdal_installation='gdal_default'):
    gfo.add_column(tmppath, layer='parcels', name='AREA', type='real', 
            expression='ST_area(geom)')
        
    layerinfo = gfo.get_layerinfo(path=tmppath, layer='parcels')
    assert 'AREA' in layerinfo.columns
    
    gdf = gfo.read_file(tmppath)
    assert round(gdf['AREA'].astype('float')[0], 1) == round(gdf['OPPERVL'].astype('float')[0], 1)

    ### Add perimeter column ###
    #with test_helper.GdalBin(gdal_installation='gdal_default'):
    gfo.add_column(tmppath, layer='parcels', name='PERIMETER', type=gfo.DataType.REAL, 
            expression='ST_perimeter(geom)')
        
    layerinfo = gfo.get_layerinfo(path=tmppath, layer='parcels')
    assert 'AREA' in layerinfo.columns
    
    gdf = gfo.read_file(tmppath)
    assert round(gdf['AREA'].astype('float')[0], 1) == round(gdf['OPPERVL'].astype('float')[0], 1)

def test_cmp(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    for suffix in test_helper.get_test_suffix_list():
        # If test input file is in wrong format, convert it
        src = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_parcels_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)
        src2 = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_invalid_geometries_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)
        
        # Copy test file to tmpdir
        dst = Path(tmpdir) / f"polygons_parcels_output{suffix}"
        gfo.copy(src, dst)

        # Now compare source and dst files
        assert gfo.cmp(src, dst) == True
        assert gfo.cmp(src2, dst) == False

def test_convert(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    for suffix in test_helper.get_test_suffix_list():
        # If test input file is in wrong format, convert it
        src = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_parcels_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)
        
        # Convert
        dst = Path(tmpdir) / f"polygons_parcels_output{suffix}"
        gfo.convert(src, dst)

        # Now compare source and dst file 
        src_layerinfo = gfo.get_layerinfo(src)
        dst_layerinfo = gfo.get_layerinfo(dst)
        assert src_layerinfo.featurecount == dst_layerinfo.featurecount
        assert len(src_layerinfo.columns) == len(dst_layerinfo.columns)

def test_convert_force_output_geometrytype(tmpdir):
    # The conversion is done by ogr, and these test are just written to explore
    # the behaviour of this ogr functionality 
    
    # Convert polygon test file and force to polygon
    src = test_helper.TestFiles.polygons_parcels_gpkg
    dst = Path(tmpdir) / 'polygons_parcels_to_polygon.gpkg'
    gfo.convert(src, dst, force_output_geometrytype=GeometryType.POLYGON)

    # Convert polygon test file and force to multipolygon
    src = test_helper.TestFiles.polygons_parcels_gpkg
    dst = Path(tmpdir) / 'polygons_parcels_to_multipolygon.gpkg'
    gfo.convert(src, dst, force_output_geometrytype=GeometryType.MULTIPOLYGON)

    # Convert polygon test file and force to linestring
    src = test_helper.TestFiles.polygons_parcels_gpkg
    dst = Path(tmpdir) / 'polygons_parcels_to_linestring.gpkg'
    gfo.convert(src, dst, force_output_geometrytype=GeometryType.LINESTRING)

    # Convert polygon test file and force to multilinestring
    src = test_helper.TestFiles.polygons_parcels_gpkg
    dst = Path(tmpdir) / 'polygons_parcels_to_multilinestring.gpkg'
    gfo.convert(src, dst, force_output_geometrytype=GeometryType.MULTILINESTRING)

    # Convert polygon test file and force to point
    src = test_helper.TestFiles.polygons_parcels_gpkg
    dst = Path(tmpdir) / 'polygons_parcels_to_point.gpkg'
    gfo.convert(src, dst, force_output_geometrytype=GeometryType.POINT)

    # Convert polygon test file and force to multipoint
    src = test_helper.TestFiles.polygons_parcels_gpkg
    dst = Path(tmpdir) / 'polygons_parcels_to_point.gpkg'
    gfo.convert(src, dst, force_output_geometrytype=GeometryType.MULTIPOINT)

def test_copy(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    for suffix in test_helper.get_test_suffix_list():
        # If test input file is in wrong format, convert it
        src = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_parcels_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)
        
        # Copy to dest file
        dst = Path(tmpdir) / f"polygons_parcels_output{suffix}"
        gfo.copy(src, dst)
        assert src.exists() == True
        assert dst.exists() == True
        if suffix == ".shp":
            assert dst.with_suffix(".shx").exists() == True

        # Copy to dest dir
        dst_dir = Path(tmpdir) / "dest_dir"
        dst_dir.mkdir(parents=True, exist_ok=True)
        gfo.copy(src, dst_dir)
        dst = dst_dir / src.name
        assert src.exists() == True
        assert dst.exists() == True
        if suffix == ".shp":
            assert dst.with_suffix(".shx").exists() == True

def test_driver_enum():
    ### Test ESRIShapefile Driver ###
    # Test getting a driver for a suffix 
    geofiletype = gfo.GeofileType('.shp')
    assert geofiletype == gfo.GeofileType.ESRIShapefile

    # Test getting a driver for a Path
    path = Path("/testje/path_naar_gfo.sHp") 
    geofiletype = gfo.GeofileType(path)
    assert geofiletype == gfo.GeofileType.ESRIShapefile

    ### GPKG Driver ###
    # Test getting a driver for a suffix 
    geofiletype = gfo.GeofileType('.gpkg')
    assert geofiletype == gfo.GeofileType.GPKG

    # Test getting a driver for a Path
    path = Path("/testje/path_naar_gfo.gPkG") 
    geofiletype = gfo.GeofileType(path)
    assert geofiletype == gfo.GeofileType.GPKG

    ### SQLite Driver ###
    # Test getting a driver for a suffix 
    geofiletype = gfo.GeofileType('.sqlite')
    assert geofiletype == gfo.GeofileType.SQLite

    # Test getting a driver for a Path
    path = Path("/testje/path_naar_gfo.sQlItE") 
    geofiletype = gfo.GeofileType(path)
    assert geofiletype == gfo.GeofileType.SQLite

def test_get_crs(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    for suffix in test_helper.get_test_suffix_list():
        # If test input file is in wrong format, convert it
        src = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_parcels_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)
        crs = gfo.get_crs(src)
        assert crs.to_epsg() == 31370
        
def test_get_default_layer(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    for suffix in test_helper.get_test_suffix_list():
        # If test input file is in wrong format, convert it
        src = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_parcels_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)
        layer = gfo.get_default_layer(src)
        assert layer == 'polygons_parcels-2020'

def test_get_layerinfo(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    for suffix in test_helper.get_test_suffix_list():
        # If test input file is in wrong format, convert it
        src = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_parcels_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)
                
        basetest_get_layerinfo(src=src)
        
    # Test geopackage, two layers
    basetest_get_layerinfo(
            src=test_helper.TestFiles.polygons_twolayers_gpkg, 
            layer='parcels')

def basetest_get_layerinfo(
        src: Path, 
        layer: Optional[str] = None):

    ### Tests on layer specified ###
    layerinfo = gfo.get_layerinfo(src, layer)
    assert str(layerinfo).startswith("<class 'geofileops.file.LayerInfo'>")
    assert layerinfo.featurecount == 46
    if src.suffix == '.shp':
        assert layerinfo.geometrycolumn == 'geometry'
        assert layerinfo.name == src.stem
    elif src.suffix == '.gpkg':
        assert layerinfo.geometrycolumn == 'geom'
        assert layerinfo.name == 'parcels'
    assert layerinfo.geometrytypename == gfo.GeometryType.MULTIPOLYGON.name
    assert layerinfo.geometrytype == gfo.GeometryType.MULTIPOLYGON
    assert len(layerinfo.columns) == 10
    assert layerinfo.total_bounds is not None
    assert layerinfo.crs is not None
    assert layerinfo.crs.to_epsg() == 31370

    ### Some tests for exception cases ###
    # Layer specified that doesn't exist
    try:
        layerinfo = gfo.get_layerinfo(src, "not_existing_layer")
        exception_raised = False
    except ValueError:
        exception_raised = True
    assert exception_raised is True

    # Path specified that doesn't exist
    try:
        not_existing_path = io_util.with_stem(src, "not_existing_layer")
        layerinfo = gfo.get_layerinfo(not_existing_path)
        exception_raised = False
    except ValueError:
        exception_raised = True
    assert exception_raised is True

    # Multiple layers available, but no layer specified
    if len(gfo.listlayers(src)) > 1:
        try:
            layerinfo = gfo.get_layerinfo(src)
            exception_raised = False
        except ValueError:
            exception_raised = True
        assert exception_raised is True

def test_get_only_layer(tmpdir):
    ### Test file with 1 layer ###
    # Prepare test data + run tests for one layer
    tmp_dir = Path(tmpdir)
    for suffix in test_helper.get_test_suffix_list():
        # If test input file is in wrong format, convert it
        src = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_parcels_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)

        layer = gfo.get_only_layer(src)
        if suffix == ".gpkg":
            assert layer == 'parcels'
        elif suffix == ".shp":
            assert layer == src.stem
        else:
            raise Exception(f"test not implemented for suffix {suffix}")

    ### Test Geopackage with 2 layers ###
    srcpath = test_helper.TestFiles.polygons_twolayers_gpkg
    layers = gfo.listlayers(srcpath)
    assert len(layers) == 2
    error_raised = False
    try:
        layer = gfo.get_only_layer(srcpath)
    except:
        error_raised = True
    assert error_raised is True

def test_is_geofile():
    assert gfo.is_geofile(test_helper.TestFiles.polygons_parcels_gpkg) == True
    assert gfo.is_geofile(test_helper.TestFiles.polygons_parcels_gpkg.with_suffix(".shp")) == True
    
    assert gfo.is_geofile("/test/testje.txt") == False
    
def test_listlayers(tmpdir):
    # Prepare test data + run tests for one layer
    tmp_dir = Path(tmpdir)
    for suffix in test_helper.get_test_suffix_list():
        # If test input file is in wrong format, convert it
        src = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_parcels_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)
        layers = gfo.listlayers(src)
    
        if suffix == ".gpkg":
            assert layers[0] == "parcels"
        elif suffix == ".shp":
            assert layers[0] == src.stem
        else:
            raise Exception(f"test not implemented for suffix {suffix}")

    # Test geopackage 2 layers
    layers = gfo.listlayers(test_helper.TestFiles.polygons_twolayers_gpkg)
    assert 'parcels' in layers
    assert 'zones' in layers

def test_move(tmpdir):
    # Prepare test data + run tests
    tmp_dir = Path(tmpdir)
    for suffix in test_helper.get_test_suffix_list():
        # Test move to dest file
        src = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_parcels_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)
        dst = Path(tmpdir) / f"polygons_parcels_output{suffix}"
        gfo.move(src, dst)
        assert src.exists() == False
        assert dst.exists() == True
        if suffix == ".shp":
            assert dst.with_suffix(".shx").exists() == True

        # Test move to dest dir
        src = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_parcels_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)
        dst_dir = Path(tmpdir) / "dest_dir"
        dst_dir.mkdir(parents=True, exist_ok=True)
        gfo.move(src, dst_dir)
        dst = dst_dir / src.name
        assert src.exists() == False
        assert dst.exists() == True
        if suffix == ".shp":
            assert dst.with_suffix(".shx").exists() == True

def test_update_column(tmpdir):
    # First copy test file to tmpdir
    # Now add area column
    src = test_helper.TestFiles.polygons_parcels_gpkg
    tmppath = Path(tmpdir) / 'polygons_parcels.gpkg'
    gfo.copy(src, tmppath)

    # The area column shouldn't be in the test file yet
    layerinfo = gfo.get_layerinfo(path=tmppath, layer='parcels')
    assert 'area' not in layerinfo.columns
        
    ### Add + update  area column ###
    #with test_helper.GdalBin(gdal_installation='gdal_default'):
    gfo.add_column(tmppath, layer='parcels', name='AREA', type='real', expression='ST_area(geom)')
    gfo.update_column(tmppath, name='AreA', expression='ST_area(geom)')

    layerinfo = gfo.get_layerinfo(path=tmppath, layer='parcels')
    assert 'AREA' in layerinfo.columns
    gdf = gfo.read_file(tmppath)
    assert round(gdf['AREA'].astype('float')[0], 1) == round(gdf['OPPERVL'].astype('float')[0], 1)

    ### Update column for rows where area > 5 ###
    gfo.update_column(tmppath, name="AreA", expression="-1", where="area > 4000")
    gdf = gfo.read_file(tmppath)
    gdf_filtered = gdf[gdf["AREA"] == -1]
    assert len(gdf_filtered) == 20

    ### Trying to remove column that doesn't exist should raise ValueError ###
    assert "not_existing column" not in layerinfo.columns
    try:
        gfo.update_column(tmppath, name="not_existing column", expression="ST_area(geom)")
        exception_raised = False
    except ValueError:
        exception_raised = True
    assert exception_raised is True

def test_read_file(tmpdir):
    # Prepare test data + run tests for one layer
    tmp_dir = Path(tmpdir)
    for suffix in test_helper.get_test_suffix_list():
        # If test input file is in wrong format, convert it
        src = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_parcels_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)

        basetest_read_file(srcpath=src)

def basetest_read_file(srcpath: Path):
    # Test with defaults
    read_gdf = gfo.read_file(srcpath)
    assert isinstance(read_gdf, gpd.GeoDataFrame)
    assert len(read_gdf) == 46

    # Test no columns
    read_gdf = gfo.read_file(srcpath, columns=[])
    assert isinstance(read_gdf, gpd.GeoDataFrame)
    assert len(read_gdf) == 46

    # Test specific columns (+ test case insensitivity)
    columns = ['OIDN', 'uidn', 'HFDTLT', 'lblhfdtlt', 'GEWASGROEP', 'lengte', 'OPPERVL']
    read_gdf = gfo.read_file(srcpath, columns=columns)
    assert len(read_gdf) == 46
    assert len(read_gdf.columns) == (len(columns) + 1)

    # Test no geom
    read_gdf = gfo.read_file_nogeom(srcpath)
    assert isinstance(read_gdf, pd.DataFrame)
    assert len(read_gdf) == 46

    # Test ignore_geometry, no columns
    read_gdf = gfo.read_file_nogeom(srcpath, columns=[])
    assert isinstance(read_gdf, pd.DataFrame)
    assert len(read_gdf) == 46

def test_rename_column(tmpdir):
    # Prepare test data + run tests for one layer
    tmp_dir = Path(tmpdir)
    for suffix in test_helper.get_test_suffix_list():
        # If test input file is in wrong format, convert it
        test_path = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_parcels_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)
        
        # Check if input file is ok
        orig_layerinfo = gfo.get_layerinfo(test_path)
        assert "OPPERVL" in orig_layerinfo.columns
        assert "area" not in orig_layerinfo.columns

        # Rename
        try:
            gfo.rename_column(test_path, "OPPERVL", "area")
            exception_raised = False
        except:
            exception_raised = True
        
        # Check if the result was expected
        if test_path.suffix == ".shp":
            # For shapefiles, columns cannot be renamed 
            assert exception_raised is True
        else:
            # For file types that support rename, check if it worked
            assert exception_raised is False
            result_layerinfo = gfo.get_layerinfo(test_path)
            assert "OPPERVL" not in result_layerinfo.columns
            assert "area" in result_layerinfo.columns

def test_rename_layer(tmpdir):
    # Prepare test data + run tests for one layer
    tmp_dir = Path(tmpdir)
    for suffix in test_helper.get_test_suffix_list():
        # If test input file is in wrong format, convert it
        src = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_parcels_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)
    
        if suffix == ".gpkg":
            gfo.rename_layer(src, layer="parcels", new_layer="parcels_renamed")
            layernames_renamed = gfo.listlayers(path=src)
            assert layernames_renamed[0] == "parcels_renamed"

        elif suffix == ".shp":
            # Now test rename layer
            try:
                gfo.rename_layer(
                        src, 
                        layer="polygons_parcels", 
                        new_layer="polygons_parcels_renamed")
                layernames_renamed = gfo.listlayers(path=src)
                assert layernames_renamed[0] == "polygons_parcels_renamed"
            except Exception as ex:
                assert "rename_layer is not possible" in str(ex) 
        else:
            raise Exception(f"test not implemented for suffix {suffix}")
    
def test_execute_sql(tmpdir):
    # First copy test file to tmpdir
    src = test_helper.TestFiles.polygons_parcels_gpkg
    tmppath = Path(tmpdir) / 'polygons_parcels.gpkg'
    gfo.copy(src, tmppath)

    ### Test using execute_sql for creating/dropping indexes ###
    # Create index
    gfo.execute_sql(path=tmppath, sql_stmt='CREATE INDEX idx_parcels_oidn ON "parcels"("oidn")')

    # Drop index
    gfo.execute_sql(path=tmppath, sql_stmt='DROP INDEX idx_parcels_oidn')

def test_spatial_index(tmpdir):
    # Prepare test data + run tests for one layer
    tmp_dir = Path(tmpdir)
    for suffix in test_helper.get_test_suffix_list():
        # If test input file is in wrong format, convert it
        src = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_parcels_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)
    
        # Check if spatial index present:
        layer = gfo.get_only_layer(src)
        has_spatial_index = gfo.has_spatial_index(path=src, layer=layer)
        assert has_spatial_index is True

        # Remove spatial index
        gfo.remove_spatial_index(path=src, layer=layer)
        has_spatial_index = gfo.has_spatial_index(path=src, layer=layer)
        assert has_spatial_index is False

        # Create spatial index
        gfo.create_spatial_index(path=src, layer=layer)
        has_spatial_index = gfo.has_spatial_index(path=src, layer=layer)
        assert has_spatial_index is True

def test_to_file(tmpdir):
    # Prepare test data + run tests for one layer
    tmp_dir = Path(tmpdir)
    for suffix in test_helper.get_test_suffix_list():
        # If test input file is in wrong format, convert it
        input_path = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_parcels_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)
        output_path = io_util.with_stem(input_path, f"{input_path}-output")
        basetest_to_file(input_path, output_path)

def basetest_to_file(srcpath, tmppath):
    # Read test file and write to tmppath
    read_gdf = gfo.read_file(srcpath)
    gfo.to_file(read_gdf, tmppath)
    tmp_gdf = gfo.read_file(tmppath)
    assert len(read_gdf) == len(tmp_gdf)

    # Append the file again to tmppath
    gfo.to_file(read_gdf, tmppath, append=True)
    tmp_gdf = gfo.read_file(tmppath)
    assert 2*len(read_gdf) == len(tmp_gdf)

def test_to_file_empty(tmpdir):
    # Prepare test data + run tests for one layer
    tmp_dir = Path(tmpdir)
    for suffix in test_helper.get_test_suffix_list():
        # If test input file is in wrong format, convert it
        input_path = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_parcels_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)
        basetest_to_file_empty(input_path, tmp_dir, suffix)

def basetest_to_file_empty(
        srcpath: Path, 
        output_dir: Path,
        output_suffix: str):
    ### Test for gdf with a None geometry + a polygon ###
    test_gdf = gpd.GeoDataFrame(geometry=[
            None, test_helper.TestData.polygon_with_island])
    test_geometrytypes = geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_geometrytypes) == 1
    output_none_path = output_dir / f"{srcpath.stem}_none{output_suffix}"
    gfo.to_file(test_gdf, output_none_path)
    
    # Now check the result if the data is still the same after being read again
    test_read_gdf = gfo.read_file(output_none_path)
    # Result is the same as the original input
    assert test_read_gdf.geometry[0] is None
    assert isinstance(test_read_gdf.geometry[1], sh_geom.Polygon)  
    # The geometrytype of the column in the file is also the same as originaly
    test_file_geometrytype = gfo.get_layerinfo(output_none_path).geometrytype
    if output_suffix == '.shp':
        assert test_file_geometrytype == GeometryType.MULTIPOLYGON
    else:
        assert test_file_geometrytype == test_geometrytypes[0]
    # The result type in the geodataframe is also the same as originaly
    test_read_geometrytypes = geoseries_util.get_geometrytypes(test_read_gdf.geometry)
    assert len(test_gdf) == len(test_read_gdf)
    assert test_read_geometrytypes == test_geometrytypes

def test_to_file_none(tmpdir):
    # Prepare test data + run tests for one layer
    tmp_dir = Path(tmpdir)
    for suffix in test_helper.get_test_suffix_list():
        # If test input file is in wrong format, convert it
        input_path = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_parcels_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)
        basetest_to_file_none(input_path, tmp_dir, suffix)

def basetest_to_file_none(
        srcpath: Path, 
        output_dir: Path,
        output_suffix: str):
    ### Test for gdf with a None geometry + a polygon ###
    test_gdf = gpd.GeoDataFrame(geometry=[
            None, test_helper.TestData.polygon_with_island])
    test_geometrytypes = geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_geometrytypes) == 1
    output_none_path = output_dir / f"{srcpath.stem}_none{output_suffix}"
    gfo.to_file(test_gdf, output_none_path)
    
    # Now check the result if the data is still the same after being read again
    test_read_gdf = gfo.read_file(output_none_path)
    # Result is the same as the original input
    assert test_read_gdf.geometry[0] is None
    assert isinstance(test_read_gdf.geometry[1], sh_geom.Polygon)  
    # The geometrytype of the column in the file is also the same as originaly
    test_file_geometrytype = gfo.get_layerinfo(output_none_path).geometrytype
    if output_suffix == '.shp':
        assert test_file_geometrytype == GeometryType.MULTIPOLYGON
    else:
        assert test_file_geometrytype == test_geometrytypes[0]
    # The result type in the geodataframe is also the same as originaly
    test_read_geometrytypes = geoseries_util.get_geometrytypes(test_read_gdf.geometry)
    assert len(test_gdf) == len(test_read_gdf)
    assert test_read_geometrytypes == test_geometrytypes

def test_to_file_gpd_empty(tmpdir):
    # Prepare test data + run tests for one layer
    tmp_dir = Path(tmpdir)
    for suffix in test_helper.get_test_suffix_list():
        # If test input file is in wrong format, convert it
        input_path = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_parcels_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)
        basetest_to_file_gpd_empty(input_path, tmp_dir, suffix)

def basetest_to_file_gpd_empty(
        srcpath: Path, 
        output_dir: Path,
        output_suffix: str):
    ### Test for gdf with an empty polygon + a polygon ###
    test_gdf = gpd.GeoDataFrame(geometry=[
            sh_geom.Polygon(), test_helper.TestData.polygon_with_island])
    # By default, get_geometrytypes ignores the type of empty geometries, as 
    # they are always stored as GeometryCollection in GeoPandas
    test_geometrytypes = geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_geometrytypes) == 1
    test_geometrytypes_includingempty = geoseries_util.get_geometrytypes(
            test_gdf.geometry, ignore_empty_geometries=False)
    assert len(test_geometrytypes_includingempty) == 2
    output_empty_path = output_dir / f"{srcpath.stem}_empty{output_suffix}"
    test_gdf.to_file(output_empty_path, driver=gfo.GeofileType(output_suffix).ogrdriver)
    
    # Now check the result if the data is still the same after being read again
    test_read_gdf = gfo.read_file(output_empty_path)
    test_read_geometrytypes = geoseries_util.get_geometrytypes(test_read_gdf.geometry)
    assert len(test_gdf) == len(test_read_gdf)
    if output_suffix == '.shp':
        # When dataframe with "empty" gemetries is written to shapefile and 
        # read again, shapefile becomes of type MULTILINESTRING!?!
        assert len(test_read_geometrytypes) == 1
        assert test_read_geometrytypes[0] is GeometryType.MULTILINESTRING
    else:
        # When written to Geopackage... the empty geometries are actually saved 
        # as None, so when read again they are None as well.
        assert test_read_gdf.geometry[0] is None
        assert isinstance(test_read_gdf.geometry[1], sh_geom.Polygon)  

        # So the geometrytype of the resulting GeoDataFrame is also POLYGON
        assert len(test_read_geometrytypes) == 1
        assert test_read_geometrytypes[0] is GeometryType.POLYGON

def test_to_file_gpd_none(tmpdir):
    # Prepare test data + run tests for one layer
    tmp_dir = Path(tmpdir)
    for suffix in test_helper.get_test_suffix_list():
        # If test input file is in wrong format, convert it
        input_path = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_parcels_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)
        basetest_to_file_gpd_none(input_path, tmp_dir, suffix)

def basetest_to_file_gpd_none(
        input_path: Path, 
        output_dir: Path,
        output_suffix: str):
    ### Test for gdf with a None geometry + a polygon ###
    test_gdf = gpd.GeoDataFrame(geometry=[
            None, test_helper.TestData.polygon_with_island])
    test_geometrytypes = geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_geometrytypes) == 1
    output_none_path = output_dir / f"{input_path.stem}_none{output_suffix}"
    test_gdf.to_file(output_none_path, driver=gfo.GeofileType(output_suffix).ogrdriver)
    
    # Now check the result if the data is still the same after being read again
    test_read_gdf = gfo.read_file(output_none_path)
    # Result is the same as the original input
    assert test_read_gdf.geometry[0] is None
    assert isinstance(test_read_gdf.geometry[1], sh_geom.Polygon)  
    # The geometrytype of the column in the file is also the same as originaly
    test_file_geometrytype = gfo.get_layerinfo(output_none_path).geometrytype
    if output_suffix == '.shp':
        # Geometrytype of shapefile always returns the multitype  
        assert test_file_geometrytype == test_geometrytypes[0].to_multitype
    else:
        assert test_file_geometrytype == test_geometrytypes[0]
    # The result type in the geodataframe is also the same as originaly
    test_read_geometrytypes = geoseries_util.get_geometrytypes(test_read_gdf.geometry)
    assert len(test_gdf) == len(test_read_gdf)
    assert test_read_geometrytypes == test_geometrytypes

def test_remove(tmpdir):
    # Prepare test data + run tests for one layer
    tmp_dir = Path(tmpdir)
    for suffix in test_helper.get_test_suffix_list():
        # If test input file is in wrong format, convert it
        input_path = test_helper.prepare_test_file(
                path=test_helper.TestFiles.polygons_parcels_gpkg,
                tmp_dir=tmp_dir,
                suffix=suffix)
        assert input_path.exists() == True

        # Remove and check result
        gfo.remove(input_path)
        assert input_path.exists() == False

if __name__ == '__main__':
    # Init
    tmpdir = test_helper.init_test_for_debug(Path(__file__).stem)

    # Run!
    #test_convert(tmpdir)
    #test_convert_force_output_geometrytype(tmpdir)
    test_get_layerinfo(tmpdir)
    #test_get_only_layer(tmpdir)
    #test_rename_column(tmpdir)
    #test_rename_layer(tmpdir)
    #test_listlayers()
    #test_add_column(tmpdir)
    #test_execute_sql(tmpdir)
    #test_read_file()
    #test_copy(tmpdir)
    #test_move(tmpdir)
    #test_spatial_index(tmpdir)
    #test_to_file_gpkg(tmpdir)
    #test_to_file_shp(tmpdir)
    #test_to_file_empty_gpkg(tmpdir)
    #test_to_file_empty_shp(tmpdir)
    #test_to_file_none_gpkg(tmpdir)
    #test_to_file_none_shp(tmpdir)
    #test_update_column(tmpdir)
