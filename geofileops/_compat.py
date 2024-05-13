from packaging import version

from osgeo import gdal
import pyogrio
import shapely

from geofileops.util import _sqlite_util

PYOGRIO_GTE_07 = version.parse(pyogrio.__version__) >= version.parse("0.7")
SHAPELY_GTE_20 = version.parse(shapely.__version__) >= version.parse("2")

# Check what version of spatialite we are dealing with
spatialite_version_info = _sqlite_util.spatialite_version_info()
spatialite_version = spatialite_version_info["spatialite_version"]
SPATIALITE_GTE_51 = version.parse(spatialite_version) >= version.parse("5.1")

GDAL_GTE_38 = version.parse(gdal.__version__) >= version.parse("3.8")
