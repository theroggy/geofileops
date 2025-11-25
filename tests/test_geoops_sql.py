import pytest

import geofileops as gfo
from geofileops.util import _geoops_sql
from geofileops.util._geopath_util import GeoPath
from tests import test_helper


@pytest.mark.parametrize(
    "descr, nb_rows_input_layer, nb_parallel, batchsize, is_twolayer_operation, "
    "exp_nb_parallel, exp_nb_batches",
    [
        ("0 input rows, batchsize=1, singlelayer", 0, 2, 1, 0, 1, 1),
        ("0 input rows, nb_parallel=2, singlelayer", 0, 2, 0, 0, 1, 1),
        ("0 input rows, singlelayer", 0, -1, -1, 0, 1, 1),
        ("0 input rows, twolayer", 0, -1, -1, 1, 1, 1),
        ("1 input row, batchsize=1, singlelayer", 1, 2, 1, 0, 1, 1),
        ("1 input rows, nb_parallel=2, singlelayer", 1, 2, 0, 0, 1, 1),
        ("1 input rows, singlelayer", 1, -1, -1, 0, 1, 1),
        ("1 input rows, twolayer", 1, -1, -1, 1, 1, 1),
        ("1 input rows, singlelayer", 1, -1, -1, 0, 1, 1),
        ("2 input rows, nb_parallel=10, singlelayer", 2, 10, -1, 0, 2, 2),
        ("100 input row, batchsize=20, singlelayer", 100, -1, 20, 0, 5, 5),
        ("100 input rows, nb_parallel=2, singlelayer", 100, 2, 0, 0, 2, 2),
        ("100 input rows, nb_parallel=1, singlelayer", 100, 1, 0, 0, 1, 1),
        ("100 input rows, singlelayer", 100, -1, -1, 0, 1, 1),
        ("100 input rows, twolayer", 100, -1, -1, 1, 1, 1),
        ("1000 input row, batchsize=20, singlelayer", 1000, -1, 20, 0, 8, 56),
        ("1000 input rows, nb_parallel=2, singlelayer", 1000, 2, 0, 0, 2, 2),
        ("1000 input rows, nb_parallel=1, singlelayer", 1000, 1, 0, 0, 1, 1),
        ("1000 input rows, singlelayer", 1000, -1, -1, 0, 8, 8),
        ("1000 input rows, twolayer", 1000, -1, -1, 1, 8, 16),
    ],
)
def test_determine_nb_batches(
    descr: str,  # noqa: ARG001
    nb_rows_input_layer: int,
    nb_parallel: int,
    batchsize: int,
    is_twolayer_operation: bool,
    exp_nb_parallel: int,
    exp_nb_batches: int,
):
    res_nb_parallel, res_nb_batches = _geoops_sql._determine_nb_batches(
        nb_rows_input_layer=nb_rows_input_layer,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        is_twolayer_operation=is_twolayer_operation,
        cpu_count=8,
    )
    assert exp_nb_parallel == res_nb_parallel
    assert exp_nb_batches == res_nb_batches


@pytest.mark.parametrize(
    "input1_suffix, input2_suffix, output1_suffix, output2_suffix, unzip_gpkg",
    [
        (".gpkg", None, ".gpkg", None, False),
        (".gpkg.zip", None, ".gpkg.zip", None, False),
        (".gpkg.zip", None, ".gpkg", None, True),
        (".gpkg", ".gpkg", ".gpkg", ".gpkg", True),
        (".gpkg.zip", ".gpkg.zip", ".gpkg", ".gpkg", True),
        (".gpkg", ".shp", ".gpkg", ".gpkg", False),
        (".gpkg", ".sqlite", ".gpkg", ".gpkg", False),
        (".shp", None, ".gpkg", None, False),
        (".shp", ".gpkg.zip", ".gpkg", ".gpkg", True),
        (".shp", ".gpkg.zip", ".gpkg", ".gpkg.zip", False),
        (".shp", ".sqlite", ".sqlite", ".sqlite", False),
        (".sqlite", None, ".sqlite", None, True),
        (".sqlite", ".shp", ".sqlite", ".sqlite", False),
        (".sqlite", ".sqlite", ".sqlite", ".sqlite", False),
    ],
)
def test_convert_to_spatialite_based(
    tmp_path, input1_suffix, input2_suffix, output1_suffix, output2_suffix, unzip_gpkg
):
    input1_path = test_helper.get_testfile("polygon-parcel", suffix=input1_suffix)
    input1_layer = gfo.get_layerinfo(input1_path)
    input2_path = None
    input2_layer = None
    if input2_suffix is not None:
        input2_path = test_helper.get_testfile("polygon-parcel", suffix=input2_suffix)
        input2_layer = gfo.get_layerinfo(input2_path)

    input1_out_path, input1_out_layer, input2_out_path, input2_out_layer = (
        _geoops_sql._convert_to_spatialite_based(  # type: ignore[assignment]
            input1_path=input1_path,
            input1_layer=input1_layer,
            tmp_dir=tmp_path,
            unzip_gpkg=unzip_gpkg,
            input2_path=input2_path,
            input2_layer=input2_layer,
        )
    )

    assert GeoPath(input1_out_path).suffix_full == output1_suffix
    assert input1_out_path.exists()
    assert input1_out_layer.name in gfo.listlayers(input1_out_path)

    # If the file format hasn't changed, the file should not be copied
    if GeoPath(input1_path).suffix_full == GeoPath(input1_out_path).suffix_full:
        assert input1_path == input1_out_path

    if input2_suffix is not None:
        assert input2_out_path.exists()
        assert input2_out_layer.name in gfo.listlayers(input2_out_path)
        assert GeoPath(input2_out_path).suffix_full == output2_suffix
        # If the file format hasn't changed, the file should not be copied
        if GeoPath(input2_out_path).suffix_full == GeoPath(input2_path).suffix_full:
            assert input2_out_path == input2_path
        # If both input files were copied, they should have been copied to seperate
        # files
        if input1_out_path.parent == tmp_path and input2_suffix is not None:
            assert input1_out_path != input2_out_path
    else:
        assert input2_out_path is None


