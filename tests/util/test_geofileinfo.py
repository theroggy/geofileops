"""
Tests for functionalities in geofiletype.
"""

from pathlib import Path

import pytest

import geofileops as gfo
from geofileops.util import _geofileinfo
from geofileops.util._geofileinfo import GeofileType
from tests import test_helper


def test_geofiletype_enum():
    # Test ESRIShapefile geofiletype
    # Test getting a geofiletype for a suffix
    assert GeofileType(".shp") == GeofileType.ESRIShapefile
    assert GeofileType(".shp").ogrdriver == "ESRI Shapefile"

    # Test getting a geofiletype for a Path (case insensitive)
    path = Path("/testje/path_naar_file.sHp")
    assert GeofileType(path) == GeofileType.ESRIShapefile

    # Test getting a geofiletype for an ogr driver
    assert GeofileType("ESRI Shapefile") == GeofileType.ESRIShapefile

    # GPKG geofiletype
    # Test getting a geofiletype for a suffix
    assert GeofileType(".gpkg") == GeofileType.GPKG
    assert GeofileType(".gpkg").ogrdriver == "GPKG"

    # Test getting a geofiletype for a Path (case insensitive)
    path = Path("/testje/path_naar_file.gPkG")
    assert GeofileType(path) == GeofileType.GPKG

    # Test getting a geofiletype for an ogr driver
    assert GeofileType("GPKG") == GeofileType.GPKG

    # SQLite geofiletype
    # Test getting a geofiletype for a suffix
    assert GeofileType(".sqlite") == GeofileType.SQLite

    # Test getting a geofiletype for a Path (case insensitive)
    path = Path("/testje/path_naar_file.sQlItE")
    assert GeofileType(path) == GeofileType.SQLite

    # Test getting a geofiletype for an ogr driver
    assert GeofileType("SQLite") == GeofileType.SQLite


@pytest.mark.parametrize(
    "test_type",
    ["EXISTING_FILE_VALID", "EXISTING_FILE_EMPTY", "NON_EXISTING_FILE", "SUFFIX"],
)
@pytest.mark.parametrize(
    "suffix, path_prefix, exp_driver",
    [
        (".gpkg", None, "GPKG"),
        (".GPKG", None, "GPKG"),
        (".gpkg", "GPKG:", "GPKG"),
        (".shp", None, "ESRI Shapefile"),
        (".csv", None, "CSV"),
        (".kml", None, "LIBKML"),
        (".kml", "LIBKML:", "LIBKML"),
        (".kml", "KML:", "KML"),
    ],
)
@pytest.mark.filterwarnings("ignore:Target SRS BD72 / Belgian Lambert 72 not taken")
@pytest.mark.filterwarnings("ignore:Empty multi geometry are not recommended")
def test_get_driver(tmp_path, test_type, suffix, path_prefix, exp_driver):
    """Get a driver."""
    if test_type == "EXISTING_FILE_EMPTY" and suffix == ".kml":
        pytest.xfail("Getting the driver of an empty .kml file seems to fail.")
    if test_type == "SUFFIX" and path_prefix is not None:
        pytest.skip("A path prefix is not supported for just a suffix.")

    # Prepare test data
    if test_type == "EXISTING_FILE_VALID":
        test_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    elif test_type == "EXISTING_FILE_EMPTY":
        test_path = tmp_path / f"test_invalid{suffix}"
        test_path.touch()
    elif test_type == "NON_EXISTING_FILE":
        test_path = tmp_path / f"test_unexisting{suffix}"
    elif test_type == "SUFFIX":
        test_path = suffix
    else:
        raise ValueError(f"Unsupported test_type: {test_type}")

    if path_prefix is not None:
        test_path = f"{path_prefix}{test_path.as_posix()}"

    # Run the test
    if suffix == ".kml" and test_type != "EXISTING_FILE_VALID" and path_prefix is None:
        # There are multiple drivers for .kml, so a warning is expected
        with pytest.warns(
            UserWarning, match="Multiple drivers found, using first one of"
        ):
            assert gfo.get_driver(test_path) == exp_driver
    else:
        assert gfo.get_driver(test_path) == exp_driver


def test_get_driver_unsupported_suffix():
    with pytest.raises(ValueError, match="Could not infer driver from path"):
        gfo.get_driver(".unsupported")


def test_get_driver_unsupported_suffix_driverprefix(tmp_path):
    csv_path = test_helper.get_testfile(
        "polygon-parcel", suffix=".csv", dst_dir=tmp_path
    )
    unsupported_path = tmp_path / f"{csv_path.stem}.unsupported"
    csv_path.rename(unsupported_path)
    assert gfo.get_driver(f"CSV:{unsupported_path}") == "CSV"


@pytest.mark.parametrize(
    "suffix, exp_driver, exp_is_fid_zerobased, exp_is_singlelayer, "
    "exp_is_spatialite_based",
    [
        (".shp", "ESRI Shapefile", True, True, False),
        (".gpkg", "GPKG", False, False, True),
        (".gpKG", "GPKG", False, False, True),
        (".sqlite", "SQLite", False, False, True),
        (".csv", "CSV", False, True, False),
    ],
)
def test_get_geofileinfo_for_suffix(
    suffix,
    exp_driver,
    exp_is_fid_zerobased,
    exp_is_singlelayer,
    exp_is_spatialite_based,
):
    """Test getting a geofiletype for some common suffixes."""
    info = _geofileinfo.get_geofileinfo(suffix)
    assert info.driver == exp_driver
    assert info.is_fid_zerobased == exp_is_fid_zerobased
    assert info.is_singlelayer == exp_is_singlelayer
    assert info.is_spatialite_based == exp_is_spatialite_based


def test_get_geofileinfo_for_vsi():
    """Test getting a geofiletype for a VSI path."""
    vsi_path = f"/vsizip/vsicurl/{test_helper.data_url}/poly_shp.zip"
    info = _geofileinfo.get_geofileinfo(vsi_path)
    assert info.driver == "ESRI Shapefile"
    assert info.is_fid_zerobased is True
    assert info.is_singlelayer is True
    assert info.is_spatialite_based is False
