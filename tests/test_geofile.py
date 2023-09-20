"""
Tests for functionalities in geofileops.general.
"""

import os
from pathlib import Path

import geopandas as gpd
import pandas as pd
from pygeoops import GeometryType
import pytest
import shapely.geometry as sh_geom

import geofileops as gfo
from geofileops import fileops
from geofileops.util import _geoseries_util
from geofileops.util import _io_util
from tests import test_helper
from tests.test_helper import SUFFIXES
from tests.test_helper import assert_geodataframe_equal


ENGINES = ["fiona", "pyogrio"]


@pytest.fixture(scope="module", params=ENGINES)
def engine_setter(request):
    engine = request.param
    engine_backup = os.environ.get("GFO_IO_ENGINE", None)
    if engine is None:
        del os.environ["GFO_IO_ENGINE"]
    else:
        os.environ["GFO_IO_ENGINE"] = engine
    yield engine
    if engine_backup is None:
        del os.environ["GFO_IO_ENGINE"]
    else:
        os.environ["GFO_IO_ENGINE"] = engine_backup


@pytest.fixture
def points_gdf():
    nb_points = 10
    gdf = gpd.GeoDataFrame(
        [
            {"geometry": sh_geom.Point(x, y), "value1": x + y, "value2": x * y}
            for x, y in zip(range(nb_points), range(nb_points))
        ],
        crs="epsg:4326",
    )
    return gdf


def test_add_column(tmp_path):
    test_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)

    # The area column shouldn't be in the test file yet
    layerinfo = gfo.get_layerinfo(path=test_path, layer="parcels")
    assert "AREA" not in layerinfo.columns

    # Add area column
    gfo.add_column(
        test_path, layer="parcels", name="AREA", type="real", expression="ST_area(geom)"
    )

    layerinfo = gfo.get_layerinfo(path=test_path, layer="parcels")
    assert "AREA" in layerinfo.columns

    gdf = gfo.read_file(test_path)
    assert round(gdf["AREA"].astype("float")[0], 1) == round(
        gdf["OPPERVL"].astype("float")[0], 1
    )

    # Add perimeter column
    gfo.add_column(
        test_path,
        name="PERIMETER",
        type=gfo.DataType.REAL,
        expression="ST_perimeter(geom)",
    )

    layerinfo = gfo.get_layerinfo(path=test_path, layer="parcels")
    assert "AREA" in layerinfo.columns

    gdf = gfo.read_file(test_path)
    assert round(gdf["AREA"].astype("float")[0], 1) == round(
        gdf["OPPERVL"].astype("float")[0], 1
    )

    # Add a column of different gdal types
    gdal_types = [
        "Binary",
        "Date",
        "DateTime",
        "Integer",
        "Integer64",
        "String",
        "Time",
        "Real",
    ]
    for type in gdal_types:
        gfo.add_column(test_path, name=f"column_{type}", type=type)
    info = gfo.get_layerinfo(test_path)
    for type in gdal_types:
        assert f"column_{type}" in info.columns

    # Adding an already existing column doesn't give an error
    existing_column = next(iter(info.columns))
    gfo.add_column(test_path, name=existing_column, type="TEXT")

    # Force update on an existing column
    assert gdf["HFDTLT"][0] == "1"
    expression = "5"
    gfo.add_column(
        test_path, name="HFDTLT", type="TEXT", expression=expression, force_update=True
    )
    gdf = gfo.read_file(test_path)
    assert gdf["HFDTLT"][0] == "5"


def test_append_different_layer(tmp_path):
    # Init
    src_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    dst_path = tmp_path / "dst.gpkg"

    # Copy src file to dst file to "layer1"
    gfo.append_to(src_path, dst_path, dst_layer="layer1")
    src_info = gfo.get_layerinfo(src_path)
    dst_layer1_info = gfo.get_layerinfo(dst_path, "layer1")
    assert src_info.featurecount == dst_layer1_info.featurecount

    # Append src file layer to dst file to new layer: "layer2"
    gfo.append_to(src_path, dst_path, dst_layer="layer2")
    dst_layer2_info = gfo.get_layerinfo(dst_path, "layer2")
    assert dst_layer1_info.featurecount == dst_layer2_info.featurecount


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_append_different_columns(tmp_path, suffix):
    src_path = test_helper.get_testfile(
        "polygon-parcel", dst_dir=tmp_path, suffix=suffix
    )
    dst_path = tmp_path / f"dst{suffix}"
    gfo.copy(src_path, dst_path)
    gfo.add_column(src_path, name="extra_column", type=gfo.DataType.INTEGER)
    gfo.append_to(src_path, dst_path)

    src_info = gfo.get_layerinfo(src_path)
    res_info = gfo.get_layerinfo(dst_path)

    # All rows are appended tot the dst layer, but the extra column is not!
    assert (src_info.featurecount * 2) == res_info.featurecount
    assert len(src_info.columns) == len(res_info.columns) + 1


def test_append_shp_laundered_columns(tmp_path):
    # GDAL doesn't seem to handle appending to a shapefile where column laundering is
    # needed very well: all laundered columns get NULL values instead of the actual
    # values.
    # gfo.append_to bypasses this by laundering the columns beforehand via an sql
    # statement so gdal doesn't need to do laundering.
    # Start from a gpkg test file, because that can have long column names that need
    # laundering.
    src_path = test_helper.get_testfile(
        "polygon-parcel", dst_dir=tmp_path, suffix=".gpkg"
    )
    gfo.add_column(
        src_path, name="extra_long_columnname", type="TEXT", expression="'TEST VALUE'"
    )
    dst_path = tmp_path / "dst.shp"
    gfo.append_to(src_path, dst_path)
    gfo.append_to(src_path, dst_path)

    src_info = gfo.get_layerinfo(src_path)
    dst_info = gfo.get_layerinfo(dst_path)

    # All rows are appended tot the dst layer, and long column name should be laundered
    assert (src_info.featurecount * 2) == dst_info.featurecount
    assert len(src_info.columns) == len(dst_info.columns)
    assert "extra_long" in dst_info.columns
    assert "extra_long_columnname" not in dst_info.columns

    # Check content
    dst_gdf = gfo.read_file(dst_path)
    assert dst_gdf is not None
    assert dst_gdf["extra_long"].to_list() == ["TEST VALUE"] * len(dst_gdf)


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_cmp(tmp_path, suffix):
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    src2 = test_helper.get_testfile("polygon-invalid", suffix=suffix)

    # Copy test file to tmpdir
    dst = tmp_path / f"polygons_parcels_output{suffix}"
    gfo.copy(src, dst)

    # Now compare source and dst files
    assert gfo.cmp(src, dst) is True
    assert gfo.cmp(src2, dst) is False


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_convert(tmp_path, suffix):
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Convert
    dst = tmp_path / f"{src.stem}-output{suffix}"
    gfo.copy_layer(src, dst)

    # Now compare source and dst file
    src_layerinfo = gfo.get_layerinfo(src)
    dst_layerinfo = gfo.get_layerinfo(dst)
    assert src_layerinfo.featurecount == dst_layerinfo.featurecount
    assert len(src_layerinfo.columns) == len(dst_layerinfo.columns)


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_convert_emptyfile(tmp_path, suffix):
    # Convert
    src = test_helper.get_testfile(
        "polygon-parcel", suffix=suffix, dst_dir=tmp_path, empty=True
    )
    dst = tmp_path / f"{src.stem}-output{suffix}"
    gfo.copy_layer(src, dst)

    # Now compare source and dst file
    assert dst.exists()
    src_layerinfo = gfo.get_layerinfo(src)
    dst_layerinfo = gfo.get_layerinfo(dst)
    assert src_layerinfo.featurecount == dst_layerinfo.featurecount
    assert len(src_layerinfo.columns) == len(dst_layerinfo.columns)


