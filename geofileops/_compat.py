import shapely

from geofileops.util import _sqlite_util

SHAPELY_GE_20 = str(shapely.__version__).split(".")[0] >= "2"

# Check what version of spatialite we are dealing with
versions = _sqlite_util.check_runtimedependencies()
SPATIALITE_GTE_51 = False if versions["spatialite_version"] < "5.1" else True
