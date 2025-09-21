import os


class classproperty(property):
    def __get__(self, owner_self, owner_cls):
        return self.fget(owner_cls)


class ConfigOptions:
    """Class to access the geofileops runtime configuration options.

    They are read from environement variables.
    """

    @classproperty
    def copy_layer_sqlite_direct(cls) -> bool:
        """Should copy_layer use sqlite directly when possible.

        This is significantly faster than using GDAL for large datasets. At the moment
        only used for .gpkg files.

        Returns:
            bool: True to use sqlite directly to copy layers. Defaults to True.
        """
        return get_bool("GFO_COPY_LAYER_SQLITE_DIRECT", default=True)

    @classproperty
    def io_engine(cls):
        """The IO engine to use."""
        io_engine = os.environ.get("GFO_IO_ENGINE", default="pyogrio").strip().lower()
        supported_values = ["pyogrio", "fiona"]
        if io_engine not in supported_values:
            raise ValueError(
                f"invalid value for configoption <GFO_IO_ENGINE>: '{io_engine}', "
                f"should be one of {supported_values}"
            )

        return io_engine

    @classproperty
    def on_data_error(cls) -> str:
        """The preferred action when a data error occurs.

        Supported values (case insensitive):
            - "raise": raise an exception.
            - "warn": log a warning and continue.

        Note that the "warn" option is only very selectively supported: in many cases,
        an exception will still be raised.

        Returns:
            str: the preferred action when a data error occurs. Defaults to "raise".
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

    @classproperty
    def remove_temp_files(cls) -> bool:
        """Should temporary files be removed or not.

        Returns:
            bool: True to remove temp files. Defaults to True.
        """
        return get_bool("GFO_REMOVE_TEMP_FILES", default=True)

    @classproperty
    def subdivide_check_parallel_fraction(cls) -> int:
        """For a file being checked in parallel, the fraction of features to check.

        Returns:
            int: The fraction of features to check for subdivision. Defaults to 5.
        """
        fraction = os.environ.get("GFO_SUBDIVIDE_CHECK_PARALLEL_FRACTION", default="5")

        return int(fraction)

    @classproperty
    def subdivide_check_parallel_rows(cls) -> int:
        """If a file has more rows, check if subdivide is needed in parallel.

        Returns:
            int: The minimum number of rows a file must have to check for subdivision in
                parallel. Defaults to 500000.
        """
        rows = os.environ.get("GFO_SUBDIVIDE_CHECK_PARALLEL_ROWS", default="500000")

        return int(rows)

    @classproperty
    def worker_type(cls) -> str:
        """The type of workers to use for parallel processing.

        Supported values (case insensitive):
            - "threads": use threads when processing in parallel.
            - "processes": use processes when processing in parallel.
            - "auto": determine the type automatically.

        Returns:
            str: the type of workers to use. Defaults to "auto".
        """
        worker_type = os.environ.get("GFO_WORKER_TYPE", default="auto").strip().lower()
        supported_values = ["threads", "processes", "auto"]
        if worker_type not in supported_values:
            raise ValueError(
                f"invalid value for configoption <GFO_WORKER_TYPE>: '{worker_type}', "
                f"should be one of {supported_values}"
            )

        return worker_type


def get_bool(key: str, default: bool) -> bool:
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
