"""
Tests for functionalities in geofileops.general.
"""

import os
import shutil
from contextlib import nullcontext
from itertools import product
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
import shapely.geometry as sh_geom
from osgeo import gdal
from pandas.testing import assert_frame_equal
from pygeoops import GeometryType

import geofileops as gfo
from geofileops import fileops
from geofileops._compat import GDAL_GTE_311
from geofileops.helpers._configoptions_helper import ConfigOptions
from geofileops.util import _geofileinfo, _geoseries_util
from geofileops.util._geopath_util import GeoPath
from tests import test_helper
from tests.test_helper import (
    SUFFIXES_FILEOPS,
    SUFFIXES_FILEOPS_EXT,
    SUFFIXES_GEOOPS,
    SUFFIXES_GEOOPS_EXT,
    assert_geodataframe_equal,
)

try:
    import fiona  # noqa: F401

    ENGINES = ["fiona", "pyogrio"]
except ImportError:
    ENGINES = ["pyogrio"]

gdal.UseExceptions()


@pytest.fixture(scope="module", params=ENGINES)
def engine_setter(request):
    engine = request.param
    if engine is not None:
        os.environ["GFO_IO_ENGINE"] = engine
    elif "GFO_IO_ENGINE" in os.environ:
        del os.environ["GFO_IO_ENGINE"]
    yield engine
    del os.environ["GFO_IO_ENGINE"]


@pytest.fixture
def points_gdf():
    nb_points = 10
    gdf = gpd.GeoDataFrame(
        [
            {"geometry": sh_geom.Point(x, y), "value1": x + y, "value2": x * y}
            for x, y in zip(range(nb_points), range(nb_points), strict=True)
        ],
        crs="epsg:4326",
    )
    return gdf


@pytest.mark.parametrize("suffix", [".gpkg", ".shp"])
def test_add_column(tmp_path, suffix):
    test_path = test_helper.get_testfile(
        "polygon-parcel", dst_dir=tmp_path, suffix=suffix
    )
    layer = "parcels" if suffix == ".gpkg" else None
    geom_column = "geom" if suffix == ".gpkg" else "geometry"

    # The area column shouldn't be in the test file yet
    layerinfo = gfo.get_layerinfo(path=test_path, layer=layer)
    assert "AREA" not in layerinfo.columns

    # Add area column
    expression = f"ST_area({geom_column})"
    gfo.add_column(
        test_path, layer=layer, name="AREA", type="real", expression=expression
    )

    layerinfo = gfo.get_layerinfo(path=test_path, layer=layer)
    assert "AREA" in layerinfo.columns

    gdf = gfo.read_file(test_path)
    assert round(gdf["AREA"].astype("float")[0], 1) == round(
        gdf["OPPERVL"].astype("float")[0], 1
    )

    # Add perimeter column
    expression = f"ST_perimeter({geom_column})"
    gfo.add_column(
        test_path, name="PERIMETER", type=gfo.DataType.REAL, expression=expression
    )

    layerinfo = gfo.get_layerinfo(path=test_path, layer=layer)
    assert "AREA" in layerinfo.columns

    gdf = gfo.read_file(test_path)
    assert round(gdf["AREA"].astype("float")[0], 1) == round(
        gdf["OPPERVL"].astype("float")[0], 1
    )

    info = gfo.get_layerinfo(test_path)

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


@pytest.mark.parametrize(
    "suffix, col_type, col_type_supported, exp_gdal_type",
    [
        (".gpkg", "Binary", True, "Binary"),
        (".gpkg", "Blob", True, "Binary"),
        (".gpkg", "Date", True, "Date"),
        (".gpkg", "DateTime", True, "DateTime"),
        (".gpkg", "Integer", True, "Integer64"),
        (".gpkg", "Text", True, "String"),
        (".gpkg", "Time", True, "DateTime"),
        (".gpkg", "Real", True, "Real"),
        (".gpkg", "Invalid", False, "Invalid"),
        (".shp", "Binary", True, "String"),
        (".shp", "Blob", True, "String"),
        (".shp", "Date", True, "Date"),
        (".shp", "DateTime", True, "String"),
        (".shp", "Integer", True, "Integer"),
        (".shp", "String", True, "String"),
        (".shp", "Text", True, "String"),
        (".shp", "Time", True, "String"),
        (".shp", "Real", True, "Real"),
        (".shp", "Invalid", True, "String"),
    ],
)
def test_add_column_types(
    tmp_path, suffix, col_type, col_type_supported, exp_gdal_type
):
    """Test adding columns of different types."""
    # Before GDAL 3.11, Datetimes were saved in a Date column instead of a String column
    # for shapefiles
    if not GDAL_GTE_311 and suffix == ".shp" and col_type in ("DateTime", "Time"):
        exp_gdal_type = "Date"

    test_path = test_helper.get_testfile(
        "polygon-parcel", suffix=suffix, dst_dir=tmp_path
    )

    column_name_add_column = f"tst_{col_type}"
    column_name_add_columns = f"tst2_{col_type}"
    if suffix == ".shp":
        # Shapefile column name length limit = 10
        column_name_add_column = column_name_add_column[:10]
        column_name_add_columns = column_name_add_columns[:10]

    handler = nullcontext() if col_type_supported else pytest.raises(RuntimeError)
    with handler:
        gfo.add_column(test_path, name=column_name_add_column, type=col_type)

        info = gfo.get_layerinfo(test_path)
        assert column_name_add_column in info.columns
        assert info.columns[column_name_add_column].gdal_type == exp_gdal_type

        gfo.add_columns(test_path, [(column_name_add_columns, col_type)])

        info = gfo.get_layerinfo(test_path)
        assert column_name_add_columns in info.columns
        assert info.columns[column_name_add_columns].gdal_type == exp_gdal_type


@pytest.mark.parametrize(
    "suffix, transaction_supported", [(".gpkg", True), (".shp", False)]
)
def test_add_column_update_error(tmp_path, suffix, transaction_supported):
    """Test on the result of an invalid update expression.

    If the file format supports transactions, the column should not be added.
    """
    test_path = test_helper.get_testfile(
        "polygon-parcel", dst_dir=tmp_path, suffix=suffix
    )

    # Add a column with an invalid expression
    with pytest.raises(RuntimeError, match="add_column error for"):
        gfo.add_column(
            test_path, name="ERROR_COL", type="TEXT", expression="invalid_expression"
        )

    # For formats that support transactions, the column should not be there
    info = gfo.get_layerinfo(test_path)
    if transaction_supported:
        assert "ERROR_COL" not in list(info.columns)
    else:
        assert "ERROR_COL" in list(info.columns)


@pytest.mark.parametrize("output_stem", [None, "new_parcels"])
@pytest.mark.parametrize("do_updates", [True, False])
@pytest.mark.parametrize("suffix", [".gpkg", ".shp"])
def test_add_columns(tmp_path, output_stem, do_updates, suffix):
    """Test the add_columns function."""
    test_path = test_helper.get_testfile(
        "polygon-parcel", dst_dir=tmp_path, suffix=suffix
    )
    test_input_gdf = gfo.read_file(test_path)

    # Columns to add. Column lengths max 10 characters for shapefiles
    test_info = gfo.get_layerinfo(path=test_path)
    new_columns = [
        ("GEWASGROEP", "string", "'testdata'"),
        ("TST_AREA", "real", f"ST_area({test_info.geometrycolumn})"),
        ("TST_PERIM", gfo.DataType.REAL, f"ST_perimeter({test_info.geometrycolumn})"),
        ("TST_INT", "integer", "1"),
        ("TST_STR", "string", "'test'"),
        ("TST_STR_N", "string", None),
        ("TST_REAL_N", "real", None),
        ("TST_INT_N", "integer", None),
    ]

    # If no updates to be done, set expressions to None
    if not do_updates:
        new_columns = [(name, col_type, None) for name, col_type, _ in new_columns]

    # Make sure the columns are not in the test file yet, except for GEWASGROEP
    layerinfo = gfo.get_layerinfo(path=test_path)
    for col_name, _, _ in new_columns:
        if col_name == "GEWASGROEP":
            assert col_name in layerinfo.columns
        else:
            assert col_name not in layerinfo.columns

    # This is the test dir that most likely will be created during the operation. Make
    # sure it doesn't exist yet.
    tmp_dir = ConfigOptions.tmp_dir / "add_columns_000001"
    shutil.rmtree(tmp_dir, ignore_errors=True)

    output_path = None if output_stem is None else tmp_path / f"{output_stem}{suffix}"
    with gfo.TempEnv({"GFO_REMOVE_TEMP_FILES": False}):
        gfo.add_columns(test_path, new_columns=new_columns, output_path=output_path)

    # Check result
    output_path = test_path if output_path is None else output_path
    output_layerinfo = gfo.get_layerinfo(path=output_path)

    # Check if columns were added
    for col_name, col_type, _ in new_columns:
        assert col_name in output_layerinfo.columns
        exp_type = (col_type if isinstance(col_type, str) else col_type.value).lower()
        output_type = output_layerinfo.columns[col_name].gdal_type.lower()
        assert output_type.startswith(exp_type), (
            f"Column {col_name}: expected {exp_type}, got {output_type}"
        )

    # Check content
    gdf = gfo.read_file(output_path)

    # The area and perimeter columns added should have similar values as the original
    if do_updates:
        assert round(gdf["TST_AREA"].astype("float")[0], 1) == round(
            gdf["OPPERVL"].astype("float")[0], 1
        )
        assert round(gdf["TST_PERIM"].astype("float")[0], 1) == round(
            gdf["LENGTE"].astype("float")[0], 1
        )

        # do_updates: the columns added with constant values should have those values
        assert all(gdf["TST_INT"] == 1)
        assert all(gdf["TST_STR"] == "test")

        # do_updates: GEWASGROEP column should be overwritten to 'testdata'
        assert all(gdf["GEWASGROEP"] == "testdata")
    else:
        # No updates, so new columns should have NaN values
        assert all(pd.isna(gdf["TST_INT"]))
        assert all(pd.isna(gdf["TST_STR"]))

        # No updates, so GEWASGROEP column should NOT be overwritten to 'testdata'
        assert all(gdf["GEWASGROEP"] == test_input_gdf["GEWASGROEP"])

    # The NULL columns should have NaN values
    assert all(pd.isna(gdf["TST_STR_N"]))
    assert all(pd.isna(gdf["TST_REAL_N"]))
    assert all(pd.isna(gdf["TST_INT_N"]))

    # Check the tmp_dir
    if output_stem is not None or do_updates:
        # If an output_path is given or if updates are done, the tmp dir should exist
        assert tmp_dir.exists()
        shutil.rmtree(tmp_dir, ignore_errors=True)
    else:
        assert not tmp_dir.exists()