@pytest.mark.parametrize(
    "testfile, force_geometrytype",
    [
        ("polygon-parcel", GeometryType.POLYGON),
        ("polygon-parcel", GeometryType.MULTIPOLYGON),
        ("polygon-parcel", GeometryType.LINESTRING),
        ("polygon-parcel", GeometryType.MULTILINESTRING),
        ("polygon-parcel", GeometryType.POINT),
        ("polygon-parcel", GeometryType.MULTIPOINT),
    ],
)
def test_convert_force_output_geometrytype(tmp_path, testfile, force_geometrytype):
    # The conversion is done by ogr, and the "test" is rather written to
    # explore the behaviour of this ogr functionality

    # Convert testfile and force to force_geometrytype
    src = test_helper.get_testfile(testfile)
    dst = tmp_path / f"{src.stem}_to_{force_geometrytype}.gpkg"
    gfo.copy_layer(src, dst, force_output_geometrytype=force_geometrytype)
    assert gfo.get_layerinfo(dst).geometrytype == force_geometrytype


def test_convert_invalid_params(tmp_path):
    # Convert
    src = tmp_path / "nonexisting_file.gpkg"
    dst = tmp_path / "output.gpkg"
    with pytest.raises(ValueError, match="src file doesn't exist: "):
        gfo.copy_layer(src, dst)


@pytest.mark.parametrize(
    "src_suffix, dst_suffix, preserve_fid, exp_preserved_fids",
    [
        (".shp", ".gpkg", True, True),
        (".shp", ".gpkg", False, False),
        (".gpkg", ".shp", True, False),
        (".shp", ".sqlite", True, True),
        (".shp", ".sqlite", False, False),
    ],
)
def test_convert_preserve_fid(
    tmp_path,
    src_suffix: str,
    dst_suffix: str,
    preserve_fid: bool,
    exp_preserved_fids: bool,
):
    src = test_helper.get_testfile("polygon-parcel", suffix=src_suffix)

    # Convert with preserve_fid=None (default)
    # ----------------------------------------
    dst = tmp_path / f"{src.stem}-output_preserve_fid-{preserve_fid}{dst_suffix}"
    gfo.copy_layer(src, dst, preserve_fid=preserve_fid)

    # Now compare source and dst file
    src_gdf = gfo.read_file(src, fid_as_index=True)
    dst_gdf = gfo.read_file(dst, fid_as_index=True)
    assert len(src_gdf) == len(dst_gdf)
    assert len(src_gdf.columns) == len(dst_gdf.columns)
    if exp_preserved_fids:
        assert src_gdf.index.tolist() == dst_gdf.index.tolist()
    else:
        assert src_gdf.index.tolist() != dst_gdf.index.tolist()


@pytest.mark.parametrize("suffix", SUFFIXES)
@pytest.mark.parametrize("src_crs", [None, 31370])
def test_convert_reproject(tmp_path, suffix, src_crs):
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Convert with reproject
    dst = tmp_path / f"{src.stem}-output_reproj4326{suffix}"
    gfo.copy_layer(src, dst, src_crs=src_crs, dst_crs=4326, reproject=True)

    # Now compare source and dst file
    src_layerinfo = gfo.get_layerinfo(src)
    dst_layerinfo = gfo.get_layerinfo(dst)
    assert src_layerinfo.featurecount == dst_layerinfo.featurecount
    assert src_layerinfo.crs is not None
    assert src_layerinfo.crs.to_epsg() == 31370
    assert dst_layerinfo.crs is not None
    assert dst_layerinfo.crs.to_epsg() == 4326

    # Check if dst file actually seems to contain lat lon coordinates
    dst_gdf = gfo.read_file(dst)
    first_geom = dst_gdf.geometry[0]
    first_poly = (
        first_geom if isinstance(first_geom, sh_geom.Polygon) else first_geom.geoms[0]
    )
    assert first_poly.exterior is not None
    for x, y in first_poly.exterior.coords:
        assert x < 100 and y < 100


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_convert_where(tmp_path, suffix):
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Convert with where
    dst = tmp_path / f"{src.stem}-output_where{suffix}"
    gfo.copy_layer(src, dst, where="ST_Area({geometrycolumn}) > 500")

    # Now compare source and dst file
    src_layerinfo = gfo.get_layerinfo(src)
    dst_layerinfo = gfo.get_layerinfo(dst)
    assert src_layerinfo.featurecount > dst_layerinfo.featurecount
    assert dst_layerinfo.featurecount == 43


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_copy(tmp_path, suffix):
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Copy to dest file
    dst = tmp_path / f"{src.stem}-output{suffix}"
    gfo.copy(src, dst)
    assert src.exists()
    assert dst.exists()
    if suffix == ".shp":
        assert dst.with_suffix(".shx").exists()

    # Copy to dest dir
    dst_dir = tmp_path / "dest_dir"
    dst_dir.mkdir(parents=True, exist_ok=True)
    gfo.copy(src, dst_dir)
    dst = dst_dir / src.name
    assert src.exists()
    assert dst.exists()
    if suffix == ".shp":
        assert dst.with_suffix(".shx").exists()


