"""Module to benchmark geofileops operations."""
# ruff: noqa: D103

import inspect
import logging
import multiprocessing
from datetime import datetime
from pathlib import Path

import geofileops as gfo
from benchmark.benchmarker import RunResult
from benchmark.benchmarks import testdata
from geofileops.util import _geoops_gpd, _geoops_sql

logger = logging.getLogger(__name__)
nb_parallel = min(multiprocessing.cpu_count(), 12)


def _get_package() -> str:
    return "geofileops"


def _get_version() -> str:
    return gfo.__version__


def buffer(tmp_dir: Path) -> RunResult:
    # Init
    input_path, _ = testdata.TestFile.AGRIPRC_2018.get_file(tmp_dir)

    # Go!
    start_time = datetime.now()
    output_path = tmp_dir / f"{input_path.stem}_buf.gpkg"
    gfo.buffer(input_path, output_path, distance=1, nb_parallel=nb_parallel, force=True)
    result = RunResult(
        package=_get_package(),
        package_version=_get_version(),
        operation="buffer",
        secs_taken=(datetime.now() - start_time).total_seconds(),
        operation_descr="buffer on agri parcel layer BEFL (~500.000 polygons)",
        run_details={"nb_cpu": nb_parallel},
    )

    # Cleanup and return
    output_path.unlink()
    return result


def buffer_spatialite(tmp_dir: Path) -> RunResult:
    # Init
    input_path, _ = testdata.TestFile.AGRIPRC_2018.get_file(tmp_dir)

    # Go!
    start_time = datetime.now()
    output_path = tmp_dir / f"{input_path.stem}_buf_spatialite.gpkg"
    _geoops_sql.buffer(
        input_path, output_path, distance=1, nb_parallel=nb_parallel, force=True
    )
    result = RunResult(
        package=_get_package(),
        package_version=_get_version(),
        operation="buffer_spatialite",
        secs_taken=(datetime.now() - start_time).total_seconds(),
        operation_descr="buffer on agri parcel layer BEFL (~500.000 polygons)",
        run_details={"nb_cpu": nb_parallel},
    )

    # Cleanup and return
    output_path.unlink()
    return result


def buffer_gridsize_spatialite(tmp_dir: Path) -> RunResult:
    # Init
    input_path, _ = testdata.TestFile.AGRIPRC_2018.get_file(tmp_dir)

    # Go!
    start_time = datetime.now()
    output_path = tmp_dir / f"{input_path.stem}_buf_grid01_spatialite.gpkg"
    _geoops_sql.buffer(
        input_path,
        output_path,
        distance=1,
        gridsize=0.1,
        nb_parallel=nb_parallel,
        force=True,
    )
    result = RunResult(
        package=_get_package(),
        package_version=_get_version(),
        operation="buffer_gridsize_spatialite",
        secs_taken=(datetime.now() - start_time).total_seconds(),
        operation_descr=(
            "buffer with gridsize 0.1 on agri parcel layer BEFL (~500.000 polygons)"
        ),
        run_details={"nb_cpu": multiprocessing.cpu_count()},
    )

    # Cleanup and return
    output_path.unlink()
    return result


def buffer_gpd(tmp_dir: Path) -> RunResult:
    # Init
    input_path, _ = testdata.TestFile.AGRIPRC_2018.get_file(tmp_dir)

    # Go!
    start_time = datetime.now()
    output_path = tmp_dir / f"{input_path.stem}_buf_gpd.gpkg"
    _geoops_gpd.buffer(
        input_path, output_path, distance=1, nb_parallel=nb_parallel, force=True
    )
    result = RunResult(
        package=_get_package(),
        package_version=_get_version(),
        operation="buffer_gpd",
        secs_taken=(datetime.now() - start_time).total_seconds(),
        operation_descr="buffer on agri parcel layer BEFL (~500.000 polygons)",
        run_details={"nb_cpu": nb_parallel},
    )

    # Cleanup and return
    output_path.unlink()
    return result