@pytest.mark.parametrize(
    "kwargs, exp_exception, exp_error",
    [
        (
            {"new_columns": ("AREA", "real", "ST_area(geom)")},
            TypeError,
            "new_columns should be a non-empty list of tuples",
        ),
        (
            {"new_columns": [("AREA", "real", "ST_area(geom)", "extra")]},
            TypeError,
            "each element in new_columns should be a tuple with 2 or 3 elements",
        ),
        (
            {"new_columns": [("AREA")]},
            TypeError,
            "each element in new_columns should be a tuple with 2 or 3 elements",
        ),
        (
            {"new_columns": ["AREA"]},
            TypeError,
            "each element in new_columns should be a tuple with 2 or 3 elements",
        ),
        (
            {
                "new_columns": [("AREA", "real", "ST_area(geom)")],
                "output_layer": "new_parcels",
            },
            ValueError,
            "output_layer can only be used together with output_path",
        ),
        (
            {"new_columns": [("AREA", "INVALID", "ST_area(geometry)")]},
            RuntimeError,
            "add_columns of name='AREA', type_str='INVALID' failed",
        ),
    ],
)
@pytest.mark.filterwarnings("ignore:Field format 'INVALID' not supported")
@pytest.mark.filterwarnings("ignore:geometry column 'AREA' of type 'INVALID' ignored")
def test_add_columns_errors(tmp_path, kwargs, exp_exception, exp_error):
    test_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)

    # new_columns not a list
    with pytest.raises(exp_exception, match=exp_error):
        gfo.add_columns(test_path, **kwargs)


def test_add_columns_errors_different_output_suffix(tmp_path):
    """Test error when output_path has a different suffix than input file."""
    test_path = test_helper.get_testfile("polygon-parcel", suffix=".gpkg")

    # Create an output path with different suffix
    output_path = tmp_path / "output.shp"
    with pytest.raises(
        ValueError, match="output_path should have the same suffix as the input path"
    ):
        gfo.add_columns(
            test_path, new_columns=[("AREA", "real")], output_path=output_path
        )


@pytest.mark.parametrize(
    "testfile, suffix, input_layer, output_layer, exp_output_layer",
    [
        ("polygon-parcel", ".shp", "DEFAULT", None, "output_file"),
        ("polygon-parcel", ".shp", "DEFAULT", "output_layer", "output_file"),
        ("polygon-parcel", ".gpkg", "parcels", "output_layer", "output_layer"),
        ("polygon-parcel", ".gpkg", "parcels", None, "output_file"),
        ("polygon-parcel", ".gpkg", "DEFAULT", "output_layer", "output_layer"),
        ("polygon-parcel", ".gpkg", "DEFAULT", None, "output_file"),
        ("polygon-twolayers", ".gpkg", "parcels", None, "parcels"),
        ("polygon-twolayers", ".gpkg", "DEFAULT", None, "INPUT_LAYER"),
        ("polygon-twolayers", ".gpkg", "parcels", "output_layer", "output_layer"),
    ],
)
def test_add_columns_output_layer(
    tmp_path, testfile, suffix, input_layer, output_layer, exp_output_layer
):
    """Test the add_columns function with output_layer parameter.

    Remark: output_layer is ignored for single-layer file formats such as shapefiles.
    """
    test_path = test_helper.get_testfile(testfile, dst_dir=tmp_path, suffix=suffix)
    if input_layer == "DEFAULT":
        input_layer = gfo.get_default_layer(test_path)
    if suffix == ".gpkg":
        gfo.rename_layer(test_path, new_layer=input_layer, layer="parcels")

    # Columns to add
    new_columns = [("new_column", "string")]

    output_path = tmp_path / f"output_file{suffix}"
    gfo.add_columns(
        test_path,
        layer=input_layer,
        new_columns=new_columns,
        output_path=output_path,
        output_layer=output_layer,
    )

    # Check result
    if exp_output_layer == "DEFAULT":
        exp_output_layer = gfo.get_default_layer(output_path)
    elif exp_output_layer == "INPUT_LAYER":
        exp_output_layer = input_layer
    output_layerinfo = gfo.get_layerinfo(path=output_path, layer=exp_output_layer)
    assert output_layerinfo.name == exp_output_layer

    # Check if columns were added
    for col_name, col_type in new_columns:
        assert col_name in output_layerinfo.columns
        exp_type = (col_type if isinstance(col_type, str) else col_type.value).lower()
        output_type = output_layerinfo.columns[col_name].gdal_type.lower()
        assert output_type.startswith(exp_type), (
            f"Column {col_name}: expected {exp_type}, got {output_type}"
        )


def test_append_to(tmp_path):
    """Test the append_to function.

    It is deprecated, but is still kept alive for backwards compatibility.
    """
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    dst = tmp_path / "output.gpkg"
    gfo.copy(src, dst)
    layer = gfo.get_only_layer(dst)

    # Append to file
    with pytest.warns(FutureWarning):
        gfo.append_to(src, dst, dst_layer=layer)

    # Test if number of rows is correct
    info = gfo.get_layerinfo(dst)
    assert info.featurecount == 96


@pytest.mark.parametrize("force_update", [True, False])
def test_add_columns_existing(tmp_path, force_update):
    """Test adding columns that already exist."""
    test_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)

    # Columns to add
    new_columns = [
        ("GEWASGROEP", "string", "'testdata'"),
        ("UIDN", "integer64", "9999"),
    ]

    # Make sure the columns are in the test file already
    layerinfo = gfo.get_layerinfo(path=test_path, layer="parcels")
    for col_name, _, _ in new_columns:
        assert col_name in layerinfo.columns

    gfo.add_columns(
        test_path,
        layer="parcels",
        new_columns=new_columns,
        force_update=force_update,
    )

    # Check result
    output_layerinfo = gfo.get_layerinfo(path=test_path, layer="parcels")

    # Check if columns are still there
    for col_name, col_type, _ in new_columns:
        assert col_name in output_layerinfo.columns
        exp_type = (col_type if isinstance(col_type, str) else col_type.value).lower()
        output_type = output_layerinfo.columns[col_name].gdal_type.lower()
        assert output_type == exp_type, (
            f"Column {col_name}: expected {exp_type}, got {output_type}"
        )

    # Check content
    gdf = gfo.read_file(test_path)

    if force_update:
        # If force_update, the new values should be there
        assert all(gdf["GEWASGROEP"] == "testdata")
        assert all(gdf["UIDN"] == 9999)
    else:
        # If not force_update, the original values should be kept
        assert all(gdf["GEWASGROEP"] != "testdata")
        assert all(gdf["UIDN"] != 9999)


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS_EXT)
@pytest.mark.parametrize("keep_permissions", [True, False])
def test_cmp(tmp_path, suffix, keep_permissions):
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    src2 = test_helper.get_testfile("polygon-invalid", suffix=suffix)

    # Copy test file to tmpdir
    dst = tmp_path / f"polygons_parcels_output{suffix}"
    gfo.copy(str(src), str(dst), keep_permissions=keep_permissions)

    # Now compare source and dst files
    assert gfo.cmp(src, dst) is True
    assert gfo.cmp(src2, dst) is False


def test_convert(tmp_path):
    """Test the convert function.

    The function is deprecated, but is still kept alive for backwards compatibility.
    """
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel")
    dst = tmp_path / "output.gpkg"

    # Test
    with pytest.warns(FutureWarning):
        gfo.convert(src, dst)

    # Now compare source and dst file
    src_layerinfo = gfo.get_layerinfo(src)
    dst_layerinfo = gfo.get_layerinfo(dst)
    assert src_layerinfo.featurecount == dst_layerinfo.featurecount
    assert len(src_layerinfo.columns) == len(dst_layerinfo.columns)
    assert src_layerinfo.geometrytypename == dst_layerinfo.geometrytypename


@pytest.mark.parametrize(
    "testfile, suffix_input, suffix_output",
    [
        *product(["polygon-parcel"], SUFFIXES_FILEOPS_EXT, SUFFIXES_FILEOPS_EXT),
        ["curvepolygon", ".gpkg", ".gpkg"],
    ],
)
def test_copy_layer(tmp_path, testfile, suffix_input, suffix_output):
    if suffix_input == ".shp.zip" and suffix_output == ".shp":
        # GDAL < 3.10 determines the layer name wrong for .shp.zip leading to this error
        pytest.xfail("Copy of .shp.zip gives issues in GDAL <= 3.10")

    # Prepare test data
    src = test_helper.get_testfile(testfile, suffix=suffix_input)
    if suffix_input == ".csv" or suffix_output == ".csv":
        raise_on_nogeom = False
    else:
        raise_on_nogeom = True

    if suffix_input == ".csv" and suffix_output in (".shp", ".shp.zip"):
        # If no geometry column, there will only be a .dbf output file
        dst = tmp_path / f"{src.stem}-output.dbf"
    else:
        dst = tmp_path / f"{src.stem}-output{suffix_output}"

    # Test
    gfo.copy_layer(str(src), str(dst))

    # Now compare source and dst file
    src_layerinfo = gfo.get_layerinfo(src, raise_on_nogeom=raise_on_nogeom)
    dst_layerinfo = gfo.get_layerinfo(dst, raise_on_nogeom=raise_on_nogeom)
    assert dst_layerinfo.name == gfo.get_default_layer(dst)
    assert src_layerinfo.featurecount == dst_layerinfo.featurecount
    assert len(src_layerinfo.columns) == len(dst_layerinfo.columns)
    if not (
        (suffix_input != ".csv" and suffix_output == ".csv")
        or (suffix_input == ".shp" and suffix_output == ".gpkg")
    ):
        assert src_layerinfo.geometrytypename == dst_layerinfo.geometrytypename


@pytest.mark.parametrize(
    "testfile, suffix_input, suffix_output",
    [
        *product(["polygon-parcel"], [".gpkg", ".shp"], [".gpkg", ".shp"]),
        ["curvepolygon", ".gpkg", ".gpkg"],
    ],
)
def test_copy_layer_dimensions_xyz(tmp_path, testfile, suffix_input, suffix_output):
    # Prepare test data
    src = test_helper.get_testfile(testfile, suffix=suffix_input, dimensions="XYZ")
    dst = tmp_path / f"{src.stem}-output{suffix_output}"

    # Test
    gfo.copy_layer(str(src), str(dst))

    # Now compare source and dst file
    src_layerinfo = gfo.get_layerinfo(src)
    dst_layerinfo = gfo.get_layerinfo(dst)
    assert dst_layerinfo.name == dst.stem
    assert src_layerinfo.featurecount == dst_layerinfo.featurecount
    assert len(src_layerinfo.columns) == len(dst_layerinfo.columns)
    if not (suffix_input == ".shp" and suffix_output == ".gpkg"):
        assert src_layerinfo.geometrytypename == dst_layerinfo.geometrytypename