def test_driver_enum():
    # Test ESRIShapefile Driver
    # Test getting a driver for a suffix
    geofiletype = gfo.GeofileType(".shp")
    assert geofiletype == gfo.GeofileType.ESRIShapefile

    # Test getting a driver for a Path
    path = Path("/testje/path_naar_gfo.sHp")
    geofiletype = gfo.GeofileType(path)
    assert geofiletype == gfo.GeofileType.ESRIShapefile

    # GPKG Driver
    # Test getting a driver for a suffix
    geofiletype = gfo.GeofileType(".gpkg")
    assert geofiletype == gfo.GeofileType.GPKG

    # Test getting a driver for a Path
    path = Path("/testje/path_naar_gfo.gPkG")
    geofiletype = gfo.GeofileType(path)
    assert geofiletype == gfo.GeofileType.GPKG

    # SQLite Driver
    # Test getting a driver for a suffix
    geofiletype = gfo.GeofileType(".sqlite")
    assert geofiletype == gfo.GeofileType.SQLite

    # Test getting a driver for a Path
    path = Path("/testje/path_naar_gfo.sQlItE")
    geofiletype = gfo.GeofileType(path)
    assert geofiletype == gfo.GeofileType.SQLite


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_drop_column(tmp_path, suffix):
    test_path = test_helper.get_testfile(
        "polygon-parcel", dst_dir=tmp_path, suffix=suffix
    )
    original_info = gfo.get_layerinfo(test_path)
    assert "GEWASGROEP" in original_info.columns
    gfo.drop_column(test_path, "GEWASGROEP")
    new_info = gfo.get_layerinfo(test_path)
    assert len(original_info.columns) == len(new_info.columns) + 1
    assert "GEWASGROEP" not in new_info.columns

    # dropping column that doesn't exist doesn't give an error
    gfo.drop_column(test_path, "NOT_EXISTING_COLUMN")


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_get_crs(suffix):
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    crs = gfo.get_crs(src)
    assert crs.to_epsg() == 31370


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_get_default_layer(suffix):
    # Prepare test data + test
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    layer = gfo.get_default_layer(src)
    assert layer == src.stem


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_get_layer_geometrytypes(suffix):
    # Prepare test data + test
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    geometrytypes = gfo.get_layer_geometrytypes(src)
    assert geometrytypes == ["POLYGON", "MULTIPOLYGON"]


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_get_layer_geometrytypes_empty(tmp_path, suffix):
    # Prepare test data + test
    src = test_helper.get_testfile(
        "polygon-parcel", suffix=suffix, dst_dir=tmp_path, empty=True
    )
    geometrytypes = gfo.get_layer_geometrytypes(src)
    assert geometrytypes == []


def test_get_layer_geometrytypes_geometry(tmp_path):
    # Prepare test data + test
    src = test_helper.get_testfile("polygon-parcel", suffix=".gpkg")
    test_path = tmp_path / f"{src.stem}_geometry{src.suffix}"
    gfo.copy_layer(src, test_path, force_output_geometrytype="GEOMETRY")
    assert gfo.get_layerinfo(test_path).geometrytypename == "GEOMETRY"
    geometrytypes = gfo.get_layer_geometrytypes(src)
    assert geometrytypes == ["POLYGON", "MULTIPOLYGON"]


@pytest.mark.parametrize("suffix", [".gpkg", ".shp"])
def test_get_layerinfo(suffix):
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    # Tests
    layerinfo = gfo.get_layerinfo(src)
    assert str(layerinfo).startswith("<class 'geofileops.fileops.LayerInfo'>")
    assert layerinfo.featurecount == 46

    if src.suffix == ".shp":
        assert layerinfo.geometrycolumn == "geometry"
        assert layerinfo.name == src.stem
        assert layerinfo.fid_column == ""
    elif src.suffix == ".gpkg":
        assert layerinfo.geometrycolumn == "geom"
        assert layerinfo.name == "parcels"
        assert layerinfo.fid_column == "fid"

    assert layerinfo.geometrytypename == gfo.GeometryType.MULTIPOLYGON.name
    assert layerinfo.geometrytype == gfo.GeometryType.MULTIPOLYGON
    assert layerinfo.total_bounds is not None
    assert layerinfo.crs is not None
    assert layerinfo.crs.to_epsg() == 31370

    assert len(layerinfo.columns) == 11
    assert layerinfo.columns["OIDN"].gdal_type == "Integer64"

    # Some tests for exception cases
    # Layer specified that doesn't exist
    with pytest.raises(ValueError, match="Layer not_existing_layer not found in file"):
        layerinfo = gfo.get_layerinfo(src, "not_existing_layer")

    # Path specified that doesn't exist
    with pytest.raises(ValueError, match="input_path doesn't exist"):
        not_existing_path = _io_util.with_stem(src, "not_existing_layer")
        layerinfo = gfo.get_layerinfo(not_existing_path)


def test_get_layerinfo_nogeom(tmp_path):
    """
    Test correct behaviour of get_layerinfo if file doesn't have a geometry column.

    Remark: no use testing shapefile, as it doesn't have a .shp file without geometry
    column, only a .dbf (and optional .cpg), so get_layerinfo doesn' work anyway!
    """
    # Prepare test data
    src_geom_path = test_helper.get_testfile("polygon-parcel")
    data_df = gfo.read_file(src_geom_path, ignore_geometry=True)
    src = tmp_path / f"{src_geom_path.stem}_nogeom{src_geom_path.suffix}"
    gfo.to_file(data_df, src)

    # Test with raise_on_nogeom=True
    # ------------------------------
    with pytest.raises(ValueError, match="Layer doesn't have a geometry column"):
        layerinfo = gfo.get_layerinfo(src, raise_on_nogeom=True)

    # Test with raise_on_nogeom=False
    # -------------------------------
    layerinfo = gfo.get_layerinfo(src, raise_on_nogeom=False)
    assert str(layerinfo).startswith("<class 'geofileops.fileops.LayerInfo'>")
    assert layerinfo.featurecount == 46

    assert layerinfo.geometrycolumn is None
    assert layerinfo.name == src.stem
    assert layerinfo.fid_column == "fid"

    assert layerinfo.geometrytypename == "NONE"
    assert layerinfo.geometrytype is None
    assert layerinfo.total_bounds is None
    assert layerinfo.crs is None

    assert len(layerinfo.columns) == 11


def test_get_layerinfo_twolayers():
    src = test_helper.get_testfile("polygon-twolayers")

    # Test first layer
    layerinfo = gfo.get_layerinfo(src, "parcels")
    assert layerinfo.featurecount == 46
    assert layerinfo.name == "parcels"
    assert len(layerinfo.columns) == 11

    # Test second layer
    layerinfo = gfo.get_layerinfo(src, "zones")
    assert layerinfo.featurecount == 5
    assert layerinfo.name == "zones"
    assert len(layerinfo.columns) == 1

    # Test error if no layer specified
    with pytest.raises(ValueError, match="Layer has > 1 layer"):
        layerinfo = gfo.get_layerinfo(src)


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_get_only_layer_one_layer(suffix):
    # Test Geopackage with 1 layer
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    layer = gfo.get_only_layer(src)
    if suffix == ".gpkg":
        assert layer == "parcels"
    else:
        assert layer == src.stem


def test_get_only_layer_two_layers():
    # Test Geopackage with 2 layers
    src = test_helper.get_testfile("polygon-twolayers")
    layers = gfo.listlayers(src)
    assert len(layers) == 2
    with pytest.raises(ValueError, match="Layer has > 1 layer"):
        _ = gfo.get_only_layer(src)


def test_is_geofile():
    assert gfo.is_geofile(test_helper.get_testfile("polygon-parcel"))
    assert gfo.is_geofile(
        test_helper.get_testfile("polygon-parcel").with_suffix(".shp")
    )

    assert gfo.is_geofile("/test/testje.txt") is False


def test_listlayers_errors():
    path = "not_existing_file.gpkg"
    with pytest.raises(RuntimeError, match=f"listlayers error for {path}"):
        _ = gfo.listlayers(path)


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_listlayers_one_layer(suffix):
    # Test with 1 layer
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    layers = gfo.listlayers(src)
    if suffix == ".gpkg":
        assert layers[0] == "parcels"
    else:
        assert layers[0] == src.stem


