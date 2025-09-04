"""Module containing utilities regarding processes."""

import multiprocessing
import multiprocessing.context
import os
from concurrent import futures

import psutil

WORKER_TYPES = {"threads", "processes"}


class PooledExecutorFactory:
    """Context manager to create a pooled executor.

    Args:
        worker_type (str, optional): type of executor pool to create.
            "threads" for a ThreadPoolExecutor, "processes" for a ProcessPoolExecutor.
        max_workers (int, optional): Maximum number of workers.
            Defaults to None to get automatic determination.
        initializer (function, optional): Function that does initialisations.
        mp_context (BaseContext, optional): multiprocessing context if processes are
            used. If None, "forkserver" will be used on linux to avoid risks on getting
            deadlocks. Defaults to None.

    """

    def __init__(
        self,
        worker_type: str = "processes",
        max_workers=None,
        initializer=None,
        mp_context: multiprocessing.context.BaseContext | None = None,
    ):
        self.worker_type = worker_type.lower()
        if self.worker_type not in WORKER_TYPES:
            raise ValueError(
                f"Invalid worker_type: {self.worker_type}. "
                f"Must be one of {WORKER_TYPES}."
            )

        if max_workers is not None and os.name == "nt":
            self.max_workers = min(max_workers, 61)
        else:
            self.max_workers = max_workers

        self.initializer = initializer
        self.mp_context = mp_context
        if mp_context is None and os.name not in {"nt", "darwin"}:
            # On linux, overrule default to "forkserver" to avoid risks to deadlocks
            self.mp_context = multiprocessing.get_context("forkserver")
        self.pool: futures.Executor | None = None

    def __enter__(self) -> futures.Executor:
        if self.worker_type == "threads":
            self.pool = futures.ThreadPoolExecutor(
                max_workers=self.max_workers, initializer=self.initializer
            )
        elif self.worker_type == "processes":
            self.pool = futures.ProcessPoolExecutor(
                max_workers=self.max_workers,
                initializer=self.initializer,
                mp_context=self.mp_context,
            )
        else:
            raise ValueError(
                f"Invalid worker_type: {self.worker_type}. "
                f"Must be one of {WORKER_TYPES}."
            )

        return self.pool

    def __exit__(self, type, value, traceback):
        if self.pool is not None:
            self.pool.shutdown(wait=True)


def initialize_worker(worker_type: str):
    """Some default inits.

    Following things are done:
    - Set the worker process priority low so the workers don't block the system.

    Args:
        worker_type (str): The type of worker to initialize.
            "threads" for thread pool, "processes" for process pool.
    """
    worker_type = worker_type.lower()
    if worker_type not in WORKER_TYPES:
        raise ValueError(
            f"Invalid worker_type: {worker_type}. Must be one of {WORKER_TYPES}."
        )

    # Reduce OpenMP threads to avoid unnecessary inflated committed memory when using
    # multiprocessing.
    # Should work for any numeric library used (openblas, mkl,...).
    # Ref: https://stackoverflow.com/questions/77764228/pandas-scipy-high-commit-memory-usage-windows
    if os.environ.get("OMP_NUM_THREADS") is None:
        os.environ["OMP_NUM_THREADS"] = "1"

    # We don't want the workers to block the entire system, so make the workers nice
    # if they aren't quite nice already.
    #
    # Remarks:
    #   - on linux, depending on system settings it is not possible to decrease
    #     niceness, even if it was you who niced before.
    #   - we are setting the niceness of the process here, so in case of
    #     `worker_type=threads` the main thread/process will also be impacted.
    nice_value = 15
    if getprocessnice() < nice_value:
        setprocessnice(nice_value)


def getprocessnice() -> int:
    """Get the niceness of the current process.

    The nice value can (typically) range from 19, which gives all other
    processes priority, to -20, which means that this process will take
    maximum priority (which isn't very nice ;-)).

    Remarks for windows:
        - windows only supports 6 niceness classes. setprocessnice en
          getprocessnice maps niceness values to these classes.
        - when setting REALTIME priority (-20 niceness) apparently this
          results only to HIGH priority.
    """
    p = psutil.Process(os.getpid())
    nice_value = p.nice()
    if os.name == "nt":
        return process_priorityclass_to_nice(nice_value)
    else:
        return int(nice_value)


def setprocessnice(nice_value: int):
    """Set the niceness of the current process.

    The nice value can (typically) range from 19, which gives all other
    processes priority, to -20, which means that this process will take
    maximum priority (which isn't very nice ;-)).

    Remarks for windows:
        - windows only supports 6 niceness classes. setprocessnice en
          getprocessnice maps niceness values to these classes.
        - when setting REALTIME priority (-20 niceness) apparently this
          results only to HIGH priority.

    Args:
        nice_value (int): the niceness to be set.
    """
    if nice_value < -20 or nice_value > 19:
        raise ValueError(
            f"Invalid value for nice_values (min: -20, max: 19): {nice_value}"
        )
    if getprocessnice() == nice_value:
        # If the nice value is already the same... no use setting it
        return

    try:
        p = psutil.Process(os.getpid())
        if os.name == "nt":
            p.nice(process_nice_to_priorityclass(nice_value))
        else:
            p.nice(nice_value)
    except Exception as ex:  # pragma: no cover
        raise RuntimeError(
            f"Error in setprocessnice with nice_value: {nice_value}"
        ) from ex


def process_nice_to_priorityclass(nice_value: int) -> int:  # pragma: no cover
    if nice_value == -20:
        return psutil.REALTIME_PRIORITY_CLASS
    elif nice_value <= -15:
        return psutil.HIGH_PRIORITY_CLASS
    elif nice_value <= -10:
        return psutil.ABOVE_NORMAL_PRIORITY_CLASS
    elif nice_value <= 0:
        return psutil.NORMAL_PRIORITY_CLASS
    elif nice_value <= 10:
        return psutil.BELOW_NORMAL_PRIORITY_CLASS
    else:
        return psutil.IDLE_PRIORITY_CLASS


def process_priorityclass_to_nice(priority_class: int) -> int:  # pragma: no cover
    if priority_class == psutil.REALTIME_PRIORITY_CLASS:
        return -20
    elif priority_class == psutil.HIGH_PRIORITY_CLASS:
        return -15
    elif priority_class == psutil.ABOVE_NORMAL_PRIORITY_CLASS:
        return -10
    elif priority_class == psutil.NORMAL_PRIORITY_CLASS:
        return 0
    elif priority_class == psutil.BELOW_NORMAL_PRIORITY_CLASS:
        return 10
    elif priority_class == psutil.IDLE_PRIORITY_CLASS:
        return 19
    else:
        return 0