def test_copy_layer_add_layer_gpkg(tmp_path):
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel")
    dst = tmp_path / "output.gpkg"
    layer1 = gfo.get_default_layer(dst)

    # First "add_layer" to file already while the file doesn't exist yet
    gfo.copy_layer(src, dst, dst_layer=layer1, write_mode="add_layer")

    # Check result
    layer1_info = gfo.get_layerinfo(dst, layer1)
    assert layer1_info.featurecount == 48

    # Now "add_layer" with the layer existing, and use force=True to overwrite it.
    # Use a filter so it is clear it was overwritten.
    gfo.copy_layer(
        src, dst, dst_layer=layer1, write_mode="add_layer", where="OIDN=1", force=True
    )

    # Check if the layer was properly overwritten
    assert gfo.listlayers(dst) == [layer1]
    layer1_info = gfo.get_layerinfo(dst, layer1)
    assert layer1_info.featurecount == 1

    # Now "add_layer" with the layer existing, and use force=False not to overwrite it.
    gfo.copy_layer(src, dst, dst_layer=layer1, write_mode="add_layer", force=False)

    # Check if the layer was properly overwritten
    assert gfo.listlayers(dst) == [layer1]
    layer1_info = gfo.get_layerinfo(dst, layer1)
    assert layer1_info.featurecount == 1

    # Finally "add_layer" to a new layer name
    layer2 = "new_layer"
    gfo.copy_layer(src, dst, dst_layer=layer2, write_mode="add_layer")

    # Check properties of both layers
    layer1_info = gfo.get_layerinfo(dst, layer1)
    assert layer1_info.featurecount == 1

    layer2_info = gfo.get_layerinfo(dst, layer2)
    assert layer2_info.featurecount == 48


def test_copy_layer_add_layer_shp(tmp_path):
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel")
    dst = tmp_path / "output.shp"
    layer1 = gfo.get_default_layer(dst)

    # First "add_layer" to file already while the file doesn't exist yet
    gfo.copy_layer(src, dst, dst_layer=layer1, write_mode="add_layer")

    # Check result
    layer1_info = gfo.get_layerinfo(dst, layer1)
    assert layer1_info.featurecount == 48


@pytest.mark.parametrize("write_mode", ["append", "append_add_fields"])
def test_copy_layer_append_different_layer(tmp_path, write_mode):
    # Prepare test data
    src_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    dst_path = tmp_path / "dst.gpkg"

    # Copy src file to dst file to "layer1"
    gfo.copy_layer(
        str(src_path), str(dst_path), dst_layer="layer1", write_mode=write_mode
    )
    src_info = gfo.get_layerinfo(src_path)
    dst_layer1_info = gfo.get_layerinfo(dst_path, "layer1")
    assert src_info.featurecount == dst_layer1_info.featurecount

    # Append src file layer to dst file to new layer: "layer2"
    gfo.copy_layer(src_path, dst_path, dst_layer="layer2", write_mode="append")
    dst_layer2_info = gfo.get_layerinfo(dst_path, "layer2")
    assert dst_layer1_info.featurecount == dst_layer2_info.featurecount


@pytest.mark.parametrize("write_mode", ["append", "append_add_fields"])
@pytest.mark.parametrize("limit_dst_columns", [True, False])
@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS)
def test_copy_layer_append_columns(tmp_path, write_mode, limit_dst_columns, suffix):
    """Test appending rows specifying some columns.

    Both the situation where the dst file has the same columns as the columns being
    appended, and where the dst file has more columns than the columns being appended
    tested.

    This doesn't seem to be supported by GDAL .csv.
    """
    # Prepare test data
    src_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    dst_path = tmp_path / f"dst{suffix}"
    gfo.copy(src_path, dst_path, keep_permissions=False)
    dst_columns = ["OIDN", "UIDN", "GEWASGROEP"]

    # Remove columns we are not going to copy from the dst file.
    dst_info_orig = gfo.get_layerinfo(dst_path, raise_on_nogeom=False)
    columns_orig = list(dst_info_orig.columns)
    if limit_dst_columns:
        for column in columns_orig:
            if column not in dst_columns:
                gfo.drop_column(dst_path, column_name=column)
        exp_columns = len(dst_columns)
    else:
        exp_columns = len(columns_orig)

    if suffix == ".csv":
        pytest.xfail("Appending only certain columns is not supported for .csv.")

    dst_layer = "parcels" if suffix == ".gpkg" else None
    gfo.copy_layer(
        src_path,
        dst_path,
        columns=dst_columns,
        dst_layer=dst_layer,
        write_mode=write_mode,
    )

    # Check results
    src_info = gfo.get_layerinfo(src_path, raise_on_nogeom=False)
    dst_info = gfo.get_layerinfo(dst_path, raise_on_nogeom=False)
    assert (src_info.featurecount * 2) == dst_info.featurecount
    assert len(dst_info.columns) == exp_columns


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS)
def test_copy_layer_append_default_layer(tmp_path, suffix):
    """Test appending rows to a file without specifying a layer name."""
    # Prepare test data
    src_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    dst_path = tmp_path / f"dst{suffix}"

    # Copy src file to dst file to "layer1"
    gfo.copy_layer(src_path, dst_path, write_mode="append")
    src_info = gfo.get_layerinfo(src_path, raise_on_nogeom=False)
    dst_info = gfo.get_layerinfo(dst_path, raise_on_nogeom=False)
    assert dst_info.featurecount == src_info.featurecount

    # Append src file layer to dst file to new layer: "layer2"
    gfo.copy_layer(src_path, dst_path, write_mode="append")
    dst_info = gfo.get_layerinfo(dst_path, raise_on_nogeom=False)
    assert dst_info.featurecount == src_info.featurecount * 2


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS)
@pytest.mark.parametrize("write_mode", ["append", "append_add_fields"])
def test_copy_layer_append_different_columns(tmp_path, write_mode, suffix):
    """Test appending rows to a file with a column less than in source file."""
    # Prepare test data
    src_path = test_helper.get_testfile(
        "polygon-parcel", dst_dir=tmp_path, suffix=suffix
    )
    dst_path = tmp_path / f"dst{suffix}"
    gfo.copy_layer(src_path, dst_path)
    gfo.add_column(src_path, name="extra_col", type=gfo.DataType.INTEGER)
    raise_on_nogeom = suffix != ".csv"
    dst_orig_info = gfo.get_layerinfo(dst_path, raise_on_nogeom=raise_on_nogeom)

    # All rows are appended tot the dst layer, but the extra column is not!
    gfo.copy_layer(src_path, dst_path, write_mode=write_mode)

    # Check results
    src_info = gfo.get_layerinfo(src_path, raise_on_nogeom=raise_on_nogeom)
    res_info = gfo.get_layerinfo(dst_path, raise_on_nogeom=raise_on_nogeom)
    exp_columns = len(dst_orig_info.columns)
    if write_mode == "append_add_fields":
        # With add_fields, the extra column should is added to the dst layer
        exp_columns += 1

    assert (src_info.featurecount * 2) == res_info.featurecount
    assert len(res_info.columns) == exp_columns


@pytest.mark.parametrize("write_mode", ["append", "append_add_fields"])
def test_copy_layer_append_error_non_default_layer(tmp_path, write_mode):
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel")
    dst = tmp_path / "output.gpkg"
    gfo.copy(src, dst, keep_permissions=False)

    # Append fails if no layer is specified and a layer that does not have the default
    # layer name exists already
    with pytest.raises(ValueError, match="dst_layer is required when write_mode is"):
        gfo.copy_layer(src, dst, write_mode=write_mode)


@pytest.mark.parametrize("write_mode", ["append", "append_add_fields"])
def test_copy_layer_append_error_other_layers(tmp_path, write_mode):
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel")
    dst = tmp_path / "output.gpkg"
    gfo.copy(src, dst, keep_permissions=False)
    gfo.copy_layer(
        src, dst, write_mode="add_layer", dst_layer=gfo.get_default_layer(dst)
    )

    # Append fails if no layer is specified and multiple layers exist already, even if
    # one of them has the default layer name
    with pytest.raises(ValueError, match="dst_layer is required when write_mode is"):
        gfo.copy_layer(src, dst, write_mode=write_mode)


@pytest.mark.parametrize("testfile", ["polygon-parcel", "curvepolygon"])
def test_copy_layer_append_shp_laundered_columns(tmp_path, testfile):
    # GDAL doesn't seem to handle appending to a shapefile where column laundering is
    # needed very well: all laundered columns get NULL values instead of the actual
    # values.
    # gfo.append_to bypasses this by laundering the columns beforehand via an sql
    # statement so gdal doesn't need to do laundering.
    # Start from a gpkg test file, because that can have long column names that need
    # laundering.
    src_path = test_helper.get_testfile(testfile, dst_dir=tmp_path, suffix=".gpkg")
    gfo.add_column(
        src_path, name="extra_long_columnname", type="TEXT", expression="'TEST VALUE'"
    )
    dst_path = tmp_path / "dst.shp"
    gfo.copy_layer(src_path, dst_path, write_mode="append")
    gfo.copy_layer(src_path, dst_path, write_mode="append")

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


@pytest.mark.parametrize("create_spatial_index", [True, False])
def test_copy_layer_append_spatial_index(tmp_path, create_spatial_index):
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel")
    dst = tmp_path / "output.gpkg"
    layer1 = gfo.get_default_layer(dst)

    if create_spatial_index is not None:
        index_expected = create_spatial_index
    else:
        index_expected = _geofileinfo.get_geofileinfo(dst).default_spatial_index

    # First append to file already while it doesn't exist yet
    gfo.copy_layer(
        src, dst, write_mode="append", create_spatial_index=create_spatial_index
    )

    # Check result
    layer1_info = gfo.get_layerinfo(dst)
    assert layer1_info.featurecount == 48
    assert gfo.has_spatial_index(dst) == index_expected

    # Now append while the file exists to the existing layer
    gfo.copy_layer(
        src, dst, write_mode="append", create_spatial_index=create_spatial_index
    )

    # Check if number of rows is correct
    layer1_info = gfo.get_layerinfo(dst)
    assert layer1_info.featurecount == 96
    assert gfo.has_spatial_index(dst) == index_expected

    # Finally append while the file exists but to a new layer
    layer2 = "new_layer"
    gfo.copy_layer(
        src,
        dst,
        dst_layer=layer2,
        write_mode="append",
        create_spatial_index=create_spatial_index,
    )

    # Check properties of both layers
    layer1_info = gfo.get_layerinfo(dst, layer1)
    assert layer1_info.featurecount == 96
    assert gfo.has_spatial_index(dst, layer1) == index_expected

    layer2_info = gfo.get_layerinfo(dst, layer2)
    assert layer2_info.featurecount == 48
    assert gfo.has_spatial_index(dst, layer2) == index_expected


