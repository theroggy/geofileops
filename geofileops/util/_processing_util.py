"""Module containing utilities regarding processes."""

import os
from concurrent import futures
from typing import Optional

import psutil


class PooledExecutorFactory:
    """Context manager to create an Executor.

    Args:
        threadpool (bool, optional): True to get a ThreadPoolExecutor,
            False to get a ProcessPoolExecutor. Defaults to True.
        max_workers (int, optional): Max number of workers.
            Defaults to None to get automatic determination.
        initialisze (function, optional): Function that does initialisations.
    """

    def __init__(self, threadpool: bool = True, max_workers=None, initializer=None):
        self.threadpool = threadpool
        if max_workers is not None and os.name == "nt":
            self.max_workers = min(max_workers, 61)
        else:
            self.max_workers = max_workers
        self.initializer = initializer
        self.pool: Optional[futures.Executor] = None

    def __enter__(self) -> futures.Executor:
        if self.threadpool:
            self.pool = futures.ThreadPoolExecutor(
                max_workers=self.max_workers, initializer=self.initializer
            )
        else:
            self.pool = futures.ProcessPoolExecutor(
                max_workers=self.max_workers, initializer=self.initializer
            )
        return self.pool

    def __exit__(self, type, value, traceback):
        if self.pool is not None:
            self.pool.shutdown(wait=True)


def initialize_worker():
    # We don't want the workers to block the entire system, so make them nice
    # if they aren't quite nice already.
    # Remark: on linux, depending on system settings it is not possible to
    # decrease niceness, even if it was you who niced before.
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
