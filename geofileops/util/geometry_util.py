# -*- coding: utf-8 -*-
"""
Module containing utilities regarding low level vector operations.
"""

import enum
import logging
import math
from typing import List, Optional, Union

import geopandas as gpd
import numpy as np
import pyproj
import shapely.coords as sh_coords
import shapely.geometry as sh_geom
import shapely.ops as sh_ops
import shapely.validation


#####################################################################
# First define/init some general variables/constants
#####################################################################


# Get a logger...
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)


#####################################################################
# Buffer helpers
#####################################################################


class BufferJoinStyle(enum.Enum):
    """
    Enumeration of the available buffer styles for the intermediate points of
    a line or polygon geometry.
    """

    ROUND = 1
    MITRE = 2
    BEVEL = 3


class BufferEndCapStyle(enum.Enum):
    """
    Enumeration of the available buffer styles for the end points of
    a line or point geometry.
    """

    ROUND = 1
    FLAT = 2
    SQUARE = 3


#####################################################################
# Geometry helpers
#####################################################################


class GeometryType(enum.Enum):
    """
    Enumeration of the different geometry types.
    """

    MISSING = -1
    GEOMETRY = 0
    POINT = 1
    LINESTRING = 2
    POLYGON = 3
    MULTIPOINT = 4
    MULTILINESTRING = 5
    MULTIPOLYGON = 6
    GEOMETRYCOLLECTION = 7

    @classmethod
    def _missing_(cls, value: Union[str, int]):
        """
        Expand options in the Geometrytype() constructor.

        Args:
            value (Union[str, int, GeometryType]):
                * string: lookup using case insensitive name
                * GeometryType: create the same GeometryType as the one passed in

        Returns:
            [GeometryType]: The corresponding GeometryType.
        """
        if isinstance(value, str):
            # If a string is passed in, try lookup based on case insensitive enum name
            return cls(GeometryType[value.upper()])
        # Default behaviour (= lookup based on value)
        return super()._missing_(value)

    @property
    def name_camelcase(self) -> str:
        """Get the name in camel case."""
        if self is GeometryType.POINT:
            return "Point"
        elif self is GeometryType.LINESTRING:
            return "LineString"
        elif self is GeometryType.POLYGON:
            return "Polygon"
        elif self is GeometryType.MULTIPOINT:
            return "MultiPoint"
        elif self is GeometryType.MULTILINESTRING:
            return "MultiLineString"
        elif self is GeometryType.MULTIPOLYGON:
            return "MultiPolygon"
        elif self is GeometryType.GEOMETRYCOLLECTION:
            return "GeometryCollection"
        elif self is GeometryType.GEOMETRY:
            return "Geometry"
        else:
            raise ValueError(f"No camelcase name implemented for: {self}")

    @property
    def is_multitype(self):
        """Returns if the geometry type is a multi type."""
        return self in (
            GeometryType.GEOMETRY,
            GeometryType.MULTIPOINT,
            GeometryType.MULTILINESTRING,
            GeometryType.MULTIPOLYGON,
            GeometryType.GEOMETRYCOLLECTION,
        )

    @property
    def to_multitype(self):
        """Get the corresponding multitype."""
        if self in [
            GeometryType.GEOMETRY,
            GeometryType.MULTIPOINT,
            GeometryType.MULTILINESTRING,
            GeometryType.MULTIPOLYGON,
            GeometryType.GEOMETRYCOLLECTION,
        ]:
            return self
        elif self is GeometryType.POINT:
            return GeometryType.MULTIPOINT
        elif self is GeometryType.LINESTRING:
            return GeometryType.MULTILINESTRING
        elif self is GeometryType.POLYGON:
            return GeometryType.MULTIPOLYGON
        else:
            raise Exception(f"No multitype implemented for: {self}")

    @property
    def to_singletype(self):
        """Get the corresponding multitype."""
        if self in [
            GeometryType.GEOMETRY,
            GeometryType.POINT,
            GeometryType.LINESTRING,
            GeometryType.POLYGON,
        ]:
            return self
        elif self is GeometryType.MULTIPOINT:
            return GeometryType.POINT
        elif self is GeometryType.MULTILINESTRING:
            return GeometryType.LINESTRING
        elif self is GeometryType.MULTIPOLYGON:
            return GeometryType.POLYGON
        elif GeometryType.GEOMETRYCOLLECTION:
            return GeometryType.GEOMETRY
        else:
            raise Exception(f"No multitype implemented for: {self}")

    @property
    def to_primitivetype(self):
        """Get the corresponding primitive type."""
        if self in [GeometryType.POINT, GeometryType.MULTIPOINT]:
            return PrimitiveType.POINT
        elif self in [GeometryType.LINESTRING, GeometryType.MULTILINESTRING]:
            return PrimitiveType.LINESTRING
        elif self in [GeometryType.POLYGON, GeometryType.MULTIPOLYGON]:
            return PrimitiveType.POLYGON
        elif self in [GeometryType.GEOMETRY, GeometryType.GEOMETRYCOLLECTION]:
            raise Exception(f"{self} doesn't have a primitive type")
        else:
            raise Exception(f"No primitive type implemented for {self}")