@pytest.mark.parametrize("suffix", [s for s in SUFFIXES_FILEOPS if s != ".csv"])
@pytest.mark.parametrize("columns", [["OIDN", "UIDN"], "OIDN"])
def test_copy_layer_columns(tmp_path, suffix, columns):
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Test
    dst = tmp_path / f"output{suffix}"
    gfo.copy_layer(src, dst, columns=columns)
    copy_gdf = gfo.read_file(dst)
    input_gdf = gfo.read_file(src, columns=columns)
    assert_geodataframe_equal(input_gdf, copy_gdf)


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS)
@pytest.mark.parametrize("dimensions", [None, "XYZ"])
def test_copy_layer_emptyfile(tmp_path, dimensions, suffix):
    # Prepare test data
    src = test_helper.get_testfile(
        "polygon-parcel",
        suffix=suffix,
        dst_dir=tmp_path,
        empty=True,
        dimensions=dimensions,
    )
    raise_on_nogeom = suffix != ".csv"
    dst = tmp_path / f"{src.stem}-output{suffix}"

    # Convert
    gfo.copy_layer(src, dst)

    # Now compare source and dst file
    assert dst.exists()
    src_layerinfo = gfo.get_layerinfo(src, raise_on_nogeom=raise_on_nogeom)
    dst_layerinfo = gfo.get_layerinfo(dst, raise_on_nogeom=raise_on_nogeom)
    assert src_layerinfo.featurecount == dst_layerinfo.featurecount
    assert len(src_layerinfo.columns) == len(dst_layerinfo.columns)
    assert src_layerinfo.geometrytypename == dst_layerinfo.geometrytypename


@pytest.mark.parametrize(
    "testfile, expected_count", [("polygon-parcel", 50), ("point", 50)]
)
def test_copy_layer_explodecollections(tmp_path, testfile, expected_count):
    # Prepare test data
    src = test_helper.get_testfile(testfile)
    dst = tmp_path / f"{src.stem}.gpkg"

    # copy_layer, with explodecollections. Default behaviour of gdal was to try to
    # preserve the fids, but this didn't work with explodecolledtions, this was
    # overruled in #395
    gfo.copy_layer(src, dst, explodecollections=True)

    result_gdf = gfo.read_file(dst)
    assert len(result_gdf) == expected_count


@pytest.mark.parametrize("suffix_input, suffix_output", [(".shp", ".kml")])
@pytest.mark.filterwarnings("ignore: Multiple drivers found, using first one of")
def test_copy_layer_extra_formats(tmp_path, suffix_input, suffix_output):
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix_input)

    # Run test
    dst = tmp_path / f"output{suffix_output}"
    gfo.copy_layer(src=src, dst=dst)

    # Check result
    result_gdf = gfo.read_file(dst)
    assert len(result_gdf) == 48


@pytest.mark.parametrize(
    "testfile, force_geometrytype",
    [
        ("polygon-parcel", GeometryType.POLYGON),
        ("polygon-parcel", GeometryType.MULTIPOLYGON),
        ("polygon-parcel", GeometryType.MULTILINESTRING),
        ("polygon-parcel", GeometryType.MULTIPOINT),
    ],
)
@pytest.mark.filterwarnings(
    "ignore:.*A geometry of type MULTIPOLYGON is inserted into .*"
)
def test_copy_layer_force_output_geometrytype(tmp_path, testfile, force_geometrytype):
    # The conversion is done by ogr, and the "test" is rather written to
    # explore the behaviour of this ogr functionality:
    # Single-part polygons are converted to the destination types, but multipolygons
    # are kept as they are.
    # Issue opened for this: https://github.com/OSGeo/gdal/issues/11068

    # copy_layer on testfile and force to force_geometrytype
    src = test_helper.get_testfile(testfile)
    dst = tmp_path / f"{src.stem}_to_{force_geometrytype}.gpkg"
    gfo.copy_layer(src, dst, force_output_geometrytype=force_geometrytype)
    assert gfo.get_layerinfo(dst).geometrytype == force_geometrytype

    result_gdf = gfo.read_file(dst)
    assert len(result_gdf) == 48


@pytest.mark.parametrize(
    "kwargs, exp_ex, exp_error",
    [
        ({"src": "non_existing_file.gpkg"}, FileNotFoundError, "File not found"),
        ({"write_mode": "invalid"}, ValueError, "Invalid write_mode"),
        (
            {"write_mode": "add_layer"},
            ValueError,
            "dst_layer is required when write_mode is",
        ),
        (
            {"write_mode": "append", "append": True},
            ValueError,
            "append parameter is deprecated, use write_mode",
        ),
        (
            {"src": test_helper.get_testfile("polygon-twolayers")},
            ValueError,
            "input has > 1 layers: a layer must be specified",
        ),
    ],
)
def test_copy_layer_errors(tmp_path, kwargs, exp_ex, exp_error):
    # Convert
    if "src" not in kwargs:
        kwargs["src"] = test_helper.get_testfile("polygon-parcel")
    kwargs["dst"] = tmp_path / "output.gpkg"

    with pytest.raises(exp_ex, match=exp_error):
        gfo.copy_layer(**kwargs)


def test_copy_layer_input_open_options(tmp_path):
    # Prepare test data
    src = tmp_path / "input.csv"
    dst = tmp_path / "output.gpkg"
    with src.open("w") as srcfile:
        srcfile.write("POINT_ID, POINT_LAT, POINT_LON, POINT_NAME\n")
        srcfile.write('1, 50.939972761,3.888498686, "random spot"\n')

    # copy_layer with open_options
    gfo.copy_layer(
        src,
        dst,
        options={
            "INPUT_OPEN.X_POSSIBLE_NAMES": "POINT_LON",
            "INPUT_OPEN.Y_POSSIBLE_NAMES": "POINT_LAT",
        },
        dst_crs="EPSG:4326",
    )

    # Check result
    assert dst.exists()
    result_gdf = gfo.read_file(dst)
    assert len(result_gdf) == 1
    assert "geometry" in result_gdf.columns
    assert result_gdf.geometry[0].x == 3.888498686
    assert result_gdf.geometry[0].y == 50.939972761


@pytest.mark.parametrize("layer", [None, "parcels_output"])
def test_copy_layer_layer(tmp_path, layer):
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel")
    dst = tmp_path / "output.gpkg"
    expected_layer = dst.stem if layer is None else layer

    gfo.copy_layer(src, dst, dst_layer=layer)

    # Check result
    dst_info = gfo.get_layerinfo(dst)
    assert dst_info.name == expected_layer
    assert dst_info.featurecount == 48


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
def test_copy_layer_preserve_fid(
    tmp_path,
    src_suffix: str,
    dst_suffix: str,
    preserve_fid: bool,
    exp_preserved_fids: bool,
):
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", suffix=src_suffix)
    dst = tmp_path / f"{src.stem}-output_preserve_fid-{preserve_fid}{dst_suffix}"

    # copy_layer
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


@pytest.mark.parametrize("suffix", [s for s in SUFFIXES_FILEOPS if s != ".csv"])
@pytest.mark.parametrize("src_crs", [None, 31370])
def test_copy_layer_reproject(tmp_path, suffix, src_crs):
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    dst = tmp_path / f"{src.stem}-output_reproj4326{suffix}"

    # copy_layer with reproject
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


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS)
def test_copy_layer_sql(tmp_path, suffix):
    # Prepare test data
    # For multi-layer filetype, use 2-layer file for better test coverage
    if _geofileinfo.get_geofileinfo(suffix).is_singlelayer:
        testfile = "polygon-parcel"
        src = test_helper.get_testfile(testfile, suffix=suffix)
        src_layer = src.stem
    else:
        testfile = "polygon-twolayers"
        src = test_helper.get_testfile(testfile, suffix=suffix)
        src_layer = "parcels"

    # Test
    sql_stmt = f'SELECT * FROM "{src_layer}"'
    dst = tmp_path / f"output{suffix}"
    gfo.copy_layer(src, dst, src_layer=src_layer, sql_stmt=sql_stmt)
    read_gdf = gfo.read_file(src, sql_stmt=sql_stmt)
    assert isinstance(read_gdf, pd.DataFrame)
    if suffix != ".csv":
        assert isinstance(read_gdf, gpd.GeoDataFrame)
    assert len(read_gdf) == 48


@pytest.mark.parametrize("suffix", [s for s in SUFFIXES_FILEOPS if s != ".csv"])
def test_copy_layer_sql_placeholders(tmp_path, suffix):
    """
    Test if placeholders are properly filled out + if casing used in columns parameter
    is retained when using placeholders.
    """
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Test
    sql_stmt = """
        SELECT {geometrycolumn} AS geom
              {columns_to_select_str}
          FROM "{input_layer}"
    """
    dst = tmp_path / f"output{suffix}"
    gfo.copy_layer(src, dst, sql_stmt=sql_stmt, sql_dialect="SQLITE", columns=["OIDN"])
    copy_gdf = gfo.read_file(dst)
    input_gdf = gfo.read_file(src, columns=["OIDN"])
    assert_geodataframe_equal(input_gdf, copy_gdf)


def test_copy_layer_to_gpkg_zip(tmp_path):
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel")
    dst = tmp_path / "output.gpkg.zip"

    # copy_layer
    gfo.copy_layer(src, dst)

    # Now compare source and dst file
    src_layerinfo = gfo.get_layerinfo(src)
    dst_layerinfo = gfo.get_layerinfo(dst)
    assert src_layerinfo.featurecount == dst_layerinfo.featurecount

    src_gdf = gfo.read_file(src)
    dst_gdf = gfo.read_file(dst)
    assert_geodataframe_equal(src_gdf, dst_gdf)


def test_copy_layer_twolayers(tmp_path):
    src = test_helper.get_testfile("polygon-twolayers")

    # Test first layer
    dst_parcels = tmp_path / "output_parcels.gpkg"
    gfo.copy_layer(src, dst_parcels, src_layer="parcels")
    layerinfo_parcels = gfo.get_layerinfo(dst_parcels)
    assert layerinfo_parcels.featurecount == 48
    assert layerinfo_parcels.name == "output_parcels"
    assert len(layerinfo_parcels.columns) == 11

    # Test second layer
    dst_zones = tmp_path / "output_zones.gpkg"
    gfo.copy_layer(src, dst_zones, src_layer="zones")
    layerinfo_zones = gfo.get_layerinfo(dst_zones)
    assert layerinfo_zones.featurecount == 5
    assert layerinfo_zones.name == "output_zones"
    assert len(layerinfo_zones.columns) == 1


@pytest.mark.parametrize(
    "src",
    [
        f"{test_helper.data_dir.as_posix()}/polygon-parcel.gpkg",
        f"/vsicurl/{test_helper.data_url}/polygon-parcel.gpkg",
        f"/vsizip//vsicurl/{test_helper.data_url}/poly_shp.zip",
        f"/vsizip//vsicurl/{test_helper.data_url}/poly_shp.zip/poly.shp",
        f"/vsizip/{test_helper.data_dir.as_posix()}/poly_shp.zip",
        f"/vsizip/{test_helper.data_dir.as_posix()}/poly_shp.zip/poly.shp",
    ],
)
def test_copy_layer_vsi(src):
    dst = "/vsimem/output.gpkg"

    try:
        # copy_layer with vsi
        gfo.copy_layer(src, dst)

        # Now compare source and dst file
        src_layerinfo = gfo.get_layerinfo(src)
        dst_layerinfo = gfo.get_layerinfo(dst)
        assert src_layerinfo.featurecount == dst_layerinfo.featurecount
    finally:
        gdal.Unlink(dst)


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS)
def test_copy_layer_where(tmp_path, suffix):
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    if suffix == ".csv":
        where = "GEWASGROEP = 'Grasland'"
        exp_featurecount = 31
        raise_on_nogeom = False
    else:
        where = "ST_Area({geometrycolumn}) > 500"
        exp_featurecount = 43
        raise_on_nogeom = True

    # copy_layer with where
    dst = tmp_path / f"{src.stem}-output_where{suffix}"
    gfo.copy_layer(src, dst, where=where)

    # Now compare source and dst file
    src_layerinfo = gfo.get_layerinfo(src, raise_on_nogeom=raise_on_nogeom)
    dst_layerinfo = gfo.get_layerinfo(dst, raise_on_nogeom=raise_on_nogeom)
    assert src_layerinfo.featurecount > dst_layerinfo.featurecount
    assert dst_layerinfo.featurecount == exp_featurecount


