"""Helper class to access the geofileops runtime options."""

import os
import tempfile
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Literal


class classproperty(property):
    """Decorator to create class-level properties."""

    def __get__(self, owner_self, owner_cls):  # noqa: ANN001, ANN204
        return self.fget(owner_cls)


class _RestoreOriginalHandler(AbstractContextManager):
    """Context manager to restore the original value of an environment variable."""

    def __init__(self, key: str, original_value: str | None) -> None:
        self.key = key
        self.original_value = original_value

    def __enter__(self) -> None:
        pass

    def __exit__(self, *args: object) -> None:
        if self.original_value is None:
            if self.key in os.environ:
                del os.environ[self.key]
        else:
            os.environ[self.key] = self.original_value


class ConfigOptions:
    """Class to get and set the geofileops runtime options.

    The runtime options are saved to and read from environment variables.

    The setter methods can be used in two ways:

        1. Permanently set the option by calling the setter method directly.
        2. Temporarily set the option by using the setter method as a context manager.

    """

    @staticmethod
    def set_copy_layer_sqlite_direct(enable: bool) -> _RestoreOriginalHandler:
        """Enable option to copy data directly in SQLite in `copy_layer` when possible.

        If not set, this option is enabled by default.

        This can be significantly faster than having the data pass through GDAL for
        large datasets.

        It is only applied if several conditions are met:

            - only used for Geopackage files
            - only `write_mode="append"`
            - only if `explodecollections=False`
            - only if `reprojection=False`
            - ...

        Remarks:

            - You can also set the option temporarily by using this function as a
              context manager.
            - You can also set the option by directly setting the environment variable
              `GFO_COPY_LAYER_SQLITE_DIRECT` to "TRUE" or "FALSE".

        Args:
            enable (bool): If True, this option is enabled.

        Examples:
            If you want to change the default value of the option in general, you can
            just call it as a function:

            .. code-block:: python

                gfo.options.set_copy_layer_sqlite_direct(False)


            If you want to temporarily change the option, you can use it as a context
            manager:

            .. code-block:: python

                with gfo.options.set_copy_layer_sqlite_direct(False):
                    gfo.copy_layer(...)

        """
        key = "GFO_COPY_LAYER_SQLITE_DIRECT"
        original_value = os.environ.get(key)
        os.environ[key] = "TRUE" if enable else "FALSE"

        return _RestoreOriginalHandler(key, original_value)

    @classproperty
    def get_copy_layer_sqlite_direct(cls) -> bool:
        """Should copy_layer use sqlite directly when possible.

        Returns:
            bool: True to use sqlite directly to copy layers. Defaults to True.
        """
        return _get_bool("GFO_COPY_LAYER_SQLITE_DIRECT", default=True)

    @staticmethod
    def set_io_engine(
        engine: Literal["pyogrio-arrow", "pyogrio", "fiona"],
    ) -> _RestoreOriginalHandler:
        """Set the IO engine to use for reading and writing files.

        Possible options are:

            - **"pyogrio-arrow"** (default if not set): use the pyogrio library via the
              arrow batch interface. The arrow batch interface will only be used if
              `pyarrow` is installed.
            - **"pyogrio"**: use the pyogrio library via the traditional interface.
            - **"fiona"**: use the fiona library. This is deprecated and support will be
              removed in a future release.

        Remarks:
            - You can also set the option temporarily by using this function as a
              context manager.
            - You can also set the option by directly setting the environment variable
              `GFO_IO_ENGINE` to one of "PYOGRIO-ARROW", "PYOGRIO", or "FIONA".

        Args:
            engine (Literal["pyogrio-arrow", "pyogrio", "fiona"]): The IO engine to use.

        Examples:
            If you want to change the default value of the option in general, you can
            just call it as a function:

            .. code-block:: python

                gfo.options.set_io_engine("pyogrio")


            If you want to temporarily change the option, you can use it as a context
            manager:

            .. code-block:: python

                with gfo.options.set_io_engine("pyogrio"):
                    gfo.read_file(...)


        """
        key = "GFO_IO_ENGINE"
        original_value = os.environ.get(key)
        os.environ[key] = engine.upper()

        return _RestoreOriginalHandler(key, original_value)

    @classproperty
    def get_io_engine(cls) -> str:
        """The IO engine to use.

        Returns:
            str: the IO engine to use. Possible values (lowercase):
                - "pyogrio-arrow" (default if not set): use the pyogrio library via the
                  arrow batch interface.
                - "pyogrio": use the pyogrio library via the traditional interface.
                - "fiona": use the fiona library.
        """
        io_engine = (
            os.environ.get("GFO_IO_ENGINE", default="pyogrio-arrow").strip().lower()
        )
        supported_values = ["pyogrio", "fiona", "pyogrio-arrow"]
        if io_engine not in supported_values:
            raise ValueError(
                f"invalid value for configoption <GFO_IO_ENGINE>: '{io_engine}', "
                f"should be one of {supported_values}"
            )

        return io_engine

    @staticmethod
    def set_on_data_error(action: Literal["raise", "warn"]) -> _RestoreOriginalHandler:
        """Set the preferred action to take when a data error occurs.

        Possible options are:

            - **"raise"** (default if not set): raise an exception.
            - **"warn"**: issue a warning and continue.

        Note that the "warn" option is only very selectively supported: in many cases,
        an exception will still be raised.

        Remarks:

            - You can also set the option temporarily by using this function as a
              context manager.
            - You can also set the option by directly setting the environment variable
              `GFO_ON_DATA_ERROR` to one of "RAISE" or "WARN".

        Args:
            action (Literal["raise", "warn"]): The action to take on data error.

        Examples:
            If you want to change the default value of the option in general, you can
            just call it as a function:

            .. code-block:: python

                gfo.options.set_on_data_error("warn")


            If you want to temporarily change the option, you can use it as a context
            manager:

            .. code-block:: python

                with gfo.options.set_on_data_error("warn"):
                    gfo.read_file(...)

        """
        key = "GFO_ON_DATA_ERROR"
        original_value = os.environ.get(key)
        os.environ[key] = action.upper()

        return _RestoreOriginalHandler(key, original_value)

    @classproperty
    def get_on_data_error(cls) -> str:
        """The preferred action when a data error occurs.

        Returns:
            str: the preferred action when a data error occurs. Possible values
                (lowercase):
                - "raise" (default if not set): raise an exception.
                - "warn": log a warning and continue.
        """
        value = os.environ.get("GFO_ON_DATA_ERROR")

        if value is None:
            return "raise"

        value_cleaned = value.strip().lower()
        supported_values = ["raise", "warn"]
        if value_cleaned not in supported_values:
            raise ValueError(
                f"invalid value for configoption <GFO_ON_DATA_ERROR>: '{value}', "
                f"should be one of {supported_values}"
            )

        return value_cleaned

    @staticmethod
    def set_remove_temp_files(enable: bool) -> _RestoreOriginalHandler:
        """Enable or disable removal of temporary files created during operations.

        If not set, the option is enabled by default, so temporary files are removed
        after the operation is complete.

        Remarks:

            - You can also set the option temporarily by using this function as a
              context manager.
            - You can also set the option by directly setting the environment variable
              `GFO_REMOVE_TEMP_FILES` to "TRUE" or "FALSE".

        Args:
            enable (bool): If True, temporary files will be removed after operations.

        Examples:
            If you want to change the default value of the option in general, you can
            just call it as a function:

            .. code-block:: python

                gfo.options.set_remove_temp_files(False)


            If you want to temporarily change the option, you can use it as a context
            manager:

            .. code-block:: python

                with gfo.options.set_remove_temp_files(False):
                    gfo.buffer(...)

        """
        key = "GFO_REMOVE_TEMP_FILES"
        original_value = os.environ.get(key)
        os.environ[key] = "TRUE" if enable else "FALSE"

        return _RestoreOriginalHandler(key, original_value)

    @classproperty
    def get_remove_temp_files(cls) -> bool:
        """Should temporary files be removed or not.

        Returns:
            bool: True to remove temp files. Defaults to True.
        """
        return _get_bool("GFO_REMOVE_TEMP_FILES", default=True)

    @staticmethod
    def set_subdivide_check_parallel_fraction(fraction: int) -> _RestoreOriginalHandler:
        """For a file being checked in parallel, the fraction of features to check.

        The value set should be an integer representing the fraction of features to
        check.
        If not set, defaults to 5, resulting in 20% of the features being checked.

        Remarks:

            - You can also set the option temporarily by using this function as a
              context manager.
            - You can also set the option by directly setting the environment variable
              `GFO_SUBDIVIDE_CHECK_PARALLEL_FRACTION` to a string representing the
              fraction.

        Args:
            fraction (int): The fraction of features to check for subdivision.

        Examples:
            If you want to change the default value of the option in general, you can
            just call it as a function:

            .. code-block:: python

                gfo.options.set_subdivide_check_parallel_fraction(10)


            If you want to temporarily change the option, you can use it as a context
            manager:

            .. code-block:: python

                with gfo.options.set_subdivide_check_parallel_fraction(10):
                    gfo.intersection(...)

        """
        key = "GFO_SUBDIVIDE_CHECK_PARALLEL_FRACTION"
        original_value = os.environ.get(key)
        os.environ[key] = str(fraction)

        return _RestoreOriginalHandler(key, original_value)

    @classproperty
    def get_subdivide_check_parallel_fraction(cls) -> int:
        """For a file being checked in parallel, the fraction of features to check.

        Returns:
            int: The fraction of features to check for subdivision. Defaults to 5.
        """
        fraction = os.environ.get("GFO_SUBDIVIDE_CHECK_PARALLEL_FRACTION", default="5")

        return int(fraction)

    @staticmethod
    def set_subdivide_check_parallel_rows(rows: int) -> _RestoreOriginalHandler:
        """For a file being checked in parallel, the number of rows to check.

        The value set should be an integer representing the minimum number of rows a
        file must have to check for subdivision in parallel.
        If not set, defaults to 500000.

        Remarks:

            - You can also set the option temporarily by using this function as a
              context manager.
            - You can also set the option by directly setting the environment variable
              `GFO_SUBDIVIDE_CHECK_PARALLEL_ROWS` to a string representing the number of
              rows.

        Args:
            rows (int): The minimum number of rows a file must have to check for
                subdivision in parallel.

        Examples:
            If you want to change the default value of the option in general, you can
            just call it as a function:

            .. code-block:: python

                gfo.options.set_subdivide_check_parallel_rows(1000000)


            If you want to temporarily change the option, you can use it as a context
            manager:

            .. code-block:: python

                with gfo.options.set_subdivide_check_parallel_rows(1000000):
                    gfo.intersection(...)

        """
        key = "GFO_SUBDIVIDE_CHECK_PARALLEL_ROWS"
        original_value = os.environ.get(key)
        os.environ[key] = str(rows)

        return _RestoreOriginalHandler(key, original_value)

    @classproperty
    def get_subdivide_check_parallel_rows(cls) -> int:
        """If a file has more rows, check if subdivide is needed in parallel.

        Returns:
            int: The minimum number of rows a file must have to check for subdivision in
                parallel. Defaults to 500000.
        """
        rows = os.environ.get("GFO_SUBDIVIDE_CHECK_PARALLEL_ROWS", default="500000")

        return int(rows)

    @staticmethod
    def set_tmp_dir(path: str) -> _RestoreOriginalHandler:
        """Set the directory to use for temporary files created during processing.

        The value set should be a valid directory path. If not set, a subdirectory
        "geofileops" created in the system temp directory is used.

        Remarks:

            - You can also set the option temporarily by using this function as a
              context manager.
            - You can also set the option by directly setting the environment variable
              `GFO_TMPDIR` to the desired temporary directory path.

        Args:
            path (str): The temporary directory path.

        Examples:
            If you want to change the default value of the option in general, you can
            just call it as a function:

            .. code-block:: python

                gfo.options.set_tmp_dir("/path/to/tmpdir")


            If you want to temporarily change the option, you can use it as a context
            manager:

            .. code-block:: python

                with gfo.options.set_tmp_dir("/path/to/tmpdir"):
                    gfo.buffer(...)

        """
        key = "GFO_TMPDIR"
        original_value = os.environ.get(key)
        os.environ[key] = path

        return _RestoreOriginalHandler(key, original_value)

    @classproperty
    def get_tmp_dir(cls) -> Path:
        """The directory to use for temporary files created during processing.

        Returns:
            Path: The directory to use for temporary files. Defaults to a "geofileops"
                subdirectory in the system temp directory.
        """
        tmp_dir_str = os.environ.get("GFO_TMPDIR")
        if tmp_dir_str is None:
            tmpdir = Path(tempfile.gettempdir()) / "geofileops"
        elif tmp_dir_str.strip() == "":
            raise ValueError(
                "GFO_TMPDIR='' environment variable found which is not supported."
            )
        else:
            tmpdir = Path(tmp_dir_str.strip())

        tmpdir.mkdir(parents=True, exist_ok=True)
        return tmpdir

    @staticmethod
    def set_worker_type(
        worker_type: Literal["processes", "threads", "auto"],
    ) -> _RestoreOriginalHandler:
        """Set the type of worker to use for parallel processing.

        Possible options are:

            - **"processes"** (default if not set): use multiprocessing with separate
              processes.
            - **"threads"**: use multithreading within the same process.
            - **"auto"**: automatically choose the best worker type based on the
              operation being performed.

        Remarks:

            - You can also set the option temporarily by using this function as a
              context manager.
            - You can also set the option by directly setting the environment variable
              `GFO_WORKER_TYPE` to one of "processes", "threads", or "auto".

        Args:
            worker_type (Literal["processes", "threads", "auto"]): The type of worker to
                use.

        Examples:
            If you want to change the default value of the option in general, you can
            just call it as a function:

            .. code-block:: python

                gfo.options.set_worker_type("threads")


            If you want to temporarily change the option, you can use it as a context
            manager:

            .. code-block:: python

                with gfo.options.set_worker_type("threads"):
                    gfo.buffer(...)

        """
        key = "GFO_WORKER_TYPE"
        original_value = os.environ.get(key)
        os.environ[key] = worker_type.upper()

        return _RestoreOriginalHandler(key, original_value)

    @classproperty
    def get_worker_type(cls) -> str:
        """The type of workers to use for parallel processing.

        Returns:
            str: the type of workers to use. Possible values (lowercase):

                - "threads": use threads when processing in parallel.
                - "processes": use processes when processing in parallel.
                - "auto" (default if not specified): determine the type automatically.
        """
        worker_type = os.environ.get("GFO_WORKER_TYPE", default="auto").strip().lower()
        supported_values = ["threads", "processes", "auto"]
        if worker_type not in supported_values:
            raise ValueError(
                f"invalid value for configoption <GFO_WORKER_TYPE>: '{worker_type}', "
                f"should be one of {supported_values}"
            )

        return worker_type


def _get_bool(key: str, default: bool) -> bool:
    """Get the value for the environment variable ``key`` as a bool.

    Supported values (case insensitive):

       - True: "1", "YES", "TRUE"
       - False: "0", "NO", "FALSE"

    Args:
        key (str): the environement variable to read.
        default (bool): the value to return if the environement variable does not exist
            or if it is "".

    Raises:
        ValueError: if an invalid value is present in the environment variable.

    Returns:
        bool: True or False.
    """
    value = os.environ.get(key, default="")
    value_cleaned = value.strip().lower()

    # If the key is not defined, return default
    if value_cleaned == "":
        return default

    # Check the value
    if value_cleaned in ("1", "yes", "true"):
        return True
    elif value_cleaned in ("0", "no", "false"):
        return False
    else:
        raise ValueError(
            f"invalid value for bool configoption <{key}>: {value}, should be one of "
            "1, 0, YES, NO, TRUE, FALSE"
        )