class PrimitiveType(enum.Enum):
    """
    Enumeration of the different existing primitive types of a geometry.
    """

    POINT = 1
    LINESTRING = 2
    POLYGON = 3

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            return cls(PrimitiveType[value.upper()])
        return super()._missing_(value)

    @property
    def to_multitype(self) -> GeometryType:
        """Get the corresponding multitype."""
        if self is PrimitiveType.POINT:
            return GeometryType.MULTIPOINT
        elif self is PrimitiveType.LINESTRING:
            return GeometryType.MULTILINESTRING
        elif self is PrimitiveType.POLYGON:
            return GeometryType.MULTIPOLYGON
        else:
            raise Exception(f"no multitype implemented for: {self}")

    @property
    def to_singletype(self) -> GeometryType:
        """Get the corresponding multitype."""
        if self is PrimitiveType.POINT:
            return GeometryType.POINT
        elif self is PrimitiveType.LINESTRING:
            return GeometryType.LINESTRING
        elif self is PrimitiveType.POLYGON:
            return GeometryType.POLYGON
        else:
            raise Exception(f"no singletype implemented for: {self}")


def collection_extract(
    geometry: Optional[sh_geom.base.BaseGeometry], primitivetype: PrimitiveType
) -> Optional[sh_geom.base.BaseGeometry]:
    """
    Extracts the geometries from the input geom that comply with the
    primitive_type specified and returns them as (Multi)geometry.

    Args:
        geometry (sh_geom.base.BaseGeometry): geometry to extract the polygons
            from.
        primitivetype (GeometryPrimitiveTypes): the primitive type to extract
            from the input geom.

    Raises:
        Exception: if in_geom is an unsupported geometry type or the primitive
            type is invalid.

    Returns:
        sh_geom.base.BaseGeometry: List of primitive geometries, only
            containing the primitive type specified.
    """
    # Extract the polygons from the multipolygon, but store them as multipolygons anyway
    if geometry is None:
        return None
    elif isinstance(geometry, (sh_geom.MultiPoint, sh_geom.Point)):
        if primitivetype == PrimitiveType.POINT:
            return geometry
    elif isinstance(geometry, (sh_geom.LineString, sh_geom.MultiLineString)):
        if primitivetype == PrimitiveType.LINESTRING:
            return geometry
    elif isinstance(geometry, (sh_geom.MultiPolygon, sh_geom.Polygon)):
        if primitivetype == PrimitiveType.POLYGON:
            return geometry
    elif isinstance(geometry, sh_geom.GeometryCollection):
        returngeoms = []
        for geometry in sh_geom.GeometryCollection(geometry).geoms:
            returngeoms.append(
                collection_extract(geometry, primitivetype=primitivetype)
            )
        if len(returngeoms) > 0:
            return collect(returngeoms)
    else:
        raise Exception(f"Invalid/unsupported geometry(type): {geometry}")

    # Nothing found yet, so return None
    return None


