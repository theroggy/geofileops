"""
Tests for single layer operations using GeoPandas.
"""

import math

import geopandas as gpd
import pygeoops
import pytest
import shapely.geometry as sh_geom

import geofileops as gfo
from geofileops import GeometryType
from geofileops.util import _geometry_util
from geofileops.util import _geoops_gpd as geoops_gpd
from geofileops.util._geofileinfo import GeofileInfo
from tests import test_helper
from tests.test_helper import SUFFIXES_GEOOPS


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize(
    "only_geom_input, gridsize, keep_empty_geoms, where_post",
    [
        (False, 0.0, True, "ST_Area({geometrycolumn}) > 70"),
        (True, 0.01, False, None),
    ],
)
def test_apply(
    tmp_path, suffix, only_geom_input, gridsize, keep_empty_geoms, where_post
):
    # Prepare test data
    test_gdf = gpd.GeoDataFrame(
        data=[
            {
                "uidn": 1,
                "min_area": 2,
                "geometry": test_helper.TestData.polygon_small_island,
            },
            {
                "uidn": 2,
                "min_area": 2,
                "geometry": test_helper.TestData.polygon_with_island,
            },
        ],
        crs=31370,
    )
    input_path = tmp_path / f"polygons_small_holes_{suffix}"
    gfo.to_file(test_gdf, input_path)
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Run test
    if only_geom_input:

        def remove_inner_rings(geom):
            return pygeoops.remove_inner_rings(
                geometry=geom, min_area_to_keep=2, crs=input_layerinfo.crs
            )
    else:

        def remove_inner_rings(row):
            return pygeoops.remove_inner_rings(
                row.geometry,
                min_area_to_keep=row.min_area,
                crs=input_layerinfo.crs,
            )

    gfo.apply(
        input_path=str(input_path),
        output_path=str(output_path),
        func=remove_inner_rings,
        only_geom_input=only_geom_input,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms,
        where_post=where_post,
        batchsize=batchsize,
    )

    # Now check if the output file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index

    # Read result for some more detailed checks
    output_gdf = gfo.read_file(output_path).sort_values("uidn").reset_index(drop=True)
    output_layerinfo = gfo.get_layerinfo(output_path)

    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Number of rows depends on keep_empty_geoms and where_post
    if where_post == "ST_Area({geometrycolumn}) > 70" and keep_empty_geoms:
        assert output_layerinfo.featurecount == input_layerinfo.featurecount - 1
    elif where_post is None and not keep_empty_geoms:
        assert output_layerinfo.featurecount == input_layerinfo.featurecount
    else:
        raise ValueError(f"unsupported where_post in test: {where_post}")

    for row in output_gdf.itertuples():
        cur_geometry = row.geometry
        assert cur_geometry is not None

        # It should be a normal Polygon, but might be wrapped as MultiPolygon
        if isinstance(cur_geometry, sh_geom.MultiPolygon):
            assert len(cur_geometry.geoms) == 1
            cur_geometry = cur_geometry.geoms[0]
        assert isinstance(cur_geometry, sh_geom.Polygon)

        if row.uidn == 1:
            # In the 1st polygon the island must be removed
            assert len(cur_geometry.interiors) == 0
        elif row.uidn == 2:
            # In the 2nd polygon the island is larger, so should be there
            assert len(cur_geometry.interiors) == 1


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize("only_geom_input", [False, True])
@pytest.mark.parametrize("force_output_geometrytype", [None, GeometryType.POLYGON])
def test_apply_None(tmp_path, suffix, only_geom_input, force_output_geometrytype):
    """
    Some tests regarding None geometries.

    The test uses None geometries as input, but is similar to apply resulting in None.
    """
    # Prepare test data
    test_gdf = gpd.GeoDataFrame(
        data=[
            {
                "id": 1,
                "min_area": 2,
                "geometry": test_helper.TestData.polygon_small_island,
            },
            {
                "id": 2,
                "min_area": 2,
                "geometry": test_helper.TestData.polygon_with_island,
            },
            {"id": 3, "min_area": 2, "geometry": None},
        ],
        crs=31370,
    )
    input_path = tmp_path / f"polygons_small_holes_{suffix}"
    gfo.to_file(test_gdf, input_path)
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    if only_geom_input:

        def remove_inner_rings(geom):
            return pygeoops.remove_inner_rings(
                geometry=geom, min_area_to_keep=2, crs=input_layerinfo.crs
            )
    else:

        def remove_inner_rings(row):
            return pygeoops.remove_inner_rings(
                row.geometry, min_area_to_keep=row.min_area, crs=input_layerinfo.crs
            )

    gfo.apply(
        input_path=input_path,
        output_path=output_path,
        func=remove_inner_rings,
        only_geom_input=only_geom_input,
        force_output_geometrytype=force_output_geometrytype,
        batchsize=batchsize,
    )

    # Now check if the output file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index

    # Read result for some more detailed checks
    output_gdf = gfo.read_file(output_path).sort_values("id").reset_index(drop=True)
    output_layerinfo = gfo.get_layerinfo(output_path)

    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)
    if force_output_geometrytype is None:
        # The first partial file during calculation to be completed has None geometry,
        # so file is created with GEOMETRY type.
        pass
    elif force_output_geometrytype is None or suffix in (".shp", ".shp.zip"):
        assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON
    else:
        assert output_layerinfo.geometrytype == GeometryType.POLYGON

    for index in range(2):
        output_geometry = output_gdf["geometry"][index]
        if index == 2:
            assert output_geometry is None
            continue
        else:
            assert output_geometry is not None
        if isinstance(output_geometry, sh_geom.MultiPolygon):
            assert len(output_geometry.geoms) == 1
            output_geometry = output_geometry.geoms[0]
        assert isinstance(output_geometry, sh_geom.Polygon)

        if index == 0:
            # In the 1st polygon the island must be removed
            assert len(output_geometry.interiors) == 0
        elif index == 1:
            # In the 2nd polygon the island is larger, so should be there
            assert len(output_geometry.interiors) == 1


