"""Test for functionalities in _geopath_util."""

from pathlib import Path

import pytest

from geofileops.util._geopath_util import GeoPath


@pytest.mark.parametrize(
    "path, exp_stem",
    [
        (Path("/tmp/testje.gpkg"), "testje"),
        ("/tmp/testje.gpkg.zip", "testje"),
        ("/tmp/testje.shp", "testje"),
        ("/tmp/testje.shp.zip", "testje"),
        ("/tmp/testje.txt", "testje"),
        ("/tmp/testje", "testje"),
        ("/tmp/testje.tar.gz", "testje.tar"),
        ("/tmp/t.estj.e.gpkg", "t.estj.e"),
        ("/tmp/t.estj.e.gpkg.zip", "t.estj.e"),
    ],
)
def test_stem(path, exp_stem):
    assert GeoPath(path).stem == exp_stem


@pytest.mark.parametrize(
    "path, exp_suffix_full, exp_suffix_nozip",
    [
        (Path("/tmp/testje.gpkg"), ".gpkg", ".gpkg"),
        ("/tmp/testje.gpkg.zip", ".gpkg.zip", ".gpkg"),
        ("/tmp/testje.shp", ".shp", ".shp"),
        ("/tmp/testje.shp.zip", ".shp.zip", ".shp"),
        ("/tmp/testje.txt", ".txt", ".txt"),
        ("/tmp/testje", "", ""),
        ("/tmp/testje.tar.gz", ".gz", ".gz"),
        ("/tmp/t.estj.e.gpkg", ".gpkg", ".gpkg"),
        ("/tmp/t.estj.e.gpkg.zip", ".gpkg.zip", ".gpkg"),
    ],
)
def test_suffix(path, exp_suffix_full, exp_suffix_nozip):
    assert GeoPath(path).suffix_full == exp_suffix_full
    assert GeoPath(path).suffix_nozip == exp_suffix_nozip


@pytest.mark.parametrize(
    "path, new_stem, exp_path",
    [
        ("/tmp/testje.gpkg", "testje_2", "/tmp/testje_2.gpkg"),
        ("/tmp/testje.gpkg.zip", "testje_2", "/tmp/testje_2.gpkg.zip"),
        ("/tmp/testje.shp", "testje_2", "/tmp/testje_2.shp"),
        ("/tmp/testje.shp.zip", "testje_2", "/tmp/testje_2.shp.zip"),
        ("/tmp/testje.txt", "testje_2", "/tmp/testje_2.txt"),
        ("/tmp/testje", "testje_2", "/tmp/testje_2"),
        ("/tmp/testje.tar.gz", "testje_2", "/tmp/testje_2.gz"),
        ("/tmp/t.estj.e.gpkg", "t.estj.e_2", "/tmp/t.estj.e_2.gpkg"),
        ("/tmp/t.estj.e.gpkg.zip", "t.estj.e_2", "/tmp/t.estj.e_2.gpkg.zip"),
    ],
)
def test_with_stem(path, new_stem, exp_path):
    assert GeoPath(path).with_stem(new_stem) == Path(exp_path)