def collect(
    geometry_list: List[sh_geom.base.BaseGeometry],
) -> Optional[sh_geom.base.BaseGeometry]:
    """
    Collect a list of geometries to one geometry.

    Examples:
      * if the list contains only Polygon's, returns a MultiPolygon.
      * if the list contains different types, returns a GeometryCollection.

    Args:
        geometry_list (List[sh_geom.base.BaseGeometry]): [description]

    Raises:
        Exception: raises an exception if one of the input geometries is of an
            unknown type.

    Returns:
        sh_geom.base.BaseGeometry: the result
    """
    # First remove all None geometries in the input list
    geometry_list = [
        geometry
        for geometry in geometry_list
        if geometry is not None and geometry.is_empty is False
    ]

    # If the list is empty or contains only 1 element, it is easy...
    if geometry_list is None or len(geometry_list) == 0:
        return None
    elif len(geometry_list) == 1:
        return geometry_list[0]

    # Loop over all elements in the list, and determine the appropriate geometry
    # type to create
    result_collection_type = GeometryType(geometry_list[0].geom_type).to_multitype
    for geom in geometry_list:
        # If it is the same as the collection_geom_type, continue checking
        if GeometryType(geom.geom_type).to_multitype == result_collection_type:
            continue
        else:
            # If multiple types in the list, result becomes a geometrycollection
            result_collection_type = GeometryType.GEOMETRYCOLLECTION
            break

    # Now we can create the collection
    # Explode the multi-geometries to single ones
    singular_geometry_list = []
    for geom in geometry_list:
        if isinstance(geom, sh_geom.base.BaseMultipartGeometry):
            singular_geometry_list.extend(geom.geoms)
        else:
            singular_geometry_list.append(geom)

    if result_collection_type == GeometryType.MULTIPOINT:
        return sh_geom.MultiPoint(singular_geometry_list)
    elif result_collection_type == GeometryType.MULTILINESTRING:
        return sh_geom.MultiLineString(singular_geometry_list)
    elif result_collection_type == GeometryType.MULTIPOLYGON:
        return sh_geom.MultiPolygon(singular_geometry_list)
    elif result_collection_type == GeometryType.GEOMETRYCOLLECTION:
        return sh_geom.GeometryCollection(geometry_list)
    else:
        raise Exception(f"Unsupported geometry type: {result_collection_type}")


"""
def force_geometrytype(
        geometry: sh_geom.base.BaseGeometry,
        dest_geometrytype: GeometryType) -> sh_geom.base.BaseGeometry:
    # Cast to destination geometrytype
    if dest_geometrytype is GeometryType.MULTIPOLYGON:
        gdf.geometry = [sh_geom.MultiPolygon([feature])
                        if type(feature) == sh_geom.Polygon
                        else feature for feature in gdf.geometry]
    elif dest_geometrytype is GeometryType.MULTIPOINT:
        gdf.geometry = [sh_geom.MultiPoint([feature])
                        if type(feature) == sh_geom.Point
                        else feature for feature in gdf.geometry]
    elif dest_geometrytype is GeometryType.MULTILINESTRING:
        gdf.geometry = [sh_geom.MultiLineString([feature])
                        if type(feature) == sh_geom.LineString
                        else feature for feature in gdf.geometry]
    elif dest_geometrytype in [
            GeometryType.POLYGON, GeometryType.POINT, GeometryType.LINESTRING]:
        logger.debug(f"geometrytype is {dest_geometrytype}, so no conversion is done")
    else:
        raise Exception(f"Unsupported geometrytype: {dest_geometrytype}")
"""


def make_valid(
    geometry: Optional[sh_geom.base.BaseGeometry],
) -> Optional[sh_geom.base.BaseGeometry]:
    """
    Make a geometry valid.

    Args:
        geometry (Optional[sh_geom.base.BaseGeometry]): A (possibly) invalid geometry.

    Returns:
        Optional[sh_geom.base.BaseGeometry]: The fixed geometry.
    """
    if geometry is None:
        return None
    else:
        return shapely.validation.make_valid(geometry)


