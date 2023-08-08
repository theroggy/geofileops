"""
Module containing utilities regarding operations on geoseries.
"""

import logging

import geopandas as gpd

#####################################################################
# First define/init some general variables/constants
#####################################################################

# Get a logger...
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

#####################################################################
# GeoDataFrame helpers
#####################################################################


def sort_values(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    result_gdf = gdf.copy()
    result_gdf["tmp_sort_geometry_wkt"] = result_gdf.geometry.to_wkt()
    columns_no_geom = [
        str(column) for column in result_gdf.columns if column != "geometry"
    ]
    result_gdf = result_gdf.sort_values(by=columns_no_geom)
    result_gdf = result_gdf.drop(columns="tmp_sort_geometry_wkt")

    assert isinstance(result_gdf, gpd.GeoDataFrame)
    return result_gdf
