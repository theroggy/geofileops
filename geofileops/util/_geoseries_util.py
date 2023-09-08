"""
Module containing utilities regarding operations on geoseries.
"""

import logging
from typing import List

import geopandas as gpd
import geopandas._compat as gpd_compat
import numpy as np
import pandas as pd
from pygeoops import GeometryType
import shapely

if gpd_compat.USE_PYGEOS:
    import pygeos as shapely2_or_pygeos
else:
    import shapely as shapely2_or_pygeos

# Get a logger...
logger = logging.getLogger(__name__)


def get_geometrytypes(
    geoseries: gpd.GeoSeries, ignore_empty_geometries: bool = True
) -> List[GeometryType]:
    """
    Determine the geometry types in the GeoDataFrame.

    Args:
        geoseries (gpd.GeoSeries): input geoseries.
        ignore_empty_geometries (bool, optional): True to ignore empty geometries.
            Defaults to True.

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

    Empty geometries are changed to None.

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


def is_valid_reason(geoseries: gpd.GeoSeries) -> pd.Series:
    # Get result and keep geoseries indexes
    return pd.Series(
        data=shapely.is_valid_reason(geoseries),
        index=geoseries.index,
    )


def _harmonize_to_multitype(
    geoseries: gpd.GeoSeries, dest_geometrytype: GeometryType
) -> gpd.GeoSeries:
    # Copy geoseries data to new array
    if gpd_compat.USE_PYGEOS:
        geometries_arr = geoseries.array.data.copy()
    else:
        geometries_arr = geoseries.copy()

    # Set empty geometries to None
    empty_idxs = shapely2_or_pygeos.is_empty(geometries_arr)
    if empty_idxs.sum():
        geometries_arr[empty_idxs] = None

    # Cast all geometries that are not of the correct multitype yet
    # Remark: all rows need to be retained, so the same indexers exist in the
    # returned geoseries
    if dest_geometrytype is GeometryType.MULTIPOLYGON:
        # Convert polygons to multipolygons
        single_idxs = shapely2_or_pygeos.get_type_id(geometries_arr) == 3
        if single_idxs.sum():
            geometries_arr[single_idxs] = np.apply_along_axis(
                shapely2_or_pygeos.multipolygons,
                arr=(np.expand_dims(geometries_arr[single_idxs], 1)),
                axis=1,
            )
    elif dest_geometrytype is GeometryType.MULTILINESTRING:
        # Convert linestrings to multilinestrings
        single_idxs = shapely2_or_pygeos.get_type_id(geometries_arr) == 1
        if single_idxs.sum():
            geometries_arr[single_idxs] = np.apply_along_axis(
                shapely2_or_pygeos.multilinestrings,
                arr=(np.expand_dims(geometries_arr[single_idxs], 1)),
                axis=1,
            )
    elif dest_geometrytype is GeometryType.MULTIPOINT:
        single_idxs = shapely2_or_pygeos.get_type_id(geometries_arr) == 0
        if single_idxs.sum():
            geometries_arr[single_idxs] = np.apply_along_axis(
                shapely2_or_pygeos.multipoints,
                arr=(np.expand_dims(geometries_arr[single_idxs], 1)),
                axis=1,
            )
    else:
        raise Exception(f"Unsupported destination GeometryType: {dest_geometrytype}")

    # Prepare result to return
    geoseries_result = gpd.GeoSeries(
        geometries_arr, index=geoseries.index, crs=geoseries.crs
    )
    assert isinstance(geoseries_result, gpd.GeoSeries)
    return geoseries_result