def dissolve_nogroupby(tmp_dir: Path) -> RunResult:
    # Init
    input_path, _ = testdata.TestFile.AGRIPRC_2018.get_file(tmp_dir)

    # Go!
    start_time = datetime.now()
    output_path = tmp_dir / f"{input_path.stem}_diss_nogroupby.gpkg"
    gfo.dissolve(
        input_path=input_path,
        output_path=output_path,
        explodecollections=True,
        nb_parallel=nb_parallel,
        force=True,
    )
    result = RunResult(
        package=_get_package(),
        package_version=_get_version(),
        operation="dissolve",
        secs_taken=(datetime.now() - start_time).total_seconds(),
        operation_descr="dissolve on agri parcels BEFL (~500.000 polygons)",
        run_details={"nb_cpu": nb_parallel},
    )

    # Cleanup and return
    output_path.unlink()
    return result


def dissolve_groupby(tmp_dir: Path) -> RunResult:
    # Init
    input_path, _ = testdata.TestFile.AGRIPRC_2018.get_file(tmp_dir)

    # Go!
    start_time = datetime.now()
    output_path = tmp_dir / f"{input_path.stem}_diss_groupby.gpkg"
    gfo.dissolve(
        input_path,
        output_path,
        groupby_columns=["GEWASGROEP"],
        explodecollections=True,
        nb_parallel=nb_parallel,
        force=True,
    )
    result = RunResult(
        package=_get_package(),
        package_version=_get_version(),
        operation="dissolve_groupby",
        secs_taken=(datetime.now() - start_time).total_seconds(),
        operation_descr=(
            "dissolve on agri parcels BEFL (~500.000 polygons), groupby=[GEWASGROEP]"
        ),
        run_details={"nb_cpu": nb_parallel},
    )

    # Cleanup and return
    output_path.unlink()
    return result


def clip(tmp_dir: Path) -> RunResult:
    # Init
    input1_path, _ = testdata.TestFile.AGRIPRC_2018.get_file(tmp_dir)
    input2_path, _ = testdata.TestFile.AGRIPRC_2019.get_file(tmp_dir)

    # Go!
    start_time = datetime.now()
    output_path = tmp_dir / f"{input1_path.stem}_clip_{input2_path.stem}.gpkg"
    gfo.clip(
        input_path=input1_path,
        clip_path=input2_path,
        output_path=output_path,
        nb_parallel=nb_parallel,
        force=True,
    )
    result = RunResult(
        package="geofileops",
        package_version=gfo.__version__,
        operation="clip",
        secs_taken=(datetime.now() - start_time).total_seconds(),
        operation_descr="clip between 2 agri parcel layers BEFL (2*~500.000 polygons)",
        run_details={"nb_cpu": nb_parallel},
    )

    # Cleanup and return
    # output_path.unlink()
    return result


def export_by_location_intersects(tmp_dir: Path) -> RunResult:
    # Init
    function_name = inspect.currentframe().f_code.co_name  # type: ignore[union-attr]

    input1_path, _ = testdata.TestFile.AGRIPRC_2018.get_file(tmp_dir)
    input2_path, _ = testdata.TestFile.AGRIPRC_2019.get_file(tmp_dir)

    # Go!
    start_time = datetime.now()
    output_path = (
        tmp_dir
        / f"{input1_path.stem}_export_inters_{input2_path.stem}_{_get_package()}.gpkg"
    )
    gfo.export_by_location(
        input_to_select_from_path=input1_path,
        input_to_compare_with_path=input2_path,
        output_path=output_path,
        # spatial_relations_query="intersects is True",
        nb_parallel=nb_parallel,
        force=True,
    )
    result = RunResult(
        package=_get_package(),
        package_version=_get_version(),
        operation=function_name,
        secs_taken=(datetime.now() - start_time).total_seconds(),
        operation_descr=(
            "export_by_location_intersects between 2 agri parcel layers BEFL "
            "(2*~500.000 polygons)"
        ),
        run_details={"nb_cpu": nb_parallel},
    )

    # Cleanup and return
    logger.info(f"nb features in result: {gfo.get_layerinfo(output_path).featurecount}")
    output_path.unlink()
    return result


