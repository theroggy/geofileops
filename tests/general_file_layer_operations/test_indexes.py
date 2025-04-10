"""Tests regarding spatial indexes in/on data sources."""

import pytest
from osgeo import gdal

import geofileops as gfo
from geofileops import fileops
from geofileops.util._geofileinfo import GeofileInfo
from tests import test_helper
from tests.test_helper import SUFFIXES_FILEOPS


@pytest.mark.parametrize("suffix", [s for s in SUFFIXES_FILEOPS if s != ".csv"])
@pytest.mark.parametrize("read_only", [True, False])
def test_create_spatial_index(tmp_path, suffix, read_only):
    test_path = test_helper.get_testfile(
        "polygon-parcel", dst_dir=tmp_path, suffix=suffix, read_only=read_only
    )
    layer = gfo.get_only_layer(test_path)
    default_spatial_index = GeofileInfo(test_path).default_spatial_index

    # Check if spatial index present
    has_spatial_index = gfo.has_spatial_index(path=test_path, layer=layer)
    assert has_spatial_index is default_spatial_index

    # Set read-write for initialisation
    test_helper.set_read_only(test_path, False)

    # Remove spatial index
    gfo.remove_spatial_index(path=test_path, layer=layer)
    has_spatial_index = gfo.has_spatial_index(path=test_path, layer=layer)
    assert has_spatial_index is False

    # Set read-only status before testing create_spatial_index
    test_helper.set_read_only(test_path, read_only)

    if read_only:
        with pytest.raises(RuntimeError, match="create_spatial_index error"):
            gfo.create_spatial_index(path=test_path, layer=layer)
    else:
        # Create spatial index
        gfo.create_spatial_index(path=test_path, layer=layer)
        has_spatial_index = gfo.has_spatial_index(path=test_path, layer=layer)
        assert has_spatial_index is True

        # Spatial index if it already exists by default gives error
        with pytest.raises(Exception, match="spatial index already exists"):
            gfo.create_spatial_index(path=test_path, layer=layer)
        gfo.create_spatial_index(path=test_path, layer=layer, exist_ok=True)


@pytest.mark.parametrize("suffix", [s for s in SUFFIXES_FILEOPS if s != ".csv"])
@pytest.mark.parametrize("read_only", [True, False])
def test_create_spatial_index_force_rebuild(tmp_path, suffix, read_only):
    test_path = test_helper.get_testfile(
        "polygon-parcel", dst_dir=tmp_path, suffix=suffix, read_only=read_only
    )
    # Set read-write for initialisation
    test_helper.set_read_only(test_path, False)
    gfo.create_spatial_index(path=test_path, exist_ok=True)
    # Set read-only status before testing create_spatial_index
    test_helper.set_read_only(test_path, read_only)

    if suffix == ".shp":
        # Shapefile doesn't have a spatial index by default
        # Test of rebuild on shp can be checked on the files created/changed
        qix_path = test_path.with_suffix(".qix")
        qix_modified_time_orig = qix_path.stat().st_mtime
        gfo.create_spatial_index(path=test_path, exist_ok=True)
        assert qix_path.stat().st_mtime == qix_modified_time_orig
        if read_only:
            with pytest.raises(RuntimeError, match="create_spatial_index error"):
                gfo.create_spatial_index(path=test_path, force_rebuild=True)
        else:
            gfo.create_spatial_index(path=test_path, force_rebuild=True)
            assert qix_path.stat().st_mtime > qix_modified_time_orig

    elif suffix == ".gpkg":
        has_spatial_index = gfo.has_spatial_index(path=test_path)
        assert has_spatial_index is True
        if read_only:
            with pytest.raises(RuntimeError, match="create_spatial_index error"):
                gfo.create_spatial_index(path=test_path, force_rebuild=True)
        else:
            gfo.create_spatial_index(path=test_path, force_rebuild=True)
            has_spatial_index = gfo.has_spatial_index(path=test_path)
            assert has_spatial_index is True