def numberpoints(geometry: Optional[sh_geom.base.BaseGeometry]) -> int:
    """
    Calculates the total number of points in a geometry.

    Args:
        geometry (sh_geom.base.BaseGeometry): the geometry to count the point of.

    Returns:
        int: the number of points in the geometry.
    """
    # If it is a multi-part, recursively call numberpoints for all parts.
    if geometry is None:
        return 0
    elif isinstance(geometry, sh_geom.base.BaseMultipartGeometry):
        nb_points = 0
        for geom in geometry.geoms:
            nb_points += numberpoints(geom)
        return nb_points
    elif isinstance(geometry, sh_geom.Polygon):
        # If it is a polygon, calculate number for exterior and interior rings.
        assert geometry.exterior is not None
        nb_points = len(geometry.exterior.coords)
        for ring in geometry.interiors:
            nb_points += len(ring.coords)
        return nb_points
    else:
        # For other types, it is just the number of coordinates.
        return len(geometry.coords)


def remove_inner_rings(
    geometry: Union[sh_geom.Polygon, sh_geom.MultiPolygon, None],
    min_area_to_keep: float,
    crs: Optional[pyproj.CRS],
) -> Union[sh_geom.Polygon, sh_geom.MultiPolygon, None]:
    """
    Remove (small) inner rings from a (multi)polygon.

    Args:
        geometry (Union[sh_geom.Polygon, sh_geom.MultiPolygon, None]): polygon
        min_area_to_keep (float, optional): keep the inner rings with at least
            this area in the coordinate units (typically m). If 0.0,
            no inner rings are kept.
        crs (pyproj.CRS, optional): the projection of the geometry. Passing
            None is fine if min_area_to_keep and/or the geometry is in a
            projected crs (not in degrees). Otherwise the/a crs should be
            passed.

    Raises:
        Exception: if the input geometry is no (multi)polygon.

    Returns:
        Union[sh_geom.Polygon, sh_geom.MultiPolygon, None]: the resulting
            (multi)polygon.
    """
    # If input geom is None, just return.
    if geometry is None:
        return None

    # Define function to treat simple polygons
    def remove_inner_rings_polygon(
        geom_poly: sh_geom.Polygon,
        min_area_to_keep: Optional[float] = None,
        crs: Optional[pyproj.CRS] = None,
    ) -> sh_geom.Polygon:
        # If all inner rings need to be removed...
        if min_area_to_keep is None or min_area_to_keep == 0.0:
            # If there are no interior rings anyway, just return input
            if len(geom_poly.interiors) == 0:
                return geom_poly
            else:
                # Else create new polygon with only the exterior ring
                return sh_ops.Polygon(geom_poly.exterior)

        # If only small rings need to be removed... loop over them
        ring_coords_to_keep = []
        small_ring_found = False
        for ring in geom_poly.interiors:
            # Calculate area
            if crs is None:
                ring_area = sh_ops.Polygon(ring).area
            elif crs.is_projected is True:
                ring_area = sh_ops.Polygon(ring).area
            else:
                geod = crs.get_geod()
                assert geod is not None
                ring_area, ring_perimeter = geod.geometry_area_perimeter(ring)

            # If ring area small, skip it, otherwise keep it
            if abs(ring_area) <= min_area_to_keep:
                small_ring_found = True
            else:
                ring_coords_to_keep.append(ring.coords)

        # If no small rings were found, just return input
        if small_ring_found is False:
            return geom_poly
        else:
            assert geom_poly.exterior is not None
            return sh_ops.Polygon(geom_poly.exterior.coords, ring_coords_to_keep)

    # If the input is a simple Polygon, apply remove on it and return.
    if isinstance(geometry, sh_geom.Polygon):
        return remove_inner_rings_polygon(geometry, min_area_to_keep, crs=crs)
    elif isinstance(geometry, sh_geom.MultiPolygon):
        # If the input is a MultiPolygon, apply remove on each Polygon in it.
        polys = []
        for poly in geometry.geoms:
            polys.append(remove_inner_rings_polygon(poly, min_area_to_keep, crs=crs))
        return sh_geom.MultiPolygon(polys)
    else:
        raise Exception(
            f"remove_inner_rings impossible on {geometry.geom_type}: {geometry}"
        )


