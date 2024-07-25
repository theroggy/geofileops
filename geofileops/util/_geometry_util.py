"""Module containing utilities regarding low level vector operations."""

import enum
import logging

# Get a logger...
logger = logging.getLogger(__name__)


class BufferJoinStyle(enum.Enum):
    """Enumeration of the available buffer styles for intermediate points.

    Relevant for the end points of a line or polygon geometry.
    """

    ROUND = 1
    MITRE = 2
    BEVEL = 3


class BufferEndCapStyle(enum.Enum):
    """Enumeration of the possible end point buffer styles.

    Relevant for the end points of a line or point geometry.
    """

    ROUND = 1
    FLAT = 2
    SQUARE = 3


class SimplifyAlgorithm(enum.Enum):
    """Enumeration of the supported simplification algorythms."""

    RAMER_DOUGLAS_PEUCKER = "rdp"
    LANG = "lang"
    LANGP = "lang+"
    VISVALINGAM_WHYATT = "vw"
