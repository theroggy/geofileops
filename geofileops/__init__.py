"""Library to make spatial operations on large geo files fast(er) and easy."""

import multiprocessing
import os
import warnings
from pathlib import Path

# Import geopandas here so the warning about pygeos <> shapely2 is given, but set
# USE_PYGEOS to avoid further warnings
import geopandas._compat as gpd_compat
import pyogrio

from geofileops import _compat
from geofileops.util import _ogr_util

if hasattr(gpd_compat, "USE_PYGEOS"):
    if gpd_compat.USE_PYGEOS:
        os.environ["USE_PYGEOS"] = "1"
    else:
        os.environ["USE_PYGEOS"] = "0"

from geofileops.fileops import *  # noqa: F403
from geofileops.geoops import *  # noqa: F403
from geofileops.helpers.layerstyles import *  # noqa: F403
from geofileops.util._general_util import TempEnv  # noqa: F401
from geofileops.util._geofileinfo import get_driver  # noqa: F401


def _get_version() -> str:
    version_path = Path(__file__).resolve().parent / "version.txt"
    with version_path.open() as file:
        return file.readline()


__version__ = _get_version()


# Do some pre-flight checks to ensure mandatory runtime dependencies are available.
def _pyogrio_spatialite_version_info() -> dict[str, str]:
    test_path = Path(__file__).resolve().parent / "util/test.gpkg"

    sql = "SELECT spatialite_version(), geos_version()"
    result = pyogrio.read_dataframe(test_path, sql=sql)
    spatialite_version = result.iloc[0, 0]
    geos_version = result.iloc[0, 1]

    if not spatialite_version:  # pragma: no cover
        warnings.warn(
            "empty pyogrio spatialite version: probably a geofileops dependency was "
            "not installed correctly: check the installation instructions in the "
            "geofileops docs.",
            stacklevel=1,
        )
    if not geos_version:  # pragma: no cover
        warnings.warn(
            "empty pyogrio spatialite GEOS version: probably a geofileops dependency "
            "was not installed correctly: check the installation instructions in the "
            "geofileops docs.",
            stacklevel=1,
        )

    versions = {
        "spatialite_version": spatialite_version,
        "geos_version": geos_version,
    }
    return versions


# Check the spatialite versions of the dependencies only in the main process
if multiprocessing.parent_process() is None:
    pyogrio_spatialite_version_info = _pyogrio_spatialite_version_info()

    gdal_spatialite_version_info = _ogr_util.spatialite_version_info()

    # Check that the spatialite versions are the same
    pyogrio_spatialite_version = pyogrio_spatialite_version_info["spatialite_version"]

    gdal_spatialite_version = gdal_spatialite_version_info["spatialite_version"]
    if (
        pyogrio_spatialite_version != _compat.sqlite3_spatialite_version
        or pyogrio_spatialite_version != gdal_spatialite_version
    ):  # pragma: no cover
        warnings.warn(
            f"different spatialite versions loaded: {pyogrio_spatialite_version=} vs "
            f"{_compat.sqlite3_spatialite_version=} vs {gdal_spatialite_version=}",
            stacklevel=1,
        )
