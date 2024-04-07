"""
Module for benchmarking.
"""

import datetime
import importlib
import inspect
import logging
from pathlib import Path
import tempfile
from typing import List, Optional

import pandas as pd

from benchmark import reporter

################################################################################
# Some init
################################################################################

logger = logging.getLogger(__name__)

################################################################################
# The real work
################################################################################


class RunResult:
    """The result of a benchmark run."""

    def __init__(
        self,
        package: str,
        package_version: str,
        operation: str,
        operation_descr: str,
        secs_taken: float,
        run_details: Optional[dict] = None,
    ):
        """
        Constructor for a RunResult.

        Args:
            package (str): Package being benchmarked.
            package_version (str): Version of the package.
            operation (str): Operation name.
            operation_descr (str): Description of the operation.
            secs_taken (float): Seconds the operation took.
            run_details (dict, optional): (Important) details of this specific
                run with impact on performance. Eg. # CPU's used,...
        """
        self.run_datetime = datetime.datetime.now()
        self.package = package
        self.package_version = package_version
        self.operation = operation
        self.operation_descr = operation_descr
        self.secs_taken = secs_taken
        self.run_details = run_details

    def __repr__(self):
        """
        Format the result.
        """
        return f"{self.__class__}({self.__dict__})"


def run_benchmarks(
    modules_to_run: Optional[List[str]] = None,
    functions_to_run: Optional[List[str]] = None,
):
    """
    Run all benchmarks specified.

    Args:
        modules_to_run (Optional[List[str]], optional): List of modules to run
            the benchmarks from. If None, all benchmark modules found are used.
            Defaults to None.
        functions_to_run (Optional[List[str]], optional): List of benchmark functions to
            be ran. If None, all benchmark functions are ran. Defaults to None.
    """
    # Init logging
    logging.basicConfig(
        format="%(asctime)s.%(msecs)03d|%(levelname)s|%(name)s|%(message)s",
        datefmt="%H:%M:%S",
        level=logging.INFO,
    )

    # Discover and run all benchmark implementations
    tmp_dir = Path(tempfile.gettempdir()) / "geobenchmark"
    logger.info(f"tmpdir: {tmp_dir}")
    tmp_dir.mkdir(parents=True, exist_ok=True)

    benchmarks_dir = Path(__file__).parent / "benchmarks"
    results = []
    for file in benchmarks_dir.glob("benchmarks_*.py"):
        module_name = file.stem
        if (not module_name.startswith("_")) and (module_name not in globals()):
            if modules_to_run is not None and module_name not in modules_to_run:
                # Benchmark whitelist specified, and this one isn't in it
                logger.info(
                    f"module {module_name} skipped, because not in modules_to_run: "
                    f"{modules_to_run}"
                )
                continue

            benchmark_implementation = importlib.import_module(
                f"benchmarks.{module_name}", __package__
            )

            # Run the functions in this benchmark
            functions = inspect.getmembers(benchmark_implementation, inspect.isfunction)
            for function_name, function in functions:
                if function_name.startswith("_"):
                    continue
                if (
                    functions_to_run is not None
                    and function_name not in functions_to_run
                ):
                    # Function whitelist specified, and this one isn't in it
                    logger.info(
                        f"function {function_name} skipped, because not in "
                        f"functions_to_run: {functions_to_run}"
                    )
                    continue

                # Run the operation benchmark
                logger.info(f"benchmarks.{module_name}.{function_name} start")
                result = function(tmp_dir=tmp_dir)
                if result is not None and isinstance(result, RunResult) is True:
                    logger.info(
                        f"benchmarks.{module_name}.{function_name} ready in "
                        f"{result.secs_taken:.2f} s"
                    )
                    results.append(result)
                else:
                    logger.warning(
                        f"benchmarks.{module_name}.{function_name} ignored: instead of "
                        f"a RunResult it returned {result}"
                    )

    # Add results to csv file
    results_path = Path(__file__).resolve().parent / "results/benchmark_results.csv"
    results_dictlist = [vars(result) for result in results]
    results_df = pd.DataFrame(results_dictlist)
    if not results_path.exists():
        results_df.to_csv(results_path, index=False)
    else:
        results_df.to_csv(results_path, index=False, mode="a", header=False)

    # Generate reports
    output_dir = Path(__file__).resolve().parent / "results"
    reporter.generate_reports(results_path, output_dir)


if __name__ == "__main__":
    run_benchmarks()
