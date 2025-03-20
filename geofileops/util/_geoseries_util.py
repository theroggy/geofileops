"""Module containing utilities regarding operations on geoseries."""

import logging
import warnings

import geopandas as gpd
import geopandas._compat as gpd_compat
import numpy as np
import pandas as pd
import pygeoops
import shapely
from numpy.typing import NDArray
from pygeoops import GeometryType
from pygeoops._general import _extract_0dim_ndarray
from shapely.geometry.base import BaseGeometry

if hasattr(gpd_compat, "USE_PYGEOS") and gpd_compat.USE_PYGEOS:
    import pygeos as shapely2_or_pygeos
else:
    import shapely as shapely2_or_pygeos

# Get a logger...
logger = logging.getLogger(__name__)


def get_geometrytypes(
    geoseries: gpd.GeoSeries, ignore_empty_geometries: bool = True
) -> list[GeometryType]:
    """Determine the geometry types in the GeoDataFrame.

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
    """Tries to harmonize the geometries in the geoseries to one type.

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
    if hasattr(gpd_compat, "USE_PYGEOS") and gpd_compat.USE_PYGEOS:
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


def set_precision(
    geometry,
    grid_size: float,
    mode: str = "valid_output",
    raise_on_topoerror: bool = True,
) -> BaseGeometry | NDArray[BaseGeometry] | None:
    """Returns geometry with the precision set to a precision grid size.

    By default, geometries use double precision coordinates (grid_size = 0).

    Coordinates will be rounded if a precision grid is less precise than the input
    geometry. Duplicated vertices will be dropped from lines and polygons for grid sizes
    greater than 0. Line and polygon geometries may collapse to empty geometries if all
    vertices are closer together than grid_size. Z values, if present, will not be
    modified.

    Note: subsequent operations will always be performed in the precision of the
    geometry with higher precision (smaller "grid_size"). That same precision will be
    attached to the operation outputs.

    Also note: input geometries should be geometrically valid; unexpected results may
    occur if input geometries are not.

    Args:
        geometry: Geometry or array_like
        grid_size (float): Precision grid size. If 0, will use double precision (will
            not modify geometry if precision grid size was not previously set). If this
            value is more precise than input geometry, the input geometry will not be
            modified.
        mode (str, optional): This parameter determines how to handle invalid output
            geometries. There are three modes:

            1. 'valid_output' (default):  The output is always valid. Collapsed
                geometry elements  (including both polygons and lines) are removed.
                Duplicate vertices are removed.
            2. 'pointwise': Precision reduction is performed pointwise. Output geometry
                may be invalid due to collapse or self-intersection. Duplicate vertices
                are not removed. In GEOS this option is called NO_TOPO.
            3. 'keep_collapsed': Like the default mode, except that collapsed linear
                geometry elements are preserved. Collapsed polygonal input elements are
                removed. Duplicate vertices are removed.
        raise_on_topoerror (bool, optional): If False, instead of raising an error on a
            topology error, retries after applying make_valid and returns the input if
            it still fails. Defaults to True.

    Returns:
        geometry or array_like: The input with the precision applied. Returns None if
            geometry is None.
    """
    if raise_on_topoerror:
        return shapely.set_precision(geometry, grid_size=grid_size, mode=mode)

    # Don't return an error when topologyerror occurs
    try:
        return shapely.set_precision(geometry, grid_size=grid_size, mode=mode)

    except shapely.errors.GEOSException as ex:
        if not str(ex).lower().startswith("topologyexception"):  # pragma: no cover
            raise

        # If set_precision fails with TopologyException, try again after make_valid
        # Because it is applied on a GeoDataFrame with typically many rows, we don't
        # know which row is invalid, so use only_if_invalid=True.
        geometry = pygeoops.make_valid(
            geometry, keep_collapsed=False, only_if_invalid=True
        )

        # Try again now
        try:
            geometry = shapely.set_precision(geometry, grid_size=grid_size, mode=mode)
            warnings.warn(
                f"error setting grid_size, but it succeeded after makevalid: <{ex}>",
                stacklevel=1,
            )
            return geometry

        except shapely.errors.GEOSException as ex:
            if not str(ex).lower().startswith("topologyexception"):  # pragma: no cover
                raise

            # Still getting a TopologyException, so apply set_precision to each element
            # seperately and keep the input for the ones giving an error.
            # Deal with 0 dim arrays as input
            geometry = _extract_0dim_ndarray(geometry)

            # If there is only one element, just return the input
            if not hasattr(geometry, "__len__"):
                warnings.warn(
                    f"error setting grid_size, input was returned, for {geometry}, "
                    f"error: {ex}",
                    stacklevel=1,
                )
                return geometry

            # The input is arraylike... so try set_precision on each element
            result = []
            for geom in geometry:
                try:
                    result.append(
                        shapely.set_precision(geom, grid_size=grid_size, mode=mode)
                    )
                except shapely.errors.GEOSException as ex:
                    if not str(ex).lower().startswith("topologyexception"):
                        raise

                    # Just return the input
                    result.append(geom)
                    warnings.warn(
                        f"error setting grid_size, input was returned, for {geom}, "
                        f"error: {ex}",
                        stacklevel=1,
                    )

            return np.array(result)