#####################################################################
# Simplify helpers
#####################################################################


class SimplifyAlgorithm(enum.Enum):
    """
    Enumeration of the supported simplification algorythms.
    """

    RAMER_DOUGLAS_PEUCKER = "rdp"
    LANG = "lang"
    VISVALINGAM_WHYATT = "vw"


def simplify_ext(
    geometry: Optional[sh_geom.base.BaseGeometry],
    tolerance: float,
    algorithm: SimplifyAlgorithm = SimplifyAlgorithm.RAMER_DOUGLAS_PEUCKER,
    lookahead: int = 8,
    preserve_topology: bool = True,
    keep_points_on: Optional[sh_geom.base.BaseGeometry] = None,
) -> Optional[sh_geom.base.BaseGeometry]:
    """
    Simplify the geometry, with extended options.

    Args:
        geometry (shapely geometry): the geometry to simplify
        tolerance (float): mandatory for the following algorithms:
            * RAMER_DOUGLAS_PEUCKER: distance to use as tolerance
            * LANG: distance to use as tolerance
            * VISVALINGAM_WHYATT: area to use as tolerance
        algorithm (SimplifyAlgorithm, optional): algorithm to use.
            Defaults to SimplifyAlgorithm.RAMER_DOUGLAS_PEUCKER.
        lookahead (int, optional): the number of points to consider for removing
            in a moving window. Used for LANG algorithm. Defaults to 8.
        preserve_topology (bool, optional): True to (try to) return valid
            geometries as result. Defaults to True.
        keep_points_on (BaseGeometry], optional): point of the geometry to
            that intersect with these geometries are not removed. Defaults to None.

    Raises:
        Exception: [description]
        Exception: [description]
        Exception: [description]

    Returns:
        sh_geom.base.BaseGeometry: The simplified version of the geometry.
    """
    # Init:
    if geometry is None:
        return None
    if algorithm in [
        SimplifyAlgorithm.RAMER_DOUGLAS_PEUCKER,
        SimplifyAlgorithm.VISVALINGAM_WHYATT,
    ]:
        try:
            import simplification.cutil as simplification
        except ImportError as ex:
            raise ImportError(
                "To use simplify_ext using rdp or vw, first install "
                "simplification with 'pip install simplification'"
            ) from ex

    # Define some inline funtions
    # Apply the simplification (can result in multipolygons)
    def simplify_polygon(
        polygon: sh_geom.Polygon,
    ) -> Union[sh_geom.Polygon, sh_geom.MultiPolygon, None]:
        # First simplify exterior ring
        assert polygon.exterior is not None
        exterior_simplified = simplify_coords(polygon.exterior.coords)

        # If topology needs to be preserved, keep original ring if simplify results in
        # None or not enough points
        if preserve_topology is True and (
            exterior_simplified is None or len(exterior_simplified) < 3
        ):
            exterior_simplified = polygon.exterior.coords

        # Now simplify interior rings
        interiors_simplified = []
        for interior in polygon.interiors:
            interior_simplified = simplify_coords(interior.coords)

            # If simplified version is ring, add it
            if interior_simplified is not None and len(interior_simplified) >= 3:
                interiors_simplified.append(interior_simplified)
            elif preserve_topology is True:
                # If result is no ring, but topology needs to be preserved,
                # add original ring
                interiors_simplified.append(interior.coords)

        result_poly = sh_geom.Polygon(exterior_simplified, interiors_simplified)

        # Extract only polygons as result + try to make valid
        result_poly = collection_extract(
            make_valid(result_poly), primitivetype=PrimitiveType.POLYGON
        )

        # If the result is None and the topology needs to be preserved, return
        # original polygon
        if preserve_topology is True and result_poly is None:
            return polygon

        return result_poly

    def simplify_linestring(linestring: sh_geom.LineString) -> sh_geom.LineString:
        # If the linestring cannot be simplified, return it
        if linestring is None or len(linestring.coords) <= 2:
            return linestring

        # Simplify
        coords_simplified = simplify_coords(linestring.coords)

        # If preserve_topology is True and the result is no line anymore, return
        # original line
        if preserve_topology is True and (
            coords_simplified is None or len(coords_simplified) < 2
        ):
            return linestring
        else:
            return sh_geom.LineString(coords_simplified)

    def simplify_coords(
        coords: Union[np.ndarray, sh_coords.CoordinateSequence]
    ) -> np.ndarray:
        if isinstance(coords, sh_coords.CoordinateSequence):
            coords = np.asarray(coords)
        # Determine the indexes of the coordinates to keep after simplification
        if algorithm is SimplifyAlgorithm.RAMER_DOUGLAS_PEUCKER:
            coords_simplify_idx = simplification.simplify_coords_idx(coords, tolerance)
        elif algorithm is SimplifyAlgorithm.VISVALINGAM_WHYATT:
            coords_simplify_idx = simplification.simplify_coords_vw_idx(
                coords, tolerance
            )
        elif algorithm is SimplifyAlgorithm.LANG:
            coords_simplify_idx = simplify_coords_lang_idx(
                coords, tolerance, lookahead=lookahead
            )
        else:
            raise Exception(
                f"Unsupported algorithm: {algorithm}, supported: {SimplifyAlgorithm}"
            )

        coords_on_border_idx = []
        if keep_points_on is not None:
            coords_gdf = gpd.GeoDataFrame(
                geometry=list(sh_geom.MultiPoint(coords).geoms)
            )
            coords_on_border_series = coords_gdf.intersects(keep_points_on)
            coords_on_border_idx = np.array(
                coords_on_border_series.index[coords_on_border_series]
            )

        # Extracts coordinates that need to be kept
        coords_to_keep = coords_simplify_idx
        if len(coords_on_border_idx) > 0:
            coords_to_keep = np.concatenate(
                [coords_to_keep, coords_on_border_idx], dtype=np.int64
            )
        return coords[coords_to_keep]

    # Loop over the rings, and simplify them one by one...
    # If the geometry is None, just return...
    if geometry is None:
        raise Exception("geom input paramerter should not be None")
    elif isinstance(geometry, sh_geom.Point):
        # Point cannot be simplified
        return geometry
    elif isinstance(geometry, sh_geom.MultiPoint):
        # MultiPoint cannot be simplified
        return geometry
    elif isinstance(geometry, sh_geom.LineString):
        result_geom = simplify_linestring(geometry)
    elif isinstance(geometry, sh_geom.Polygon):
        result_geom = simplify_polygon(geometry)
    elif isinstance(geometry, sh_geom.base.BaseMultipartGeometry):
        # If it is a multi-part, recursively call simplify for all parts.
        simplified_geometries = []
        for geom in geometry.geoms:
            simplified_geometries.append(
                simplify_ext(
                    geom,
                    tolerance=tolerance,
                    algorithm=algorithm,
                    lookahead=lookahead,
                    preserve_topology=preserve_topology,
                    keep_points_on=keep_points_on,
                )
            )
        result_geom = collect(simplified_geometries)
    else:
        raise Exception(f"Unsupported geom_type: {geometry.geom_type}, {geometry}")

    return make_valid(result_geom)