def test_create_spatial_index_gpkg_zip(tmp_path):
    """Spatial index tests are specific for .gpkg.zip as it is read-only."""
    # Test cases where the input file has an index
    # --------------------------------------------
    test_path = test_helper.get_testfile(
        "polygon-parcel", dst_dir=tmp_path, suffix=".gpkg.zip"
    )
    layer = gfo.get_only_layer(test_path)

    # Check if spatial index present
    has_spatial_index = gfo.has_spatial_index(path=test_path, layer=layer)
    assert has_spatial_index is True

    # Removing spatial index in not supported as .gpkg.zip is read-only
    with pytest.raises(RuntimeError, match="remove_spatial_index error"):
        gfo.remove_spatial_index(path=test_path, layer=layer)

    # Create spatial index is supported with `exist_ok=True`
    gfo.create_spatial_index(path=test_path, layer=layer, exist_ok=True)

    # If no `exist_ok=True` is specified, error
    with pytest.raises(RuntimeError, match="spatial index already exists"):
        gfo.create_spatial_index(path=test_path, layer=layer)

    # If  `force_rebuild=True` is specified, error
    with pytest.raises(RuntimeError, match="create_spatial_index error"):
        gfo.create_spatial_index(path=test_path, layer=layer, force_rebuild=True)

    # Test cases where the input file does not have an index
    # ------------------------------------------------------
    # Prepare .gpkg file without spatial index
    test_path = test_helper.get_testfile(
        "polygon-parcel", dst_dir=tmp_path, suffix=".gpkg"
    )
    layer = gfo.get_only_layer(test_path)
    gfo.remove_spatial_index(path=test_path, layer=layer)
    assert not gfo.has_spatial_index(path=test_path, layer=layer)
    test_zip_path = tmp_path / f"{test_path.name}.zip"
    fileops._zip(test_path, test_zip_path)
    assert not gfo.has_spatial_index(path=test_path, layer=layer)

    with pytest.raises(RuntimeError, match="create_spatial_index error"):
        gfo.create_spatial_index(path=test_zip_path, layer=layer)


def test_create_spatial_index_unsupported(tmp_path):
    # Prepare test data
    suffix = ".geojson"
    path = tmp_path / f"unsupported_type{suffix}"
    geojson_data = """{
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [125.6, 10.1]
            },
            "properties": {
                "name": "Dinagat Islands"
            }
        }
    """
    with open(path, "w") as file:
        file.write(geojson_data)

    # Test
    with pytest.raises(
        ValueError, match="create_spatial_index not supported for GeoJSON"
    ):
        _ = gfo.create_spatial_index(path, path.stem)

    with pytest.raises(ValueError, match="has_spatial_index not supported for GeoJSON"):
        _ = gfo.has_spatial_index(path, path.stem)

    with pytest.raises(
        ValueError, match="remove_spatial_index not supported for GeoJSON"
    ):
        _ = gfo.remove_spatial_index(path, path.stem)


def test_create_spatial_index_invalid_params():
    path = test_helper.get_testfile("polygon-parcel")

    # Test invalid parameters
    with pytest.raises(
        ValueError, match="exist_ok and force_rebuild can't both be True"
    ):
        _ = gfo.create_spatial_index(path=path, exist_ok=True, force_rebuild=True)


@pytest.mark.parametrize("suffix", [s for s in SUFFIXES_FILEOPS if s != ".csv"])
def test_has_spatial_index(tmp_path, suffix):
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix, dst_dir=tmp_path)

    # Test
    has_spatial_index = gfo.has_spatial_index(src)
    if GeofileInfo(src).default_spatial_index:
        assert has_spatial_index
    else:
        # File format that doesn't have a spatial index by default
        assert not has_spatial_index
        gfo.create_spatial_index(src)
        assert gfo.has_spatial_index(src)


def test_has_spatial_index_datasource():
    src = test_helper.get_testfile("polygon-parcel")

    # Test
    datasource = gdal.OpenEx(str(src), gdal.OF_VECTOR)
    has_spatial_index = gfo.has_spatial_index(src, datasource=datasource)
    assert has_spatial_index

    assert datasource is not None
    datasource = None


def test_has_spatial_index_no_geom(tmp_path):
    """A geofile without geometry column never has a spatial index."""
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", suffix=".csv")
    test_path = tmp_path / "test_file.dbf"
    gfo.copy_layer(src, test_path)

    # Test
    has_spatial_index = gfo.has_spatial_index(test_path)
    assert not has_spatial_index


@pytest.mark.parametrize("suffix", [".csv"])
def test_has_spatial_index_unsupported(suffix):
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Test
    with pytest.raises(ValueError, match="has_spatial_index not supported for CSV"):
        _ = gfo.has_spatial_index(src)


def test_remove_spatial_index(tmp_path):
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    gfo.create_spatial_index(src, exist_ok=True)
    assert gfo.has_spatial_index(src)

    # Remove spatial index and check result
    gfo.remove_spatial_index(src)
    assert not gfo.has_spatial_index(src)


def test_remove_spatial_index_datasource(tmp_path):
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    gfo.create_spatial_index(src, exist_ok=True)
    assert gfo.has_spatial_index(src)

    # Remove spatial index and check result
    datasource = gdal.OpenEx(str(src), gdal.OF_VECTOR | gdal.OF_UPDATE)
    gfo.remove_spatial_index(src, datasource=datasource)

    # Check result
    assert not gfo.has_spatial_index(src)
    # Datasource should not be closed by has_spatial_index
    assert datasource is not None
    datasource = None
