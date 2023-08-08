"""
Module containing utilities to create/manipulate grids.
"""

import logging
import math
from typing import Optional, Tuple, Union

import geopandas as gpd
import pyproj
import shapely.ops as sh_ops
import shapely.geometry as sh_geom

#####################################################################
# First define/init some general variables/constants
#####################################################################

# Get a logger...
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

#####################################################################
# Grid tile helpers
#####################################################################


def create_grid(
    total_bounds: Tuple[float, float, float, float],
    nb_columns: int,
    nb_rows: int,
    crs: Union[pyproj.CRS, int, str, None],
) -> gpd.GeoDataFrame:
    xmin, ymin, xmax, ymax = total_bounds
    width = (xmax - xmin) / nb_columns
    height = (ymax - ymin) / nb_rows

    return create_grid3(total_bounds=total_bounds, width=width, height=height, crs=crs)


def create_grid3(
    total_bounds: Tuple[float, float, float, float],
    width: float,
    height: float,
    crs: Union[pyproj.CRS, int, str, None],
) -> gpd.GeoDataFrame:
    """


    Args:
        total_bounds (Tuple[float, float, float, float]): [description]
        width (float): [description]
        height (float): [description]
        crs (Union[pyproj.CRS, int, str, None]): [description]
        number_decimals (int, optional): The number of decimals the coordinates
            of the grid will have. Defaults to None, so no rounding.

    Returns:
        gpd.GeoDataFrame: [description]
    """

    xmin, ymin, xmax, ymax = total_bounds
    rows = int(math.ceil((ymax - ymin) / height))
    cols = int(math.ceil((xmax - xmin) / width))

    polygons = []
    cell_left = xmin
    cell_right = xmin + width
    for _ in range(cols):
        if cell_left > xmax:
            break
        cell_top = ymin + height
        cell_bottom = ymin
        for _ in range(rows):
            if cell_bottom > ymax:
                break
            polygons.append(
                sh_ops.Polygon(
                    [
                        (cell_left, cell_top),
                        (cell_right, cell_top),
                        (cell_right, cell_bottom),
                        (cell_left, cell_bottom),
                    ]
                )
            )
            cell_top += height
            cell_bottom += height

        cell_left += width
        cell_right += width

    return gpd.GeoDataFrame(geometry=polygons, crs=crs)


def create_grid2(
    total_bounds: Tuple[float, float, float, float],
    nb_squarish_tiles: int,
    crs: Union[pyproj.CRS, int, str, None],
    nb_squarish_tiles_max: Optional[int] = None,
) -> gpd.GeoDataFrame:
    """
    Creates a grid and tries to approximate the number of cells asked as
    good as possible with grid cells that as close to square as possible.

    Args:
        total_bounds (Tuple[float, float, float, float]): bounds of the grid to be
            created
        nb_squarish_cells (int): about the number of cells wanted
        crs (pyproj.CRS, int, str, optional): the projection to create the grid in
        nb_squarish_tiles_max (int, optional): the maximum number of cells

    Returns:
        gpd.GeoDataFrame: geodataframe with the grid
    """
    # Check input
    if nb_squarish_tiles_max is not None and nb_squarish_tiles_max < 1:
        raise Exception("The maximum nb of tiles should be larger than 1")

    # If more cells asked, calculate optimal number
    xmin, ymin, xmax, ymax = total_bounds
    total_width = xmax - xmin
    total_height = ymax - ymin

    columns_vs_rows = total_width / total_height
    nb_rows = max(round(math.sqrt(nb_squarish_tiles / columns_vs_rows)), 1)

    # Evade having too many cells (if few cells are asked)
    if nb_rows > nb_squarish_tiles:
        nb_rows = nb_squarish_tiles
    nb_columns = max(round(nb_squarish_tiles / nb_rows), 1)
    # If a maximum number of tiles is specified, check it
    if nb_squarish_tiles_max is not None:
        while (nb_rows * nb_columns) > nb_squarish_tiles_max:
            # If the number of cells became larger than the max number of cells,
            # increase the number of cells in the direction of the longest side
            # of the resulting cells
            if nb_columns > 1 and (
                nb_rows == 1 or total_width / nb_columns > total_height / nb_rows
            ):
                # Cell width is larger than cell height
                nb_columns -= 1
            else:
                nb_rows -= 1

    # Now we know everything to create the grid
    return create_grid(
        total_bounds=total_bounds, nb_columns=nb_columns, nb_rows=nb_rows, crs=crs
    )


def split_tiles(
    input_tiles: gpd.GeoDataFrame, nb_tiles_wanted: int
) -> gpd.GeoDataFrame:
    nb_tiles = len(input_tiles)
    if nb_tiles >= nb_tiles_wanted:
        return input_tiles

    nb_tiles_ratio_target = nb_tiles_wanted / nb_tiles

    # Loop over all tiles in the grid
    result_tiles = []
    for tile in input_tiles.itertuples():
        # For this tile, as long as the curr_nb_tiles_ratio_todo is not 1, keep
        # splitting
        curr_nb_tiles_ratio_todo = nb_tiles_ratio_target
        curr_tiles_being_split = [tile.geometry]
        while curr_nb_tiles_ratio_todo > 1:
            # Check in how many parts the tiles are split in this iteration
            divisor = 0
            if round(curr_nb_tiles_ratio_todo) == 3:
                divisor = 3
            else:
                divisor = 2
            curr_nb_tiles_ratio_todo /= divisor

            # Split all current tiles
            tmp_tiles_after_split = []
            for tile_to_split in curr_tiles_being_split:
                xmin, ymin, xmax, ymax = tile_to_split.bounds
                width = abs(xmax - xmin)
                height = abs(ymax - ymin)

                # Split in 2 or 3...
                if divisor == 3:
                    if width > height:
                        split_line = sh_geom.LineString(
                            [
                                (xmin + width / 3, ymin - 1),
                                (xmin + width / 3, ymax + 1),
                                (xmin + 2 * width / 3, ymax + 1),
                                (xmin + 2 * width / 3, ymin - 1),
                            ]
                        )
                    else:
                        split_line = sh_geom.LineString(
                            [
                                (xmin - 1, ymin + height / 3),
                                (xmax + 1, ymin + height / 3),
                                (xmax + 1, ymin + 2 * height / 3),
                                (xmin - 1, ymin + 2 * height / 3),
                            ]
                        )
                else:
                    if width > height:
                        split_line = sh_geom.LineString(
                            [(xmin + width / 2, ymin - 1), (xmin + width / 2, ymax + 1)]
                        )
                    else:
                        split_line = sh_geom.LineString(
                            [
                                (xmin - 1, ymin + height / 2),
                                (xmax + 1, ymin + height / 2),
                            ]
                        )
                tmp_tiles_after_split.extend(
                    sh_ops.split(tile_to_split, split_line).geoms
                )
            curr_tiles_being_split = tmp_tiles_after_split

        # Copy the tile parts to the result and retain possible other columns
        for tile_split_part in curr_tiles_being_split:
            result_tiles.append(tile._replace(geometry=tile_split_part))

    # We should be ready...
    return gpd.GeoDataFrame(data=result_tiles, crs=input_tiles.crs)
