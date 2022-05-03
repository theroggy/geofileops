import warnings

warnings.warn(
    "the vector_util module is deprecated, please import grid_util and/or geometry_util directly instead",
    FutureWarning,
)
from .grid_util import *
from .geometry_util import *
