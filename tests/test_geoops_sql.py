import pytest

import geofileops as gfo
from geofileops.util import _geoops_sql
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
    descr: str,
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
    "input1_suffix, input2_suffix, output1_suffix, output2_suffix",
    [
        (".gpkg", None, ".gpkg", None),
        (".gpkg", ".gpkg", ".gpkg", ".gpkg"),
        (".gpkg", ".shp", ".gpkg", ".gpkg"),
        (".gpkg", ".sqlite", ".gpkg", ".gpkg"),
        (".shp", None, ".gpkg", None),
        (".shp", ".gpkg", ".gpkg", ".gpkg"),
        (".shp", ".sqlite", ".sqlite", ".sqlite"),
        (".sqlite", None, ".sqlite", None),
        (".sqlite", ".shp", ".sqlite", ".sqlite"),
        (".sqlite", ".sqlite", ".sqlite", ".sqlite"),
    ],
)
def test_convert_to_spatialite_based(
    tmp_path, input1_suffix, input2_suffix, output1_suffix, output2_suffix
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
            tempdir=tmp_path,
            input2_path=input2_path,
            input2_layer=input2_layer,
        )
    )

    assert input1_out_path.suffix == output1_suffix
    assert input1_out_path.exists()
    assert input1_out_layer.name in gfo.listlayers(input1_out_path)

    # If the file format hasn't changed, the file should not be copied
    if input1_path.suffix == input1_out_path.suffix:
        assert input1_path == input1_out_path

    if input2_suffix is not None:
        assert input2_out_path.exists()
        assert input2_out_layer.name in gfo.listlayers(input2_out_path)
        assert input2_out_path.suffix == output2_suffix
        # If the file format hasn't changed, the file should not be copied
        if input2_out_path.suffix == input2_path.suffix:
            assert input2_out_path == input2_path
        # If both input files were copied, they should have been copied to seperate
        # files
        if input1_out_path.parent == tmp_path and input2_suffix is not None:
            assert input1_out_path != input2_out_path
    else:
        assert input2_out_path is None


@pytest.mark.parametrize(
    "desc, testfile, subdivide_coords, expected_subdivided",
    [
        ("input poly not complex", "polygon-zone", 1000, False),
        ("input poly complex", "polygon-zone", 1, True),
        ("input line not complex", "linestring-watercourse", 10_000, False),
        ("input line complex", "linestring-watercourse", 1, True),
        ("input point complex", "point", 1, False),
    ],
)
def test_subdivide_layer(
    desc, tmp_path, testfile, subdivide_coords, expected_subdivided: bool
):
    path = test_helper.get_testfile(testfile)
    result = _geoops_sql._subdivide_layer(
        path=path,
        layer=None,
        output_path=tmp_path,
        subdivide_coords=subdivide_coords,
        keep_fid=False,
    )

    if expected_subdivided:
        assert result is not None
    else:
        assert result is None
