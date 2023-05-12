# -*- coding: utf-8 -*-
"""
Tests for functionalities in geofileops.general.
"""

from pathlib import Path

from geofileops.util.geofiletype import GeofileType


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
