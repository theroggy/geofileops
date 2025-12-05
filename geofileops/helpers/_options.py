"""Helper class to access the geofileops runtime options."""

import multiprocessing
import os
import tempfile
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Literal

from pyproj import CRS


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
    def set_copy_layer_sqlite_direct(enable: bool | None) -> _RestoreOriginalHandler:
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

        .. versionadded:: 0.11.0

        Args:
            enable (bool | None): If True, this option is enabled. If None, the option
                is unset (so the default behavior is used).

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
        if enable is not None:
            os.environ[key] = "TRUE" if enable else "FALSE"
        elif key in os.environ:
            del os.environ[key]

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
        engine: Literal["pyogrio-arrow", "pyogrio", "fiona"] | None,
    ) -> _RestoreOriginalHandler:
        """Set the IO engine to use for reading and writing files to/from GeoDataFrames.

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

        .. versionadded:: 0.11.0

        Args:
            engine (Literal["pyogrio-arrow", "pyogrio", "fiona"] | None): The IO engine
                to use. If None, the option is unset (so the default behavior is used).

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
        if engine is not None:
            os.environ[key] = engine.upper()
        elif key in os.environ:
            del os.environ[key]

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
    def set_nb_parallel(nb_parallel: int | None) -> _RestoreOriginalHandler:
        """Set the preferred number of parallel workers to be used.

        If not set or set to <= 0, the number of available CPU cores will be used.
        If set to a positive value, that value is the preferred number of workers.

        Remarks:

            - You can also set the option temporarily by using this function as a
              context manager.
            - You can also set the option by directly setting the environment variable
              `GFO_NB_PARALLEL` to a string representing the number of CPU cores to use.

        .. versionadded:: 0.11.0

        Args:
            nb_parallel (int | None): The preferred number of workers. If None, the
                option is unset (so the default behavior will be used).

        Examples:
            If you want to change the default value of the option in general, you can
            just call it as a function:

            .. code-block:: python

                gfo.options.set_nb_parallel(10)


            If you want to temporarily change the option, you can use it as a context
            manager:

            .. code-block:: python

                with gfo.options.set_nb_parallel(10):
                    gfo.intersection(...)

        """
        key = "GFO_NB_PARALLEL"
        original_value = os.environ.get(key)
        if nb_parallel is not None:
            os.environ[key] = str(nb_parallel)
        elif key in os.environ:
            del os.environ[key]

        return _RestoreOriginalHandler(key, original_value)

    @staticmethod
    def get_nb_parallel(
        nb_parallel_overrule: int | None, nb_cpu_cores: int | None = None
    ) -> int:
        """Get the preferred number of workers to use for processing.

        Args:
            nb_parallel_overrule (int | None): If not None, the value specified
                overrules the configuration option.
            nb_cpu_cores (int | None): The number of CPU cores available. If None, this
                is determined automatically.

        Returns:
            int: The preferred number of workers to use for processing.
        """
        if nb_parallel_overrule is not None:
            nb_parallel = nb_parallel_overrule
        else:
            try:
                nb_parallel = int(os.environ.get("GFO_NB_PARALLEL", default="0"))
            except ValueError as ex:
                raise ValueError(
                    "invalid value for configoption <GFO_NB_PARALLEL>: "
                    f"'{os.environ.get('GFO_NB_PARALLEL')}'"
                ) from ex

        # If nb_parallel <= 0, use the number of available CPU cores
        if nb_parallel <= 0:
            if nb_cpu_cores is not None:
                nb_parallel = nb_cpu_cores
            else:
                nb_parallel = multiprocessing.cpu_count()

        return nb_parallel

    @staticmethod
    def set_on_data_error(
        action: Literal["raise", "warn"] | None,
    ) -> _RestoreOriginalHandler:
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

        .. versionadded:: 0.11.0

        Args:
            action (Literal["raise", "warn"] | None): The action to take on data error.
                If None, the option is unset (so the default behavior is used).

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
        if action is not None:
            os.environ[key] = action.upper()
        elif key in os.environ:
            del os.environ[key]

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
    def set_remove_temp_files(enable: bool | None) -> _RestoreOriginalHandler:
        """Enable or disable removal of temporary files created during operations.

        If not set, the option is enabled by default, so temporary files are removed
        after the operation is complete.

        Remarks:

            - You can also set the option temporarily by using this function as a
              context manager.
            - You can also set the option by directly setting the environment variable
              `GFO_REMOVE_TEMP_FILES` to "TRUE" or "FALSE".

        .. versionadded:: 0.11.0

        Args:
            enable (bool | None): If True, temporary files will be removed after
                operations. If False, temporary files will be kept. If None, the option
                is unset (so the default behavior is used).

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
        if enable is not None:
            os.environ[key] = "TRUE" if enable else "FALSE"
        elif key in os.environ:
            del os.environ[key]

        return _RestoreOriginalHandler(key, original_value)

    @classproperty
    def get_remove_temp_files(cls) -> bool:
        """Should temporary files be removed or not.

        Returns:
            bool: True to remove temp files. Defaults to True.
        """
        return _get_bool("GFO_REMOVE_TEMP_FILES", default=True)

    @staticmethod
    def set_sliver_tolerance(tolerance: float | None) -> _RestoreOriginalHandler:
        """Tolerance to filter out slivers from overlay operations between polygons.

        If 0.0, no sliver filtering is done. If negative, only slivers with tolerance
        abs(value) are retained in the output instead of filtering them out.

        If the tolerance is not set, the default depends on the ``crs``. If ``crs`` is a
        projected CRS, the default tolerance is 0.001 CRS units (typically meters or
        feet). If it is a geographic CRS, the default tolerance 1e-7 CRS units
        (typically degrees). If ``crs`` is None or invalid, the default tolerance is
        0.0, so no sliver filtering is done.

        The slivers meant here are very small, often very narrow polygons that are
        created as a side-effect of overlay operations between polygons. Due to the
        limitations of finite-precision floating point arithmetic used in such
        operations, a point that is "snapped" on a line segment, is sometimes not
        exactly located on the line. When calculating e.g. an intersection, this can
        lead to very small "sliver" polygons being created.

        Most of the time, such slivers are not desired in the output. Hence, they are
        filtered out based on certain criteria by default.

        The basic algorythm used to determine if a geometry is a sliver is to use the
        GEOS `set_precision` algorythm with a small tolerance. If the polygon becomes
        NULL, because it is smaller/narrower than the tolerance, it is considered a
        sliver. Note that this means the tolerance should not be interpreted as an
        absolute minimum width of polygons to retain, as the way the `set_precision`
        algorythm works is more complex than that.

        Because the `set_precision` algorythm is relatively costly to apply, geometries
        are first pre-filtered with a less expensive filter: the average width:

        .. code_block::

            average_width(geom) = 2 * area(geom) / length(geom)

        This formula is an approximation that works well for long, narrow polygons, but
        it underestimates the width for square or round polygons. Some examples:

           - **a 10 x 10 meter square**: `2 * (10 * 10)  / (4 * 10) = 400 / 40 = 5`,
             which is an underestimation, as the real average width is 10.
           - **a 1 x 100 meter rectangle**:
             `2 * (1 * 100) / (2 * (1 + 100)) = 200 / 202 = ~0.99`, which is almost
             correct as the real average width is 1.

        The average width being underestimated for some shapes means that some
        geometries are marked as slivers even if they are not. Because the
        `average_width` check is only a pre-filter, this is not a problem: such
        geometries will still be retained if they pass the more precise `set_precision`
        check.

        Remarks:

            - You can also set the option temporarily by using this function as a
              context manager.
            - You can also set the option by directly setting the environment variable
              `GFO_SLIVER_TOLERANCE` to a string representing the tolerance value.

        .. versionadded:: 0.11.0

        Args:
            tolerance (float | None): The sliver tolerance value. If None, the option is
                unset (so the default behavior is used).

        Examples:
            If you want to change the default value of the option in general, you can
            just call the function:

            .. code-block:: python

                gfo.options.set_sliver_tolerance(0.01)

            If you want to temporarily change the option, you can use the function as a
            context manager:

            .. code-block:: python

                with gfo.options.set_sliver_tolerance(0.01):
                    gfo.intersection(...)

        """
        key = "GFO_SLIVER_TOLERANCE"
        original_value = os.environ.get(key)
        if tolerance is not None:
            os.environ[key] = str(tolerance)
        elif key in os.environ:
            del os.environ[key]

        return _RestoreOriginalHandler(key, original_value)

    @staticmethod
    def get_sliver_tolerance(crs: CRS | None) -> float:
        """Tolerance to use to filter out slivers from overlay operations.

        Args:
            crs (CRS): The CRS of the geometries being processed. Used to determine
                the sliver tolerance. For projected CRSes, the tolerance is in the units
                of the CRS (e.g. meters). For geographic CRSes, the tolerance is in
                degrees.

        Returns:
            float: the sliver tolerance to be used. If 0.0, no sliver filtering should
                be done. If negative, only slivers with tolerance abs(value) should be
                retained in the output instead of filtering them out.
                If not set, the default depends on the ``crs``. If ``crs`` is a
                projected CRS, the default tolerance is 0.001 meters. If it is a
                geographic CRS, the default tolerance is 1etolerance 1e-7 degrees.
                If ``crs`` is None or invalid, the default tolerance is 0.0, so no
                sliver filtering is done.
        """
        try:
            tol_str = os.environ.get("GFO_SLIVER_TOLERANCE", None)
            if tol_str is not None:
                return float(tol_str)
            elif crs is None:
                return 0.0
            elif crs.is_projected:
                # Only found projected CRSs so far that use meters or feet, and for both
                # of those this tolerance is fine.
                return 0.001
            elif crs.is_geographic:
                return 1e-7
            else:  # pragma: no cover
                return 0.0

        except Exception as ex:
            raise ValueError(
                "invalid value for configoption <GFO_SLIVER_TOLERANCE>: "
                "should be a number"
            ) from ex

    @staticmethod
    def set_subdivide_check_parallel_fraction(
        fraction: int | None,
    ) -> _RestoreOriginalHandler:
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

        .. versionadded:: 0.11.0

        Args:
            fraction (int | None): The fraction of features to check for subdivision.
                If None, the option is unset (so the default behavior is used).

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
        if fraction is not None:
            os.environ[key] = str(fraction)
        elif key in os.environ:
            del os.environ[key]

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
    def set_subdivide_check_parallel_rows(rows: int | None) -> _RestoreOriginalHandler:
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

        .. versionadded:: 0.11.0

        Args:
            rows (int | None): The minimum number of rows a file must have to check for
                subdivision in parallel. If None, the option is unset (so the default
                behavior is used).

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
        if rows is not None:
            os.environ[key] = str(rows)
        elif key in os.environ:
            del os.environ[key]

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
    def set_tmp_dir(path: str | None) -> _RestoreOriginalHandler:
        """Set the directory to use for temporary files created during processing.

        The value set should be a valid directory path. If not set, a subdirectory
        "geofileops" created in the system temp directory is used.

        Remarks:

            - You can also set the option temporarily by using this function as a
              context manager.
            - You can also set the option by directly setting the environment variable
              `GFO_TMPDIR` to the desired temporary directory path.

        .. versionadded:: 0.11.0

        Args:
            path (str | None): The temporary directory path. If None, the option is
                unset (so the default behavior is used).

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
        if path is not None:
            os.environ[key] = path
        elif key in os.environ:
            del os.environ[key]

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
        worker_type: Literal["processes", "threads", "auto"] | None,
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

        .. versionadded:: 0.11.0

        Args:
            worker_type (Literal["processes", "threads", "auto"] | None): The type of
                worker to use. If None, the option is unset (so the default behavior is
                used).

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
        if worker_type is not None:
            os.environ[key] = worker_type.upper()
        elif key in os.environ:
            del os.environ[key]

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