def export_by_location_intersects_complexpoly(tmp_dir: Path) -> RunResult:
    # Init
    function_name = inspect.currentframe().f_code.co_name  # type: ignore[union-attr]

    input1_path, _ = testdata.TestFile.AGRIPRC_2018.get_file(tmp_dir)
    bbox = gfo.get_layerinfo(input1_path).total_bounds
    input2_path, input2_descr = testdata.create_testfile(
        bbox=bbox, nb_points=300_000, dst_dir=tmp_dir
    )

    # Go!
    start_time = datetime.now()
    output_path = (
        tmp_dir
        / f"{input1_path.stem}_export_inters_{input2_path.stem}_{_get_package()}.gpkg"
    )
    gfo.export_by_location(
        input_to_select_from_path=input1_path,
        input_to_compare_with_path=input2_path,
        output_path=output_path,
        nb_parallel=nb_parallel,
        # subdivide_coords=0,
        force=True,
    )
    result = RunResult(
        package=_get_package(),
        package_version=_get_version(),
        operation=function_name,
        secs_taken=(datetime.now() - start_time).total_seconds(),
        operation_descr=(
            f"{function_name} between agri parcels (~500k poly) and {input2_descr}"
        ),
        run_details={"nb_cpu": nb_parallel},
    )

    # Cleanup and return
    logger.info(f"nb features in result: {gfo.get_layerinfo(output_path).featurecount}")
    output_path.unlink()
    return result


def intersection(tmp_dir: Path) -> RunResult:
    # Init
    input1_path, _ = testdata.TestFile.AGRIPRC_2018.get_file(tmp_dir)
    input2_path, _ = testdata.TestFile.AGRIPRC_2019.get_file(tmp_dir)

    # Go!
    start_time = datetime.now()
    output_path = tmp_dir / f"{input1_path.stem}_inters_{input2_path.stem}.gpkg"
    gfo.intersection(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        nb_parallel=nb_parallel,
        force=True,
    )
    result = RunResult(
        package=_get_package(),
        package_version=_get_version(),
        operation="intersection",
        secs_taken=(datetime.now() - start_time).total_seconds(),
        operation_descr=("intersection between 2 agri parcel layers (2*~500k poly)"),
        run_details={"nb_cpu": nb_parallel},
    )

    # Cleanup and return
    output_path.unlink()
    return result


def intersection_complexpoly_agri(tmp_dir: Path) -> RunResult:
    # Init
    function_name = inspect.currentframe().f_code.co_name  # type: ignore[union-attr]

    input2_path, _ = testdata.TestFile.AGRIPRC_2018.get_file(tmp_dir)
    bbox = gfo.get_layerinfo(input2_path).total_bounds
    input1_path, input1_descr = testdata.create_testfile(
        bbox=bbox, nb_points=50_000, dst_dir=tmp_dir
    )

    # Go!
    start_time = datetime.now()
    output_path = tmp_dir / f"{input1_path.stem}_inters_{input2_path.stem}.gpkg"
    gfo.intersection(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        nb_parallel=nb_parallel,
        force=True,
    )
    result = RunResult(
        package=_get_package(),
        package_version=_get_version(),
        operation=function_name,
        secs_taken=(datetime.now() - start_time).total_seconds(),
        operation_descr=(
            f"{function_name} between {input1_descr} and agri parcels (~500k poly)"
        ),
        run_details={"nb_cpu": nb_parallel},
    )

    # Cleanup and return
    output_path.unlink()
    return result


def intersection_complexpoly_complexpoly(tmp_dir: Path) -> RunResult:
    # Init
    function_name = inspect.currentframe().f_code.co_name  # type: ignore[union-attr]

    bbox = (30_000.123, 170_000.123, 250_000, 250_000)
    input1_path, input1_descr = testdata.create_testfile(
        bbox=bbox, nb_points=50_000, dst_dir=tmp_dir
    )
    bbox = (31_000.123, 171_000.123, 250_000, 250_000)
    input2_path, input2_descr = testdata.create_testfile(
        bbox=bbox, nb_points=50_000, dst_dir=tmp_dir
    )
    # Go!
    start_time = datetime.now()
    output_path = tmp_dir / f"{input1_path.stem}_inters_{input2_path.stem}.gpkg"
    gfo.intersection(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        nb_parallel=nb_parallel,
        force=True,
    )
    result = RunResult(
        package=_get_package(),
        package_version=_get_version(),
        operation=function_name,
        secs_taken=(datetime.now() - start_time).total_seconds(),
        operation_descr=(f"{function_name} between {input1_descr} and {input2_descr}"),
        run_details={"nb_cpu": nb_parallel},
    )

    # Cleanup and return
    output_path.unlink()
    return result


