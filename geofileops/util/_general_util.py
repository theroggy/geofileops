# -*- coding: utf-8 -*-
"""
Module containing some general utilities.
"""

from concurrent import futures
import datetime
import locale
import logging
import os
from typing import Optional

import psutil

################################################################################
# Some init
################################################################################

logger = logging.getLogger(__name__)
locale.setlocale(locale.LC_ALL, "")

################################################################################
# The real stuff
################################################################################


class MissingRuntimeDependencyError(Exception):
    """
    Exception raised when an unsupported SQL statement is passed.

    Attributes:
        message (str): Exception message
    """

    def __init__(self, message):
        self.message = message
        super().__init__(self.message)


################################################################################
# The real work
################################################################################


def report_progress(
    start_time: datetime.datetime,
    nb_done: int,
    nb_todo: int,
    operation: Optional[str] = None,
    nb_parallel: int = 1,
):

    # If logging level not enabled for INFO, no progress reporting...
    if logger.isEnabledFor(logging.INFO) is False:
        return

    message = format_progress(
        start_time=start_time,
        nb_done=nb_done,
        nb_todo=nb_todo,
        operation=operation,
        nb_parallel=nb_parallel,
    )
    if message is not None:
        if nb_done >= nb_todo:
            message += "\n"
        print(f"\r{message}", end="", flush=True)


def format_progress(
    start_time: datetime.datetime,
    nb_done: int,
    nb_todo: int,
    operation: Optional[str] = None,
    nb_parallel: int = 1,
) -> Optional[str]:

    # Init
    time_passed = (datetime.datetime.now() - start_time).total_seconds()
    pct_progress = 100.0 - (nb_todo - nb_done) * 100 / nb_todo
    nb_todo_str = f"{nb_todo:n}"
    nb_decimal = len(nb_todo_str)

    # If we haven't really started yet, don't report time estimate yet
    if nb_done == 0:
        return f" ?: ?: ? left, {operation} done on {nb_done:{nb_decimal}n} of {nb_todo:{nb_decimal}n} ({pct_progress:3.2f}%)    "
    else:
        pct_progress = 100.0 - (nb_todo - nb_done) * 100 / nb_todo
        if time_passed > 0:
            # Else, report progress properly...
            processed_per_hour = (nb_done / time_passed) * 3600
            # Correct the nb processed per hour if running parallel
            if nb_done < nb_parallel:
                processed_per_hour = round(processed_per_hour * nb_parallel / nb_done)
            hours_to_go = (int)((nb_todo - nb_done) / processed_per_hour)
            min_to_go = (int)((((nb_todo - nb_done) / processed_per_hour) % 1) * 60)
            secs_to_go = (int)(
                ((((nb_todo - nb_done) / processed_per_hour) % 1) * 3600) % 60
            )
            time_left_str = f"{hours_to_go:02d}:{min_to_go:02d}:{secs_to_go:02d}"
            nb_left_str = f"{nb_done:{nb_decimal}n} of {nb_todo:{nb_decimal}n}"
            pct_str = f"({pct_progress:3.2f}%)    "
        elif pct_progress >= 100:
            time_left_str = "00:00:00"
            nb_left_str = f"{nb_done:{nb_decimal}n} of {nb_todo:{nb_decimal}n}"
            pct_str = f"({pct_progress:3.2f}%)    "
        else:
            return None
        message = f"{time_left_str} left, {operation} done on {nb_left_str} {pct_str}"
        return message


class PooledExecutorFactory(object):
    """
    Context manager to create an Executor.

    Args:
        threadpool (bool, optional): True to get a ThreadPoolExecutor,
            False to get a ProcessPoolExecutor. Defaults to True.
        max_workers (int, optional): Max number of workers.
            Defaults to None to get automatic determination.
        initialisze (function, optional): Function that does initialisations.
    """

    def __init__(self, threadpool: bool = True, max_workers=None, initializer=None):
        self.threadpool = threadpool
        self.max_workers = max_workers
        self.initializer = initializer
        self.pool = None

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


def formatbytes(bytes: float):
    """
    Return the given bytes as a human friendly KB, MB, GB, or TB string
    """

    bytes_float = float(bytes)
    KB = float(1024)
    MB = float(KB**2)  # 1,048,576
    GB = float(KB**3)  # 1,073,741,824
    TB = float(KB**4)  # 1,099,511,627,776

    if bytes_float < KB:
        return "{0} {1}".format(bytes_float, "Bytes" if bytes_float > 1 else "Byte")
    elif KB <= bytes_float < MB:
        return "{0:.2f} KB".format(bytes_float / KB)
    elif MB <= bytes_float < GB:
        return "{0:.2f} MB".format(bytes_float / MB)
    elif GB <= bytes_float < TB:
        return "{0:.2f} GB".format(bytes_float / GB)
    elif TB <= bytes_float:
        return "{0:.2f} TB".format(bytes_float / TB)


def setprocessnice(nice_value: int):
    """
    Set the niceness of the current process.

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
            if nice_value == -20:
                p.nice(psutil.REALTIME_PRIORITY_CLASS)
            elif nice_value <= -15:
                p.nice(psutil.HIGH_PRIORITY_CLASS)
            elif nice_value <= -10:
                p.nice(psutil.ABOVE_NORMAL_PRIORITY_CLASS)
            elif nice_value <= 0:
                p.nice(psutil.NORMAL_PRIORITY_CLASS)
            elif nice_value <= 10:
                p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            else:
                p.nice(psutil.IDLE_PRIORITY_CLASS)
        else:
            p.nice(nice_value)
    except Exception as ex:
        raise Exception(
            f"Error in setprocessnice with nice_value: {nice_value}"
        ) from ex


def getprocessnice() -> int:
    """
    Get the niceness of the current process.

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
        if nice_value == psutil.REALTIME_PRIORITY_CLASS:
            return -20
        elif nice_value == psutil.HIGH_PRIORITY_CLASS:
            return -15
        elif nice_value == psutil.ABOVE_NORMAL_PRIORITY_CLASS:
            return -10
        elif nice_value == psutil.NORMAL_PRIORITY_CLASS:
            return 0
        elif nice_value == psutil.BELOW_NORMAL_PRIORITY_CLASS:
            return 10
        elif nice_value == psutil.IDLE_PRIORITY_CLASS:
            return 19
        else:
            return 0
    else:
        return int(nice_value)


def initialize_worker():
    # We don't want the workers to block the entire system, so make them nice
    # if they aren't quite nice already.
    # Remark: on linux, depending on system settings it is not possible to
    # decrease niceness, even if it was you who niced before.
    nice_value = 15
    if getprocessnice() < nice_value:
        setprocessnice(nice_value)
