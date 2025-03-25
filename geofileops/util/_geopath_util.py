"""Helper functions for working with paths to geo files."""

import os
from pathlib import Path, PurePath
from typing import Any, Union

GEO_MULTI_SUFFIXES = [".gpkg.zip", ".shp.zip"]


def stem(path: Union[str, "os.PathLike[Any]"]) -> str:
    """Return the stem of a path, supporting multi-suffixes for geo formats.

    Args:
        path (PathLike): The path to get the stem of.

    Returns:
        str: the stem of the path.
    """
    # If there are multiple "."s in the name, check if it is a geo multi-suffix
    path = PurePath(path)
    if path.name.count(".") > 1:
        name_lower = path.name.lower()
        is_geo_multi_suffix = False
        for suffixes in GEO_MULTI_SUFFIXES:
            if name_lower.endswith(suffixes):
                is_geo_multi_suffix = True
                break

        # A geo multi-suffix has been found
        if is_geo_multi_suffix:
            return path.name[: -len(suffixes)]

    return path.stem


def suffixes(path: Union[str, "os.PathLike[Any]"]) -> str:
    """Return the suffixes of a path, supporting multi-suffixes for geo formats.

    Args:
        path (PathLike): The path to get the suffixes of.

    Returns:
        str: The suffixes of the path.
    """
    # If there are multiple "."s in the name, check if it is a geo multi-suffix
    path = PurePath(path)
    if path.name.count(".") > 1:
        name_lower = path.name.lower()
        for suffixes in GEO_MULTI_SUFFIXES:
            if name_lower.endswith(suffixes):
                return path.name[-len(suffixes) :]

    return path.suffix


def with_stem(path: Union[str, "os.PathLike[Any]"], new_stem: str) -> str | Path:
    """Return a Path with a new stem, supporting multi-suffixes for geo formats.

    If the input is a string, the output will be a string. If the input is a Path, the
    output will be a Path.

    Args:
        path (PathLike): The path to change the stem of.
        new_stem (str): The new stem to set.

    Returns:
        str | Path: The path with the new stem.

    """
    # If there are multiple "."s in the name, check if it is a geo multi-suffix
    path_p = PurePath(path)

    new_path_str = None
    if path_p.name.count(".") > 1:
        # Determine if the filename has a geo multi-suffix (case insensitive)
        name_lower = path_p.name.lower()
        is_geo_multi_suffix = False
        for suffixes in GEO_MULTI_SUFFIXES:
            if name_lower.endswith(suffixes):
                is_geo_multi_suffix = True
                break

        # The file name has a geo multi-suffix
        if is_geo_multi_suffix:
            # Recover the suffixes from the file name to keep the casing
            suffixes = path_p.name[-len(suffixes) :]
            new_name = f"{new_stem}{suffixes}"
            # Use os.path to retain forward/backward slashes in the path
            parent, _ = os.path.split(path)
            new_path_str = f"{parent}/{new_name}"

    # If the input was a Path, return a Path
    if isinstance(path, Path):
        if new_path_str is not None:
            return Path(new_path_str)
        else:
            return Path(path_p).with_stem(new_stem)

    # The input was not a Path, return a string
    if new_path_str is not None:
        return new_path_str
    else:
        # Retain forward/backward slashes in the path by using os.path.
        parent, tail = os.path.split(path)
        return f"{parent}/{new_stem}{path_p.suffix}"
