import pytest

from geofileops.util import _geoops_sql


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