def test_copy_layer_write_mode_add_layer(tmp_path):
    src = test_helper.get_testfile("polygon-parcel")
    dst = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    dst_layer = "parcels_2"

    # Test
    gfo.copy_layer(src, dst, dst_layer=dst_layer, write_mode="add_layer")

    # Test if number of rows is correct
    layers = gfo.listlayers(dst)
    assert len(layers) == 2
    assert dst_layer in layers

    info = gfo.get_layerinfo(dst, layer=dst_layer)
    assert info.featurecount == 48


def test_copy_layer_write_mode_append(tmp_path):
    src = test_helper.get_testfile("polygon-parcel")
    dst = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    dst_layer = gfo.get_only_layer(dst)

    # Test
    gfo.copy_layer(src, dst, dst_layer=dst_layer, write_mode="append")

    # Test if number of rows is correct
    info = gfo.get_layerinfo(dst)
    assert info.featurecount == 96


@pytest.mark.parametrize("write_mode", [None, "create", "add_layer"])
@pytest.mark.parametrize("force", [True, False])
def test_copy_layer_write_mode_force(tmp_path, write_mode, force):
    """Test if force parameter is properly handled."""
    src = test_helper.get_testfile("polygon-parcel")
    dst = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    kwargs = {}
    if write_mode is not None:
        kwargs["write_mode"] = write_mode
    dst_layer = gfo.get_only_layer(dst)

    mtime_orig = dst.stat().st_mtime
    gfo.copy_layer(src, dst, dst_layer=dst_layer, force=force, **kwargs)
    if force:
        assert dst.stat().st_mtime > mtime_orig
    else:
        assert dst.stat().st_mtime == mtime_orig


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS_EXT)
@pytest.mark.parametrize("keep_permissions", [True, False])
def test_copy(tmp_path, suffix, keep_permissions):
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Copy to dest file
    dst = tmp_path / f"{src.stem}-output{suffix}"
    gfo.copy(src, dst, keep_permissions=keep_permissions)
    assert src.exists()
    assert dst.exists()
    if suffix == ".shp":
        assert dst.with_suffix(".shx").exists()

    # Copy to dest dir
    dst_dir = tmp_path / "dest_dir"
    dst_dir.mkdir(parents=True, exist_ok=True)
    gfo.copy(src, dst_dir, keep_permissions=keep_permissions)
    dst = dst_dir / src.name
    assert src.exists()
    assert dst.exists()
    if suffix == ".shp":
        assert dst.with_suffix(".shx").exists()


def test_copy_error(tmp_path):
    src = tmp_path / "non_existing_file.gpkg"
    dst = tmp_path / "output.gpkg"
    with pytest.raises(FileNotFoundError, match="File not found"):
        gfo.copy(src, dst)


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS)
def test_drop_column(tmp_path, suffix):
    # Prepare test data
    test_path = test_helper.get_testfile(
        "polygon-parcel", dst_dir=tmp_path, suffix=suffix
    )
    raise_on_nogeom = suffix != ".csv"
    original_info = gfo.get_layerinfo(test_path, raise_on_nogeom=raise_on_nogeom)
    assert "GEWASGROEP" in original_info.columns

    # Test
    gfo.drop_column(str(test_path), "GEWASGROEP")
    new_info = gfo.get_layerinfo(test_path, raise_on_nogeom=raise_on_nogeom)
    assert len(original_info.columns) == len(new_info.columns) + 1
    assert "GEWASGROEP" not in new_info.columns

    # dropping column that doesn't exist doesn't give an error
    gfo.drop_column(test_path, "NOT_EXISTING_COLUMN")


@pytest.mark.parametrize("suffix", [s for s in SUFFIXES_FILEOPS if s != ".csv"])
def test_get_crs(suffix):
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    crs = gfo.get_crs(str(src))
    assert crs.to_epsg() == 31370


def test_get_crs_bad_prj(tmp_path):
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path, suffix=".shp")
    bad_prj_src = test_helper.data_dir / "crs_custom_match" / "31370_no_epsg.prj"
    bad_prj_dst = src.with_suffix(".prj")
    shutil.copy(bad_prj_src, bad_prj_dst)
    with bad_prj_src.open() as prj_bad:
        assert prj_bad.read() != fileops.PRJ_EPSG_31370

    crs = fileops.get_crs(src)
    assert crs.to_epsg() == 31370
    assert bad_prj_dst.exists()
    with bad_prj_dst.open() as file_corrected:
        assert file_corrected.read() == fileops.PRJ_EPSG_31370


def test_get_crs_invalid_params():
    src = test_helper.get_testfile("polygon-parcel")
    with pytest.raises(ValueError, match="Layer not_existing not found in file"):
        _ = gfo.get_crs(str(src), layer="not_existing")


def test_get_crs_vsi():
    # Prepare test data
    src = f"/vsizip//vsicurl/{test_helper.data_url}/poly_shp.zip/poly.shp"

    # Test
    crs = gfo.get_crs(src)
    assert crs.to_epsg() == 27700


@pytest.mark.parametrize(
    "path, exp_default_layer",
    [
        ("/tmp/polygons.gpkg", "polygons"),
        (Path("/tmp/polygons.gpkg"), "polygons"),
        ("/tmp/polygons.gpkg.zip", "polygons"),
        (Path("/tmp/polygons.gpkg.zip"), "polygons"),
        (r"C:\tmp\polygons.gpkg.zip", "polygons"),
        (Path(r"C:\tmp\polygons.gpkg.zip"), "polygons"),
        ("/tmp/polygons.shp", "polygons"),
        ("/tmp/polygons.csv", "polygons"),
        ("/tmp/polygons.csv", "polygons"),
        ("/vsizip//vsicurl/poly_shp.zip/poly.shp", "poly"),
    ],
)
def test_get_default_layer(path, exp_default_layer):
    if os.name != "nt" and str(path).lower().startswith("c:"):
        pytest.skip("Test only valid on Windows")

    layer = gfo.get_default_layer(path)
    assert layer == exp_default_layer


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS)
def test_get_default_layer_files(suffix):
    # Prepare test data + test
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    layer = gfo.get_default_layer(str(src))
    assert layer == src.stem


@pytest.mark.parametrize("suffix", [s for s in SUFFIXES_FILEOPS if s != ".csv"])
def test_get_layer_geometrytypes(suffix):
    # Prepare test data + test
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    geometrytypes = gfo.get_layer_geometrytypes(str(src))
    if suffix == ".shp":
        assert geometrytypes == ["POLYGON", "MULTIPOLYGON", None]
    else:
        assert geometrytypes == ["POLYGON", "MULTIPOLYGON"]


@pytest.mark.parametrize("suffix", [s for s in SUFFIXES_FILEOPS if s != ".csv"])
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


def test_get_layer_geometrytypes_vsi():
    """Test get_layer_geometrytypes on an online zipped shapefile via vsi."""
    src = f"/vsizip//vsicurl/{test_helper.data_url}/poly_shp.zip/poly.shp"

    geometrytypes = gfo.get_layer_geometrytypes(src)
    assert geometrytypes == ["POLYGON"]


@pytest.mark.parametrize("suffix", [".gpkg", ".gpkg.zip", ".shp", ".shp.zip"])
@pytest.mark.parametrize("dimensions", [None, "XYZ"])
def test_get_layerinfo(suffix, dimensions):
    if dimensions == "XYZ" and suffix == ".gpkg.zip":
        pytest.skip(
            "get_testfile for dim=XYZ requires updating: so skip .gpkg.zip + XYZ"
        )

    src = test_helper.get_testfile(
        "polygon-parcel", suffix=suffix, dimensions=dimensions
    )
    # Tests
    layerinfo = gfo.get_layerinfo(str(src))
    assert str(layerinfo).startswith("<class 'geofileops.fileops.LayerInfo'>")
    assert layerinfo.featurecount == 48

    if src.suffix == ".shp":
        assert layerinfo.geometrycolumn == "geometry"
        assert layerinfo.name == src.stem
        assert layerinfo.fid_column == ""
    elif src.suffix == ".gpkg":
        assert layerinfo.geometrycolumn == "geom"
        assert layerinfo.name == "parcels"
        assert layerinfo.fid_column == "fid"

    if dimensions is None:
        assert layerinfo.geometrytypename == gfo.GeometryType.MULTIPOLYGON.name
        assert layerinfo.geometrytype == gfo.GeometryType.MULTIPOLYGON
    else:
        assert layerinfo.geometrytypename == gfo.GeometryType.MULTIPOLYGONZ.name
        assert layerinfo.geometrytype == gfo.GeometryType.MULTIPOLYGONZ
    assert layerinfo.total_bounds is not None
    assert layerinfo.crs is not None
    assert layerinfo.crs.to_epsg() == 31370

    assert len(layerinfo.columns) == 11
    assert layerinfo.columns["OIDN"].gdal_type == "Integer64"


def test_get_layerinfo_datasource():
    """Test get_layerinfo with datasource as input.

    The datasource should not be closed after the function call.
    """
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel")

    # Test
    datasource = gdal.OpenEx(str(src), gdal.OF_VECTOR)
    layerinfo = gfo.get_layerinfo(src, datasource=datasource)

    # Check results
    assert layerinfo.featurecount == 48

    # The datasource should still be open
    assert datasource is not None
    datasource = None


@pytest.mark.xfail
def test_get_layerinfo_curve():
    """Don't get this test to pass when running all tests.

    If it is ran on its own, it is fine?"""
    src = test_helper.get_testfile("curvepolygon")

    # Test
    layerinfo = gfo.get_layerinfo(str(src))
    assert layerinfo.geometrytypename == "MULTISURFACE"


def test_get_layerinfo_errors_not_existing_src():
    """Tests with non-existing source layer or path."""
    src = test_helper.get_testfile("polygon-parcel")

    # Layer specified that doesn't exist
    with pytest.raises(ValueError, match="Layer not_existing_layer not found in file"):
        _ = gfo.get_layerinfo(src, "not_existing_layer")

    # Path specified that doesn't exist
    with pytest.raises(FileNotFoundError, match="File not found"):
        not_existing_path = src.with_stem("not_existing_file_stem")
        _ = gfo.get_layerinfo(not_existing_path)


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
    assert layerinfo.featurecount == 48

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
    assert layerinfo.featurecount == 48
    assert layerinfo.name == "parcels"
    assert len(layerinfo.columns) == 11

    # Test second layer
    layerinfo = gfo.get_layerinfo(src, "zones")
    assert layerinfo.featurecount == 5
    assert layerinfo.name == "zones"
    assert len(layerinfo.columns) == 1

    # Test error if no layer specified
    with pytest.raises(
        ValueError, match="input has > 1 layers: a layer must be specified"
    ):
        layerinfo = gfo.get_layerinfo(src)