def test_listlayers_two_layers():
    # Test geopackage with 2 layers
    src = test_helper.get_testfile("polygon-twolayers")
    layers = gfo.listlayers(src)
    assert "parcels" in layers
    assert "zones" in layers


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_move(tmp_path, suffix):
    src = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path, suffix=suffix)

    # Test
    dst = tmp_path / f"{src.stem}-output{suffix}"
    gfo.move(src, dst)
    assert src.exists() is False
    assert dst.exists()
    if suffix == ".shp":
        assert dst.with_suffix(".shx").exists()

    # Test move to dest dir
    src = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path, suffix=suffix)
    dst_dir = tmp_path / "dest_dir"
    dst_dir.mkdir(parents=True, exist_ok=True)
    gfo.move(src, dst_dir)
    dst = dst_dir / src.name
    assert src.exists() is False
    assert dst.exists()
    if suffix == ".shp":
        assert dst.with_suffix(".shx").exists()

    # Add column to make sure the dst file isn't locked
    if suffix == ".gpkg":
        gfo.add_column(
            path=dst,
            name="PERIMETER",
            type=gfo.DataType.REAL,
            expression="ST_perimeter(geom)",
        )


def test_update_column(tmp_path):
    test_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)

    # The area column shouldn't be in the test file yet
    layerinfo = gfo.get_layerinfo(path=test_path, layer="parcels")
    assert "area" not in layerinfo.columns

    # Add + update area column
    gfo.add_column(
        test_path, layer="parcels", name="AREA", type="real", expression="ST_area(geom)"
    )
    gfo.update_column(test_path, name="AreA", expression="ST_area(geom)")

    layerinfo = gfo.get_layerinfo(path=test_path, layer="parcels")
    assert "AREA" in layerinfo.columns
    gdf = gfo.read_file(test_path)
    assert round(gdf["AREA"].astype("float")[0], 1) == round(
        gdf["OPPERVL"].astype("float")[0], 1
    )

    # Update column for rows where area > 5
    gfo.update_column(test_path, name="AreA", expression="-1", where="area > 4000")
    gdf = gfo.read_file(test_path)
    gdf_filtered = gdf[gdf["AREA"] == -1]
    assert len(gdf_filtered) == 20


def test_update_column_error(tmp_path):
    test_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    layerinfo = gfo.get_layerinfo(path=test_path, layer="parcels")

    # Trying to update column that doesn't exist should raise ValueError
    assert "not_existing column" not in layerinfo.columns
    with pytest.raises(ValueError, match="Column .* doesn't exist in"):
        gfo.update_column(
            test_path, name="not_existing column", expression="ST_area(geom)"
        )

    # Try to update column with invalid expression
    assert "not_existing column" not in layerinfo.columns
    with pytest.raises(RuntimeError, match="update_column error for"):
        gfo.update_column(test_path, name="OPPERVL", expression="invalid_expression")


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_read_file(suffix, engine_setter):
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Test with defaults
    read_gdf = gfo.read_file(src)
    assert isinstance(read_gdf, gpd.GeoDataFrame)
    assert len(read_gdf.columns) == 12
    assert len(read_gdf) == 46

    # Test no columns
    read_gdf = gfo.read_file(src, columns=[])
    assert isinstance(read_gdf, gpd.GeoDataFrame)
    assert len(read_gdf.columns) == 1
    assert len(read_gdf) == 46

    # Test specific columns (+ test case insensitivity + order)
    columns = ["OIDN", "uidn", "HFDTLT", "lblhfdtlt", "GEWASGROEP", "lengte", "OPPERVL"]
    read_gdf = gfo.read_file(src, columns=columns)
    assert len(read_gdf) == 46
    columns.append("geometry")
    for index, column in enumerate(read_gdf.columns):
        assert str(column) == columns[index]

    # Test no geom
    read_gdf = gfo.read_file_nogeom(src)
    assert isinstance(read_gdf, pd.DataFrame)
    assert len(read_gdf) == 46

    # Test ignore_geometry, no columns
    read_gdf = gfo.read_file_nogeom(src, columns=[])
    assert isinstance(read_gdf, pd.DataFrame)
    if engine_setter == "fiona":
        # fiona: 0 rows
        assert len(read_gdf) == 0
    else:
        # pyogrio: 0, pyogrio + pyarrow=True: 46 (= the index)
        assert len(read_gdf) == 0


def test_read_file_invalid_params(tmp_path, engine_setter):
    src = tmp_path / "nonexisting_file.gpkg"

    with pytest.raises(ValueError, match="file doesn't exist:"):
        _ = gfo.read_file(src)


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_read_file_fid_as_index(suffix, engine_setter):
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # First read without fid_as_index=True
    read_gdf = gfo.read_file(src, rows=slice(5, 10))
    assert isinstance(read_gdf, pd.DataFrame)
    assert len(read_gdf.columns) == 12
    assert len(read_gdf) == 5
    assert read_gdf.index[0] == 0

    # Now with fid_as_index=True
    read_gdf = gfo.read_file(src, rows=slice(5, 10), fid_as_index=True)
    assert isinstance(read_gdf, pd.DataFrame)
    assert len(read_gdf.columns) == 12
    assert len(read_gdf) == 5
    if gfo.GeofileType(src).is_fid_zerobased:
        assert read_gdf.index[0] == 5
    else:
        # Geopackage fid starts at 1
        assert read_gdf.index[0] == 6


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_read_file_sql(suffix, engine_setter):
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Test
    src_layerinfo = gfo.get_layerinfo(src)
    sql_stmt = f'SELECT * FROM "{src_layerinfo.name}"'
    if engine_setter == "fiona":
        with pytest.raises(ValueError, match="sql_stmt is not supported with fiona"):
            _ = gfo.read_file(src, sql_stmt=sql_stmt)
        return

    read_gdf = gfo.read_file(src, sql_stmt=sql_stmt)
    assert isinstance(read_gdf, gpd.GeoDataFrame)
    assert len(read_gdf) == 46


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_read_file_sql_deprecated(suffix, engine_setter):
    if engine_setter == "fiona":
        pytest.skip("sql_stmt param not supported for fiona engine")

    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Test
    src_layerinfo = gfo.get_layerinfo(src)
    read_gdf = gfo.read_file_sql(src, sql_stmt=f'SELECT * FROM "{src_layerinfo.name}"')
    assert isinstance(read_gdf, gpd.GeoDataFrame)
    assert len(read_gdf) == 46


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_read_file_sql_no_geom(suffix, engine_setter):
    if engine_setter == "fiona":
        pytest.skip("sql_stmt param not supported for fiona engine")

    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Test
    src_layerinfo = gfo.get_layerinfo(src)
    sql_stmt = f'SELECT count(*) AS aantal FROM "{src_layerinfo.name}"'
    read_df = gfo.read_file(src, sql_stmt=sql_stmt)
    assert isinstance(read_df, pd.DataFrame)
    assert len(read_df) == 1
    assert read_df.aantal.item() == 46


