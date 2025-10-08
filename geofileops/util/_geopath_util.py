"""Helper functions for working with paths to geo files."""

import os
from pathlib import Path
from typing import Any, Union

GEO_MULTI_SUFFIXES = (".gpkg.zip", ".shp.zip")


class GeoPath:
    """Class to work with geo file paths."""

    def __init__(self, path: Union[str, "os.PathLike[Any]"]) -> None:
        """Initialize the GeoPath object.

        Args:
            path (PathLike): The path to work with.
        """
        self._path = Path(path)

    @property
    def is_multi_suffix(self) -> bool:
        """Return True if the path has a geo multi-suffix.

        Returns:
            bool: True if the path has a geo multi-suffix.
        """
        name_lower = self._path.name.lower()
        for multi_suffix in GEO_MULTI_SUFFIXES:
            if name_lower.endswith(multi_suffix):
                return True

        return False

    @property
    def path(self) -> Path:
        """Return the original path as a Path object."""
        return self._path

    @property
    def name_nozip(self) -> str:
        """Return the name of a path, removing a .zip suffix if present.

        Returns:
            str: The name of the path without a .zip suffix.
        """
        if self._path.suffix.lower() == ".zip":
            return self._path.name[: -len(".zip")]
        return self._path.name

    @property
    def stem(self) -> str:
        """Return the stem of a path, supporting multi-suffixes for geo formats.

        Args:
            path (PathLike): The path to get the stem of.

        Returns:
            str: the stem of the path.
        """
        name_lower = self._path.name.lower()
        for suffixes in GEO_MULTI_SUFFIXES:
            if name_lower.endswith(suffixes):
                # Geo multi-suffix found, remove it from the name to get the stem
                return self._path.name[: -len(suffixes)]

        return self._path.stem

    @property
    def suffix_full(self) -> str:
        """Return the suffixes of a path, supporting multi-suffixes for geo formats.

        Returns:
            str: The suffixes of the path.
        """
        # If there are multiple "."s in the name, check if it is a geo multi-suffix
        name_lower = self._path.name.lower()
        for multi_suffix in GEO_MULTI_SUFFIXES:
            if name_lower.endswith(multi_suffix):
                return self._path.name[-len(multi_suffix) :]

        return self._path.suffix

    @property
    def suffix_nozip(self) -> str:
        """Return the suffixes of a path, removing a .zip suffix if present.

        Returns:
            str: The suffixes of the path without a .zip suffix.
        """
        suffix_tmp = self.suffix_full
        if suffix_tmp.lower().endswith(".zip"):
            return suffix_tmp[: -len(".zip")]

        return suffix_tmp

    def with_stem(self, stem: str) -> Path:
        """Return a Path with a new stem, supporting multi-suffixes for geo formats.

        If the input is a string, the output will be a string. If the input is a Path,
        the output will be a Path.

        Args:
            stem (str): The new stem to set.

        Returns:
            Path: The path with the new stem.

        """
        # Determine if the filename has a geo multi-suffix (case insensitive)
        new_path_str = None
        name_lower = self._path.name.lower()
        is_geo_multi_suffix = False
        for multi_suffix in GEO_MULTI_SUFFIXES:
            if name_lower.endswith(multi_suffix):
                is_geo_multi_suffix = True
                break

        # The file name has a geo multi-suffix
        if is_geo_multi_suffix:
            # Recover the suffixes from the file name to keep the casing
            multi_suffix = self._path.name[-len(multi_suffix) :]
            new_name = f"{stem}{multi_suffix}"
            # Use os.path to retain forward/backward slashes in the path
            parent, _ = os.path.split(self._path)
            new_path_str = f"{parent}/{new_name}"

        # If the input was a Path, return a Path
        if new_path_str is not None:
            return Path(new_path_str)
        else:
            return self._path.with_stem(stem)

    def with_stem_suffix(self, stem_suffix: str) -> Path:
        """Return a Path with a new stem by adding a stem_suffix.

        Multiple suffixes are supported for geo formats.

        If the input is a string, the output will be a string. If the input is a Path,
        the output will be a Path.

        Args:
            stem_suffix (str): The suffix to add to the stem.

        Returns:
            Path: The path with the new stem.

        """
        return self._path.parent / f"{self.stem}{stem_suffix}{self.suffix_full}"