def test_apply_geooperation_invalid_operation(tmp_path):
    input_path = test_helper.get_testfile("polygon-parcel")
    layerinfo = gfo.get_layerinfo(input_path)

    with pytest.raises(ValueError, match="operation not supported: INVALID"):
        geoops_gpd._apply_geooperation(
            input_path=input_path,
            output_path=tmp_path / "output.gpkg",
            operation="INVALID",
            operation_params={},
            input_layer=layerinfo,
        )


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
def test_apply_vectorized(tmp_path, suffix):
    # Prepare test data
    test_gdf = gpd.GeoDataFrame(
        data=[
            {"id": 1, "geometry": test_helper.TestData.polygon_small_island},
            {"id": 2, "geometry": test_helper.TestData.polygon_with_island},
            {"id": 3, "geometry": None},
        ],
        crs=31370,
    )
    input_path = tmp_path / f"polygons_small_holes_{suffix}"
    gfo.to_file(test_gdf, input_path)
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    min_area = 2

    def remove_inner_rings_vectorized(geometry, min_area_to_keep, crs=None):
        return [
            pygeoops.remove_inner_rings(
                geom, min_area_to_keep=min_area_to_keep, crs=crs
            )
            for geom in geometry
        ]

    # Run test
    output_gdf = gfo.apply_vectorized(
        input_path=input_path,
        output_path=output_path,
        func=lambda geom: remove_inner_rings_vectorized(
            geom, min_area_to_keep=min_area
        ),
        batchsize=batchsize,
    )

    # Now check if the output file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index

    # Read result for some more detailed checks
    output_gdf = gfo.read_file(output_path).sort_values("id").reset_index(drop=True)
    output_layerinfo = gfo.get_layerinfo(output_path)

    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)

    for index in range(2):
        output_geometry = output_gdf["geometry"][index]
        if index == 2:
            assert output_geometry is None
            continue
        else:
            assert output_geometry is not None
        if isinstance(output_geometry, sh_geom.MultiPolygon):
            assert len(output_geometry.geoms) == 1
            output_geometry = output_geometry.geoms[0]
        assert isinstance(output_geometry, sh_geom.Polygon)

        if index == 0:
            # In the 1st polygon the island must be removed
            assert len(output_geometry.interiors) == 0
        elif index == 1:
            # In the 2nd polygon the island is larger, so should be there
            assert len(output_geometry.interiors) == 1


@pytest.mark.parametrize(
    "suffix, epsg", [(".gpkg", 31370), (".gpkg", 4326), (".shp", 31370)]
)
def test_buffer_styles(tmp_path, suffix, epsg):
    # Prepare test data
    input_path = test_helper.get_testfile("polygon-parcel", suffix=suffix, epsg=epsg)
    output_path = tmp_path / f"{input_path.stem}-output{suffix}"
    input_layerinfo = gfo.get_layerinfo(input_path)
    assert input_layerinfo.crs is not None
    distance = 1
    if input_layerinfo.crs.is_projected is False:
        # 1 degree = 111 km or 111000 m
        distance /= 111000
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Run standard buffer to compare with
    gfo.buffer(
        input_path=str(input_path),
        output_path=str(output_path),
        distance=distance,
        batchsize=batchsize,
    )

    # Read result
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
    area_default_buffer = sum(output_gdf.area)

    # Test polygon buffer with square endcaps
    output_path = (
        output_path.parent / f"{output_path.stem}_endcap_join{output_path.suffix}"
    )
    gfo.buffer(
        input_path=input_path,
        output_path=output_path,
        distance=distance,
        endcap_style=_geometry_util.BufferEndCapStyle.SQUARE,
        join_style=_geometry_util.BufferJoinStyle.MITRE,
        batchsize=batchsize,
    )

    # Now check if the output file is correctly created
    assert output_path.exists()
    output_layerinfo = gfo.get_layerinfo(output_path)
    assert input_layerinfo.featurecount == output_layerinfo.featurecount + 1
    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON

    # Read result for some more detailed checks
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None
    area_square_buffer = sum(output_gdf.area)
    assert area_square_buffer > area_default_buffer