@pytest.mark.parametrize("suffix", SUFFIXES)
@pytest.mark.parametrize("columns", [["OIDN", "UIDN"], ["OidN", "UidN"]])
def test_read_file_sql_placeholders(suffix, engine_setter, columns):
    """
    Test if placeholders are properly filled out + if casing used in columns parameter
    is retained when using placeholders.
    """
    if engine_setter == "fiona":
        pytest.skip("sql_stmt param not supported for fiona engine")

    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Test
    sql_stmt = """
        SELECT {geometrycolumn}
              {columns_to_select_str}
          FROM "{input_layer}" layer
    """
    read_sql_gdf = gfo.read_file(
        src, sql_stmt=sql_stmt, sql_dialect="SQLITE", columns=columns
    )
    read_gdf = gfo.read_file(src, columns=columns)
    assert_geodataframe_equal(read_gdf, read_sql_gdf)


def test_read_file_two_layers(engine_setter):
    src = test_helper.get_testfile("polygon-twolayers")
    layers = gfo.listlayers(src)
    assert "parcels" in layers
    assert "zones" in layers

    read_gdf = gfo.read_file(src, layer="zones")
    assert isinstance(read_gdf, gpd.GeoDataFrame)
    assert len(read_gdf) == 5

    read_gdf = gfo.read_file(src, layer="parcels")
    assert isinstance(read_gdf, gpd.GeoDataFrame)
    assert len(read_gdf) == 46


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_rename_column(tmp_path, suffix):
    test_path = test_helper.get_testfile(
        "polygon-parcel", dst_dir=tmp_path, suffix=suffix
    )

    # Check if input file is ok
    orig_layerinfo = gfo.get_layerinfo(test_path)
    assert "OPPERVL" in orig_layerinfo.columns
    assert "area" not in orig_layerinfo.columns

    # Rename
    if test_path.suffix == ".shp":
        with pytest.raises(ValueError, match="rename_column is not possible for"):
            gfo.rename_column(test_path, "OPPERVL", "area")
    else:
        gfo.rename_column(test_path, "OPPERVL", "area")
        result_layerinfo = gfo.get_layerinfo(test_path)
        assert "OPPERVL" not in result_layerinfo.columns
        assert "area" in result_layerinfo.columns

        # Rename non-existing column to existing columns doesn't give an error
        gfo.rename_column(test_path, "OPPERVL", "area")
        result_layerinfo = gfo.get_layerinfo(test_path)
        assert "OPPERVL" not in result_layerinfo.columns
        assert "area" in result_layerinfo.columns


def test_rename_column_unsupported(tmp_path):
    path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path, suffix=".shp")
    with pytest.raises(ValueError, match="rename_column is not possible for"):
        _ = gfo.rename_column(path, column_name="abc", new_column_name="def")

    path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path, suffix=".fgb")
    with pytest.raises(ValueError, match="rename_column is not implemented for"):
        _ = gfo.rename_column(path, column_name="abc", new_column_name="def")


def test_rename_layer(tmp_path):
    test_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    gfo.add_layerstyle(test_path, layer="parcels", name="stylename", qml="")

    gfo.rename_layer(test_path, new_layer="parcels_renamed")
    layernames_renamed = gfo.listlayers(path=test_path)
    assert layernames_renamed[0] == "parcels_renamed"
    assert len(gfo.get_layerstyles(test_path, layer="parcels_renamed")) == 1


def test_rename_layer_unsupported(tmp_path):
    path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path, suffix=".shp")
    with pytest.raises(ValueError, match="rename_layer not possible for"):
        _ = gfo.rename_layer(path, layer="layer", new_layer="new_layer")

    path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path, suffix=".fgb")
    with pytest.raises(ValueError, match="rename_layer not implemented for"):
        _ = gfo.rename_layer(path, layer="layer", new_layer="new_layer")


def test_execute_sql(tmp_path):
    # Prepare testfile
    test_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)

    # Test using execute_sql for creating/dropping indexes
    gfo.execute_sql(
        path=test_path, sql_stmt='CREATE INDEX idx_parcels_oidn ON "parcels"("oidn")'
    )
    gfo.execute_sql(path=test_path, sql_stmt="DROP INDEX idx_parcels_oidn")


def test_execute_sql_invalid(tmp_path):
    # Prepare testfile
    test_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)

    # Test using execute_sql with invalid sql statement
    with pytest.raises(RuntimeError, match="execute_sql error"):
        gfo.execute_sql(path=test_path, sql_stmt="SELECT abc FROM cde")


def test_fill_out_sql_placeholders():
    path = test_helper.get_testfile("polygon-parcel")
    layer = gfo.get_only_layer(path)
    columns = ["UIDN", "OIDN"]

    # Test the different existing placeholders
    sql_stmt = 'SELECT {columns_to_select_str} FROM "parcels"'
    result = fileops._fill_out_sql_placeholders(
        path, layer=layer, sql_stmt=sql_stmt, columns=columns
    )
    assert result == 'SELECT ,"UIDN" "UIDN", "OIDN" "OIDN" FROM "parcels"'

    sql_stmt = 'SELECT {geometrycolumn} FROM "parcels"'
    result = fileops._fill_out_sql_placeholders(
        path, layer=layer, sql_stmt=sql_stmt, columns=columns
    )
    assert result == 'SELECT geom FROM "parcels"'

    sql_stmt = 'SELECT geom FROM "{input_layer}"'
    result = fileops._fill_out_sql_placeholders(
        path, layer=layer, sql_stmt=sql_stmt, columns=columns
    )
    assert result == 'SELECT geom FROM "parcels"'


def test_fill_out_sql_placeholders_errors():
    path = test_helper.get_testfile("polygon-parcel")

    # Test invalid placeholder
    sql_stmt = 'SELECT {invalid_placeholder} FROM "parcel"'
    with pytest.raises(ValueError, match="unknown placeholder invalid_placeholder "):
        fileops._fill_out_sql_placeholders(
            path, layer="parcel", sql_stmt=sql_stmt, columns=None
        )


