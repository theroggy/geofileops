# -*- coding: utf-8 -*-
"""
Module containing utilities regarding operations on geoseries.
"""

import datetime
import logging
from typing import List

import geopandas as gpd
import numpy as np
import pygeos as pg
from shapely import geometry as sh_geom

from . import geometry_util
from .geometry_util import GeometryType, PrimitiveType

#####################################################################
# First define/init some general variables/constants
#####################################################################

# Get a logger...
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

#####################################################################
# GeoDataFrame helpers
#####################################################################


def geometry_collection_extract(
    geoseries: gpd.GeoSeries, primitivetype: PrimitiveType
) -> gpd.GeoSeries:
    """
    # Apply the collection_extract
    return gpd.GeoSeries(
            [geometry_util.collection_extract(geom, primitivetype) for geom in geoseries])
    """
    # Apply the collection_extract
    geoseries_copy = geoseries.copy()
    for index, geom in geoseries_copy.iteritems():
        geoseries_copy[index] = geometry_util.collection_extract(geom, primitivetype)
    assert isinstance(geoseries_copy, gpd.GeoSeries)
    return geoseries_copy


def get_geometrytypes(
    geoseries: gpd.GeoSeries, ignore_empty_geometries: bool = True
) -> List[GeometryType]:
    """
    Determine the geometry types in the GeoDataFrame.

    In a GeoDataFrame, empty geometries are always treated as
    geometrycollections. These are by default ignored.

    Args:
        geoseries (gpd.GeoSeries): input geoseries.
        ignore_empty_geometries (bool, optional): True to ignore empty
            geometries, as they are always stored as GeometryCollections by
            GeoPandas. Defaults to True.

    Returns:
        List[GeometryType]: [description]
    """
    if ignore_empty_geometries is True:
        input_geoseries = geoseries[~geoseries.is_empty]
    else:
        input_geoseries = geoseries
    geom_types_2D = input_geoseries[~input_geoseries.has_z].geom_type.unique()
    geom_types_2D = [gtype for gtype in geom_types_2D if gtype is not None]
    geom_types_3D = input_geoseries[input_geoseries.has_z].geom_type.unique()
    geom_types_3D = ["3D " + gtype for gtype in geom_types_3D if gtype is not None]
    geom_types = geom_types_3D + geom_types_2D

    if len(geom_types) == 0:
        return [GeometryType.GEOMETRY]

    geometrytypes_list = [GeometryType[geom_type.upper()] for geom_type in geom_types]
    return geometrytypes_list


def harmonize_geometrytypes(
    geoseries: gpd.GeoSeries, force_multitype: bool = False
) -> gpd.GeoSeries:
    """
    Tries to harmonize the geometries in the geoseries to one type.

    Eg. if Polygons and MultiPolygons are present in the geoseries, all
    geometries are converted to MultiPolygons.

    Empty geometries are changed to None, because Empty geometries are always
    treated as GeometryCollections by GeoPandas.

    If they cannot be harmonized, the original series is returned...

    Args:
        geoseries (gpd.GeoSeries): The geoseries to harmonize.
        force_multitype (bool, optional): True to force all geometries to the
            corresponding multitype. Defaults to False.

    Returns:
        gpd.GeoSeries: the harmonized geoseries if possible, otherwise the
            original one.
    """
    # Get unique list of geometrytypes in gdf
    geometrytypes = get_geometrytypes(geoseries)

    # If already only one geometrytype...
    if len(geometrytypes) == 1:
        if force_multitype is True:
            # If it is already a multitype, return
            if geometrytypes[0].is_multitype is True:
                return geoseries
            else:
                # Else convert to corresponding multitype
                return _harmonize_to_multitype(geoseries, geometrytypes[0].to_multitype)
        else:
            return geoseries
    elif (
        len(geometrytypes) == 2
        and geometrytypes[0].to_primitivetype == geometrytypes[1].to_primitivetype
    ):
        # There are two geometrytypes, but they are of the same primitive type,
        # so can just be harmonized to the multitype
        return _harmonize_to_multitype(geoseries, geometrytypes[0].to_multitype)
    else:
        # Too difficult to harmonize, so just return
        return geoseries


def _harmonize_to_multitype(
    geoseries: gpd.GeoSeries, dest_geometrytype: GeometryType
) -> gpd.GeoSeries:

    # Copy geoseries to pygeos array
    geometries_arr = geoseries.array.data.copy()  # type: ignore

    # Set empty geometries to None
    empty_idxs = pg.get_type_id(geometries_arr) == 7
    if empty_idxs.sum():
        geometries_arr[empty_idxs] = None

    # Cast all geometries that are not of the correct multitype yet
    # Remark: all rows need to be retained, so the same indexers exist in the
    # returned geoseries
    if dest_geometrytype is GeometryType.MULTIPOLYGON:
        # Convert polygons to multipolygons
        single_idxs = pg.get_type_id(geometries_arr) == 3
        if single_idxs.sum():
            geometries_arr[single_idxs] = np.apply_along_axis(
                pg.multipolygons,
                arr=(np.expand_dims(geometries_arr[single_idxs], 1)),
                axis=1,
            )
    elif dest_geometrytype is GeometryType.MULTILINESTRING:
        # Convert linestrings to multilinestrings
        single_idxs = pg.get_type_id(geometries_arr) == 1
        if single_idxs.sum():
            geometries_arr[single_idxs] = np.apply_along_axis(
                pg.multilinestrings,
                arr=(np.expand_dims(geometries_arr[single_idxs], 1)),
                axis=1,
            )
    elif dest_geometrytype is GeometryType.MULTIPOINT:
        single_idxs = pg.get_type_id(geometries_arr) == 0
        if single_idxs.sum():
            geometries_arr[single_idxs] = np.apply_along_axis(
                pg.multipoints,
                arr=(np.expand_dims(geometries_arr[single_idxs], 1)),
                axis=1,
            )
    else:
        raise Exception(f"Unsupported destination GeometryType: {dest_geometrytype}")

    # Prepare result to return
    geoseries_result = geoseries.copy()
    geoseries_result.array.data = geometries_arr  # type: ignore
    assert isinstance(geoseries_result, gpd.GeoSeries)
    return geoseries_result


def polygons_to_lines(geoseries: gpd.GeoSeries) -> gpd.GeoSeries:
    polygons_lines = []
    for geom in geoseries:
        if geom is None or geom.is_empty:
            continue
        if (
            isinstance(geom, sh_geom.Polygon) is False
            and isinstance(geom, sh_geom.MultiPolygon) is False
        ):
            raise ValueError(f"Invalid geometry: {geom}")
        boundary = geom.boundary
        if boundary.type == "MultiLineString":
            for line in boundary.geoms:
                polygons_lines.append(line)
        else:
            polygons_lines.append(boundary)

    return gpd.GeoSeries(polygons_lines)


def simplify_ext(
    geoseries: gpd.GeoSeries,
    algorithm: geometry_util.SimplifyAlgorithm,
    tolerance: float,
    lookahead: int = 8,
) -> gpd.GeoSeries:
    # If ramer-douglas-peucker, use standard geopandas algorithm
    if algorithm is geometry_util.SimplifyAlgorithm.RAMER_DOUGLAS_PEUCKER:
        return geoseries.simplify(tolerance=tolerance, preserve_topology=True)
    else:
        # For other algorithms, use vector_util.simplify_ext()
        return gpd.GeoSeries(
            [
                geometry_util.simplify_ext(
                    geom, algorithm=algorithm, tolerance=tolerance, lookahead=lookahead
                )
                for geom in geoseries
            ]
        )