def simplify_coords_lang(
    coords: Union[np.ndarray, list, sh_coords.CoordinateSequence],
    tolerance: float,
    lookahead: int,
) -> Union[np.ndarray, list]:
    """
    Simplify a line using lang algorithm.

    Args:
        coords (Union[np.ndarray, list]): list of coordinates to be simplified.
        tolerance (float): distance tolerance to use.
        lookahead (int, optional): the number of points to consider for removing
            in a moving window. Defaults to 8.

    Returns:
        Return the coordinates kept after simplification.
        If input coords is np.ndarray, returns np.ndarray, otherwise returns a list.
    """

    # Init variables
    if isinstance(coords, np.ndarray):
        coords_arr = coords
    elif isinstance(coords, sh_coords.CoordinateSequence):
        coords_arr = np.asarray(coords)
    else:
        coords_arr = np.array(list(coords))

    # Determine the coordinates that need to be kept
    coords_to_keep_idx = simplify_coords_lang_idx(
        coords=coords_arr, tolerance=tolerance, lookahead=lookahead
    )
    coords_simplified_arr = coords_arr[coords_to_keep_idx]

    # If input was np.ndarray, return np.ndarray, otherwise list
    if isinstance(coords, (np.ndarray, sh_coords.CoordinateSequence)):
        return coords_simplified_arr
    else:
        return coords_simplified_arr.tolist()