def test_spatial_index_unsupported(tmp_path):
    path = tmp_path / "unsupported_type.unsupported"
    path.touch()
    with pytest.raises(ValueError, match="Unknown extension .unsupported"):
        _ = gfo.create_spatial_index(path, "layer")

    with pytest.raises(ValueError, match="Unknown extension .unsupported"):
        _ = gfo.has_spatial_index(path, "layer")

    with pytest.raises(ValueError, match="Unknown extension .unsupported"):
        _ = gfo.remove_spatial_index(path, "layer")


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_spatial_index(tmp_path, suffix):
    test_path = test_helper.get_testfile(
        "polygon-parcel", dst_dir=tmp_path, suffix=suffix
    )
    layer = gfo.get_only_layer(test_path)

    # Check if spatial index present
    has_spatial_index = gfo.has_spatial_index(path=test_path, layer=layer)
    assert has_spatial_index is True

    # Remove spatial index
    gfo.remove_spatial_index(path=test_path, layer=layer)
    has_spatial_index = gfo.has_spatial_index(path=test_path, layer=layer)
    assert has_spatial_index is False

    # Create spatial index
    gfo.create_spatial_index(path=test_path, layer=layer)
    has_spatial_index = gfo.has_spatial_index(path=test_path, layer=layer)
    assert has_spatial_index is True

    # Spatial index if it exists already by default gives error
    with pytest.raises(Exception, match="Error adding spatial index to"):
        gfo.create_spatial_index(path=test_path, layer=layer)
    gfo.create_spatial_index(path=test_path, layer=layer, exist_ok=True)

    # Test of rebuild only easy on shapefile
    if suffix == ".shp":
        qix_path = test_path.with_suffix(".qix")
        qix_modified_time_orig = qix_path.stat().st_mtime
        gfo.create_spatial_index(path=test_path, layer=layer, exist_ok=True)
        assert qix_path.stat().st_mtime == qix_modified_time_orig
        gfo.create_spatial_index(path=test_path, layer=layer, force_rebuild=True)
        assert qix_path.stat().st_mtime > qix_modified_time_orig


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_to_file(tmp_path, suffix, engine_setter):
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    output_path = tmp_path / f"{src.stem}-output{suffix}"

    # Read test file and write to tmppath
    read_gdf = gfo.read_file(src)
    gfo.to_file(read_gdf, output_path)
    written_gdf = gfo.read_file(output_path)
    assert len(read_gdf) == len(written_gdf)
    assert_geodataframe_equal(written_gdf, read_gdf)

    # Append the file again to tmppath
    gfo.to_file(read_gdf, output_path, append=True)
    written_gdf = gfo.read_file(output_path)
    assert 2 * len(read_gdf) == len(written_gdf)


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_to_file_append_to_unexisting_file(tmp_path, suffix, engine_setter):
    test_path = test_helper.get_testfile(
        "polygon-parcel", dst_dir=tmp_path, suffix=suffix
    )
    test_gdf = gfo.read_file(test_path)
    dst_path = tmp_path / f"dst{suffix}"
    gfo.to_file(test_gdf, path=dst_path, append=True)
    assert dst_path.exists()
    dst_info = gfo.get_layerinfo(dst_path)
    assert dst_info.featurecount == len(test_gdf)


def test_to_file_append_different_columns(tmp_path, engine_setter):
    test_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)

    test_gdf = gfo.read_file(test_path)
    test_gdf["extra_column"] = 123
    if engine_setter == "fiona":
        ex_message = "Record does not match collection schema"
    else:
        ex_message = "destination layer doesn't have the same columns as gdf"
    with pytest.raises(ValueError, match=ex_message):
        gfo.to_file(test_gdf, path=test_path, append=True)


def test_to_file_attribute_table_gpkg(tmp_path, engine_setter):
    # Prepare test data
    test_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)

    # Test writing a DataFrame to geopackage
    test_gdf = gfo.read_file(test_path)
    test_df = test_gdf.drop(columns="geometry")
    assert isinstance(test_df, pd.DataFrame)
    assert isinstance(test_df, gpd.GeoDataFrame) is False
    gfo.to_file(test_df, test_path)

    # Now check if the layer are correctly found afterwards
    assert len(gfo.listlayers(test_path)) == 1
    assert len(gfo.listlayers(test_path, only_spatial_layers=False)) == 2


