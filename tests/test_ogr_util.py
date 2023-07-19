# -*- coding: utf-8 -*-
"""
Tests for functionalities in ogr_util.
"""

import os

from osgeo import gdal
import pytest

import geofileops as gfo
from geofileops.util import _ogr_util
from tests import test_helper


def test_get_drivers():
    drivers = _ogr_util.get_drivers()
    assert len(drivers) > 0
    assert "GPKG" in drivers
    assert "ESRI Shapefile" in drivers


def test_prepare_gdal_options():
    # Some basic variants that should all be OK
    options_ok = [
        {"LAYER_CREATION.SPATIAL_INDEX": True},
        {"layer_creation.spatial_index": True},
        {" LAYER_CREATION . SPATIAL_INDEX ": True},
    ]
    for option in options_ok:
        prepared = _ogr_util._prepare_gdal_options(option)
        assert prepared["LAYER_CREATION.SPATIAL_INDEX"] == "YES"

        prepared = _ogr_util._prepare_gdal_options(option, split_by_option_type=True)
        assert "LAYER_CREATION" in prepared
        assert prepared["LAYER_CREATION"]["SPATIAL_INDEX"] == "YES"

    # Some more specific cases
    prepared = _ogr_util._prepare_gdal_options({"LAYER_CREATION.SPATIAL_INDEX": False})
    assert prepared["LAYER_CREATION.SPATIAL_INDEX"] == "NO"

    # These options should give an error
    options_nok = [
        {"LAYER_CREATION-SPATIAL_INDEX": True},
        {"NOT_EXISTING_OPTION_TYPE.SPATIAL_INDEX": True},
        {"LAYER_CREATION.SPATIAL_INDEX": True, "layer_creation.spatial_index": False},
    ]
    for option in options_nok:
        try:
            _ = _ogr_util._prepare_gdal_options(option)
            error_raised = False
        except Exception:
            error_raised = True
        assert error_raised is True, f"Error should have been raised for {option}"


def test_set_config_options():
    # Init
    test1_config_notset = "TEST_CONFIG_OPTION_1"
    test2_config_alreadyset = "TEST_CONFIG_OPTION_2"
    test3_config_envset = "TEST_CONFIG_OPTION_3"
    test4_bool_true = "TEST_CONFIG_OPTION_4"
    test5_bool_false = "TEST_CONFIG_OPTION_5"
    test6_int_50 = "TEST_CONFIG_OPTION_6"
    assert gdal.GetConfigOption(test1_config_notset) is None
    assert gdal.GetConfigOption(test2_config_alreadyset) is None
    gdal.SetConfigOption(test2_config_alreadyset, "test2_original_value")
    assert test3_config_envset not in os.environ
    os.environ[test3_config_envset] = "test3_original_env_value"

    # Set config options with context manager
    with _ogr_util.set_config_options(
        {
            test1_config_notset: "test1_context_value",
            test2_config_alreadyset: "test2_context_value",
            test3_config_envset: "test3_context_value",
            test4_bool_true: True,
            test5_bool_false: False,
            test6_int_50: 50,
        }
    ):
        assert gdal.GetConfigOption(test1_config_notset) == "test1_context_value"
        assert gdal.GetConfigOption(test2_config_alreadyset) == "test2_context_value"
        assert gdal.GetConfigOption(test3_config_envset) == "test3_context_value"
        assert gdal.GetConfigOption(test4_bool_true) == "YES"
        assert gdal.GetConfigOption(test5_bool_false) == "NO"
        assert gdal.GetConfigOption(test6_int_50) == "50"

    # The options set with context manager should be gone
    assert gdal.GetConfigOption(test1_config_notset) is None
    # TODO: delete next line + uncomment 2nd if GetConfigOptions is supported
    assert gdal.GetConfigOption(test2_config_alreadyset) is None
    # assert gdal.GetConfigOption(test2_config_alreadyset) == "test2_original_value"
    assert gdal.GetConfigOption(test3_config_envset) == "test3_original_env_value"

    # If option via env is changed, it changes here as well
    os.environ[test3_config_envset] = "test3_new_env_value"
    assert gdal.GetConfigOption(test3_config_envset) == "test3_new_env_value"