@pytest.mark.parametrize(
    "descr, testfile, subdivide_coords, expected_subdivided",
    [
        ("input poly not complex", "polygon-zone", 1000, False),
        ("input poly complex", "polygon-zone", 1, True),
        ("input line not complex", "linestring-watercourse", 10_000, False),
        ("input line complex", "linestring-watercourse", 2, True),
        ("input point complex", "point", 1, False),
    ],
)
def test_subdivide_layer(
    tmp_path,
    descr,  # noqa: ARG001
    testfile,
    subdivide_coords,
    expected_subdivided: bool,
):
    path = test_helper.get_testfile(testfile)
    output_path = tmp_path / "output.gpkg"
    result = _geoops_sql._subdivide_layer(
        path=path,
        layer=None,
        output_path=output_path,
        subdivide_coords=subdivide_coords,
        keep_fid=False,
        tmp_basedir=tmp_path,
    )

    if expected_subdivided:
        assert result is not None
    else:
        assert result is None


@pytest.mark.parametrize(
    "nb_rows, fraction", [("1000", "1"), ("10", "5"), ("10", "1"), (None, None)]
)
def test_subdivide_layer_check_parallel(tmp_path, nb_rows, fraction):
    path = test_helper.get_testfile("polygon-parcel")
    layer = gfo.get_layerinfo(path)

    envs = {
        "GFO_SUBDIVIDE_CHECK_PARALLEL_FRACTION": fraction,
        "GFO_SUBDIVIDE_CHECK_PARALLEL_ROWS": nb_rows,
    }
    output_path = tmp_path / "output.gpkg"
    with gfo.TempEnv(envs):
        result = _geoops_sql._subdivide_layer(
            path=path,
            layer=layer,
            output_path=output_path,
            subdivide_coords=1,
            tmp_basedir=None,
            keep_fid=False,
        )

    assert result is not None


