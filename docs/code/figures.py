"""Common figure settings and utilities for the documentation."""

from math import sqrt

from matplotlib.axes import Axes
from shapely import affinity
from shapely.geometry.base import BaseGeometry

GM = (sqrt(5) - 1.0) / 2.0
W = 8.0
H = W * GM
SIZE = (W, H)

BLUE = "#4c8ecf"
GRAY = "#999999"
DARKGRAY = "#333333"
YELLOW = "#ffcc33"
GREEN = "#339933"
RED = "#ff3333"
BLACK = "#000000"


def add_origin(ax: Axes, geom: BaseGeometry, origin: object) -> None:
    """Add an origin marker to a plot."""
    x, y = xy = affinity.interpret_origin(geom, origin, 2)
    ax.plot(x, y, "o", color=GRAY, zorder=1)
    ax.annotate(str(xy), xy=xy, ha="center", textcoords="offset points", xytext=(0, 8))


def set_limits(ax: Axes, x0: float, xN: float, y0: float, yN: float) -> None:
    """Set axis limits and ticks for a plot."""
    ax.set_xlim(x0, xN)
    ax.set_xticks(range(x0, xN + 1))  # type: ignore[call-overload]
    ax.set_ylim(y0, yN)
    ax.set_yticks(range(y0, yN + 1))  # type: ignore[call-overload]
    ax.set_aspect("equal")