@pytest.mark.parametrize(
    "suffix, create_spatial_index, expected_spatial_index",
    [
        [".gpkg", True, True],
        [".gpkg", False, False],
        [".gpkg", None, True],
        [".shp", True, True],
        [".shp", False, False],
        [".shp", None, False],
    ],
)
def test_to_file_create_spatial_index(
    tmp_path,
    suffix: str,
    create_spatial_index: bool,
    expected_spatial_index: bool,
    engine_setter,
):
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    output_path = tmp_path / f"{src.stem}-output{suffix}"

    # Read test file and write to tmppath
    read_gdf = gfo.read_file(src)
    gfo.to_file(read_gdf, output_path, create_spatial_index=create_spatial_index)
    assert gfo.has_spatial_index(output_path) is expected_spatial_index


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_to_file_emptyfile(tmp_path, suffix):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    input_layerinfo = gfo.get_layerinfo(input_path)
    read_gdf = gfo.read_file(input_path)
    empty_gdf = read_gdf.drop(read_gdf.index)
    assert isinstance(empty_gdf, gpd.GeoDataFrame)

    # Test
    # Remark: if no force_output_geometrytype is specified, the ouput geometry type in
    # the depends on the file type, eg. Geometry for gpkg, MultiLinestring for shp.
    output_path = tmp_path / f"output-emptyfile{suffix}"
    gfo.to_file(
        empty_gdf,
        output_path,
        force_output_geometrytype=input_layerinfo.geometrytype,
    )

    # Check result
    input_layerinfo = gfo.get_layerinfo(input_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert output_layerinfo.featurecount == 0
    assert len(input_layerinfo.columns) == len(output_layerinfo.columns)
    assert input_layerinfo.geometrytype == output_layerinfo.geometrytype


def test_to_file_fid_append_to(tmp_path, engine_setter):
    """Write 2 gpkg files with fid, then use append_to to merge them."""
    # Prepare test data
    suffix = ".gpkg"
    test1_gdf = gpd.GeoDataFrame(
        [
            {"geometry": sh_geom.Point(0, 1), "fid": 2},
            {"geometry": sh_geom.Point(0, 1), "fid": 3},
        ],
        crs="epsg:31370",
    )
    test2_gdf = gpd.GeoDataFrame(
        [
            {"geometry": sh_geom.Point(0, 1), "fid": 5},
            {"geometry": sh_geom.Point(0, 1), "fid": 6},
        ],
        crs="epsg:31370",
    )
    output1_path = tmp_path / f"output1{suffix}"
    output2_path = tmp_path / f"output2{suffix}"
    output_path = tmp_path / f"output{suffix}"

    # Write the two geodataframes each to a file
    gfo.to_file(test1_gdf, output1_path)
    gfo.to_file(test2_gdf, output2_path)

    # Check if the files were written properly
    output1_gdf = gfo.read_file(output1_path, fid_as_index=True)
    assert_geodataframe_equal(output1_gdf, test1_gdf.set_index("fid"))
    output2_gdf = gfo.read_file(output2_path, fid_as_index=True)
    assert_geodataframe_equal(output2_gdf, test2_gdf.set_index("fid"))

    # Now merge them, but start with the high fid numbers
    gfo.copy(output2_path, output_path)
    gfo.rename_layer(output_path, output_path.stem)
    gfo.append_to(
        output1_path, output_path, dst_layer=output_path.stem, preserve_fid=True
    )

    # Prepare expected result
    expected_gdf = pd.concat([test1_gdf, test2_gdf]).set_index("fid")
    # Now check result
    written_gdf = gfo.read_file(output_path, fid_as_index=True)
    assert_geodataframe_equal(written_gdf, expected_gdf)


def test_to_file_force_geometrytype_multitype(tmp_path, engine_setter):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel")
    read_gdf = gfo.read_file(input_path)
    read_gdf.geometry = read_gdf.geometry.buffer(0)
    poly_gdf = read_gdf[read_gdf.geometry.geom_type == "Polygon"]
    assert isinstance(poly_gdf, gpd.GeoDataFrame)

    # Default behaviour -> Polygon
    output_path = tmp_path / f"{input_path.stem}-output.gpkg"
    gfo.to_file(poly_gdf, output_path)
    output_info = gfo.get_layerinfo(output_path)
    assert output_info.featurecount == len(poly_gdf)
    assert output_info.geometrytype == GeometryType.POLYGON

    # force_output_geometrytype=GeometryType.MULTIPOLYGON -> MultiPolygon
    output_force_path = tmp_path / f"{input_path.stem}-output-force.gpkg"
    gfo.to_file(
        poly_gdf,
        output_force_path,
        force_output_geometrytype=GeometryType.MULTIPOLYGON,
    )
    output_force_info = gfo.get_layerinfo(output_force_path)
    assert output_force_info.featurecount == len(poly_gdf)
    assert output_force_info.geometrytype == GeometryType.MULTIPOLYGON

    # force_multitype=True -> MultiPolygon
    output_force_path = tmp_path / f"{input_path.stem}-output-force.gpkg"
    gfo.to_file(poly_gdf, output_force_path, force_multitype=True)
    output_force_info = gfo.get_layerinfo(output_force_path)
    assert output_force_info.featurecount == len(poly_gdf)
    assert output_force_info.geometrytype == GeometryType.MULTIPOLYGON


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_to_file_geomempty(tmp_path, suffix, engine_setter):
    # Test for gdf with an empty polygon + a polygon
    test_gdf = gpd.GeoDataFrame(
        geometry=[
            sh_geom.GeometryCollection(),
            test_helper.TestData.polygon_with_island,
        ]
    )
    # By default, get_geometrytypes ignores the type of empty geometries.
    test_geometrytypes = _geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_geometrytypes) == 1
    test_geometrytypes_includingempty = _geoseries_util.get_geometrytypes(
        test_gdf.geometry, ignore_empty_geometries=False
    )
    assert len(test_geometrytypes_includingempty) == 2
    output_empty_path = tmp_path / f"testfile_with_emptygeom{suffix}"
    test_gdf.to_file(output_empty_path, driver=gfo.GeofileType(suffix).ogrdriver)

    # Now check the result if the data is still the same after being read again
    test_read_gdf = gfo.read_file(output_empty_path)
    test_read_geometrytypes = _geoseries_util.get_geometrytypes(test_read_gdf.geometry)
    assert len(test_gdf) == len(test_read_gdf)
    if suffix == ".shp":
        # When dataframe with "empty" gemetries is written to shapefile and
        # read again, shapefile becomes of type MULTILINESTRING!?!
        assert len(test_read_geometrytypes) == 1
        assert test_read_geometrytypes[0] is GeometryType.MULTILINESTRING
    else:
        # When written to Geopackage... the empty geometries are actually saved
        # as None. When read again they are None for fiona and empty for pyogrio.
        assert test_read_gdf.geometry[0] is None or test_read_gdf.geometry[0].is_empty
        assert isinstance(test_read_gdf.geometry[1], sh_geom.Polygon)

        # So the geometrytype of the resulting GeoDataFrame is also POLYGON
        assert len(test_read_geometrytypes) == 1
        assert test_read_geometrytypes[0] is GeometryType.POLYGON


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_to_file_geomnone(tmp_path, suffix, engine_setter):
    # Test for gdf with a None geometry + a polygon
    test_gdf = gpd.GeoDataFrame(
        geometry=[None, test_helper.TestData.polygon_with_island]
    )
    test_geometrytypes = _geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_geometrytypes) == 1
    output_none_path = tmp_path / f"file_with_nonegeom{suffix}"
    gfo.to_file(test_gdf, output_none_path)

    # Now check the result if the data is still the same after being read again
    test_read_gdf = gfo.read_file(output_none_path)
    # Result is the same as the original input
    assert test_read_gdf.geometry[0] is None
    assert isinstance(test_read_gdf.geometry[1], sh_geom.Polygon)
    # The geometrytype of the column in the file is also the same as originaly
    test_file_geometrytype = gfo.get_layerinfo(output_none_path).geometrytype
    if suffix == ".shp":
        assert test_file_geometrytype == GeometryType.MULTIPOLYGON
    else:
        assert test_file_geometrytype == test_geometrytypes[0]
    # The result type in the geodataframe is also the same as originaly
    test_read_geometrytypes = _geoseries_util.get_geometrytypes(test_read_gdf.geometry)
    assert len(test_gdf) == len(test_read_gdf)
    assert test_read_geometrytypes == test_geometrytypes


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_to_file_index(tmp_path, points_gdf, suffix, engine_setter):
    """Strongly based on similar test in geopandas."""

    class FileNumber:
        def __init__(self, tmpdir, base, ext):
            self.tmpdir = str(tmpdir)
            self.base = base
            self.ext = ext
            self.fileno = 0

        def __repr__(self):
            filename = f"{self.base}{self.fileno:02d}.{self.ext}"
            return os.path.join(self.tmpdir, filename)

        def __next__(self):
            self.fileno += 1
            return repr(self)

    fngen = FileNumber(tmp_path, "check", suffix)

    def do_checks(df, index_is_used):
        # check combinations of index=None|True|False on GeoDataFrame
        other_cols = list(df.columns)
        other_cols.remove("geometry")

        if suffix == ".shp":
            # ESRI Shapefile will add FID if no other columns exist
            driver_col = ["FID"]
        else:
            driver_col = []

        if index_is_used:
            index_cols = list(df.index.names)
        else:
            index_cols = [None] * len(df.index.names)

        # replicate pandas' default index names for regular and MultiIndex
        if index_cols == [None]:
            index_cols = ["index"]
        elif len(index_cols) > 1 and not all(index_cols):
            for level, index_col in enumerate(index_cols):
                if index_col is None:
                    index_cols[level] = "level_" + str(level)

        # check GeoDataFrame with default index=None to autodetect
        tempfilename = next(fngen)
        gfo.to_file(df, tempfilename, index=None)
        df_check = gfo.read_file(tempfilename)
        if len(other_cols) == 0:
            expected_cols = driver_col[:]
        else:
            expected_cols = []
        if index_is_used:
            expected_cols += index_cols
        expected_cols += other_cols + ["geometry"]
        assert list(df_check.columns) == expected_cols

        # check GeoDataFrame with index=True
        tempfilename = next(fngen)
        gfo.to_file(df, tempfilename, index=True)
        df_check = gfo.read_file(tempfilename)
        assert list(df_check.columns) == index_cols + other_cols + ["geometry"]

        # check GeoDataFrame with index=False
        tempfilename = next(fngen)
        gfo.to_file(df, tempfilename, index=False)
        df_check = gfo.read_file(tempfilename)
        if len(other_cols) == 0:
            expected_cols = driver_col + ["geometry"]
        else:
            expected_cols = other_cols + ["geometry"]
        assert list(df_check.columns) == expected_cols

    # Checks where index is not used/saved
    # ------------------------------------

    # index is a default RangeIndex
    p_gdf = points_gdf.copy()
    gdf = gpd.GeoDataFrame(p_gdf["value1"], geometry=p_gdf.geometry)
    do_checks(gdf, index_is_used=False)

    # index is a RangeIndex, starting from 1
    gdf.index += 1
    do_checks(gdf, index_is_used=False)

    # index is a Int64Index regular sequence from 1
    p_gdf.index = list(range(1, len(gdf) + 1))
    gdf = gpd.GeoDataFrame(p_gdf["value1"], geometry=p_gdf.geometry)
    do_checks(gdf, index_is_used=False)

    # index was a default RangeIndex, but delete one row to make an Int64Index
    p_gdf = points_gdf.copy()
    gdf = gpd.GeoDataFrame(p_gdf["value1"], geometry=p_gdf.geometry)
    gdf = gdf.drop(5, axis=0)
    do_checks(gdf, index_is_used=False)

    # no other columns (except geometry)
    gdf = gpd.GeoDataFrame(geometry=p_gdf.geometry)
    do_checks(gdf, index_is_used=False)

    # Checks where index is used/saved
    # --------------------------------

    # named index
    p_gdf = points_gdf.copy()
    gdf = gpd.GeoDataFrame(p_gdf["value1"], geometry=p_gdf.geometry)
    gdf.index.name = "foo_index"
    do_checks(gdf, index_is_used=True)

    # named index, same as pandas' default name after .reset_index(drop=False)
    gdf.index.name = "index"
    do_checks(gdf, index_is_used=True)

    # named MultiIndex
    p_gdf = points_gdf.copy()
    p_gdf["value3"] = p_gdf["value2"] - p_gdf["value1"]
    p_gdf.set_index(["value1", "value2"], inplace=True)
    gdf = gpd.GeoDataFrame(p_gdf, geometry=p_gdf.geometry)
    do_checks(gdf, index_is_used=True)

    # partially unnamed MultiIndex
    gdf.index.names = ["first", None]
    do_checks(gdf, index_is_used=True)

    # unnamed MultiIndex
    gdf.index.names = [None, None]
    do_checks(gdf, index_is_used=True)

    # unnamed Float64Index
    p_gdf = points_gdf.copy()
    gdf = gpd.GeoDataFrame(p_gdf["value1"], geometry=p_gdf.geometry)
    gdf.index = p_gdf.index.astype(float) / 10
    do_checks(gdf, index_is_used=True)

    # named Float64Index
    gdf.index.name = "centile"
    do_checks(gdf, index_is_used=True)

    # index as string
    p_gdf = points_gdf.copy()
    gdf = gpd.GeoDataFrame(p_gdf["value1"], geometry=p_gdf.geometry)
    gdf.index = pd.TimedeltaIndex(range(len(gdf)), "days")
    # TODO: TimedeltaIndex is an invalid field type
    gdf.index = gdf.index.astype(str)
    do_checks(gdf, index_is_used=True)

    # unnamed DatetimeIndex
    p_gdf = points_gdf.copy()
    gdf = gpd.GeoDataFrame(p_gdf["value1"], geometry=p_gdf.geometry)
    gdf.index = pd.TimedeltaIndex(range(len(gdf)), "days") + pd.DatetimeIndex(
        ["1999-12-27"] * len(gdf)
    )
    if suffix == ".shp":
        # Shapefile driver does not support datetime fields
        gdf.index = gdf.index.astype(str)
    do_checks(gdf, index_is_used=True)

    # named DatetimeIndex
    gdf.index.name = "datetime"
    do_checks(gdf, index_is_used=True)


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_to_file_nogeom(tmp_path, suffix):
    """
    Remark: a shapefile doesn't have a .shp file without geometry column, only a .dbf
    (and optional .cpg)!
    """
    # Prepare test data
    input_geom_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    input_df = gfo.read_file(input_geom_path, ignore_geometry=True)
    test_path = tmp_path / f"{input_geom_path.stem}_nogeom{suffix}"
    gfo.to_file(input_df, test_path)

    # Check the file written
    if suffix == ".gpkg":
        layerinfo = gfo.get_layerinfo(test_path, raise_on_nogeom=False)
        assert str(layerinfo).startswith("<class 'geofileops.fileops.LayerInfo'>")
        assert layerinfo.featurecount == 46

        assert layerinfo.geometrycolumn is None
        assert layerinfo.name == test_path.stem
        assert layerinfo.fid_column == "fid"

        assert layerinfo.geometrytypename == "NONE"
        assert layerinfo.geometrytype is None
        assert layerinfo.total_bounds is None
        assert layerinfo.crs is None

        assert len(layerinfo.columns) == 11
    elif suffix == ".shp":
        # a shapefile doesn't have a .shp file without geometry column, only a .dbf
        # (and optional .cpg).
        assert not test_path.exists()
        test_df = gfo.read_file(test_path.with_suffix(".dbf"))
        assert len(test_df) == 46
        assert len(test_df.columns) == 11
    else:
        raise ValueError(f"test not implemented for suffix {suffix}")