def test_get_layerinfo_vsi():
    """Test get_layerinfo on an online zipped shapefile via vsi."""
    src = f"/vsizip//vsicurl/{test_helper.data_url}/poly_shp.zip/poly.shp"

    # Test
    layerinfo = gfo.get_layerinfo(src)
    assert layerinfo.featurecount == 10
    assert layerinfo.name == "poly"
    assert len(layerinfo.columns) == 3
    assert layerinfo.geometrytypename == "MULTIPOLYGON"


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS)
def test_get_only_layer_one_layer(suffix):
    # Test Geopackage with 1 layer
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    layer = gfo.get_only_layer(str(src))
    if suffix == ".gpkg":
        assert layer == "parcels"
    else:
        assert layer == src.stem


def test_get_only_layer_two_layers():
    # Test Geopackage with 2 layers
    src = test_helper.get_testfile("polygon-twolayers")
    layers = gfo.listlayers(src)
    assert len(layers) == 2
    with pytest.raises(
        ValueError, match="input has > 1 layers: a layer must be specified"
    ):
        _ = gfo.get_only_layer(src)


def test_get_only_layer_vsi():
    """Test get_only_layer on an online zipped shapefile via vsi."""
    src = f"/vsizip//vsicurl/{test_helper.data_url}/poly_shp.zip/poly.shp"

    # Test
    layer = gfo.get_only_layer(src)
    assert layer == "poly"


@pytest.mark.filterwarnings(
    "ignore: is_geofile is deprecated and will be removed in a future version"
)
@pytest.mark.filterwarnings(
    "ignore: is_geofile_ext is deprecated and will be removed in a future version"
)
def test_is_geofile_deprecated():
    assert gfo.is_geofile(test_helper.get_testfile("polygon-parcel"))
    assert gfo.is_geofile(
        test_helper.get_testfile("polygon-parcel").with_suffix(".shp")
    )

    assert gfo.is_geofile("/test/testje.txt") is False


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS)
def test_listlayers_errors(suffix):
    path = f"not_existing_file{suffix}"
    with pytest.raises(FileNotFoundError, match=f"File not found: {path}"):
        _ = gfo.listlayers(path)


@pytest.mark.parametrize(
    "suffix, only_spatial_layers, expected",
    [
        (".gpkg", True, ["parcels"]),
        (".gpkg.zip", True, ["parcels"]),
        (".shp", True, ["{src_stem}"]),
        (".shp.zip", True, ["{src_stem}"]),
        (".csv", True, []),
        (".csv", False, ["{src_stem}"]),
    ],
)
def test_listlayers_one_layer(suffix, only_spatial_layers, expected):
    """Test listlayers on with 1 layer."""
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    layers = gfo.listlayers(src, only_spatial_layers=only_spatial_layers)

    expected = [exp.format(src_stem=GeoPath(src).stem) for exp in expected]
    assert layers == expected


def test_listlayers_two_layers():
    """Test listlayers on geopackage with 2 layers."""
    src = test_helper.get_testfile("polygon-twolayers")
    layers = gfo.listlayers(str(src))
    assert "parcels" in layers
    assert "zones" in layers


def test_listlayers_vsi():
    """Test listlayers on zipped shapefile via vsi."""
    src = f"/vsizip//vsicurl/{test_helper.data_url}/poly_shp.zip/poly.shp"
    layers = gfo.listlayers(src)
    assert "poly" in layers


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS_EXT)
def test_move(tmp_path, suffix):
    src = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path, suffix=suffix)

    # Test
    dst = tmp_path / f"{src.stem}-output{suffix}"
    gfo.move(str(src), str(dst))
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
    gfo.update_column(str(test_path), name="AreA", expression="ST_area(geom)")

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
    with pytest.raises(ValueError, match=r"Column .* doesn't exist in"):
        gfo.update_column(
            test_path, name="not_existing column", expression="ST_area(geom)"
        )

    # Try to update column with invalid expression
    assert "not_existing column" not in layerinfo.columns
    with pytest.raises(RuntimeError, match="update_column error for"):
        gfo.update_column(test_path, name="OPPERVL", expression="invalid_expression")


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS_EXT)
@pytest.mark.parametrize("dimensions", [None, "XYZ"])
def test_read_file(suffix, dimensions, engine_setter):  # noqa: ARG001
    # Remark: it seems like Z dimensions aren't read in geopandas.
    # Prepare and validate test data
    if dimensions == "XYZ" and suffix == ".gpkg.zip":
        pytest.skip(
            "get_testfile for dim=XYZ requires updating: so skip .gpkg.zip + XYZ"
        )

    src = test_helper.get_testfile(
        "polygon-parcel", suffix=suffix, dimensions=dimensions
    )
    src_info = gfo.get_layerinfo(src, raise_on_nogeom=False)
    if src_info.geometrycolumn is not None and dimensions is not None:
        assert src_info.geometrytypename == "MULTIPOLYGONZ"

    # Test with defaults
    read_gdf = gfo.read_file(str(src))

    # Check result
    assert isinstance(read_gdf, pd.DataFrame)
    assert len(read_gdf) == 48
    if suffix == ".csv":
        # No geometry column, so pd.DataFrame as result
        assert len(read_gdf.columns) == 11
    else:
        assert len(read_gdf.columns) == 12
        assert isinstance(read_gdf, gpd.GeoDataFrame)
        if src_info.geometrycolumn is not None and dimensions is not None:
            assert read_gdf.iloc[0].geometry.has_z


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS)
@pytest.mark.parametrize(
    "columns, geometry",
    [
        ([], "YES"),
        ("OIDN", "YES"),
        (["OIDN", "GEWASGROEP", "lengte"], "YES"),
        (["OIDN", "GEWASGROEP", "lengte"], "NO"),
        (["OIDN", "GEWASGROEP", "lengte"], "IGNORE"),
    ],
)
def test_read_file_columns_geometry(tmp_path, suffix, columns, geometry, engine_setter):  # noqa: ARG001
    # Prepare test data
    # For multi-layer filetype, use 2-layer file for better test coverage
    src_info = _geofileinfo.get_geofileinfo(suffix)
    if src_info.is_singlelayer:
        testfile = "polygon-parcel"
        src = test_helper.get_testfile(testfile, suffix=suffix)
        layer = src.stem
    else:
        testfile = "polygon-twolayers"
        src = test_helper.get_testfile(testfile, suffix=suffix)
        layer = "parcels"

    # Interprete the geometry parameter
    if geometry == "YES":
        ignore_geometry = False
    elif geometry == "NO":
        # Write test file without geometry
        input_df = gfo.read_file(src, layer=layer, ignore_geometry=True)
        layer = f"{src.stem}_nogeom"
        if suffix == ".shp":
            # A shapefile without geometry results in only a .dbf file
            test_path = tmp_path / f"{layer}.dbf"
        else:
            test_path = tmp_path / f"{layer}{suffix}"
        if src_info.is_singlelayer:
            gfo.to_file(input_df, test_path, layer=layer)
        else:
            # For a multilayer filetype, add the attribute table so the file stays
            # multi-layer
            gfo.copy(src, test_path, keep_permissions=False)
            gfo.to_file(input_df, test_path, layer=layer, append=False)
            assert len(gfo.listlayers(test_path)) > 1
        src = test_path
        ignore_geometry = True
    elif geometry == "IGNORE":
        ignore_geometry = True
    else:
        raise ValueError(f"Invalid value for geometry: {geometry}")

    expect_geometry = not (ignore_geometry or src_info.driver == "CSV")

    exp_columns = list(columns) if isinstance(columns, list) else [columns]
    if expect_geometry:
        exp_columns += ["geometry"]

    exp_featurecount = 0 if columns == [] and not expect_geometry else 48

    # Test
    read_gdf = gfo.read_file(
        src, layer=layer, columns=columns, ignore_geometry=ignore_geometry
    )
    assert isinstance(read_gdf, pd.DataFrame)
    if expect_geometry:
        assert isinstance(read_gdf, gpd.GeoDataFrame)
    assert list(read_gdf.columns) == exp_columns
    assert len(read_gdf) == exp_featurecount


def test_read_file_curve():
    """Test reading a curve file.

    The geometry type is automatically converted to a linear one in read_file.
    """
    # Prepare test data
    src = test_helper.get_testfile("curvepolygon")

    # Test
    read_gdf = gfo.read_file(src)
    assert isinstance(read_gdf, gpd.GeoDataFrame)
    assert isinstance(read_gdf.geometry[0], sh_geom.Polygon)


def test_read_file_invalid_params(tmp_path, engine_setter):  # noqa: ARG001
    src = tmp_path / "nonexisting_file.gpkg"

    with pytest.raises(FileNotFoundError, match="File not found:"):
        _ = gfo.read_file(src)


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS)
def test_read_file_fid_as_index(suffix, engine_setter):  # noqa: ARG001
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    # if no geometry column available in file, a pd.DataFrame is returned
    exp_columns = 11 if suffix == ".csv" else 12

    # First read without fid_as_index=True
    read_gdf = gfo.read_file(src, rows=slice(5, 10))
    assert isinstance(read_gdf, pd.DataFrame)
    assert len(read_gdf.columns) == exp_columns
    assert len(read_gdf) == 5
    assert read_gdf.index[0] == 0

    # Now with fid_as_index=True
    read_gdf = gfo.read_file(src, rows=slice(5, 10), fid_as_index=True)
    assert isinstance(read_gdf, pd.DataFrame)
    assert len(read_gdf.columns) == exp_columns
    assert len(read_gdf) == 5
    if _geofileinfo.get_geofileinfo(src).is_fid_zerobased:
        assert read_gdf.index[0] == 5
    else:
        # Geopackage fid starts at 1
        assert read_gdf.index[0] == 6


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS)
def test_read_file_sql(suffix, engine_setter):
    # Prepare test data
    # For multi-layer filetype, use 2-layer file for better test coverage
    if _geofileinfo.get_geofileinfo(suffix).is_singlelayer:
        testfile = "polygon-parcel"
        src = test_helper.get_testfile(testfile, suffix=suffix)
        layer = src.stem
    else:
        testfile = "polygon-twolayers"
        src = test_helper.get_testfile(testfile, suffix=suffix)
        layer = "parcels"

    # Test
    sql_stmt = f'SELECT * FROM "{layer}"'
    if engine_setter == "fiona":
        with pytest.raises(ValueError, match="sql_stmt is not supported with fiona"):
            _ = gfo.read_file(src, sql_stmt=sql_stmt)
        return

    read_gdf = gfo.read_file(src, sql_stmt=sql_stmt)
    assert isinstance(read_gdf, pd.DataFrame)
    if not (suffix == ".csv" and engine_setter == "pyogrio"):
        assert isinstance(read_gdf, gpd.GeoDataFrame)
    assert len(read_gdf) == 48


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS)
@pytest.mark.filterwarnings("ignore: read_file_sql is deprecated")
def test_read_file_sql_deprecated(suffix, engine_setter):
    if engine_setter == "fiona":
        pytest.skip("sql_stmt param not supported for fiona engine")
    raise_on_nogeom = suffix != ".csv"

    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Test
    src_layerinfo = gfo.get_layerinfo(src, raise_on_nogeom=raise_on_nogeom)
    read_gdf = gfo.read_file_sql(src, sql_stmt=f'SELECT * FROM "{src_layerinfo.name}"')
    if suffix != ".csv":
        assert isinstance(read_gdf, gpd.GeoDataFrame)
    assert len(read_gdf) == 48


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS)
def test_read_file_sql_no_geom(suffix, engine_setter):
    if engine_setter == "fiona":
        pytest.skip("sql_stmt param not supported for fiona engine")
    raise_on_nogeom = suffix != ".csv"

    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    # Test
    src_layerinfo = gfo.get_layerinfo(src, raise_on_nogeom=raise_on_nogeom)
    sql_stmt = f'SELECT count(*) AS aantal FROM "{src_layerinfo.name}"'
    read_df = gfo.read_file(src, sql_stmt=sql_stmt)
    assert isinstance(read_df, pd.DataFrame)
    assert len(read_df) == 1
    assert read_df.aantal.item() == 48


