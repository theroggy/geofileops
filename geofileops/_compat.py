"""Module with compatibility and dependency availability checks."""

import warnings
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
import shapely
from osgeo import gdal
from packaging import version

from geofileops.util import _ogr_util, _sqlite_util

gdal.UseExceptions()


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


pyogrio_spatialite_version_info = _pyogrio_spatialite_version_info()
sqlite3_spatialite_version_info = _sqlite_util.spatialite_version_info()
gdal_spatialite_version_info = _ogr_util.spatialite_version_info()

# Check that the spatialite versions are the same
pyogrio_spatialite_version = pyogrio_spatialite_version_info["spatialite_version"]
sqlite3_spatialite_version = sqlite3_spatialite_version_info["spatialite_version"]
gdal_spatialite_version = gdal_spatialite_version_info["spatialite_version"]
if (
    pyogrio_spatialite_version != sqlite3_spatialite_version
    or pyogrio_spatialite_version != gdal_spatialite_version
):  # pragma: no cover
    warnings.warn(
        f"different spatialite versions loaded: {pyogrio_spatialite_version=} vs "
        f"{sqlite3_spatialite_version=} vs {gdal_spatialite_version=}",
        stacklevel=1,
    )

# Determine the versions of the runtime dependencies
GDAL_GTE_38 = version.parse(gdal.__version__) >= version.parse("3.8")
GEOPANDAS_GTE_10 = version.parse(gpd.__version__) >= version.parse("1.0")
PANDAS_GTE_22 = version.parse(pd.__version__) >= version.parse("2.2")
PYOGRIO_GTE_07 = version.parse(pyogrio.__version__) >= version.parse("0.7")
SHAPELY_GTE_20 = version.parse(shapely.__version__) >= version.parse("2")
SPATIALITE_GTE_51 = version.parse(sqlite3_spatialite_version) >= version.parse("5.1")

GDAL_GTE_38 = version.parse(gdal.__version__) >= version.parse("3.8")
GDAL_ST_311 = version.parse(gdal.__version__) < version.parse("3.11")