def test_vector_translate_input_nolayer(tmp_path):
    input_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)
    output_path = tmp_path / f"output{input_path.suffix}"
    layer = gfo.get_only_layer(input_path)
    gfo.execute_sql(input_path, sql_stmt=f'DROP TABLE "{layer}"')

    with pytest.raises(
        Exception, match="Error .* not recognized as a supported file format"
    ):
        _ogr_util.vector_translate(str(input_path), output_path)


@pytest.mark.parametrize(
    "input_suffix, output_suffix, geom_null_asc, exp_null_geoms",
    [
        (".gpkg", ".gpkg", True, 7),
        (".gpkg", ".shp", False, 46),
        (".shp", ".gpkg", False, 46),
        (".shp", ".shp", True, 7),
    ],
)
def test_vector_translate_geom_null(
    tmp_path, input_suffix, output_suffix, geom_null_asc, exp_null_geoms
):
    """
    If there the first row of the result has a NULL geometry in the result, all
    geometries become NULL. Using ORDER BY geom IS NULL controls this.
       -> https://github.com/geofileops/geofileops/issues/308
    """
    input_path = test_helper.get_testfile("polygon-parcel", suffix=input_suffix)
    output_path = tmp_path / f"output{output_suffix}"
    input_layerinfo = gfo.get_layerinfo(input_path)
    orderby_direction = "ASC" if geom_null_asc else "DESC"
    sql_stmt = f"""
        SELECT * FROM (
          SELECT ST_Buffer({input_layerinfo.geometrycolumn}, -10) AS geom, oidn, uidn
            FROM "{input_layerinfo.name}"
          )
        ORDER BY geom IS NULL {orderby_direction}
    """
    _ogr_util.vector_translate(
        input_path,
        output_path,
        sql_stmt=sql_stmt,
        sql_dialect="SQLITE",
        force_output_geometrytype=input_layerinfo.geometrytype,
    )

    assert output_path.exists()
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert "geom" not in output_layerinfo.columns
    assert "geometry" not in output_layerinfo.columns
    assert len(output_layerinfo.columns) == 2

    if output_suffix == ".gpkg":
        assert output_layerinfo.geometrycolumn == "geom"
    else:
        assert output_layerinfo.geometrycolumn == "geometry"

    output_gdf = gfo.read_file(output_path)
    assert "geometry" in output_gdf.columns
    assert len(output_gdf.loc[output_gdf.geometry.isna()]) == exp_null_geoms


@pytest.mark.parametrize("input_suffix", test_helper.SUFFIXES)
@pytest.mark.parametrize("output_suffix", test_helper.SUFFIXES)
def test_vector_translate_input_empty(tmp_path, input_suffix, output_suffix):
    input_path = test_helper.get_testfile(
        "polygon-parcel", suffix=input_suffix, empty=True
    )
    output_path = tmp_path / f"output{output_suffix}"
    layer = gfo.get_only_layer(input_path)
    sql_stmt = f'SELECT * FROM "{layer}"'
    _ogr_util.vector_translate(input_path, output_path, sql_stmt=sql_stmt)

    assert output_path.exists()
    input_layerinfo = gfo.get_layerinfo(input_path)
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert len(input_layerinfo.columns) == len(output_layerinfo.columns)


@pytest.mark.parametrize(
    "expected_error, kwargs",
    [
        (
            "it is not supported to specify both sql_stmt and where",
            {"where": "abc", "sql_stmt": "def"},
        ),
        (
            "Error input_layers .* not found in",
            {"input_layers": "unexisting"},
        ),
    ],
)
def test_vector_translate_invalid_params(tmp_path, kwargs, expected_error):
    input_path = test_helper.get_testfile("polygon-parcel")
    output_path = tmp_path / f"output{input_path.suffix}"

    with pytest.raises(Exception, match=expected_error):
        _ogr_util.vector_translate(str(input_path), output_path, **kwargs)