@pytest.mark.parametrize("columns", [["OIDN", "UIDN"], ["OidN", "UidN"]])
@pytest.mark.parametrize(
    "suffix, testfile, layer",
    [
        (".gpkg", "polygon-parcel", None),
        (".shp", "polygon-parcel", None),
        (".gpkg", "polygon-twolayers", "parcels"),
    ],
)
def test_read_file_sql_placeholders(suffix, testfile, layer, columns, engine_setter):
    """Test if placeholders are properly filled out.

    Also verify if casing used in columns parameter is retained when using placeholders.
    """
    if engine_setter == "fiona":
        pytest.skip("sql_stmt param not supported for fiona engine")

    # Prepare test data
    src = test_helper.get_testfile(testfile, suffix=suffix)

    # Test
    sql_stmt = """
        SELECT {geometrycolumn}
              {columns_to_select_str}
          FROM "{input_layer}" layer
    """
    read_sql_gdf = gfo.read_file(
        src, sql_stmt=sql_stmt, sql_dialect="SQLITE", layer=layer, columns=columns
    )
    read_gdf = gfo.read_file(src, columns=columns, layer=layer)
    assert_geodataframe_equal(read_gdf, read_sql_gdf)


def test_read_file_two_layers(engine_setter):  # noqa: ARG001
    src = test_helper.get_testfile("polygon-twolayers")
    layers = gfo.listlayers(src)
    assert "parcels" in layers
    assert "zones" in layers

    read_gdf = gfo.read_file(src, layer="zones")
    assert isinstance(read_gdf, gpd.GeoDataFrame)
    assert len(read_gdf) == 5

    read_gdf = gfo.read_file(src, layer="parcels")
    assert isinstance(read_gdf, gpd.GeoDataFrame)
    assert len(read_gdf) == 48


def test_read_file_vsi():
    src = f"/vsizip//vsicurl/{test_helper.data_url}/poly_shp.zip/poly.shp"
    read_gdf = gfo.read_file(src)
    assert isinstance(read_gdf, gpd.GeoDataFrame)
    assert len(read_gdf) == 10


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS)
def test_rename_column(tmp_path, suffix):
    # Prepare test data
    test_path = test_helper.get_testfile(
        "polygon-parcel", dst_dir=tmp_path, suffix=suffix
    )
    raise_on_nogeom = suffix != ".csv"

    # Check if input file is ok
    orig_layerinfo = gfo.get_layerinfo(test_path, raise_on_nogeom=raise_on_nogeom)
    assert "OPPERVL" in orig_layerinfo.columns
    assert "area" not in orig_layerinfo.columns

    # Rename
    gfo.rename_column(str(test_path), "OPPERVL", "area")
    result_layerinfo = gfo.get_layerinfo(test_path, raise_on_nogeom=raise_on_nogeom)
    assert "OPPERVL" not in result_layerinfo.columns
    assert "area" in result_layerinfo.columns

    # Rename non-existing column to existing columns doesn't give an error
    gfo.rename_column(test_path, "OPPERVL", "area")
    result_layerinfo = gfo.get_layerinfo(test_path, raise_on_nogeom=raise_on_nogeom)
    assert "OPPERVL" not in result_layerinfo.columns
    assert "area" in result_layerinfo.columns

    # Rename column with different casing
    gfo.add_column(str(test_path), "TMP_0", "TEXT")
    gfo.rename_column(str(test_path), "area", "AREA")
    result_layerinfo = gfo.get_layerinfo(test_path, raise_on_nogeom=raise_on_nogeom)
    assert "area" not in result_layerinfo.columns
    assert "AREA" in result_layerinfo.columns


def test_rename_column_unsupported(tmp_path):
    path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path, suffix=".shp")
    with pytest.raises(Exception, match="rename_column error"):
        _ = gfo.rename_column(path, column_name="abc", new_column_name="def")


def test_rename_layer(tmp_path):
    test_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    gfo.add_layerstyle(test_path, layer="parcels", name="stylename", qml="")

    # Rename
    gfo.rename_layer(test_path, new_layer="parcels_renamed")
    layernames_renamed = gfo.listlayers(path=test_path)
    assert layernames_renamed[0] == "parcels_renamed"
    assert len(gfo.get_layerstyles(test_path, layer="parcels_renamed")) == 1

    # # Rename layer with different casing
    gfo.rename_layer(test_path, new_layer="PARCELS_RENAMED")
    layernames_renamed = gfo.listlayers(path=test_path)
    assert layernames_renamed[0] == "PARCELS_RENAMED"
    assert len(gfo.get_layerstyles(test_path, layer="PARCELS_RENAMED")) == 1


@pytest.mark.parametrize(
    "suffix, layer, expected_error",
    [
        (".shp", None, "rename_layer not supported for"),
        (".shp.zip", None, "rename_layer not supported for"),
        (".shp", "layer", "rename_layer not supported for"),
        (".shp.zip", "layer", "rename_layer not supported for"),
    ],
)
def test_rename_layer_unsupported(tmp_path, suffix, layer, expected_error):
    path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path, suffix=suffix)
    with pytest.raises(ValueError, match=expected_error):
        _ = gfo.rename_layer(path, layer=layer, new_layer="new_layer")


def test_execute_sql(tmp_path):
    # Prepare testfile
    test_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)

    # Test using execute_sql for creating/dropping indexes
    gfo.execute_sql(
        path=str(test_path),
        sql_stmt='CREATE INDEX idx_parcels_oidn ON "parcels"("oidn")',
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
        str(path), layer=layer, sql_stmt=sql_stmt, columns=columns
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


@pytest.mark.parametrize(
    "layer, sql_stmt, error",
    [
        (
            "parcels",
            'SELECT {invalid_placeholder} FROM "parcel"',
            "unknown placeholder invalid_placeholder ",
        ),
        (
            None,
            'SELECT * FROM "{input_layer}"',
            "input has > 1 layers: a layer must be specified",
        ),
    ],
)
def test_fill_out_sql_placeholders_errors(layer, sql_stmt, error):
    path = test_helper.get_testfile("polygon-twolayers")

    # Test
    with pytest.raises(ValueError, match=error):
        fileops._fill_out_sql_placeholders(
            path, layer=layer, sql_stmt=sql_stmt, columns=None
        )


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS_EXT)
@pytest.mark.parametrize("dimensions", [None])
def test_to_file(tmp_path, suffix, dimensions, engine_setter):
    # Remark: geopandas doesn't seem seem to read the Z dimension, so writing can't be
    # tested?
    # Prepare test file
    src = test_helper.get_testfile(
        "polygon-parcel", suffix=suffix, dimensions=dimensions
    )
    output_path = tmp_path / f"{GeoPath(src).stem}-output{suffix}"
    uidn = str(2318781) if suffix == ".csv" else 2318781
    encoding = "utf-8" if suffix == ".csv" else None

    # Read test file and write to tmppath
    read_gdf = gfo.read_file(src, encoding=encoding)

    # Validate if string (encoding) is correct for data read.
    assert read_gdf.loc[read_gdf["UIDN"] == uidn]["LBLHFDTLT"].item() == "Silomaïs"

    if suffix in (".gpkg.zip", ".shp.zip"):
        pytest.xfail("writing a dataframe to gpkg.zip or .shp.zip has issue")

    gfo.to_file(read_gdf, str(output_path))
    written_gdf = gfo.read_file(output_path)

    # Validate if string (encoding) is correct for data read after writing.
    assert read_gdf.loc[read_gdf["UIDN"] == uidn]["LBLHFDTLT"].item() == "Silomaïs"

    assert len(read_gdf) == len(written_gdf)
    if suffix == ".csv":
        # if no geometry column, a pd.Dataframe is returned
        assert_frame_equal(written_gdf, read_gdf)
    else:
        if engine_setter == "fiona":
            if suffix == ".gpkg":
                # Fiona doesn't seem to write EMPTY geom to gpkg, but writes None.
                read_gdf.loc[46, "geometry"] = None
            elif suffix == ".shp":
                # The data column is written as string with fiona.
                written_gdf["DATUM"] = pd.to_datetime(written_gdf["DATUM"]).astype(
                    "datetime64[ms]"
                )

        assert_geodataframe_equal(written_gdf, read_gdf)


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS)
def test_to_file_append(tmp_path, suffix, engine_setter):  # noqa: ARG001
    test_path = test_helper.get_testfile(
        "polygon-parcel", dst_dir=tmp_path, suffix=suffix
    )
    raise_on_nogeom = suffix != ".csv"

    test_gdf = gfo.read_file(test_path)
    gfo.to_file(test_gdf, path=test_path, append=True)

    # Check result
    assert test_path.exists()
    dst_info = gfo.get_layerinfo(test_path, raise_on_nogeom=raise_on_nogeom)
    assert dst_info.featurecount == len(test_gdf) * 2


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS)
def test_to_file_append_to_unexisting_file(tmp_path, suffix, engine_setter):  # noqa: ARG001
    test_path = test_helper.get_testfile(
        "polygon-parcel", dst_dir=tmp_path, suffix=suffix
    )
    raise_on_nogeom = suffix != ".csv"

    test_gdf = gfo.read_file(test_path)
    dst_path = tmp_path / f"dst{suffix}"
    gfo.to_file(test_gdf, path=str(dst_path), append=True)

    # Check result
    assert dst_path.exists()
    dst_info = gfo.get_layerinfo(dst_path, raise_on_nogeom=raise_on_nogeom)
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