@pytest.mark.parametrize("suffix", SUFFIXES)
def test_remove(tmp_path, suffix):
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path, suffix=suffix)
    assert src.exists()

    # Remove and check result
    gfo.remove(src)
    assert src.exists() is False


def test_launder_columns():
    columns = [f"TOO_LONG_COLUMNNAME{index}" for index in range(0, 21)]
    laundered = fileops._launder_column_names(columns)
    assert laundered[0] == ("TOO_LONG_COLUMNNAME0", "TOO_LONG_C")
    assert laundered[1] == ("TOO_LONG_COLUMNNAME1", "TOO_LONG_1")
    assert laundered[9] == ("TOO_LONG_COLUMNNAME9", "TOO_LONG_9")
    assert laundered[10] == ("TOO_LONG_COLUMNNAME10", "TOO_LONG10")
    assert laundered[20] == ("TOO_LONG_COLUMNNAME20", "TOO_LONG20")

    # Laundering happens case-insensitive
    columns = ["too_LONG_COLUMNNAME", "TOO_long_COLUMNNAME2", "TOO_LONG_columnname3"]
    laundered = fileops._launder_column_names(columns)
    expected = [
        ("too_LONG_COLUMNNAME", "too_LONG_C"),
        ("TOO_long_COLUMNNAME2", "TOO_long_1"),
        ("TOO_LONG_columnname3", "TOO_LONG_2"),
    ]
    assert laundered == expected

    # Too many similar column names to be supported to launder
    columns = [f"TOO_LONG_COLUMNNAME{index}" for index in range(0, 200)]
    with pytest.raises(
        NotImplementedError, match="Not supported to launder > 99 columns starting with"
    ):
        laundered = fileops._launder_column_names(columns)