def intersection_gridsize(tmp_dir: Path) -> RunResult:
    # Init
    input1_path, _ = testdata.TestFile.AGRIPRC_2018.get_file(tmp_dir)
    input2_path, _ = testdata.TestFile.AGRIPRC_2019.get_file(tmp_dir)

    # Go!
    start_time = datetime.now()
    output_path = tmp_dir / f"{input1_path.stem}_inters_grid01_{input2_path.stem}.gpkg"
    gfo.intersection(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        gridsize=0.001,
        nb_parallel=nb_parallel,
        force=True,
    )
    result = RunResult(
        package=_get_package(),
        package_version=_get_version(),
        operation="intersection_gridsize",
        secs_taken=(datetime.now() - start_time).total_seconds(),
        operation_descr=(
            "intersection with gridsize 0.001 between 2 agri parcel layers BEFL "
            "(2*~500k polygons)"
        ),
        run_details={"nb_cpu": nb_parallel},
    )

    # Cleanup and return
    output_path.unlink()
    return result


def join_by_location_intersects(tmp_dir: Path) -> RunResult:
    # Init-
    input1_path, _ = testdata.TestFile.AGRIPRC_2018.get_file(tmp_dir)
    input2_path, _ = testdata.TestFile.AGRIPRC_2019.get_file(tmp_dir)

    # Go!
    start_time = datetime.now()
    output_path = (
        tmp_dir
        / f"{input1_path.stem}_join_inters_{input2_path.stem}_{_get_package()}.gpkg"
    )
    gfo.join_by_location(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        spatial_relations_query="intersects is True",
        nb_parallel=nb_parallel,
        force=True,
    )
    result = RunResult(
        package=_get_package(),
        package_version=_get_version(),
        operation="join_by_location_intersects",
        secs_taken=(datetime.now() - start_time).total_seconds(),
        operation_descr=(
            "join_by_location_intersects between 2 agri parcel layers BEFL "
            "(2*~500.000 polygons)"
        ),
        run_details={"nb_cpu": nb_parallel},
    )

    # Cleanup and return
    logger.info(f"nb features in result: {gfo.get_layerinfo(output_path).featurecount}")
    output_path.unlink()
    return result


def makevalid_gridsize_gpd(tmp_dir: Path) -> RunResult:
    # Init
    function_name = inspect.currentframe().f_code.co_name  # type: ignore[union-attr]
    input_path, _ = testdata.TestFile.AGRIPRC_2018.get_file(tmp_dir)

    # Go!
    start_time = datetime.now()
    output_path = tmp_dir / f"{input_path.stem}_{function_name}.gpkg"
    gfo.makevalid(
        input_path, output_path, gridsize=0.001, nb_parallel=nb_parallel, force=True
    )
    result = RunResult(
        package=_get_package(),
        package_version=_get_version(),
        operation=function_name,
        secs_taken=(datetime.now() - start_time).total_seconds(),
        operation_descr=f"{function_name} on agri parcel layer BEFL (~500k polygons)",
        run_details={"nb_cpu": nb_parallel},
    )

    # Cleanup and return
    output_path.unlink()
    return result


def makevalid_gridsize_spatialite(tmp_dir: Path) -> RunResult:
    # Init
    function_name = inspect.currentframe().f_code.co_name  # type: ignore[union-attr]
    input_path, _ = testdata.TestFile.AGRIPRC_2018.get_file(tmp_dir)

    # Go!
    start_time = datetime.now()
    output_path = tmp_dir / f"{input_path.stem}_{function_name}.gpkg"
    _geoops_sql.makevalid(
        input_path, output_path, gridsize=0.001, nb_parallel=nb_parallel, force=True
    )
    result = RunResult(
        package=_get_package(),
        package_version=_get_version(),
        operation=function_name,
        secs_taken=(datetime.now() - start_time).total_seconds(),
        operation_descr=f"{function_name} on agri parcel layer BEFL (~500k polygons)",
        run_details={"nb_cpu": nb_parallel},
    )

    # Cleanup and return
    output_path.unlink()
    return result


