import logging
import pytest

from geofileops.util import _geoops_gpd


@pytest.mark.parametrize(
    "descr, nb_rows_input_layer, nb_parallel, batchsize, cpu_count, bytes_usable, "
    "exp_nb_parallel, exp_nb_batches",
    [
        ("0 input rows, batchsize=1", 0, 2, 1, 8, 500_000_000, 1, 1),
        ("0 input rows, nb_parallel=2", 0, 2, 0, 8, 500_000_000, 1, 1),
        ("0 input rows", 0, -1, -1, 8, 500_000_000, 1, 1),
        ("1 input row, batchsize=1", 1, 2, 1, 8, 500_000_000, 1, 1),
        ("1 input rows, nb_parallel=2", 1, 2, 0, 8, 500_000_000, 1, 1),
        ("1 input rows", 1, -1, -1, 8, 500_000_000, 1, 1),
        ("2 input rows, nb_parallel=10", 2, 10, -1, 8, 500_000_000, 1, 1),
        ("100 input row, batchsize=20", 100, -1, 20, 8, 500_000_000, 5, 5),
        ("100 input rows", 100, -1, -1, 8, 500_000_000, 1, 1),
        ("1000 input row, batchsize=20", 1000, -1, 20, 8, 500_000_000, 8, 50),
        ("1000 input rows", 1000, -1, -1, 8, 500_000_000, 1, 1),
        ("2000 input rows", 2000, -1, -1, 8, 500_000_000, 2, 2),
        ("100_000 input rows", 100000, -1, -1, 8, 500_000_000, 8, 8),
        ("100_000 input rows, 250MB RAM", 1_000_000, -1, -1, 8, 250_000_000, 4, 28),
        ("100_000 input rows, 2CPU", 1_000_000, -1, -1, 2, 500_000_000, 2, 10),
    ],
)
def test_determine_nb_batches(
    descr: str,
    nb_rows_input_layer: int,
    nb_parallel: int,
    batchsize: int,
    cpu_count: int,
    bytes_usable: int,
    exp_nb_parallel: int,
    exp_nb_batches: int,
):
    # Set the parallelization parameters dependend on machine running the tests to keep
    # them stable regardless of the machine runninng the tests.
    config = _geoops_gpd.ParallelizationConfig(
        bytes_usable=bytes_usable, cpu_count=cpu_count
    )

    try:
        # Enable debug logging so debug code is covered
        logging.getLogger().setLevel(logging.DEBUG)

        res_nb_parallel, res_nb_batches = _geoops_gpd._determine_nb_batches(
            nb_rows_total=nb_rows_input_layer,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            parallelization_config=config,
        )
    finally:
        # Remove all handlers associated with the root logger object again.
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)

    assert exp_nb_parallel == res_nb_parallel
    assert exp_nb_batches == res_nb_batches