@pytest.mark.parametrize(
    (
        "query, "
        "subdivided, "
        "optimize_simple_queries, "
        "exp_spatial_relation_filter, "
        "exp_spatial_relation_column, "
        "exp_groupby,"
        "exp_true_for_disjoint, "
        "exp_relation_should_be_found"
    ),
    [
        (
            "intersects is True",
            False,
            False,
            (
                '((ST_RelateMatch(sub_filter."GFO_$TEMP$_SPATIAL_RELATION",'
                " 'T********') = 1 or"
                ' ST_RelateMatch(sub_filter."GFO_$TEMP$_SPATIAL_RELATION",'
                " '*T*******') = 1 or"
                ' ST_RelateMatch(sub_filter."GFO_$TEMP$_SPATIAL_RELATION",'
                " '***T*****') = 1 or"
                ' ST_RelateMatch(sub_filter."GFO_$TEMP$_SPATIAL_RELATION",'
                " '****T****') = 1) = 1)"
            ),
            (
                ",ST_relate(layer1.{input1_geometrycolumn}"
                ', layer2.{input2_geometrycolumn}) AS "GFO_$TEMP$_SPATIAL_RELATION"'
            ),
            "",
            False,
            True,
        ),
        (
            "intersects is True",
            False,
            True,
            'sub_filter."GFO_$TEMP$_SPATIAL_RELATION" = 1',
            (
                ",ST_intersects(layer1.{input1_geometrycolumn}"
                ', layer2.{input2_geometrycolumn}) AS "GFO_$TEMP$_SPATIAL_RELATION"'
            ),
            "",
            False,
            True,
        ),
        (
            "intersects is True",
            True,
            False,
            (
                '((ST_RelateMatch(sub_filter."GFO_$TEMP$_SPATIAL_RELATION",'
                " 'T********') = 1 or"
                ' ST_RelateMatch(sub_filter."GFO_$TEMP$_SPATIAL_RELATION",'
                " '*T*******') = 1 or"
                ' ST_RelateMatch(sub_filter."GFO_$TEMP$_SPATIAL_RELATION",'
                " '***T*****') = 1 or"
                ' ST_RelateMatch(sub_filter."GFO_$TEMP$_SPATIAL_RELATION",'
                " '****T****') = 1) = 1)"
            ),
            (
                ",ST_relate(layer1.{input1_geometrycolumn}"
                ", ST_union(layer2.{input2_geometrycolumn}))"
                ' AS "GFO_$TEMP$_SPATIAL_RELATION"'
            ),
            "GROUP BY layer2.fid_1",
            False,
            True,
        ),
        (
            "intersects is True",
            True,
            True,
            'sub_filter."GFO_$TEMP$_SPATIAL_RELATION" = 1',
            (
                ",ST_intersects(layer1.{input1_geometrycolumn},"
                " ST_union(layer2.{input2_geometrycolumn}))"
                ' AS "GFO_$TEMP$_SPATIAL_RELATION"'
            ),
            "GROUP BY layer2.fid_1",
            False,
            True,
        ),
        (
            "intersects is False",
            False,
            False,
            (
                'NOT (((ST_RelateMatch(sub_filter."GFO_$TEMP$_SPATIAL_RELATION",'
                " 'T********') = 1 or"
                ' ST_RelateMatch(sub_filter."GFO_$TEMP$_SPATIAL_RELATION",'
                " '*T*******') = 1 or"
                ' ST_RelateMatch(sub_filter."GFO_$TEMP$_SPATIAL_RELATION",'
                " '***T*****') = 1 or"
                ' ST_RelateMatch(sub_filter."GFO_$TEMP$_SPATIAL_RELATION",'
                " '****T****') = 1) = 0))"
            ),
            (
                ",ST_relate(layer1.{input1_geometrycolumn}"
                ', layer2.{input2_geometrycolumn}) AS "GFO_$TEMP$_SPATIAL_RELATION"'
            ),
            "",
            True,
            False,
        ),
        (
            "intersects is False",
            False,
            True,
            'NOT (sub_filter."GFO_$TEMP$_SPATIAL_RELATION" = 0)',
            (
                ",ST_intersects(layer1.{input1_geometrycolumn}"
                ', layer2.{input2_geometrycolumn}) AS "GFO_$TEMP$_SPATIAL_RELATION"'
            ),
            "",
            True,
            False,
        ),
        (
            "intersects is False",
            True,
            False,
            (
                'NOT (((ST_RelateMatch(sub_filter."GFO_$TEMP$_SPATIAL_RELATION",'
                " 'T********') = 1 or"
                ' ST_RelateMatch(sub_filter."GFO_$TEMP$_SPATIAL_RELATION",'
                " '*T*******') = 1 or"
                ' ST_RelateMatch(sub_filter."GFO_$TEMP$_SPATIAL_RELATION",'
                " '***T*****') = 1 or"
                ' ST_RelateMatch(sub_filter."GFO_$TEMP$_SPATIAL_RELATION",'
                " '****T****') = 1) = 0))"
            ),
            (
                ",ST_relate(layer1.{input1_geometrycolumn}"
                ", ST_union(layer2.{input2_geometrycolumn}))"
                ' AS "GFO_$TEMP$_SPATIAL_RELATION"'
            ),
            "GROUP BY layer2.fid_1",
            True,
            False,
        ),
        (
            "intersects is False",
            True,
            True,
            'NOT (sub_filter."GFO_$TEMP$_SPATIAL_RELATION" = 0)',
            (
                ",ST_intersects(layer1.{input1_geometrycolumn}"
                ", ST_union(layer2.{input2_geometrycolumn}))"
                ' AS "GFO_$TEMP$_SPATIAL_RELATION"'
            ),
            "GROUP BY layer2.fid_1",
            True,
            False,
        ),
    ],
)
@pytest.mark.parametrize(
    "geom1, geom2",
    [
        ("layer1.{input1_geometrycolumn}", "layer2.{input2_geometrycolumn}"),
    ],
)
def test_prepare_filter_by_location_fields(
    query,
    geom1,
    geom2,
    subdivided,
    optimize_simple_queries,
    exp_spatial_relation_column,
    exp_spatial_relation_filter,
    exp_groupby,
    exp_true_for_disjoint,
    exp_relation_should_be_found,
):
    (
        spatial_relations_column,
        spatial_relations_filter,
        groupby,
        relation_should_be_found,
        true_for_disjoint,
    ) = _geoops_sql._prepare_filter_by_location_params(
        query=query,
        geom1=geom1,
        geom2=geom2,
        subdivided=subdivided,
        optimize_simple_queries=optimize_simple_queries,
    )

    # Check results
    assert spatial_relations_column == exp_spatial_relation_column

    # Ignore any formatting like newlines and multiple spaces
    spatial_relations_filter = " ".join(spatial_relations_filter.split())
    exp_spatial_relation_filter = " ".join(exp_spatial_relation_filter.split())
    assert spatial_relations_filter == exp_spatial_relation_filter

    assert groupby == exp_groupby
    assert true_for_disjoint == exp_true_for_disjoint
    assert relation_should_be_found == exp_relation_should_be_found