def test_to_file_attribute_table_gpkg(tmp_path, engine_setter):  # noqa: ARG001
    """Test writing a DataFrame without geometry to a geopackage."""
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
    engine_setter,  # noqa: ARG001
):
    src = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    output_path = tmp_path / f"{src.stem}-output{suffix}"

    # Read test file and write to tmppath
    read_gdf = gfo.read_file(src)
    gfo.to_file(read_gdf, output_path, create_spatial_index=create_spatial_index)
    assert gfo.has_spatial_index(output_path) is expected_spatial_index


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS)
def test_to_file_emptyfile(tmp_path, suffix):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    raise_on_nogeom = suffix != ".csv"
    input_layerinfo = gfo.get_layerinfo(input_path, raise_on_nogeom=raise_on_nogeom)
    read_gdf = gfo.read_file(input_path)
    empty_gdf = read_gdf.drop(read_gdf.index)
    if suffix != ".csv":
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
    input_layerinfo = gfo.get_layerinfo(input_path, raise_on_nogeom=raise_on_nogeom)
    output_layerinfo = gfo.get_layerinfo(output_path, raise_on_nogeom=raise_on_nogeom)
    assert output_layerinfo.featurecount == 0
    assert len(input_layerinfo.columns) == len(output_layerinfo.columns)
    assert input_layerinfo.geometrytype == output_layerinfo.geometrytype


def test_to_file_fid_append_to(tmp_path, engine_setter):  # noqa: ARG001
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
    gfo.copy_layer(
        output1_path,
        output_path,
        dst_layer=output_path.stem,
        write_mode="append",
        preserve_fid=True,
    )

    # Prepare expected result
    expected_gdf = pd.concat([test1_gdf, test2_gdf]).set_index("fid")
    # Now check result
    written_gdf = gfo.read_file(output_path, fid_as_index=True)
    assert_geodataframe_equal(written_gdf, expected_gdf)


def test_to_file_force_geometrytype_multitype(tmp_path, engine_setter):  # noqa: ARG001
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


@pytest.mark.parametrize("suffix", [s for s in SUFFIXES_FILEOPS if s != ".csv"])
def test_to_file_geomempty(tmp_path, suffix, engine_setter):  # noqa: ARG001
    # Test for gdf with an empty polygon + a polygon
    test_gdf = gpd.GeoDataFrame(
        geometry=[
            sh_geom.GeometryCollection(),
            test_helper.TestData.polygon_with_island,
        ],
        crs=31370,
    )
    # By default, get_geometrytypes ignores the type of empty geometries.
    test_geometrytypes = _geoseries_util.get_geometrytypes(test_gdf.geometry)
    assert len(test_geometrytypes) == 1
    test_geometrytypes_includingempty = _geoseries_util.get_geometrytypes(
        test_gdf.geometry, ignore_empty_geometries=False
    )
    assert len(test_geometrytypes_includingempty) == 2
    output_empty_path = tmp_path / f"testfile_with_emptygeom{suffix}"
    test_gdf.to_file(output_empty_path, driver=gfo.get_driver(suffix))

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


@pytest.mark.parametrize("suffix", [s for s in SUFFIXES_FILEOPS if s != ".csv"])
def test_to_file_geomnone(tmp_path, suffix, engine_setter):  # noqa: ARG001
    # Test for gdf with a None geometry + a polygon
    test_gdf = gpd.GeoDataFrame(
        geometry=[None, test_helper.TestData.polygon_with_island], crs=31370
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


@pytest.mark.parametrize("suffix", [s for s in SUFFIXES_FILEOPS if s != ".csv"])
def test_to_file_index(tmp_path, points_gdf, suffix, engine_setter):  # noqa: ARG001
    """Strongly based on similar test in geopandas."""

    class FileNumber:
        def __init__(self, tmpdir: Path, base, ext: str):
            self.tmpdir = tmpdir
            self.base = base
            self.ext = ext
            self.fileno = 0

        def __repr__(self) -> str:
            return self.format_filepath().as_posix()

        def __next__(self) -> Path:
            self.fileno += 1
            return self.format_filepath()

        def format_filepath(self) -> Path:
            filename = f"{self.base}{self.fileno:02d}.{self.ext}"
            return self.tmpdir / filename

    fngen = FileNumber(tmp_path, "check", suffix)

    def do_checks(df, index_is_used):
        # check combinations of index=None|True|False on GeoDataFrame
        other_cols = list(df.columns)
        other_cols.remove("geometry")

        # ESRI Shapefile will add FID if no other columns exist
        driver_col = ["FID"] if suffix == ".shp" else []

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
        expected_cols = driver_col[:] if len(other_cols) == 0 else []

        if index_is_used:
            expected_cols += index_cols
        expected_cols += [*other_cols, "geometry"]
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
            expected_cols = [*driver_col, "geometry"]
        else:
            expected_cols = [*other_cols, "geometry"]
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
    gdf.index = pd.to_timedelta(range(len(gdf)), "days")
    gdf.index = gdf.index.astype(str)
    do_checks(gdf, index_is_used=True)

    # unnamed DatetimeIndex
    p_gdf = points_gdf.copy()
    gdf = gpd.GeoDataFrame(p_gdf["value1"], geometry=p_gdf.geometry)
    gdf.index = pd.to_timedelta(range(len(gdf)), "days") + pd.DatetimeIndex(
        ["1999-12-27"] * len(gdf)
    )
    if suffix == ".shp":
        # Shapefile driver does not support datetime fields
        gdf.index = gdf.index.astype(str)
    do_checks(gdf, index_is_used=True)

    # named DatetimeIndex
    gdf.index.name = "datetime"
    do_checks(gdf, index_is_used=True)


@pytest.mark.parametrize("suffix", [s for s in SUFFIXES_FILEOPS if s != ".csv"])
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
    exp_featurecount = 48
    exp_columns = 11
    if suffix == ".gpkg":
        layerinfo = gfo.get_layerinfo(test_path, raise_on_nogeom=False)
        assert str(layerinfo).startswith("<class 'geofileops.fileops.LayerInfo'>")
        assert layerinfo.featurecount == exp_featurecount

        assert layerinfo.geometrycolumn is None
        assert layerinfo.name == test_path.stem
        assert layerinfo.fid_column == "fid"

        assert layerinfo.geometrytypename == "NONE"
        assert layerinfo.geometrytype is None
        assert layerinfo.total_bounds is None
        assert layerinfo.crs is None

        assert len(layerinfo.columns) == exp_columns
    elif suffix == ".shp":
        # a shapefile doesn't have a .shp file without geometry column, only a .dbf
        # (and optional .cpg).
        assert not test_path.exists()
        test_df = gfo.read_file(test_path.with_suffix(".dbf"))
        assert len(test_df) == exp_featurecount
        assert len(test_df.columns) == exp_columns
    else:
        raise ValueError(f"test not implemented for suffix {suffix}")


def test_to_file_vsi():
    """Test writing to a file in vsimem."""
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel")
    read_gdf = gfo.read_file(src)

    # Test
    vsi_path = f"/vsimem/{src.stem}{src.suffix}"
    gfo.to_file(read_gdf, vsi_path)

    # Check result
    assert src.stem in gfo.listlayers(vsi_path)
    result_gdf = gfo.read_file(vsi_path)
    gdal.Unlink(vsi_path)
    assert_geodataframe_equal(read_gdf, result_gdf, check_geom_empty_vs_None=False)


@pytest.mark.parametrize("suffix", SUFFIXES_FILEOPS)
def test_remove(tmp_path, suffix):
    # Prepare test data
    src = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path, suffix=suffix)
    assert src.exists()

    # Remove and check result
    gfo.remove(str(src))
    assert not src.exists()


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.skipif(not GDAL_GTE_311, reason="sozip requires gdal>=3.11")
def test_zip_geofile(tmp_path, suffix):
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)

    sozip_path = tmp_path / "zipped.zip"
    fileops.zip_geofile(input_path, sozip_path)

    # Check result
    assert sozip_path.exists()
    assert sozip_path.stat().st_size > 0

    unzipped_dir = tmp_path / "unzipped"
    fileops.unzip_geofile(sozip_path, unzipped_dir)
    for path in input_path if isinstance(input_path, list) else [input_path]:
        assert (unzipped_dir / path.name).exists()


def test_launder_columns():
    columns = [f"TOO_LONG_COLUMNNAME{index}" for index in range(21)]
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
    columns = [f"TOO_LONG_COLUMNNAME{index}" for index in range(200)]
    with pytest.raises(
        NotImplementedError, match="Not supported to launder > 99 columns starting with"
    ):
        laundered = fileops._launder_column_names(columns)


@pytest.mark.parametrize("suffix, exp_nb_files", [(".gpkg", 1), (".shp", 4)])
def test_unzip_geofile(tmp_path, suffix, exp_nb_files):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    zip_dir = tmp_path / "dir_to_zip"
    zip_dir.mkdir()
    gfo.copy(input_path, zip_dir)
    zip_path = tmp_path / "zipped.zip"
    fileops._zip(zip_dir, zip_path)

    # Unzip and check result
    output_dir = tmp_path / "unzipped"
    output_geofile_path = fileops.unzip_geofile(zip_path, output_dir)
    assert output_dir.exists()
    assert output_geofile_path.exists()
    assert output_geofile_path == output_dir / input_path.name
    assert len(list(output_dir.iterdir())) == exp_nb_files
    assert (output_dir / input_path.name).exists()


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS_EXT)
def test_unzip_geofile_error_multi_files(tmp_path, suffix):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix)
    zip_dir = tmp_path / "dir_to_zip"
    zip_dir.mkdir()
    file = zip_dir / GeoPath(input_path).with_stem_suffix("_1").name
    gfo.copy(input_path, file)
    file = zip_dir / GeoPath(input_path).with_stem_suffix("_2").name
    gfo.copy(input_path, file)
    zip_path = tmp_path / "zipped.zip"
    fileops._zip(zip_dir, zip_path)

    # Unzip and check result
    output_dir = tmp_path / "unzipped"
    with pytest.raises(ValueError, match="Multiple geofiles found in zip"):
        _ = fileops.unzip_geofile(zip_path, output_dir)


def test_unzip_geofile_error_no_files(tmp_path):
    # Prepare test data
    zip_dir = tmp_path / "dir_to_zip"
    zip_dir.mkdir()
    zip_path = tmp_path / "zipped.zip"
    fileops._zip(zip_dir, zip_path)

    # Unzip and check result
    output_dir = tmp_path / "unzipped"
    with pytest.raises(ValueError, match="No files found in zip"):
        _ = fileops.unzip_geofile(zip_path, output_dir)


def test_unzip_geofile_error_no_geofiles(tmp_path):
    # Prepare test data
    zip_dir = tmp_path / "dir_to_zip"
    zip_dir.mkdir()
    file1 = zip_dir / "no_geo_file1.txt"
    file1.touch()
    file2 = zip_dir / "no_geo_file2.txt"
    file2.touch()
    zip_path = tmp_path / "zipped.zip"
    fileops._zip(zip_dir, zip_path)

    # Unzip and check result
    output_dir = tmp_path / "unzipped"
    with pytest.raises(ValueError, match="No geofile found in zip"):
        _ = fileops.unzip_geofile(zip_path, output_dir)