def makevalid_gpd(tmp_dir: Path) -> RunResult:
    # Init
    function_name = inspect.currentframe().f_code.co_name  # type: ignore[union-attr]
    input_path, _ = testdata.TestFile.AGRIPRC_2018.get_file(tmp_dir)

    # Go!
    start_time = datetime.now()
    output_path = tmp_dir / f"{input_path.stem}_{function_name}.gpkg"
    gfo.makevalid(input_path, output_path, nb_parallel=nb_parallel, force=True)
    result = RunResult(
        package=_get_package(),
        package_version=_get_version(),
        operation=function_name,
        secs_taken=(datetime.now() - start_time).total_seconds(),
        operation_descr=f"{function_name} on agri parcel layer BEFL (~500k polygons)",
        run_details={"nb_cpu": nb_parallel},
    )

    # Cleanup and return
    output_path.unlink()
    return result


def makevalid_spatialite(tmp_dir: Path) -> RunResult:
    # Init
    function_name = inspect.currentframe().f_code.co_name  # type: ignore[union-attr]
    input_path, _ = testdata.TestFile.AGRIPRC_2018.get_file(tmp_dir)

    # Go!
    start_time = datetime.now()
    output_path = tmp_dir / f"{input_path.stem}_{function_name}.gpkg"
    _geoops_sql.makevalid(input_path, output_path, nb_parallel=nb_parallel, force=True)
    result = RunResult(
        package=_get_package(),
        package_version=_get_version(),
        operation=function_name,
        secs_taken=(datetime.now() - start_time).total_seconds(),
        operation_descr=f"{function_name} on agri parcel layer BEFL (~500k polygons)",
        run_details={"nb_cpu": nb_parallel},
    )

    # Cleanup and return
    output_path.unlink()
    return result


def symmetric_difference_complexpolys_agri(tmp_dir: Path) -> RunResult:
    # Init
    function_name = inspect.currentframe().f_code.co_name  # type: ignore[union-attr]

    input2_path, _ = testdata.TestFile.AGRIPRC_2018.get_file(tmp_dir)
    bbox = gfo.get_layerinfo(input2_path).total_bounds
    input1_path, input1_descr = testdata.create_testfile(
        bbox=bbox, nb_points=50_000, dst_dir=tmp_dir
    )

    # Go!
    start_time = datetime.now()
    output_path = tmp_dir / f"{input1_path.stem}_inters_{input2_path.stem}.gpkg"
    gfo.symmetric_difference(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        nb_parallel=nb_parallel,
        force=True,
    )
    result = RunResult(
        package=_get_package(),
        package_version=_get_version(),
        operation=function_name,
        secs_taken=(datetime.now() - start_time).total_seconds(),
        operation_descr=(
            f"{function_name} between {input1_descr} and agriparcels BEFL (~500k poly)"
        ),
        run_details={"nb_cpu": nb_parallel},
    )

    # Cleanup and return
    output_path.unlink()
    return result


def union(tmp_dir: Path) -> RunResult:
    # Init
    input1_path, _ = testdata.TestFile.AGRIPRC_2018.get_file(tmp_dir)
    input2_path, _ = testdata.TestFile.AGRIPRC_2019.get_file(tmp_dir)

    # Go!
    start_time = datetime.now()
    output_path = tmp_dir / f"{input1_path.stem}_inters_{input2_path.stem}.gpkg"
    gfo.union(
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        nb_parallel=nb_parallel,
        force=True,
    )
    result = RunResult(
        package=_get_package(),
        package_version=_get_version(),
        operation="union",
        secs_taken=(datetime.now() - start_time).total_seconds(),
        operation_descr="union between 2 agri parcel layers BEFL (2*~500.000 polygons)",
        run_details={"nb_cpu": nb_parallel},
    )

    # Cleanup and return
    output_path.unlink()
    return result
