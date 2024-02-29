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
def test_prepare_processing_params_filetypes(
    tmp_path, input1_suffix, input2_suffix, output1_suffix, output2_suffix
):
    input1_path = test_helper.get_testfile("polygon-parcel", suffix=input1_suffix)
    input1_layer = gfo.get_only_layer(input1_path)
    input2_path = None
    input2_layer = None
    if input2_suffix is not None:
        input2_path = test_helper.get_testfile("polygon-parcel", suffix=input2_suffix)
        input2_layer = gfo.get_only_layer(input2_path)

    params = _geoops_sql._prepare_processing_params(
        input1_path=input1_path,
        input1_layer=input1_layer,
        input2_path=input2_path,
        input2_layer=input2_layer,
        tempdir=tmp_path,
        convert_to_spatialite_based=True,
        nb_parallel=2,
    )

    assert params is not None
    assert params.input1_path.suffix == output1_suffix
    assert params.input1_path.exists()
    assert params.input1_layer in gfo.listlayers(params.input1_path)

    # If the file format hasn't changed, the file should not be copied
    if input1_path.suffix == params.input1_path.suffix:
        assert input1_path == params.input1_path

    if input2_suffix is not None:
        assert params.input2_path.exists()
        assert params.input2_layer in gfo.listlayers(params.input2_path)
        assert params.input2_path.suffix == output2_suffix
        # If the file format hasn't changed, the file should not be copied
        if input2_path.suffix == params.input2_path.suffix:
            assert input2_path == params.input2_path
        # If both input files were copied, they should have been copied to seperate
        # files
        if params.input1_path.parent == tmp_path and input2_suffix is not None:
            assert params.input1_path != params.input2_path
    else:
        assert params.input2_path is None
