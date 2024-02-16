import os


class classproperty(property):
    def __get__(self, owner_self, owner_cls):
        return self.fget(owner_cls)


class ConfigOptions:
    """
    Class to access the geofileops runtime configuration options.

    They are read from environement variables.
    """

    @classproperty
    def remove_temp_files(cls) -> bool:
        """
        Configuration options to cleanup temp files or not.

        Returns:
            bool: True to remove temp files. Defaults to True.
        """
        return get_bool("GFO_REMOVE_TEMP_FILES", default=True)

    @classproperty
    def io_engine(cls):
        return os.environ.get("GFO_IO_ENGINE", default="pyogrio").strip().lower()


def get_bool(key: str, default: bool) -> bool:
    """
    Get the value for the environment variable ``key`` as a bool.

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
