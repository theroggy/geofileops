import math
from pathlib import Path

import geopandas as gpd
import pytest
import shapely

import geofileops as gfo
from geofileops import GeometryType

# from geofileops._compat import GDAL_GTE_38, GDAL_GTE_39
from geofileops.util._geofileinfo import GeofileInfo
from tests import test_helper
from tests.test_helper import SUFFIXES_GEOOPS

# if GDAL_GTE_38 and not GDAL_GTE_39:
#     pytest.skip(
#         "These tests crash with GDAL>=3.8 and GDAL<3.9", allow_module_level=True
#     )

input_wkts_1 = [
    "POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0))",
    "POLYGON ((10 1, 13 1, 13 4, 10 4, 10 1))",
    "POLYGON ((7 2, 8 2, 8 5, 1 5, 1 4, 7 4, 7 2))",
    "POLYGON ((7 1, 7 -2, 10 -2, 10 -1, 8 -1, 8 1, 7 1))",
]

input_wkts_2 = [
    "POLYGON ((-2 4, 0 4, 0 6, -2 6, -2 4))",
    "POLYGON ((3 6, 5 6, 5 8, 3 8, 3 6))",
]


@pytest.mark.parametrize("suffix", SUFFIXES_GEOOPS)
@pytest.mark.parametrize(
    "columns, gridsize, where_post, subdivide_coords, fid_column, exp_featurecount",
    [
        (["OIDN", "UIDN"], 0.0, "ST_Area(geom) > 2000", 0, "fid", 25),
        (None, 0.01, None, 10, "fid_custom", 27),
    ],
)
def test_export_by_location(
    tmp_path,
    suffix,
    columns,
    gridsize,
    where_post,
    subdivide_coords,
    fid_column,
    exp_featurecount,
):
    input_to_select_from_path = test_helper.get_testfile(
        "polygon-parcel", suffix=suffix, fid_column=fid_column
    )
    input_to_compare_with_path = test_helper.get_testfile("polygon-zone", suffix=suffix)
    output_path = tmp_path / f"{input_to_select_from_path.stem}-output{suffix}"
    input_layerinfo = gfo.get_layerinfo(input_to_select_from_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Test
    gfo.export_by_location(
        input_to_select_from_path=str(input_to_select_from_path),
        input_to_compare_with_path=str(input_to_compare_with_path),
        output_path=str(output_path),
        input1_columns=columns,
        gridsize=gridsize,
        where_post=where_post,
        subdivide_coords=subdivide_coords,
        batchsize=batchsize,
    )

    # Check if the output file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(output_path)
    exp_columns = len(input_layerinfo.columns) if columns is None else len(columns)
    assert len(output_layerinfo.columns) == exp_columns
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON
    assert output_layerinfo.featurecount == exp_featurecount

    # Check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None


@pytest.mark.parametrize(
    "query, area_inters_column_name, min_area_intersect, subdivide_coords, "
    "exp_featurecount",
    [
        (None, None, None, 10, 27),
        (None, "area_custom", None, 0, 27),
        ("within is False", "area_custom", None, 0, 40),
        (None, None, 1000, 10, 24),
        ("within is False", None, 1000, 0, 16),
    ],
)
@pytest.mark.filterwarnings("ignore:.*Field format '' not supported.*")
def test_export_by_location_area(
    tmp_path,
    query,
    area_inters_column_name,
    min_area_intersect,
    subdivide_coords,
    exp_featurecount,
):
    input_to_select_from_path = test_helper.get_testfile("polygon-parcel")
    input_to_compare_with_path = test_helper.get_testfile("polygon-zone")
    output_path = tmp_path / f"{input_to_select_from_path.stem}-output.gpkg"
    input_layerinfo = gfo.get_layerinfo(input_to_select_from_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Test
    kwargs = {}
    if query is not None:
        kwargs["spatial_relations_query"] = query
    gfo.export_by_location(
        input_to_select_from_path=str(input_to_select_from_path),
        input_to_compare_with_path=str(input_to_compare_with_path),
        output_path=str(output_path),
        area_inters_column_name=area_inters_column_name,
        min_area_intersect=min_area_intersect,
        batchsize=batchsize,
        subdivide_coords=subdivide_coords,
        **kwargs,
    )

    # Check if the output file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(output_path)
    exp_columns = len(input_layerinfo.columns)
    exp_area_inters_column_name = area_inters_column_name
    if exp_area_inters_column_name is None and min_area_intersect is not None:
        exp_area_inters_column_name = "area_inters"
    if exp_area_inters_column_name is not None:
        exp_columns += 1
        assert exp_area_inters_column_name in output_layerinfo.columns
    assert len(output_layerinfo.columns) == exp_columns
    assert output_layerinfo.geometrytype == GeometryType.MULTIPOLYGON
    assert output_layerinfo.featurecount == exp_featurecount

    # Check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    assert output_gdf["geometry"][0] is not None

    # If an area column name is specified, check the number of None values
    # (= number features without intersection)
    if area_inters_column_name is not None:
        exp_nb_None = 21 if query == "within is False" else 0
        assert len(output_gdf[output_gdf.area_custom.isna()]) == exp_nb_None


def test_export_by_location_force(tmp_path):
    # Prepare test data
    input1_path = test_helper.get_testfile("polygon-parcel")
    input2_path = test_helper.get_testfile("polygon-zone")
    output_path = tmp_path / f"output{input1_path.suffix}"
    output_path.touch()

    # Test with force False (the default): existing output file should stay the same
    mtime_orig = output_path.stat().st_mtime
    gfo.export_by_location(
        input_to_select_from_path=input1_path,
        input_to_compare_with_path=input2_path,
        output_path=output_path,
    )
    assert output_path.stat().st_mtime == mtime_orig

    # With force=True
    gfo.export_by_location(
        input_to_select_from_path=input1_path,
        input_to_compare_with_path=input2_path,
        output_path=output_path,
        force=True,
    )
    assert output_path.stat().st_mtime != mtime_orig


@pytest.mark.parametrize(
    "kwargs, expected_error",
    [
        ({"subdivide_coords": -1}, "subdivide_coords < 0 is not allowed"),
    ],
)
def test_export_by_location_invalid_params(kwargs, expected_error):
    with pytest.raises(ValueError, match=expected_error):
        gfo.export_by_location(
            input_to_select_from_path="input.gpkg",
            input_to_compare_with_path="input2.gpkg",
            output_path="output.gpkg",
            **kwargs,
        )


@pytest.mark.parametrize("subdivide_coords", [0, 10])
@pytest.mark.parametrize("area_inters_column_name", [None, "area_inters"])
@pytest.mark.parametrize(
    "query, exp_featurecount",
    [
        ("intersects is True or intersects is False", 48),
        ("intersects is True", 27),
        ("intersects is False", 21),
        ("within is True", 8),
        ("T-F--F--- is True", 8),  # Equivalent to "within is True"
        ("within is False", 40),
        ("T-F--F--- is False", 40),  # Equivalent to "within is False"
        ("disjoint is True", 21),
        ("FF*FF**** is True", 21),  # Equivalent to "disjoint is True"
        ("disjoint is False", 27),
        ("FF*FF**** is False", 27),  # Equivalent to "disjoint is False"
        ("within is True or disjoint is True", 29),
        ("within is True and disjoint is True", 0),
        ("equals is True", 0),
        ("equals is False", 48),
        ("coveredby is True", 8),
        ("coveredby is False", 40),
        ("covers is True", 0),
        ("covers is False", 48),
        ("touches is True", 0),
        ("touches is False", 48),
        ("", 48),
    ],
)
def test_export_by_location_query(
    tmp_path, query, subdivide_coords, area_inters_column_name, exp_featurecount
):
    # Having asterisks in the test parameters above gives issues... so use dashes there
    # and replace them with asterisks here.
    query = query.replace("-", "*")

    # Prepare test data
    input_to_select_from_path = test_helper.get_testfile("polygon-parcel")
    input_to_compare_with_path = test_helper.get_testfile("polygon-zone")
    output_path = tmp_path / f"{input_to_select_from_path.stem}-output.gpkg"

    # Test
    _test_export_by_location(
        input_to_select_from_path,
        input_to_compare_with_path,
        output_path,
        spatial_relations_query=query,
        area_inters_column_name=area_inters_column_name,
        subdivide_coords=subdivide_coords,
        exp_featurecount=exp_featurecount,
    )


@pytest.mark.parametrize("input_to_select_from_wkts", [input_wkts_1])
@pytest.mark.parametrize(
    "input_to_compare_with_wkts",
    [
        [
            "POLYGON ((0.5 0.5, 2.5 0.5, 2.5 2.5, 0.5 2.5, 0.5 0.5))",
            *input_wkts_2,
        ]
    ],
)
@pytest.mark.parametrize("subdivide_coords", [0, 10])
@pytest.mark.parametrize(
    "spatial_relations_query, exp_featurecount",
    [("contains is True", 1), ("contains is False", 3)],
)
def test_query_contains(
    tmp_path,
    input_to_select_from_wkts,
    input_to_compare_with_wkts,
    spatial_relations_query,
    subdivide_coords,
    exp_featurecount,
):
    _test_export_by_location_for_wkts(
        tmp_path,
        input_to_select_from_wkts,
        input_to_compare_with_wkts,
        spatial_relations_query,
        subdivide_coords,
        exp_featurecount,
    )


@pytest.mark.parametrize("input_to_compare_with_wkts", [input_wkts_1])
@pytest.mark.parametrize(
    "input_to_select_from_wkts",
    [["POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))", *input_wkts_2]],
)
@pytest.mark.parametrize("subdivide_coords", [0, 10])
@pytest.mark.parametrize(
    "spatial_relations_query, exp_featurecount",
    [("coveredby is True", 1), ("coveredby is False", 2)],
)
def test_query_coveredby(
    tmp_path,
    input_to_select_from_wkts,
    input_to_compare_with_wkts,
    spatial_relations_query,
    subdivide_coords,
    exp_featurecount,
):
    _test_export_by_location_for_wkts(
        tmp_path,
        input_to_select_from_wkts,
        input_to_compare_with_wkts,
        spatial_relations_query,
        subdivide_coords,
        exp_featurecount,
    )


@pytest.mark.parametrize("input_to_compare_with_wkts", [input_wkts_1])
@pytest.mark.parametrize(
    "input_to_select_from_wkts",
    [["POLYGON ((-1 -1, 4 -1, 4 4, -1 4, -1 -1))", *input_wkts_2]],
)
@pytest.mark.parametrize("subdivide_coords", [0, 10])
@pytest.mark.parametrize(
    "spatial_relations_query, exp_featurecount",
    [("covers is True", 1), ("covers is False", 2)],
)
def test_query_covers(
    tmp_path,
    input_to_select_from_wkts,
    input_to_compare_with_wkts,
    spatial_relations_query,
    subdivide_coords,
    exp_featurecount,
):
    _test_export_by_location_for_wkts(
        tmp_path,
        input_to_select_from_wkts,
        input_to_compare_with_wkts,
        spatial_relations_query,
        subdivide_coords,
        exp_featurecount,
    )


@pytest.mark.parametrize("input_to_compare_with_wkts", [input_wkts_1])
@pytest.mark.parametrize(
    "input_to_select_from_wkts",
    [
        [
            "POLYGON ((4 1, 6 1, 6 3, 4 3, 4 1))",
            "POLYGON ((4 -2, 6 -2, 6 0, 4 0, 4 -2))",
            "POLYGON ((9 0, 11 0, 11 2, 9 2, 9 0))",
            *input_wkts_2,
        ]
    ],
)
@pytest.mark.parametrize("subdivide_coords", [0, 10])
@pytest.mark.parametrize(
    "spatial_relations_query, exp_featurecount",
    [("disjoint is True", 4), ("disjoint is False", 1)],
)
def test_query_disjoint(
    tmp_path,
    input_to_select_from_wkts,
    input_to_compare_with_wkts,
    spatial_relations_query,
    subdivide_coords,
    exp_featurecount,
):
    _test_export_by_location_for_wkts(
        tmp_path,
        input_to_select_from_wkts,
        input_to_compare_with_wkts,
        spatial_relations_query,
        subdivide_coords,
        exp_featurecount,
    )


@pytest.mark.parametrize("input_to_compare_with_wkts", [input_wkts_1])
@pytest.mark.parametrize(
    "input_to_select_from_wkts",
    [["POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0))", *input_wkts_2]],
)
@pytest.mark.parametrize("subdivide_coords", [0, 10])
@pytest.mark.parametrize(
    "spatial_relations_query, exp_featurecount",
    [("equals is True", 1), ("equals is False", 2)],
)
def test_query_equals(
    tmp_path,
    input_to_select_from_wkts,
    input_to_compare_with_wkts,
    spatial_relations_query,
    subdivide_coords,
    exp_featurecount,
):
    _test_export_by_location_for_wkts(
        tmp_path,
        input_to_select_from_wkts,
        input_to_compare_with_wkts,
        spatial_relations_query,
        subdivide_coords,
        exp_featurecount,
    )


@pytest.mark.parametrize("input_to_compare_with_wkts", [input_wkts_1])
@pytest.mark.parametrize(
    "input_to_select_from_wkts",
    [["POLYGON ((2 1, 4 1, 4 3, 2 3, 2 1))", *input_wkts_2]],
)
@pytest.mark.parametrize("subdivide_coords", [0, 10])
@pytest.mark.parametrize(
    "spatial_relations_query, exp_featurecount",
    [("intersects is True", 1), ("intersects is False", 2)],
)
def test_query_intersects(
    tmp_path,
    input_to_select_from_wkts,
    input_to_compare_with_wkts,
    spatial_relations_query,
    subdivide_coords,
    exp_featurecount,
):
    _test_export_by_location_for_wkts(
        tmp_path,
        input_to_select_from_wkts,
        input_to_compare_with_wkts,
        spatial_relations_query,
        subdivide_coords,
        exp_featurecount,
    )


@pytest.mark.parametrize("input_to_compare_with_wkts", [input_wkts_1])
@pytest.mark.parametrize(
    "input_to_select_from_wkts",
    [
        [
            "POLYGON ((2 1, 4 1, 4 3, 2 3, 2 1))",
            "POLYGON ((2 -2, 4 -2, 4 0, 2 0, 2 -2))",
            *input_wkts_2,
        ]
    ],
)
@pytest.mark.parametrize("subdivide_coords", [0, 10])
@pytest.mark.parametrize(
    "spatial_relations_query, exp_featurecount",
    [
        ("intersects is True and touches is False", 1),
        ("intersects is True and touches is True", 1),
        ("intersects is True or touches is False", 4),
        ("intersects is True or touches is True", 2),
    ],
)
def test_query_intersects_true_touches_false(
    tmp_path,
    input_to_select_from_wkts,
    input_to_compare_with_wkts,
    spatial_relations_query,
    subdivide_coords,
    exp_featurecount,
):
    _test_export_by_location_for_wkts(
        tmp_path,
        input_to_select_from_wkts,
        input_to_compare_with_wkts,
        spatial_relations_query,
        subdivide_coords,
        exp_featurecount,
    )


@pytest.mark.parametrize("input_to_compare_with_wkts", [input_wkts_1])
@pytest.mark.parametrize(
    "input_to_select_from_wkts",
    [["POLYGON ((2 1, 4 1, 4 3, 2 3, 2 1))", *input_wkts_2]],
)
@pytest.mark.parametrize("subdivide_coords", [0, 10])
@pytest.mark.parametrize(
    "spatial_relations_query, exp_featurecount",
    [("overlaps is True", 1), ("overlaps is False", 2)],
)
def test_query_overlaps(
    tmp_path,
    input_to_select_from_wkts,
    input_to_compare_with_wkts,
    spatial_relations_query,
    subdivide_coords,
    exp_featurecount,
):
    _test_export_by_location_for_wkts(
        tmp_path,
        input_to_select_from_wkts,
        input_to_compare_with_wkts,
        spatial_relations_query,
        subdivide_coords,
        exp_featurecount,
    )


@pytest.mark.parametrize("input_to_compare_with_wkts", [input_wkts_1])
@pytest.mark.parametrize(
    "input_to_select_from_wkts",
    [["POLYGON ((3 1, 5 1, 5 3, 3 3, 3 1))", *input_wkts_2]],
)
@pytest.mark.parametrize("subdivide_coords", [0, 10])
@pytest.mark.parametrize(
    "spatial_relations_query, exp_featurecount",
    [("touches is True", 1), ("touches is False", 2)],
)
def test_query_touches(
    tmp_path,
    input_to_select_from_wkts,
    input_to_compare_with_wkts,
    spatial_relations_query,
    subdivide_coords,
    exp_featurecount,
):
    _test_export_by_location_for_wkts(
        tmp_path,
        input_to_select_from_wkts,
        input_to_compare_with_wkts,
        spatial_relations_query,
        subdivide_coords,
        exp_featurecount,
    )


@pytest.mark.parametrize("input_to_compare_with_wkts", [input_wkts_1])
@pytest.mark.parametrize(
    "input_to_select_from_wkts",
    [["POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))", *input_wkts_2]],
)
@pytest.mark.parametrize("subdivide_coords", [0, 10])
@pytest.mark.parametrize(
    "spatial_relations_query, exp_featurecount",
    [("within is True", 1), ("within is False", 2)],
)
def test_query_within(
    tmp_path,
    input_to_select_from_wkts,
    input_to_compare_with_wkts,
    spatial_relations_query,
    subdivide_coords,
    exp_featurecount,
):
    _test_export_by_location_for_wkts(
        tmp_path,
        input_to_select_from_wkts,
        input_to_compare_with_wkts,
        spatial_relations_query,
        subdivide_coords,
        exp_featurecount,
    )


def _test_export_by_location_for_wkts(
    tmp_path: Path,
    input_to_select_from_wkts: list[str],
    input_to_compare_with_wkts: list[str],
    spatial_relations_query: str,
    subdivide_coords: int,
    exp_featurecount: int,
):
    """Helper function to run export_by_location with wkt geometries as input.

    Args:
        tmp_path (Path): temporary directory to write files to.
        input_to_select_from_wkts (list[str]): list of wkt strings to use as
            input_to_select_from.
        input_to_compare_with_wkts (list[str]): list of wkt strings to use as
            input_to_compare_with.
        spatial_relations_query (str): the spatial relations query to use.
        subdivide_coords (int): value to use for the subdivide_coords parameter.
        exp_featurecount (int): the number of features expected in the output file.
    """
    # Prepare input_to_select_from file
    input_to_select_from_path = tmp_path / "input_to_select_from.gpkg"
    input_to_select_from_geoms = [
        shapely.from_wkt(wkt) for wkt in input_to_select_from_wkts
    ]
    gdf_parcel = gpd.GeoDataFrame(geometry=input_to_select_from_geoms, crs="EPSG:31370")
    gfo.to_file(gdf=gdf_parcel, path=input_to_select_from_path)

    # Prepare input_to_compare_with file
    input_to_compare_with_path = tmp_path / "input_to_compare_with.gpkg"
    input_to_compare_with_geoms = [
        shapely.segmentize(shapely.from_wkt(wkt), 1)
        for wkt in input_to_compare_with_wkts
    ]
    gdf_zone = gpd.GeoDataFrame(geometry=input_to_compare_with_geoms, crs="EPSG:31370")
    gfo.to_file(gdf=gdf_zone, path=input_to_compare_with_path)

    output = "_".join(spatial_relations_query.split(" ")).lower()
    output_path = tmp_path / f"{output}.gpkg"

    _test_export_by_location(
        input_to_select_from_path,
        input_to_compare_with_path,
        output_path,
        spatial_relations_query,
        area_inters_column_name=None,
        subdivide_coords=subdivide_coords,
        exp_featurecount=exp_featurecount,
    )


def _test_export_by_location(
    input_to_select_from_path: Path,
    input_to_compare_with_path: Path,
    output_path: Path,
    spatial_relations_query: str,
    area_inters_column_name: str | None,
    subdivide_coords: int,
    exp_featurecount: int,
):
    """Helper function to test export_by_location with basic parameters.

    Args:
        input_to_select_from_path (Path): input file to select from.
        input_to_compare_with_path (Path): input file to compare with.
        output_path (Path): output file to write to.
        spatial_relations_query (str): spatial relations query to use.
        area_inters_column_name (Optional[str]): the name of the column to use for the
            area of the intersection.
        subdivide_coords (int): the number of coordinates to use to subdivide the
            geometries in input_to_compare_with_path.
        exp_featurecount (int): the number of features expected in the output file.
    """
    input_layerinfo = gfo.get_layerinfo(input_to_select_from_path)
    batchsize = math.ceil(input_layerinfo.featurecount / 2)

    # Run test
    gfo.export_by_location(
        input_to_select_from_path=input_to_select_from_path,
        input_to_compare_with_path=input_to_compare_with_path,
        output_path=output_path,
        spatial_relations_query=spatial_relations_query,
        area_inters_column_name=area_inters_column_name,
        batchsize=batchsize,
        subdivide_coords=subdivide_coords,
    )

    # Plot
    plot_path = output_path.with_suffix(".png")
    test_helper.plot(
        [input_to_select_from_path, input_to_compare_with_path, output_path], plot_path
    )

    # Check if the output file is correctly created
    assert output_path.exists()
    exp_spatial_index = GeofileInfo(output_path).default_spatial_index
    assert gfo.has_spatial_index(output_path) is exp_spatial_index
    output_layerinfo = gfo.get_layerinfo(output_path)
    exp_columns = len(input_layerinfo.columns)
    if area_inters_column_name is not None:
        exp_columns += 1
        assert area_inters_column_name in output_layerinfo.columns
    assert len(output_layerinfo.columns) == exp_columns
    assert output_layerinfo.geometrytype == input_layerinfo.geometrytype
    assert output_layerinfo.featurecount == exp_featurecount

    # Check the contents of the result file
    output_gdf = gfo.read_file(output_path)
    if exp_featurecount > 0:
        assert output_gdf["geometry"][0] is not None
    elif exp_featurecount == 0:
        assert output_gdf.empty
