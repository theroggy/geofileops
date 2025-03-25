"""Test for functionalities in _geopath_util."""

from pathlib import Path

import pytest

from geofileops.util import _geopath_util


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
    assert _geopath_util.stem(path) == exp_stem


@pytest.mark.parametrize(
    "path, exp_suffixes",
    [
        (Path("/tmp/testje.gpkg"), ".gpkg"),
        ("/tmp/testje.gpkg.zip", ".gpkg.zip"),
        ("/tmp/testje.shp", ".shp"),
        ("/tmp/testje.shp.zip", ".shp.zip"),
        ("/tmp/testje.txt", ".txt"),
        ("/tmp/testje", ""),
        ("/tmp/testje.tar.gz", ".gz"),
        ("/tmp/t.estj.e.gpkg", ".gpkg"),
        ("/tmp/t.estj.e.gpkg.zip", ".gpkg.zip"),
    ],
)
def test_suffixes(path, exp_suffixes):
    assert _geopath_util.suffixes(path) == exp_suffixes


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
    # If input is a string, output should be a string
    assert _geopath_util.with_stem(path, new_stem) == exp_path

    # If input is a Path, output should be a Path
    assert _geopath_util.with_stem(Path(path), new_stem) == Path(exp_path)
