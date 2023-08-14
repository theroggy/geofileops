"""
Library to make spatial operations on large geo files fast(er) and easy.
"""

from pathlib import Path
import os

# Import geopandas here so the warning about pygeos <> shapely2 is given, but set
# USE_PYGEOS to avoid further warnings
import geopandas._compat as gpd_compat

if gpd_compat.USE_PYGEOS:
    os.environ["USE_PYGEOS"] = "1"
else:
    os.environ["USE_PYGEOS"] = "0"

from geofileops.fileops import *  # noqa: F403
from geofileops.geoops import *  # noqa: F403
from geofileops.helpers.layerstyles import *  # noqa: F403


def _get_version():
    version_path = Path(__file__).resolve().parent / "version.txt"
    with open(version_path) as file:
        return file.readline()


__version__ = _get_version()
