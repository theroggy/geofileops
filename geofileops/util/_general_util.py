"""Module containing some general utilities."""

import datetime
import logging
import os
import re
import time
from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from types import TracebackType
from typing import Any

logger = logging.getLogger(__name__)


class MissingRuntimeDependencyError(RuntimeError):
    """Exception raised when a geofileops runtime dependency is missing.

    Attributes:
        message (str): Exception message
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(self.message)


def align_casing(string_to_align: str, strings_to_align_to: Iterable) -> str:
    """Search a string case-insentive in a list of string to align its casing.

    If the string is not found in strings_to_align_to, a ValueError is thrown.

    Args:
        string_to_align (str): string to align the casing of to strings_to_align_to.
        strings_to_align_to (Iterable): strings to align the casing with.

    Raises:
        ValueError: the string was not found in strings_to_align_to.

    Returns:
        str: the aligned string.
    """
    return align_casing_list([string_to_align], strings_to_align_to)[0]


def align_casing_list(
    strings_to_align: list[str],
    strings_to_align_to: Iterable,
    raise_on_missing: bool = True,
) -> list[str]:
    """Search the string caseintensitive in a list of strings.

    Args:
        strings_to_align (List[str]): strings to align the casing of to
            strings_to_align_to.
        strings_to_align_to (Iterable): strings to align the casing with.
        raise_on_missing (bool, optional): if True, a ValueError is raised if a string
            in ``strings_to_align`` is not found in ``strings_to_align_to``. If False,
            the casing in ``strings_to_align`` is retained in the output.

    Raises:
        ValueError: a string in strings_to_align was nog found in strings_to_align_to.

    Returns:
        List[str]: the aligned list of strings.
    """
    strings_to_align_to_upper_dict = {
        string.upper(): string for string in strings_to_align_to
    }
    strings_aligned = []
    for string in strings_to_align:
        string_aligned = strings_to_align_to_upper_dict.get(string.upper())
        if string_aligned is not None:
            strings_aligned.append(string_aligned)
        elif raise_on_missing:
            raise ValueError(f"{string} not available in: {strings_to_align_to}")
        else:
            strings_aligned.append(string)

    return strings_aligned


def report_progress(
    start_time: datetime.datetime,
    nb_done: int,
    nb_todo: int,
    operation: str | None = None,
    nb_parallel: int = 1,
) -> None:
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
    operation: str | None = None,
    nb_parallel: int = 1,
) -> str | None:
    # Init
    time_passed = (datetime.datetime.now() - start_time).total_seconds()
    pct_progress = 100.0 - (nb_todo - nb_done) * 100 / nb_todo
    nb_todo_str = f"{nb_todo:n}"
    nb_decimal = len(nb_todo_str)

    # If we haven't really started yet, don't report time estimate yet
    if nb_done == 0:
        return (
            f" ?: ?: ? left, {operation} done on {nb_done:{nb_decimal}n} of "
            f"{nb_todo:{nb_decimal}n} ({pct_progress:3.2f}%)    "
        )
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


def formatbytes(nb_bytes: float) -> str:
    """Return the given bytes as a human friendly KB, MB, GB, or TB string."""
    bytes_float = float(nb_bytes)
    KB = float(1024)
    MB = float(KB**2)  # 1,048,576
    GB = float(KB**3)  # 1,073,741,824
    TB = float(KB**4)  # 1,099,511,627,776

    if bytes_float < KB:
        return "{} {}".format(bytes_float, "Bytes" if bytes_float > 1 else "Byte")
    elif KB <= bytes_float < MB:
        return f"{bytes_float / KB:.2f} KB"
    elif MB <= bytes_float < GB:
        return f"{bytes_float / MB:.2f} MB"
    elif GB <= bytes_float < TB:
        return f"{bytes_float / GB:.2f} GB"
    else:
        return f"{bytes_float / TB:.2f} TB"


def prepare_for_serialize(data: dict) -> dict:
    prepared: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            prepared[key] = prepare_for_serialize(value)
        elif isinstance(value, list | tuple):
            prepared[key] = value
        else:
            prepared[key] = str(value)

    return prepared


def retry(
    max_tries: int,
    delay_fixed: float | None = None,
    delay_incremental: float | None = None,
    exceptions: tuple[type[BaseException], ...] = (Exception,),
    match: Iterable[str] | str | None = None,
) -> Callable:
    """Decorator to retry a function a number of times in case of an exception.

    Args:
        max_tries (int): maximum number of times the function is attempted.
        delay_fixed (float, optional): fixed delay in seconds between retries.
            If None, no fixed dalay is applied. Defaults to None.
        delay_incremental (float, optional): delay in seconds that increases between
            retries like this: delay = `delay_incremental` * <try_count>. If None,
            no incremental delay is applied. Defaults to None.
        exceptions (tuple[type[BaseException], ...], optional): types of exceptions to
            retry on. Defaults to (Exception,).
        match (Iterable[str] | str, optional): if specified, only exceptions with
            messages matching the given regular expression(s) are retried.
            Defaults to None.
    """
    if match is not None and isinstance(match, str):
        match = [match]

    def decorator(func: Callable) -> Callable:
        def wrapper(*args, **kwargs) -> Callable:  # noqa: ANN002, ANN003
            for try_count in range(max_tries):
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as ex:
                    if (
                        try_count >= (max_tries - 1)
                        or not isinstance(ex, exceptions)
                        or (
                            match is not None
                            and not any(re.search(m, str(ex)) for m in match)
                        )
                    ):
                        # No more retries... raise
                        raise ex

                    logger.info(
                        f"Retrying function {func.__name__} due to exception: {ex}. "
                        f"Try {try_count + 1} of {max_tries}."
                    )
                    # Sleep if needed
                    delay = 0.0
                    if delay_fixed is not None:
                        delay = delay_fixed
                    elif delay_incremental is not None:
                        delay += delay_incremental * (try_count + 1)

                    if delay > 0:
                        time.sleep(delay)

            raise RuntimeError("Error in retry decorator. Should not be reached.")

        return wrapper

    return decorator


class TempEnv(AbstractContextManager):
    """Context manager to temporarily set/change environment variables.

    Existing values for variables are backed up and reset when the scope is left,
    variables that didn't exist before are deleted again.

    If value is None, the environment variable is deleted within the context.

    Args:
        envs (Dict[str, Any]): dict with environment variables to set.
    """

    def __init__(self, envs: dict[str, Any]) -> None:
        self._envs_backup: dict[str, str] = {}
        self._envs = envs

    def __enter__(self) -> None:
        # Only if a name and value is specified...
        for name, value in self._envs.items():
            # If the environment variable is already defined, make backup
            if name in os.environ:
                self._envs_backup[name] = os.environ[name]

            # Set env variable to value
            if value is None:
                if name in os.environ:
                    del os.environ[name]
            else:
                os.environ[name] = str(value)

    def __exit__(
        self,
        type: type[BaseException] | None,  # noqa: A002
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # Set variables that were backed up back to original value
        for name, env_value in self._envs_backup.items():
            # Recover backed up value
            os.environ[name] = env_value
        # For variables without backup, remove them
        for name, _ in self._envs.items():
            if name not in self._envs_backup and name in os.environ:
                del os.environ[name]