def simplify_coords_lang_idx(
    coords: Union[np.ndarray, list, sh_coords.CoordinateSequence],
    tolerance: float,
    lookahead: int = 8,
) -> Union[np.ndarray, list]:
    """
    Simplify a line using lang algorithm and return the coordinate indexes to
    be kept.

    Inspiration for the implementation came from:
        * https://github.com/giscan/Generalizer/blob/master/simplify.py
        * https://github.com/keszegrobert/polyline-simplification/blob/master/6.%20Lang.ipynb
        * https://web.archive.org/web/20171005193700/http://web.cs.sunyit.edu/~poissad/projects/Curve/about_algorithms/lang.php

    Args:
        coords (Union[np.ndarray, list]): list of coordinates to be simplified.
        tolerance (float): distance tolerance to use.
        lookahead (int, optional): the number of points to consider for removing
            in a moving window. Defaults to 8.

    Returns:
        Return the indexes of coordinates that need to be kept after
        simplification.
        If input coords is np.ndarray, returns np.ndarray, otherwise returns a list.
    """

    def point_line_distance(
        point_x, point_y, line_x1, line_y1, line_x2, line_y2
    ) -> float:
        denominator = math.sqrt(
            (line_x2 - line_x1) * (line_x2 - line_x1)
            + (line_y2 - line_y1) * (line_y2 - line_y1)
        )
        if denominator == 0:
            return float("Inf")
        else:
            numerator = abs(
                (line_x2 - line_x1) * (line_y1 - point_y)
                - (line_x1 - point_x) * (line_y2 - line_y1)
            )
            return numerator / denominator

    # Init variables
    if isinstance(coords, np.ndarray):
        line_arr = coords
    elif isinstance(coords, sh_coords.CoordinateSequence):
        line_arr = np.asarray(coords)
    else:
        line_arr = np.array(list(coords))

    # Prepare lookahead
    nb_points = len(line_arr)
    if lookahead == -1:
        window_size = nb_points - 1
    else:
        window_size = min(lookahead, nb_points - 1)

    # mask = np.ones(nb_points), dtype='bool')
    mask = np.zeros(nb_points, dtype="bool")
    mask[0] = True
    window_start = 0
    window_end = window_size

    # Apply simplification till the window_start arrives at the last point.
    ready = False
    while ready is False:
        # Check if all points between window_start and window_end are within
        # tolerance distance to the line (window_start, window_end).
        all_points_in_tolerance = True
        for i in range(window_start + 1, window_end):
            distance = point_line_distance(
                line_arr[i, 0],
                line_arr[i, 1],
                line_arr[window_start, 0],
                line_arr[window_start, 1],
                line_arr[window_end, 0],
                line_arr[window_end, 1],
            )
            # If distance is nan (= linepoint1 == linepoint2) or > tolerance
            if distance > tolerance:
                all_points_in_tolerance = False
                break

        # If not all the points are within the tolerance distance...
        if not all_points_in_tolerance:
            # Move window_end to previous point, and try again
            window_end -= 1
        else:
            # All points are within the tolerance, so they can be masked
            mask[window_end] = True
            # mask[window_start+1:window_end-1] = False

            # Move the window forward
            window_start = window_end
            if window_start == nb_points - 1:
                ready = True
            window_end = window_start + window_size
            if window_end >= nb_points:
                window_end = nb_points - 1

    # Prepare result: convert the mask to a list of indices of points to keep.
    idx_to_keep_arr = mask.nonzero()[0]

    # If input was np.ndarray, return np.ndarray, otherwise list
    if isinstance(coords, np.ndarray):
        return idx_to_keep_arr
    else:
        return idx_to_keep_arr.tolist()
