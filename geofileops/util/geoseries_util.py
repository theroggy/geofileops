"""
Module containing utilities regarding operations on geoseries.
"""

import logging
from typing import List, Optional

import geopandas as gpd
import geopandas._compat as gpd_compat
import numpy as np
import pandas as pd

if gpd_compat.USE_PYGEOS:
    import pygeos as shapely2_or_pygeos
else:
    import shapely as shapely2_or_pygeos
import shapely
from shapely import geometry as sh_geom

from . import geometry_util
from .geometry_util import GeometryType, PrimitiveType, SimplifyAlgorithm

# Get a logger...
logger = logging.getLogger(__name__)


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
    for index, geom in geoseries_copy.items():
        geoseries_copy[index] = geometry_util.collection_extract(geom, primitivetype)
    assert isinstance(geoseries_copy, gpd.GeoSeries)
    return geoseries_copy


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
    geometries_arr = geoseries.array.data.copy()

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
        if boundary.geom_type == "MultiLineString":
            for line in boundary.geoms:
                polygons_lines.append(line)
        else:
            polygons_lines.append(boundary)

    return gpd.GeoSeries(polygons_lines)


def simplify_topo_ext(
    geoseries: gpd.GeoSeries,
    tolerance: float,
    algorithm: SimplifyAlgorithm = SimplifyAlgorithm.RAMER_DOUGLAS_PEUCKER,
    lookahead: int = 8,
    keep_points_on: Optional[sh_geom.base.BaseGeometry] = None,
) -> gpd.GeoSeries:
    """
    Applies simplify while retaining common boundaries between geometries in the
    geoseries.

    Args:
        geoseries (gpd.GeoSeries): the geoseries to simplify.
        algorithm (SimplifyAlgorithm): algorithm to use.
        tolerance (float): tolerance to use for simplify
        lookahead (int, optional): lookahead value for algorithms that use this.
            Defaults to 8.
        keep_points_on (Optional[sh_geom.base.BaseGeometry], optional): points that
            intersect with this geometry won't be removed by the simplification.
            Defaults to None.

    Returns:
        gpd.GeoSeries: the simplified geoseries
    """
    try:
        import topojson
        import topojson.ops
    except ImportError as ex:
        raise ImportError(
            "simplify_topo_ext needs an optional package. Install with "
            "'pip install topojson'"
        ) from ex

    topo = topojson.Topology(geoseries, prequantize=False)
    topolines = sh_geom.MultiLineString(topo.output["arcs"])
    topolines_simpl = geometry_util.simplify_ext(
        geometry=topolines,
        tolerance=tolerance,
        algorithm=algorithm,
        lookahead=lookahead,
        keep_points_on=keep_points_on,
        preserve_topology=True,
    )
    assert topolines_simpl is not None

    # Copy the results of the simplified lines
    if algorithm == SimplifyAlgorithm.LANG:
        # For LANG, a simple copy is OK
        assert isinstance(topolines_simpl, sh_geom.MultiLineString)
        topo.output["arcs"] = [list(geom.coords) for geom in topolines_simpl.geoms]
    else:
        # For RDP, only overwrite the lines that have a valid result
        for index in range(len(topo.output["arcs"])):
            # If the result of the simplify is a point, keep original
            topoline_simpl = topolines_simpl.geoms[index].coords
            if len(topoline_simpl) < 2:
                continue
            elif (
                list(topoline_simpl[0]) != topo.output["arcs"][index][0]
                or list(topoline_simpl[-1]) != topo.output["arcs"][index][-1]
            ):
                # Start or end point of the simplified version is not the same anymore
                continue
            else:
                topo.output["arcs"][index] = list(topoline_simpl)

    topo_simpl_gdf = topo.to_gdf(crs=geoseries.crs)
    topo_simpl_gdf.geometry = shapely.make_valid(topo_simpl_gdf.geometry)
    geometry_types_orig = geoseries.geom_type.unique()
    geometry_types_simpl = topo_simpl_gdf.geometry.geom_type.unique()
    if len(geometry_types_orig) == 1 and len(geometry_types_simpl) > 1:
        topo_simpl_gdf.geometry = geometry_collection_extract(
            topo_simpl_gdf.geometry,
            GeometryType(geometry_types_orig[0]).to_primitivetype,
        )
    return topo_simpl_gdf.geometry


def simplify_ext(
    geoseries: gpd.GeoSeries,
    tolerance: float,
    algorithm: SimplifyAlgorithm = SimplifyAlgorithm.RAMER_DOUGLAS_PEUCKER,
    lookahead: int = 8,
    keep_points_on: Optional[sh_geom.base.BaseGeometry] = None,
) -> gpd.GeoSeries:
    """
    Applies simplify on the geometries in the geoseries.

    Args:
        geoseries (gpd.GeoSeries): the geoseries to simplify.
        algorithm (SimplifyAlgorithm): algorithm to use.
        tolerance (float): tolerance to use for simplify
        lookahead (int, optional): lookahead value for algorithms that use this.
            Defaults to 8.
        keep_points_on (Optional[sh_geom.base.BaseGeometry], optional): points that
            intersect with this geometry won't be removed by the simplification.
            Defaults to None.

    Returns:
        gpd.GeoSeries: the simplified geoseries
    """
    # If ramer-douglas-peucker and no keep_points_on, use standard geopandas algorithm
    if algorithm is SimplifyAlgorithm.RAMER_DOUGLAS_PEUCKER and keep_points_on is None:
        return geoseries.simplify(tolerance=tolerance, preserve_topology=True)
    else:
        # For other algorithms, use vector_util.simplify_ext()
        return gpd.GeoSeries(
            [
                geometry_util.simplify_ext(
                    geom,
                    algorithm=algorithm,
                    tolerance=tolerance,
                    lookahead=lookahead,
                    keep_points_on=keep_points_on,
                    preserve_topology=True,
                )
                for geom in geoseries
            ]
        )