@pytest.mark.parametrize(
    "suffix, epsg, testfile, gridsize",
    [
        (".gpkg", 31370, "polygon-parcel", 0.01),
        (".gpkg", 31370, "linestring-row-trees", 0.01),
        (".gpkg", 4326, "polygon-parcel", 0.0),
        (".shp", 31370, "polygon-parcel", 0.01),
        (".shp", 4326, "polygon-parcel", 0.0),
    ],
)
def test_simplify_lang(tmp_path, suffix, epsg, testfile, gridsize):
    input_path = test_helper.get_testfile(testfile, suffix=suffix, epsg=epsg)
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    assert input_layerinfo.crs is not None
    # 1 degree = 111 km or 111000 m
    tolerance = 5 if input_layerinfo.crs.is_projected else 5 / 111000

    # Test lang algorithm
    output_path = tmp_path / f"{input_path.stem}-output_lang{suffix}"
    gfo.simplify(
        input_path=str(input_path),
        output_path=str(output_path),
        tolerance=tolerance,
        algorithm=_geometry_util.SimplifyAlgorithm.LANG,
        lookahead=8,
        gridsize=gridsize,
        batchsize=batchsize,
    )

    # Check if the output file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(output_path)
    expected_featurecount = input_layerinfo.featurecount
    if testfile == "polygon-parcel":
        # The EMPTY geometry will be removed
        expected_featurecount -= 1
        if gridsize > 0.0:
            # The sliver geometry will be removed
            expected_featurecount -= 1
    assert output_layerinfo.featurecount == expected_featurecount
    assert len(output_layerinfo.columns) == len(input_layerinfo.columns)
    assert output_layerinfo.geometrytype == input_layerinfo.geometrytype

    # Check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == output_layerinfo.featurecount
    assert output_gdf["geometry"][0] is not None
    # TODO: some more in-depth validations would be better


@pytest.mark.parametrize(
    "suffix, epsg, testfile, gridsize",
    [
        (".gpkg", 31370, "polygon-parcel", 0.01),
        (".gpkg", 31370, "linestring-row-trees", 0.01),
        (".gpkg", 4326, "polygon-parcel", 0.0),
        (".shp", 31370, "polygon-parcel", 0.01),
        (".shp", 4326, "polygon-parcel", 0.0),
    ],
)
def test_simplify_vw(tmp_path, suffix, epsg, testfile, gridsize):
    # Skip test if simplification is not available
    _ = pytest.importorskip("simplification")

    # Init
    input_path = test_helper.get_testfile(testfile, suffix=suffix, epsg=epsg)
    input_layerinfo = gfo.get_layerinfo(input_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)
    assert input_layerinfo.crs is not None
    # 1 degree = 111 km or 111000 m
    tolerance = 5 if input_layerinfo.crs.is_projected else 5 / 111000

    # Test vw (visvalingam-whyatt) algorithm
    output_path = tmp_path / f"{input_path.stem}-output_vw{suffix}"
    gfo.simplify(
        input_path=input_path,
        output_path=output_path,
        tolerance=tolerance,
        algorithm=_geometry_util.SimplifyAlgorithm.VISVALINGAM_WHYATT,
        gridsize=gridsize,
        batchsize=batchsize,
    )

    # Check if the file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(output_path)
    expected_featurecount = input_layerinfo.featurecount
    if testfile == "polygon-parcel":
        # The EMPTY geometry will be removed
        expected_featurecount -= 1
        if gridsize > 0.0:
            # The sliver geometry will be removed
            expected_featurecount -= 1
    assert output_layerinfo.featurecount == expected_featurecount
    assert len(input_layerinfo.columns) == len(output_layerinfo.columns)
    assert output_layerinfo.geometrytype == input_layerinfo.geometrytype

    # Check the contents of the result file
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert input_gdf.crs == output_gdf.crs
    assert len(output_gdf) == output_layerinfo.featurecount
    assert output_gdf["geometry"][0] is not None
    # TODO: a more in-depth check would be better
