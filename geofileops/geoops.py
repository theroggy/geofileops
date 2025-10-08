"""Module exposing all supported operations on geometries in geofiles."""

import logging
import logging.config
import shutil
import warnings
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, Union

from pygeoops import GeometryType

from geofileops import fileops
from geofileops.helpers._configoptions_helper import ConfigOptions
from geofileops.util import (
    _geofileinfo,
    _geoops_gpd,
    _geoops_ogr,
    _geoops_sql,
    _io_util,
    _sqlite_util,
)
from geofileops.util._geometry_util import (
    BufferEndCapStyle,
    BufferJoinStyle,
    SimplifyAlgorithm,
)
from geofileops.util._geopath_util import GeoPath

if TYPE_CHECKING:  # pragma: no cover
    import os

logger = logging.getLogger(__name__)


def dissolve_within_distance(
    input_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    distance: float,
    gridsize: float,
    close_internal_gaps: bool = False,
    input_layer: str | None = None,
    output_layer: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """Dissolve geometries that are within the distance specified.

    The output layer will contain the dissolved geometries where all gaps between the
    input geometries up to ``distance`` are closed.

    Notes:
      - Only tested on polygon input.
      - Gaps between the individual polygons of multipolygon input features will also
        be closed.
      - The polygons in the output file are exploded to simple geometries.
      - No attributes from the input layer are retained.
      - If ``close_internal_gaps`` is False, the default, a ``gridsize`` > 0
        (E.g. 0.000001) should be specified, otherwise some input boundary gaps could
        still be closed due to rounding side effects.

    Alternative names:
      - ArcMap: aggregate_polygons (similar functionality)
      - Keywords: merge, dissolve, aggregate, snap, close gaps, union

    Args:
        input_path (PathLike): the input file.
        output_path (PathLike): the file to write the result to.
        distance (float): the maximum distance between geometries to be dissolved.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. If ``close_boundary_gaps`` is False, the default, a
            ``gridsize`` > 0 (E.g. 0.000001) should be specified, otherwise some
            boundary gaps in the input geometries could still be closed due to rounding
            side effects.
        close_internal_gaps (bool, optional): also close gaps, strips or holes in the
            input geometries that are narrower than the ``distance`` specified. E.g.
            small holes, narrow strips starting at the boundary,... Defaults to False.
        input_layer (str, optional): input layer name. If None, ``input_path`` should
            contain only one layer. Defaults to None.
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    See Also:
        * :func:`dissolve`: dissolve the input layer

    """
    input_path = Path(input_path)
    output_path = Path(output_path)
    if _io_util.output_exists(path=output_path, remove_if_exists=force):
        return

    start_time = datetime.now()
    operation_name = "dissolve_within_distance"
    logger = logging.getLogger(f"geofileops.{operation_name}")
    nb_steps = 9

    tempdir = _io_util.create_tempdir(f"geofileops/{operation_name}")
    try:
        # First dissolve the input.
        #
        # Note: this reduces the complexity of operations to be executed later on.
        # Note2: don't apply gridsize yet
        logger.info(f"Start, with input file {input_path}")
        step = 1
        logger.info(f"Step {step} of {nb_steps}")
        diss_path = tempdir / "100_diss.gpkg"
        _geoops_gpd.dissolve(
            input_path=input_path,
            output_path=diss_path,
            explodecollections=True,
            input_layer=input_layer,
            gridsize=0.0,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix=f"{operation_name}-",
        )

        # Positive buffer of distance / 2 to close all gaps.
        #
        # Note: no gridsize is applied to preserve all possible accuracy for these
        # temporary boundaries, otherwise the polygons are sometimes enlarged slightly,
        # which isn't wanted + creates issues when determining the
        # addedpieces_1neighbour later on.
        step += 1
        logger.info(f"Step {step} of {nb_steps}")
        bufp_path = tempdir / "110_diss_bufp.gpkg"
        _geoops_gpd.buffer(
            input_path=diss_path,
            output_path=bufp_path,
            distance=distance / 2,
            endcap_style=BufferEndCapStyle.SQUARE,
            join_style=BufferJoinStyle.MITRE,
            mitre_limit=1.25,
            gridsize=0.0,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix=f"{operation_name}-",
        )

        # Dissolve the buffered input.
        #
        # Note: no gridsize is applied to preserve all possible accuracy for these
        # temporary boundaries, otherwise the polygons are sometimes enlarged slightly,
        # which isn't wanted + creates issues when determining the
        # addedpieces_1neighbour later on.
        step += 1
        logger.info(f"Step {step} of {nb_steps}")
        buff_diss_path = tempdir / "120_diss_bufp_diss.gpkg"
        _geoops_gpd.dissolve(
            input_path=bufp_path,
            output_path=buff_diss_path,
            explodecollections=True,
            gridsize=0.0,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix=f"{operation_name}-",
        )

        # Negative buffer to get back to the borders of the input geometries
        # Use a larger mitre limit, otherwise there are a lot of small triangles that
        # don't dissappear again.
        step += 1
        logger.info(f"Step {step} of {nb_steps}")
        bufp_diss_bufm_path = tempdir / "130_diss_bufp_diss_bufm.gpkg"
        _geoops_gpd.buffer(
            input_path=buff_diss_path,
            output_path=bufp_diss_bufm_path,
            distance=-(distance / 2),
            endcap_style=BufferEndCapStyle.SQUARE,
            join_style=BufferJoinStyle.MITRE,
            mitre_limit=2,
            explodecollections=True,
            gridsize=0.0,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix=f"{operation_name}-",
        )

        # We want to keep the original boundaries as identical as possible. However,
        # when the same positive and negative buffer is applied on a polygon, even if no
        # dissolve is happening with neighbouring polygons, the result won't be exactly
        # the same as the input. Small differences will appear, e.g.:
        #   - with a "standard" buffer, internal corners will be rounded afterwards
        #   - with a "mitre" buffer the internal corners will in many cases stay the
        #     same, but for external corners where the mitre kicks in, the boundaries of
        #     the result will move slightly so the end result is smaller.
        #
        # To minimize changes to original boundaries, determine which parts are actually
        # gaps "within distance" between original features that need to be filled. Then,
        # those features can be added and dissolved into the original polygons.
        # Note: no gridsize is applied to preserve all possible accuracy for these
        # temporary boundariesstep += 1
        logger.info(f"Step {step} of {nb_steps}")
        parts_to_add_path = tempdir / "200_parts_to_add.gpkg"
        _geoops_sql.difference(
            input1_path=bufp_diss_bufm_path,
            input2_path=diss_path,
            output_path=parts_to_add_path,
            overlay_self=False,
            explodecollections=True,
            gridsize=0.0,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix=f"{operation_name}-",
        )

        # To avoid parts not being detected as touching to 2 neighbours because of
        # rounding issues, apply a small buffer to them.
        if gridsize > 0.0:
            distance_parts_to_add = gridsize / 10
        else:
            distance_parts_to_add = 0.0000000001
        step += 1
        logger.info(f"Step {step} of {nb_steps}")
        parts_to_add_bufp_path = tempdir / "200_parts_to_add_bufp.gpkg"
        bufp_path = tempdir / "110_diss_bufp.gpkg"
        _geoops_gpd.buffer(
            input_path=parts_to_add_path,
            output_path=parts_to_add_bufp_path,
            distance=distance_parts_to_add,
            endcap_style=BufferEndCapStyle.SQUARE,
            join_style=BufferJoinStyle.MITRE,
            mitre_limit=1.25,
            gridsize=0.0,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix=f"{operation_name}-",
        )

        # Build a filter to only keep the pieces that actually need to be added to the
        # input layer.
        # The filter will depend on input parameters.
        if close_internal_gaps:
            # True, so also gaps in the original input boundaries should be closed.
            # This means that in theory all pieces can be retained, but in practice
            # there are some cases where unwanted area would be added anyway, so remove
            # it from the area to be added.
            #
            # Parameters that indicate that added pieces should be added:
            #   - large areas (>= distance²) seem OK.
            #   - if > 1 neighbour, seems OK.
            #
            # For all pieces that don't comply to the above, the following parameters
            # indicate that they need to be selected to difference them:
            #   - pieces can be very narrow slivers. E.g. alongside a long boundary with
            #     a small bend, probably due to rounding side effects in the +/- buffer.
            #   - pieces can be spikes. E.g. when a "road" of ~ 'distance' width is not
            #     filled up between two input geometries has a bend. Depending on the
            #     angle, the mitre of the negative buffer can leave a spike in place.
            parts_to_add_filter = f"""
                neighbours_count_distinct > 1
                OR geom_area > {distance} * {distance}
                OR neighbours_perimeter/2 + neighbours_length > 0.8 * geom_perimeter
            """
        else:
            # False, so we only want to add yhe pieces that intersect with > 1 neighbour
            # in the input.
            parts_to_add_filter = "neighbours_count_distinct > 1"

        # Notes:
        # - The conversion to json followed by extraction from json allows to use a
        #   correlated subquery to return multiple columns. Joining the subquery gives
        #   very bad performance.
        # - Every level of nesting of SQL queries is needed to get good performance, in
        #   combination with "LIMIT -1 OFFSET 0" to avoid the subquery flattening.
        #   Flattening e.g. "geom IS NOT NULL" leads to geom operation to be calculated
        #   twice!
        input1_layer_rtree = "rtree_{input1_layer}_{input1_geometrycolumn}"
        input2_layer_rtree = "rtree_{input2_layer}_{input2_geometrycolumn}"
        sql_stmt = f"""
            WITH neighbours AS (
                SELECT layer1_sub.rowid AS layer1_rowid
                      ,layer2_sub.rowid AS layer2_rowid
                      ,ST_Intersection(
                          layer1_sub.{{input1_geometrycolumn}},
                          layer2_sub.{{input2_geometrycolumn}}
                       ) AS intersect_geom
                  FROM {{input1_databasename}}."{{input1_layer}}" layer1_sub
                  JOIN {{input1_databasename}}."{input1_layer_rtree}" layer1tree
                    ON layer1_sub.rowid = layer1tree.id
                  JOIN {{input2_databasename}}."{{input2_layer}}" layer2_sub
                  JOIN {{input2_databasename}}."{input2_layer_rtree}" layer2tree
                    ON layer2_sub.rowid = layer2tree.id
                 WHERE 1=1
                   AND layer1tree.minx <= layer2tree.maxx
                   AND layer1tree.maxx >= layer2tree.minx
                   AND layer1tree.miny <= layer2tree.maxy
                   AND layer1tree.maxy >= layer2tree.miny
                   AND ST_Intersects(
                          layer1_sub.{{input1_geometrycolumn}},
                          layer2_sub.{{input2_geometrycolumn}}) = 1
              )
            SELECT * FROM (
              SELECT geom
                    ,ST_Perimeter(geom) AS geom_perimeter
                    ,ST_Area(geom) AS geom_area
                    ,neighbours_json ->> '$.nb_distinct' AS neighbours_count_distinct
                    ,neighbours_json ->> '$.length' AS neighbours_length
                    ,neighbours_json ->> '$.perimeter' AS neighbours_perimeter
                FROM (
                  SELECT layer1.{{input1_geometrycolumn}} AS geom
                        ,( SELECT json_object(
                                    'nb_distinct', COUNT(DISTINCT layer2_rowid),
                                    'length', SUM(ST_Length(intersect_geom)),
                                    'perimeter', SUM(ST_Perimeter(intersect_geom))
                                  )
                             FROM neighbours
                            WHERE neighbours.layer1_rowid = layer1.rowid
                              AND neighbours.intersect_geom IS NOT NULL
                            GROUP BY neighbours.layer1_rowid
                            LIMIT -1 OFFSET 0
                         ) AS neighbours_json
                    FROM {{input1_databasename}}."{{input1_layer}}" layer1
                   WHERE 1=1
                     {{batch_filter}}
                   LIMIT -1 OFFSET 0
                  )
                  LIMIT -1 OFFSET 0
               )
             WHERE geom IS NOT NULL
               AND ({parts_to_add_filter})
        """

        # Note: no gridsize is applied to preserve all possible accuracy for these
        # temporary boundariesstep += 1
        step += 1
        logger.info(f"Step {step} of {nb_steps}")
        parts_to_add_filtered_path = tempdir / "210_parts_to_add_filtered.gpkg"
        _geoops_sql.select_two_layers(
            input1_path=parts_to_add_bufp_path,
            input2_path=input_path,
            output_path=parts_to_add_filtered_path,
            sql_stmt=sql_stmt,
            input2_layer=input_layer,
            explodecollections=True,
            gridsize=0.0,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix=f"{operation_name}-",
            output_with_spatial_index=False,
        )

        # Note: no gridsize is applied to preserve all possible accuracy for these
        # temporary boundariesstep += 1
        step += 1
        logger.info(f"Step {step} of {nb_steps}")
        dst_layer = fileops.get_only_layer(diss_path)
        fileops.copy_layer(
            src=parts_to_add_filtered_path,
            dst=diss_path,
            dst_layer=dst_layer,
            write_mode="append",
        )

        step += 1
        logger.info(f"Step {step} of {nb_steps}")
        # Apply gridsize for output
        _geoops_gpd.dissolve(
            input_path=diss_path,
            output_path=output_path,
            explodecollections=True,
            output_layer=output_layer,
            gridsize=gridsize,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix=f"{operation_name}-",
        )

    finally:
        if ConfigOptions.remove_temp_files:
            shutil.rmtree(tempdir, ignore_errors=True)

    logger.info(f"Ready, took {datetime.now() - start_time}")


def apply(
    input_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    func: Callable[[Any], Any],
    only_geom_input: bool = True,
    input_layer: str | None = None,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    explodecollections: bool = False,
    force_output_geometrytype: GeometryType | str | None = None,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = False,
    where_post: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """Apply a python function on the geometry column of the input file.

    The result is written to the output file specified.

    If the function you want to apply accepts an array of geometries as input, you can
    typically use :func:`apply_vectorized` instead, which is faster.

    If ``explodecollections`` is False and the input and output file type is GeoPackage,
    the fid will be preserved. In other cases this will typically not be the case.

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        func (Callable): lambda function to apply to the geometry column.
        only_geom_input (bool, optional): If True, only the geometry
            column is available. If False, the entire row is input.
            Remark: when False, the operation is 50% slower. Defaults to True.
        input_layer (str, optional): input layer name. If None, ``input_path`` should
            contain only one layer. Defaults to None.
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        columns (List[str], optional): list of columns to retain. If None, all standard
            columns are retained. In addition to standard columns, it is also possible
            to specify "fid", a unique index available in all input files. Note that the
            "fid" will be aliased eg. to "fid_1". Defaults to None.
        explodecollections (bool, optional): True to output only simple geometries.
            Defaults to False.
        force_output_geometrytype (GeometryType, optional): The output geometry type to
            force. If None, a best-effort guess is made and will always result in a
            multi-type. Defaults to None.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        keep_empty_geoms (bool, optional): True to keep rows with empty/null geometries
            in the output. Defaults to False.
        where_post (str, optional): SQL filter to apply after all other processing,
            including e.g. ``explodecollections``. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    See Also:
        * :func:`apply_vectorized`: apply a vectorized python function on the geometry
          column

    Examples:
        This example shows the basic usage of ``gfo.apply``:

        .. code-block:: python

            gfo.apply(
                input_path="input.gpkg",
                output_path="output.gpkg",
                func=lambda geom: pygeoops.remove_inner_rings(geom, min_area_to_keep=1),
            )

        If you need to use the contents of other columns in your lambda function, you can
        call ``gfo.apply`` like this:

        .. code-block:: python

            gfo.apply(
                input_path="input.gpkg",
                output_path="output.gpkg",
                func=lambda row: pygeoops.remove_inner_rings(
                    row.geometry, min_area_to_keep=row.min_area_to_keep
                ),
                only_geom_input=False,
            )


    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    logger = logging.getLogger("geofileops.apply")
    logger.info(f"Start on {input_path}")

    return _geoops_gpd.apply(
        input_path=Path(input_path),
        output_path=Path(output_path),
        func=func,
        only_geom_input=only_geom_input,
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        force_output_geometrytype=force_output_geometrytype,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def apply_vectorized(
    input_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    func: Callable[[Any], Any],
    input_layer: str | None = None,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    explodecollections: bool = False,
    force_output_geometrytype: GeometryType | str | None = None,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = False,
    where_post: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """Apply a vectorized python function on the geometry column of the input file.

    The result is written to the output file specified.

    It is not possible to use the contents of other columns in the input file in the
    python function. If you need this, use :func:`apply` instead.

    If ``explodecollections`` is False and the input and output file type is GeoPackage,
    the fid will be preserved. In other cases this will typically not be the case.

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        func (Callable): vectorized lambda function to apply to the geometry column.
            Vectorized means here that the function should accept a shapely geometry
            array as input and will return a shapely geometry for each item in the input
            array.
        input_layer (str, optional): input layer name. If None, ``input_path`` should
            contain only one layer. Defaults to None.
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        columns (List[str], optional): list of columns to retain. If None, all standard
            columns are retained. In addition to standard columns, it is also possible
            to specify "fid", a unique index available in all input files. Note that the
            "fid" will be aliased eg. to "fid_1". Defaults to None.
        explodecollections (bool, optional): True to output only simple geometries.
            Defaults to False.
        force_output_geometrytype (GeometryType, optional): The output geometry type to
            force. If None, a best-effort guess is made and will always result in a
            multi-type. Defaults to None.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        keep_empty_geoms (bool, optional): True to keep rows with empty/null geometries
            in the output. Defaults to False.
        where_post (str, optional): SQL filter to apply after all other processing,
            including e.g. ``explodecollections``. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    See Also:
        * :func:`apply`: apply a python function on the geometry column

    Examples:
        This example shows the usage of ``gfo.apply_vectorized``:

        .. code-block:: python

            gfo.apply_vectorized(
                input_path="input.gpkg",
                output_path="output.gpkg",
                func=lambda geom: pygeoops.centerline(geom, densify_distance=0),
            )


    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    logger = logging.getLogger("geofileops.apply_vectorized")
    logger.info(f"Start on {input_path}")

    return _geoops_gpd.apply_vectorized(
        input_path=Path(input_path),
        output_path=Path(output_path),
        func=func,
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        force_output_geometrytype=force_output_geometrytype,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def buffer(
    input_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    distance: float,
    quadrantsegments: int = 5,
    endcap_style: BufferEndCapStyle = BufferEndCapStyle.ROUND,
    join_style: BufferJoinStyle = BufferJoinStyle.ROUND,
    mitre_limit: float = 5.0,
    single_sided: bool = False,
    input_layer: str | None = None,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = False,
    where_post: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """Applies a buffer operation on geometry column of the input file.

    The result is written to the output file specified.

    If ``explodecollections`` is False and the input and output file type is GeoPackage,
    the fid will be preserved. In other cases this will typically not be the case.

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        distance (float): the buffer size to apply. In projected coordinate
            systems this is typically in meter, in geodetic systems this is
            typically in degrees.
        quadrantsegments (int): the number of points a quadrant needs to be
            approximated with for rounded styles. Defaults to 5.
        endcap_style (BufferEndCapStyle, optional): buffer style to use for a
            point or the end points of a line. Defaults to ROUND.

              * ROUND: for points and lines the ends are buffered rounded.
              * FLAT: a point stays a point, a buffered line will end flat
                at the end points
              * SQUARE: a point becomes a square, a buffered line will end
                flat at the end points, but elongated by ``distance``
        join_style (BufferJoinStyle, optional): buffer style to use for
            corners in a line or a polygon boundary. Defaults to ROUND.

              * ROUND: corners in the result are rounded
              * MITRE: corners in the result are sharp
              * BEVEL: are flattened
        mitre_limit (float, optional): in case of ``join_style`` MITRE, if the
            spiky result for a sharp angle becomes longer than this ratio limit, it
            is "beveled" using this maximum ratio. Defaults to 5.0.
        single_sided (bool, optional): only one side of the line is buffered,
            if distance is negative, the left side, if distance is positive,
            the right hand side. Only relevant for line geometries.
            Defaults to False.
        input_layer (str, optional): input layer name. If None, ``input_path`` should
            contain only one layer. Defaults to None.
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        columns (List[str], optional): list of columns to retain. If None, all standard
            columns are retained. In addition to standard columns, it is also possible
            to specify "fid", a unique index available in all input files. Note that the
            "fid" will be aliased eg. to "fid_1". Defaults to None.
        explodecollections (bool, optional): True to output only simple geometries.
            Defaults to False.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        keep_empty_geoms (bool, optional): True to keep rows with empty/null geometries
            in the output. Defaults to False.
        where_post (str, optional): SQL filter to apply after all other processing,
            including e.g. ``explodecollections``. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    Notes:
        Using the different buffer style option parameters you can control how the
        buffer is created:

        - **quadrantsegments** *(int)*

        .. list-table::
            :header-rows: 1

            * - 5 (default)
              - 2
              - 1
            * - |buffer_quadrantsegm_5|
              - |buffer_quadrantsegm_2|
              - |buffer_quadrantsegm_1|

        - **endcap_style** *(BufferEndCapStyle)*

        .. list-table::
            :header-rows: 1

            * - ROUND (default)
              - FLAT
              - SQUARE
            * - |buffer_endcap_round|
              - |buffer_endcap_flat|
              - |buffer_endcap_square|

        - **join_style** *(BufferJoinStyle)*

        .. list-table::
            :header-rows: 1

            * - ROUND (default)
              - MITRE
              - BEVEL
            * - |buffer_joinstyle_round|
              - |buffer_joinstyle_mitre|
              - |buffer_joinstyle_bevel|

        - **mitre** *(float)*

        .. list-table::
            :header-rows: 1

            * - 5.0 (default)
              - 2.5
              - 1.0
            * - |buffer_mitre_50|
              - |buffer_mitre_25|
              - |buffer_mitre_10|


    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite</a>

    .. |buffer_quadrantsegm_5| image:: ../_static/images/buffer_quadrantsegments_5.png
        :alt: Buffer with quadrantsegments=5
    .. |buffer_quadrantsegm_2| image:: ../_static/images/buffer_quadrantsegments_2.png
        :alt: Buffer with quadrantsegments=2
    .. |buffer_quadrantsegm_1| image:: ../_static/images/buffer_quadrantsegments_1.png
        :alt: Buffer with quadrantsegments=1
    .. |buffer_endcap_round| image:: ../_static/images/buffer_endcap_round.png
        :alt: Buffer with endcap_style=BufferEndCapStyle.ROUND (default)
    .. |buffer_endcap_flat| image:: ../_static/images/buffer_endcap_flat.png
        :alt: Buffer with endcap_style=BufferEndCapStyle.FLAT
    .. |buffer_endcap_square| image:: ../_static/images/buffer_endcap_square.png
        :alt: Buffer with endcap_style=BufferEndCapStyle.SQUARE
    .. |buffer_joinstyle_round| image:: ../_static/images/buffer_joinstyle_round.png
        :alt: Buffer with joinstyle=BufferJoinStyle.ROUND (default)
    .. |buffer_joinstyle_mitre| image:: ../_static/images/buffer_joinstyle_mitre.png
        :alt: Buffer with joinstyle=BufferJoinStyle.MITRE
    .. |buffer_joinstyle_bevel| image:: ../_static/images/buffer_joinstyle_bevel.png
        :alt: Buffer with joinstyle=BufferJoinStyle.BEVEL
    .. |buffer_mitre_50| image:: ../_static/images/buffer_mitre_50.png
        :alt: Buffer with mitre=5.0
    .. |buffer_mitre_25| image:: ../_static/images/buffer_mitre_25.png
        :alt: Buffer with mitre=2.5
    .. |buffer_mitre_10| image:: ../_static/images/buffer_mitre_10.png
        :alt: Buffer with mitre=1.0

    """  # noqa: E501
    logger = logging.getLogger("geofileops.buffer")
    logger.info(
        f"Start, on {input_path} "
        f"(distance: {distance}, quadrantsegments: {quadrantsegments})"
    )

    if (
        endcap_style == BufferEndCapStyle.ROUND
        and join_style == BufferJoinStyle.ROUND
        and single_sided is False
    ):
        # If default buffer options for spatialite, use the faster SQL version
        return _geoops_sql.buffer(
            input_path=Path(input_path),
            output_path=Path(output_path),
            distance=distance,
            quadrantsegments=quadrantsegments,
            input_layer=input_layer,
            output_layer=output_layer,
            columns=columns,
            explodecollections=explodecollections,
            gridsize=gridsize,
            keep_empty_geoms=keep_empty_geoms,
            where_post=where_post,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            force=force,
        )
    else:
        # If special buffer options, use geopandas version
        return _geoops_gpd.buffer(
            input_path=Path(input_path),
            output_path=Path(output_path),
            distance=distance,
            quadrantsegments=quadrantsegments,
            endcap_style=endcap_style,
            join_style=join_style,
            mitre_limit=mitre_limit,
            single_sided=single_sided,
            input_layer=input_layer,
            output_layer=output_layer,
            columns=columns,
            explodecollections=explodecollections,
            gridsize=gridsize,
            keep_empty_geoms=keep_empty_geoms,
            where_post=where_post,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            force=force,
        )


def clip_by_geometry(
    input_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    clip_geometry: tuple[float, float, float, float] | str,
    input_layer: str | None = None,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    explodecollections: bool = False,
    force: bool = False,
):
    """Clip all geometries in the input file by the geometry provided.

    If ``explodecollections`` is False and the input and output file type is GeoPackage,
    the fid will be preserved. In other cases this will typically not be the case.

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        clip_geometry (Union[Tuple[float, float, float, float], str]): the bounds
            or WKT geometry to clip with.
        input_layer (str, optional): input layer name. If None, ``input_path`` should
            contain only one layer. Defaults to None.
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        columns (List[str], optional): list of columns to retain. If None, all standard
            columns are retained. In addition to standard columns, it is also possible
            to specify "fid", a unique index available in all input files. Note that the
            "fid" will be aliased eg. to "fid_1". Defaults to None.
        explodecollections (bool, optional): True to output only simple geometries.
            Defaults to False.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    See Also:
        * :func:`clip`: clip geometries by the features in another layer

    """
    logger = logging.getLogger("geofileops.clip_by_geometry")
    logger.info(f"Start, on {input_path}")
    return _geoops_ogr.clip_by_geometry(
        input_path=Path(input_path),
        output_path=Path(output_path),
        clip_geometry=clip_geometry,
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        force=force,
    )


def convexhull(
    input_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    input_layer: str | None = None,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = False,
    where_post: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """Applies a convexhull operation on the input file.

    The result is written to the output file specified.

    If ``explodecollections`` is False and the input and output file type is GeoPackage,
    the fid will be preserved. In other cases this will typically not be the case.

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        input_layer (str, optional): input layer name. If None, ``input_path`` should
            contain only one layer. Defaults to None.
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        columns (List[str], optional): list of columns to retain. If None, all standard
            columns are retained. In addition to standard columns, it is also possible
            to specify "fid", a unique index available in all input files. Note that the
            "fid" will be aliased eg. to "fid_1". Defaults to None.
        explodecollections (bool, optional): True to output only simple geometries.
            Defaults to False.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        keep_empty_geoms (bool, optional): True to keep rows with empty/null geometries
            in the output. Defaults to False.
        where_post (str, optional): SQL filter to apply after all other processing,
            including e.g. ``explodecollections``. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    logger = logging.getLogger("geofileops.convexhull")
    logger.info(f"Start, on {input_path}")

    return _geoops_sql.convexhull(
        input_path=Path(input_path),
        output_path=Path(output_path),
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def delete_duplicate_geometries(
    input_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    input_layer: str | None = None,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    priority_column: str | None = None,
    priority_ascending: bool = True,
    explodecollections: bool = False,
    keep_empty_geoms: bool = False,
    where_post: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """Copy all rows to the output file, except for duplicate geometries.

    The check for duplicates is done using ``ST_Equals``. ``ST_Equals`` is ``True`` if`
    the given geometries are "topologically equal". This means that the geometries have
    the same dimension and their point-sets occupy the same space. This means e.g. that
    the order of vertices may be different, starting points of rings can be different
    and polygons can contain extra points if they don't change the surface occupied.

    If a ``priority_column`` is specified, the row with the lowest value in this column
    is retained. If ``priority_ascending`` is False, the row with the highest value is
    retained.

    If ``explodecollections`` is False and the input and output file type is GeoPackage,
    the fid will be preserved. In other cases this will typically not be the case.

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        input_layer (str, optional): input layer name. If None, ``input_path`` should
            contain only one layer. Defaults to None.
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        columns (List[str], optional): list of columns to retain. If None, all standard
            columns are retained. In addition to standard columns, it is also possible
            to specify "fid", a unique index available in all input files. Note that the
            "fid" will be aliased eg. to "fid_1". Defaults to None.
        priority_column (str, optional): column to use as priority for keeping rows.
            Defaults to None.
        priority_ascending (bool, optional): True to keep the row with the lowest
            priority value. Defaults to True.
        explodecollections (bool, optional): True to output only simple geometries.
            Defaults to False.
        keep_empty_geoms (bool, optional): True to keep rows with empty/null geometries
            in the output. Defaults to False.
        where_post (str, optional): SQL filter to apply after all other processing,
            including e.g. ``explodecollections``. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    logger = logging.getLogger("geofileops.delete_duplicate_geometries")
    logger.info(f"Start, on {input_path}")

    return _geoops_sql.delete_duplicate_geometries(
        input_path=Path(input_path),
        output_path=Path(output_path),
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        priority_column=priority_column,
        priority_ascending=priority_ascending,
        explodecollections=explodecollections,
        keep_empty_geoms=keep_empty_geoms,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def dissolve(
    input_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    explodecollections: bool,
    groupby_columns: list[str] | str | None = None,
    agg_columns: dict | None = None,
    tiles_path: Union[str, "os.PathLike[Any]", None] = None,
    nb_squarish_tiles: int = 1,
    input_layer: str | None = None,
    output_layer: str | None = None,
    gridsize: float = 0.0,
    where_post: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """Applies a dissolve operation on the input file.

    If columns are specified with ``groupby_columns``, the data is first grouped
    on those columns before the geometries are merged.

    Data in other columns can be retained in the output by specifying the
    ``agg_columns`` parameter.

    Because the input layer is tiled using a grid to speed up, extra collinear points
    will typically be present in the output geometries. Rows with null or empty
    geometries are ignored.

    This is an example of how data in the columns that isn't grouped on can be
    aggregated to be added to the output file:

    .. code-block:: python

        gfo.dissolve(
            input_path="input.gpkg",
            output_path="output.gpkg",
            groupby_columns=["cropgroup"],
            agg_columns={
                "columns": [
                    {"column": "crop", "agg": "max", "as": "crop_max"},
                    {"column": "crop", "agg": "count", "as": "crop_count"},
                    {
                        "column": "crop",
                        "agg": "concat",
                        "as": "crop_concat",
                        "distinct": True,
                        "sep": ";",
                    },
                    {"column": "area", "agg": "mean", "as": "area_mean"},
                ]
            },
            explodecollections=False,
        )

    The following example will save all detailed data for the columns
    "crop_label" and "area" in the output file. The detailed data is encoded
    per group/row in a "json" text field. Shapefiles only support up to 254
    characters in a text field, so this format won't be very suited as output
    format for this option.

    .. code-block:: python

        gfo.dissolve(
            input_path="input.gpkg",
            output_path="output.gpkg",
            groupby_columns=["cropgroup"],
            agg_columns={"json": ["crop", "area"]},
            explodecollections=False,
        )

    This results in this type of output:
    ::

        cropgroup  json
        Grasses    ["{"crop":"Meadow","area":1290,"fid_orig":5}","{"crop":"Pasture",...
        Maize      ["{"crop":"Silo","area":3889.29,"fid_orig":2}","{"crop":"Fodder",...

    If the output is tiled (by specifying ``tiles_path`` or ``nb_squarish_tiles`` > 1),
    the result will be clipped on the output tiles and the tile borders are
    never crossed.

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        explodecollections (bool): True to output only simple geometries. If
            False, this can result in huge geometries for large files,
            especially if no ``groupby_columns`` are specified.
        groupby_columns (list[str] or str, optional): columns (case insensitive) to
            group on while aggregating. Defaults to None, resulting in a spatial union
            of all geometries that touch.
        agg_columns (dict, optional): columns to aggregate based on
            the groupings by groupby columns. Depending on the top-level key
            value of the dict, the output for the aggregation is different:

                - "json": dump all data per group to one "json" column. The
                  value can be None (= all columns) or a list of columns to include.
                - "columns": aggregate to seperate columns. The value should
                  be a list of dicts with the following keys:

                    - "column": column name (case insensitive) in the input file. In
                      addition to standard columns, it is also possible to specify
                      "fid", a unique index available in all input files.
                    - "agg": aggregation to use:

                        - count: the number of values in the group
                        - sum: the sum of the values in the group
                        - mean: the mean/average of the values in the group
                        - min: the minimum value in the group
                        - max: the maximum value in the group
                        - median: the median value in the group
                        - concat: all non-null values in the group concatenated (in
                          arbitrary order)

                    - "as": column name in the output file. Note: using "fid" as alias
                      is not recommended: it can cause errors or odd behaviour.
                    - "distinct" (optional): True to distinct the values before
                      aggregation.
                    - "sep" (optional): the separator to use for concat. Default: ",".

        tiles_path (PathLike, optional): a path to a geofile containing tiles.
            If specified, the output will be dissolved/unioned only within the
            tiles provided.
            Can be used to avoid huge geometries being created if the input
            geometries are very interconnected.
            Defaults to None (= the output is not tiled).
        nb_squarish_tiles (int, optional): the approximate number of tiles the
            output should be dissolved/unioned to. If > 1, a tiling grid is
            automatically created based on the total bounds of the input file.
            The input geometries will be dissolved/unioned only within the
            tiles generated.
            Can be used to avoid huge geometries being created if the input
            geometries are very interconnected.
            Defaults to 1 (= the output is not tiled).
        input_layer (str, optional): input layer name. If None, ``input_path`` should
            contain only one layer. Defaults to None.
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): SQL filter to apply after all other processing,
            including e.g. ``explodecollections``. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    See Also:
        * :func:`dissolve_within_distance`: dissolve all feature within the distance
          specified of each other


    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    # Init
    if tiles_path is not None:
        tiles_path = Path(tiles_path)

    logger = logging.getLogger("geofileops.dissolve")
    logger.info(f"Start, on {input_path} to {output_path}")
    return _geoops_gpd.dissolve(
        input_path=Path(input_path),
        output_path=Path(output_path),
        explodecollections=explodecollections,
        groupby_columns=groupby_columns,
        agg_columns=agg_columns,
        tiles_path=tiles_path,
        nb_squarish_tiles=nb_squarish_tiles,
        input_layer=input_layer,
        output_layer=output_layer,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def export_by_bounds(
    input_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    bounds: tuple[float, float, float, float],
    input_layer: str | None = None,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    explodecollections: bool = False,
    force: bool = False,
):
    """Export the rows that intersect with the bounds specified.

    If ``explodecollections`` is False and the input and output file type is GeoPackage,
    the fid will be preserved. In other cases this will typically not be the case.

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        bounds (Tuple[float, float, float, float]): the bounds to filter on.
        input_layer (str, optional): input layer name. If None, ``input_path`` should
            contain only one layer. Defaults to None.
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        columns (List[str], optional): list of columns to retain. If None, all standard
            columns are retained. In addition to standard columns, it is also possible
            to specify "fid", a unique index available in all input files. Note that the
            "fid" will be aliased eg. to "fid_1". Defaults to None.
        explodecollections (bool, optional): True to output only simple geometries.
            Defaults to False.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    See Also:
        * :func:`export_by_distance`: export features that are within a certain distance
          of features of another layer
        * :func:`export_by_location`: export features that e.g. intersect with features
          of another layer

    """
    logger = logging.getLogger("geofileops.export_by_bounds")
    logger.info(f"Start, on {input_path}")
    return _geoops_ogr.export_by_bounds(
        input_path=Path(input_path),
        output_path=Path(output_path),
        bounds=bounds,
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        force=force,
    )


def isvalid(
    input_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]", None] = None,
    only_invalid: bool = True,
    input_layer: str | None = None,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    explodecollections: bool = False,
    validate_attribute_data: bool = False,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
) -> bool:
    """Checks for all geometries in the geofile if they are valid.

    The results are written to the output file.

    If ``explodecollections`` is False and the input and output file type is GeoPackage,
    the fid will be preserved. In other cases this will typically not be the case.

    Args:
        input_path (PathLike): The input file.
        output_path (PathLike, optional): The output file path. If not
            specified the result will be written in a new file alongside the
            input file. Defaults to None.
        only_invalid (bool, optional): if True, only put invalid results in the
            output file. Deprecated: always treated as True.
        input_layer (str, optional): input layer name. If None, ``input_path`` should
            contain only one layer. Defaults to None.
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        columns (List[str], optional): list of columns to retain. If None, all standard
            columns are retained. In addition to standard columns, it is also possible
            to specify "fid", a unique index available in all input files. Note that the
            "fid" will be aliased eg. to "fid_1". Defaults to None.
        explodecollections (bool, optional): True to output only simple geometries.
            Defaults to False.
        validate_attribute_data (bool, optional): True to validate if all attribute data
            can be read. Defaults to False.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    Returns:
        bool: True if all geometries were valid.

    See Also:
        * :func:`make_valid`: make the geometries in the input layer valid

    """
    # Check parameters
    input_path = Path(input_path)
    if output_path is not None:
        output_path = Path(output_path)
    else:
        input_geopath = GeoPath(input_path)
        output_path = input_geopath.with_stem(f"{input_geopath.stem}_isvalid")

    # Go!
    logger = logging.getLogger("geofileops.isvalid")
    logger.info(f"Start, on {input_path}")
    return _geoops_sql.isvalid(
        input_path=input_path,
        output_path=output_path,
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        validate_attribute_data=validate_attribute_data,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def makevalid(
    input_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    input_layer: str | None = None,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    explodecollections: bool = False,
    force_output_geometrytype: str | None | GeometryType = None,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = False,
    where_post: str | None = None,
    precision: float | None = None,
    validate_attribute_data: bool = False,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """Makes all geometries in the input file valid.

    Writes the result to the output path.

    Alternative names:
        - QGIS: fix geometries
        - shapely, geopandas: make_valid

    If ``explodecollections`` is False and the input and output file type is GeoPackage,
    the fid will be preserved. In other cases this will typically not be the case.

    Args:
        input_path (PathLike): The input file.
        output_path (PathLike): The file to write the result to.
        input_layer (str, optional): input layer name. If None, ``input_path`` should
            contain only one layer. Defaults to None.
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        columns (List[str], optional): list of columns to retain. If None, all standard
            columns are retained. In addition to standard columns, it is also possible
            to specify "fid", a unique index available in all input files. Note that the
            "fid" will be aliased eg. to "fid_1". Defaults to None.
        explodecollections (bool, optional): True to output only simple geometries.
            Defaults to False.
        force_output_geometrytype (GeometryType, optional): The output geometry type to
            force the output to. If None, the geometry type of the input is retained.
            Defaults to None.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        precision (float, optional): deprecated. Use ``gridsize``.
        keep_empty_geoms (bool, optional): True to keep rows with empty/null geometries
            in the output. Defaults to False.
        where_post (str, optional): SQL filter to apply after all other processing,
            including e.g. ``explodecollections``. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        validate_attribute_data (bool, optional): True to validate if all attribute data
            can be read. Raises an exception if an error is found, as this type of error
            cannot be fixed using makevalid. Defaults to False.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    See Also:
        * :func:`isvalid`: check if the geometries in the input layer are valid

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    logger = logging.getLogger("geofileops.makevalid")
    logger.info(f"Start, on {input_path}")
    input_path = Path(input_path)
    output_path = Path(output_path)

    if gridsize is None:
        gridsize = 0.0
    if precision is not None and gridsize != 0.0:
        raise ValueError(
            "the precision parameter is deprecated and cannot be combined with gridsize"
        )
    if precision is not None:
        gridsize = precision
        warnings.warn(
            "the precision parameter is deprecated and will be removed in a future "
            "version: please use gridsize",
            FutureWarning,
            stacklevel=2,
        )

    if gridsize == 0.0:
        # If spatialite >= 5.1 available use faster/less memory using SQL implementation
        # Only use this version if gridsize is 0.0, because when gridsize applied it is
        # less robust than the gpd implementation.
        _geoops_sql.makevalid(
            input_path=input_path,
            output_path=output_path,
            input_layer=input_layer,
            output_layer=output_layer,
            columns=columns,
            explodecollections=explodecollections,
            force_output_geometrytype=force_output_geometrytype,
            gridsize=gridsize,
            keep_empty_geoms=keep_empty_geoms,
            where_post=where_post,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            force=force,
        )
    else:
        _geoops_gpd.makevalid(
            input_path=input_path,
            output_path=output_path,
            input_layer=input_layer,
            output_layer=output_layer,
            columns=columns,
            explodecollections=explodecollections,
            force_output_geometrytype=force_output_geometrytype,
            gridsize=gridsize,
            keep_empty_geoms=keep_empty_geoms,
            where_post=where_post,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            force=force,
        )

    # If asked and output is spatialite based, check if all data can be read
    if validate_attribute_data:
        output_geofileinfo = _geofileinfo.get_geofileinfo(input_path)
        if input_path.suffix != ".zip" and output_geofileinfo.is_spatialite_based:
            _sqlite_util.test_data_integrity(path=input_path)


def warp(
    input_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    gcps: list[tuple[float, float, float, float, float | None]],
    algorithm: str = "polynomial",
    order: int | None = None,
    input_layer: str | None = None,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    explodecollections: bool = False,
    force: bool = False,
):
    """Warp all input features to the output file according to the gcps specified.

    Alternative names:
        - rubbersheet, rubbersheeting

    Args:
        input_path (PathLike): The input file.
        output_path (PathLike): The file to write the result to.
        gcps (List[Tuple[float, float, float, float]]): ground control points to
            use to warp the input geometries. This is a list of tuples like this:
            [(x_orig, y_orig, x_dest, y_dest, elevation), ...].
        algorithm (str, optional): algorithm to use to warp:
            - "polynomial": use a polynomial transformation
            - "tps": use a thin plate spline transformer
            Defaults to "polynomial".
        order (int, optional): if algorithm is "polynomial", the order of the
            polynomial to use for warping.
        input_layer (str, optional): input layer name. If None, ``input_path`` should
            contain only one layer. Defaults to None.
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        columns (List[str], optional): list of columns to retain. If None, all standard
            columns are retained. In addition to standard columns, it is also possible
            to specify "fid", a unique index available in all input files. Note that the
            "fid" will be aliased eg. to "fid_1". Defaults to None.
        explodecollections (bool, optional): True to output only simple geometries.
            Defaults to False.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.
    """
    logger = logging.getLogger("geofileops.warp")
    logger.info(f"Start, on {input_path}")
    _geoops_ogr.warp(
        input_path=Path(input_path),
        output_path=Path(output_path),
        gcps=gcps,
        algorithm=algorithm,
        order=order,
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        force=force,
    )


def select(
    input_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    sql_stmt: str,
    sql_dialect: Literal["SQLITE", "OGRSQL"] | None = "SQLITE",
    input_layer: str | None = None,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    explodecollections: bool = False,
    force_output_geometrytype: GeometryType | str | None = None,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = True,
    nb_parallel: int = 1,
    batchsize: int = -1,
    force: bool = False,
):
    '''Execute a SELECT SQL statement on the input file.

    The ``sql_stmt`` must be in SQLite dialect and can contain placeholders that will be
    replaced automatically. More details can be found in the notes and examples below.

    The result is written to the output file specified.

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        sql_stmt (str): the SELECT SQL statement to execute
        sql_dialect (str, optional): the SQL dialect to use. If None, the default SQL
            dialect of the underlying source is used. Defaults to "SQLITE".
        input_layer (str, optional): input layer name. If None, ``input_path`` should
            contain only one layer. Defaults to None.
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        columns (List[str], optional): list of columns to retain, if
            {columns_to_select_str} is used. If None, all standard
            columns are retained. In addition to standard columns, it is also possible
            to specify "fid", a unique index available in all input files. Note that the
            "fid" will be aliased eg. to "fid_1". Defaults to None.
        explodecollections (bool, optional): True to convert all multi-geometries to
            singular ones. Defaults to False.
        force_output_geometrytype (GeometryType, optional): The output geometry type to
            force. Defaults to None, and then the geometry type of the input is used
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        keep_empty_geoms (bool, optional): True to keep rows with empty/null geometries
            in the output. Defaults to True.
        nb_parallel (int, optional): the number of parallel processes to use. If -1, all
            available cores are used. Defaults to 1.
            If ``nb_parallel`` != 1, make sure your query still returns correct results
            if it is executed per batch of rows instead of in one go on the entire
            layer.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage. If batchsize != -1,
            make sure your query still returns correct results if it is executed per
            batch of rows instead of in one go on the entire layer.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s). Defaults to False.

    See Also:
        * :func:`select_two_layers`: select features using two input layers based on a
          SQL query

    Notes:
        By convention, the sqlite query can contain following placeholders that
        will be automatically replaced for you:

        * {geometrycolumn}: the column where the primary geometry is stored.
        * {columns_to_select_str}: if ``columns`` is not None, those columns, otherwise
          all columns of the layer.
        * {input_layer}: the layer name of the input layer.
        * {batch_filter}: the filter used to process in parallel per batch.

        Hint: often you will want to use f"" formatting on the SQL statement to fill out
        some parameters of your own as well. You can easily escape the placeholders
        above by doubling the "{" and "}", e.g. use {{geometrycolumn}} for
        {geometrycolumn}. Also check out the example below.

        Example: buffer all rows with a certain minimum area to the output file.

        .. code-block:: python

            minimum_area = 100
            sql_stmt = f"""
                SELECT ST_Buffer({{geometrycolumn}}, 1) AS {{geometrycolumn}}
                      {{columns_to_select_str}}
                  FROM "{{input_layer}}" layer
                 WHERE 1=1
                   {{batch_filter}}
                   AND ST_Area({{geometrycolumn}}) > {minimum_area}
            """
            gfo.select(
                input_path="input.gpkg",
                output_path="output.gpkg",
                sql_stmt=sql_stmt,
            )

        Some important remarks:

        * Because some SQL statements won't give the same result when parallelized
          (eg. when using a group by statement), ``nb_parallel`` is 1 by default.
          If you do want to use parallel processing, specify ``nb_parallel`` + make
          sure to include the placeholder {batch_filter} in your ``sql_stmt``.
          This placeholder will be replaced with a filter of the form
          "AND rowid >= x AND rowid < y".
        * The name of the geometry column depends on the file format of the input file.
          E.g. for .shp files the column will be called "geometry", for .gpkg files the
          default name is "geom". If you use the {geometrycolumn} placeholder,
          geofileops will replace it with the correct column name for the input file.
        * If you apply (spatialite) functions on the geometry column always alias them
          again to its original column name, e.g. with "AS {geometrycolumn}".
        * Some SQL statements won't give correct results when parallelized/ran in
          multiple batches, e.g. when using a group by statement. This is why the
          default value for nb_parallel is 1. If you want to parallelize or run the
          query in multiple batches (by specifying ``nb_parallel`` != 1 or ``batchsize``
          > 0), you should make sure your query will give correct results if it is
          executed per batch of rows instead of once on the entire layer.
          Additionally, if you do so, make sure to include the placeholder
          {batch_filter} in your ``sql_stmt``. This placeholder will be replaced with a
          filter of the form "AND rowid >= x AND rowid < y" and will ensure every row is
          only treated once.
        * Table names are best double quoted as in the example, because some
          characters are otherwise not supported in the table name, eg. '-'.
        * It is recommend to give the table you select from "layer" as alias. If
          you use the {batch_filter} placeholder this is even mandatory.
        * When using the (default) "SQLITE" SQL dialect, you can also use the spatialite
          functions as documented here: |spatialite_reference_link|.
        * It is supported to use an attribute table (= table without geometry column) as
          input layer and/or not to include the geometry column in the selected columns.
          Note though that if the {columns_to_select_str} placeholder is used, it will
          start with a "," and if no column precedes it the SQL statement will be
          invalid.


    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    '''  # noqa: E501
    logger = logging.getLogger("geofileops.select")
    logger.info(f"Start, on {input_path}")

    # Convert force_output_geometrytype to GeometryType (if necessary)
    if force_output_geometrytype is not None:
        force_output_geometrytype = GeometryType(force_output_geometrytype)

    return _geoops_sql.select(
        input_path=Path(input_path),
        output_path=Path(output_path),
        sql_stmt=sql_stmt,
        sql_dialect=sql_dialect,
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        force_output_geometrytype=force_output_geometrytype,
        keep_empty_geoms=keep_empty_geoms,
        gridsize=gridsize,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def simplify(
    input_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    tolerance: float,
    algorithm: str | SimplifyAlgorithm = "rdp",
    lookahead: int = 8,
    input_layer: str | None = None,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = False,
    where_post: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """Applies a simplify operation on geometry column of the input file.

    The result is written to the output file specified.

    Several `algorithm`s are available.

    If ``explodecollections`` is False and the input and output file type is GeoPackage,
    the fid will be preserved. In other cases this will typically not be the case.

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        tolerance (float): tolerance to use for the simplification. Depends on the
            ``algorithm`` specified.
            In projected coordinate systems this tolerance will typically be
            in meter, in geodetic systems this is typically in degrees.
        algorithm (str, optional): algorithm to use. Defaults to "rdp".

                * **"rdp"**: Ramer Douglas Peucker: tolerance is a distance
                * **"lang"**: Lang: tolerance is a distance
                * **"lang+"**: Lang, with extensions to increase number of points reduced.
                * **"vw"**: Visvalingam Whyatt: tolerance is an area.

        lookahead (int, optional): used for Lang algorithms. Defaults to 8.
        input_layer (str, optional): input layer name. If None, ``input_path`` should
            contain only one layer. Defaults to None.
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        columns (List[str], optional): list of columns to retain. If None, all standard
            columns are retained. In addition to standard columns, it is also possible
            to specify "fid", a unique index available in all input files. Note that the
            "fid" will be aliased eg. to "fid_1". Defaults to None.
        explodecollections (bool, optional): True to output only simple geometries.
            Defaults to False.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        keep_empty_geoms (bool, optional): True to keep rows with empty/null geometries
            in the output. Defaults to False.
        where_post (str, optional): SQL filter to apply after all other processing,
            including e.g. ``explodecollections``. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    logger = logging.getLogger("geofileops.simplify")
    logger.info(f"Start, on {input_path} with tolerance {tolerance}")
    if isinstance(algorithm, str):
        algorithm = SimplifyAlgorithm(algorithm)

    if algorithm == SimplifyAlgorithm.RAMER_DOUGLAS_PEUCKER:
        return _geoops_sql.simplify(
            input_path=Path(input_path),
            output_path=Path(output_path),
            tolerance=tolerance,
            input_layer=input_layer,
            output_layer=output_layer,
            columns=columns,
            explodecollections=explodecollections,
            gridsize=gridsize,
            keep_empty_geoms=keep_empty_geoms,
            where_post=where_post,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            force=force,
        )
    else:
        return _geoops_gpd.simplify(
            input_path=Path(input_path),
            output_path=Path(output_path),
            tolerance=tolerance,
            algorithm=algorithm,
            lookahead=lookahead,
            input_layer=input_layer,
            output_layer=output_layer,
            columns=columns,
            explodecollections=explodecollections,
            gridsize=gridsize,
            keep_empty_geoms=keep_empty_geoms,
            where_post=where_post,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            force=force,
        )


# -----------------------------
# Operations on multiple layers
# -----------------------------


def clip(
    input_path: Union[str, "os.PathLike[Any]"],
    clip_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    input_layer: str | None = None,
    input_columns: list[str] | None = None,
    clip_layer: str | None = None,
    output_layer: str | None = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 15000,
    force: bool = False,
):
    """Clip the input layer with the clip layer.

    The resulting layer will contain the parts of the geometries in the
    input layer that overlap with the dissolved geometries in the clip layer.

    Notes:
        - every row in the input layer will result in maximum one row in the
          output layer.
        - geometries in the input layer that overlap with multiple adjacent
          geometries in the clip layer won't result in the input geometries
          getting split.
        - To speed up processing, complex clip geometries are subdivided by default.
          In this case, the output geometries can contain extra collinear points where
          the subdividing occured. This behaviour can be controlled via the
          ``subdivide_coords`` parameter.

    This is the result you can expect when clipping a polygon layer (yellow)
    with another polygon layer (purple):

    .. list-table::
       :header-rows: 1

       * - Input
         - Clip result
       * - |clip_input|
         - |clip_result|

    Args:
        input_path (PathLike): The file to clip.
        clip_path (PathLike): The file with the geometries to clip with.
        output_path (PathLike): the file to write the result to
        input_layer (str, optional): input layer name. If None, ``input_path`` should
            contain only one layer. Defaults to None.
        input_columns (List[str], optional): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased eg. to "fid_1". Defaults to None.
        clip_layer (str, optional): clip layer name. If None, ``clip_path`` should
            contain only one layer. Defaults to None.
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        explodecollections (bool, optional): True to convert all multi-geometries to
            singular ones after the dissolve. Defaults to False.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): SQL filter to apply after all other processing,
            including e.g. ``explodecollections``. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        subdivide_coords (int, optional): the input geometries will be subdivided to
            parts with about ``subdivide_coords`` coordinates during processing which
            can offer a large speed up for complex geometries. Subdividing can result in
            extra collinear points being added to the boundaries of the output. If 0, no
            subdividing is applied. Defaults to 15000.
        force (bool, optional): True to overwrite existing output file(s).
            Defaults to False.

    See Also:
        * :func:`clip_by_geometry`: clip the input layer by a geometry specified

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    .. |clip_input| image:: ../_static/images/clip_input.png
        :alt: Clip input
    .. |clip_result| image:: ../_static/images/clip_result.png
        :alt: Clip result
    """  # noqa: E501
    logger = logging.getLogger("geofileops.clip")
    logger.info(f"Start on {input_path} with {clip_path} to {output_path}")
    return _geoops_sql.clip(
        input_path=Path(input_path),
        clip_path=Path(clip_path),
        output_path=Path(output_path),
        input_layer=input_layer,
        input_columns=input_columns,
        clip_layer=clip_layer,
        output_layer=output_layer,
        explodecollections=explodecollections,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        subdivide_coords=subdivide_coords,
        force=force,
    )


def concat(
    input_paths: list[Union[str, "os.PathLike[Any]"]],
    output_path: Union[str, "os.PathLike[Any]"],
    input_layers: list[str | None] | str | None = None,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    explodecollections: bool = False,
    create_spatial_index: bool | None = None,
    force: bool = False,
):
    """Concatenate multiple geofiles into one output geofile.

    The input files will be appended one after the other in the output file, so only
    output file types that support appending are supported.

    By default, all columns in any of the input files are retained. If columns are not
    present in some input files, the values of these columns will be NULL for those
    rows. If you want to retain only a subset of the columns, specify these in the
    ``columns`` parameter.

    Args:
        input_paths (list[PathLike]): the paths to the files to concatenate.
        output_path (PathLike): the path to the output file.
        input_layers (list[str | None] | str, optional): the layer names to use in the
            input files. The layer names can be None for input files that only contain a
            single layer. If a single value is specified, this value is used for all
            input files. Defaults to None.
        output_layer (str, optional): the layer name to use in the output file. If not
            specified, the default layer name is used. Defaults to None.
        columns (list[str], optional): the columns to keep in the output file.
            If None, all columns present in the first input file are retained.
            Defaults to None.
        explodecollections (bool, optional): True to explode geometry collections
            into separate features. Defaults to False.
        create_spatial_index (bool, optional): True to create a spatial index on the
            output file/layer. If None, the default behaviour by gdal for that file
            type is respected. Defaults to None.
        force (bool, optional): True to overwrite the output file if it already exists.
    """
    # Validate + cleanup input parameters
    logger = logging.getLogger("geofileops.concat")
    if input_layers is None or isinstance(input_layers, str):
        input_layers = [input_layers] * len(input_paths)
    elif len(input_layers) != len(input_paths):
        raise ValueError(
            "input_layers must have the same length as input_paths if it is a list"
        )
    output_path = Path(output_path)
    if _io_util.output_exists(path=output_path, remove_if_exists=force):
        return

    if create_spatial_index is None:
        output_geofileinfo = _geofileinfo.get_geofileinfo(output_path)
        create_spatial_index = output_geofileinfo.default_spatial_index

    logger.info(f"Start concat to {output_path}")

    start_time = datetime.now()
    tmp_dir = _io_util.create_tempdir("geofileops/concat")
    try:
        # Loop over all files and copy_layer them one by one together.
        tmp_dst = tmp_dir / output_path.name
        is_first = True
        for src_path, src_layer in zip(input_paths, input_layers):
            # This first file will be created, the others appended
            if is_first:
                force_local = force
                write_mode = "create"
            else:
                force_local = False
                write_mode = "append_add_fields"

            # The columns specified should only be columns present in the file,
            # otherwise the output is invalid.
            if columns is None or len(columns) == 0:
                columns_local = columns
            else:
                src_info = fileops.get_layerinfo(src_path, layer=src_layer)
                src_columns_lower = {col.lower() for col in src_info.columns}
                columns_local = [
                    col for col in columns if col.lower() in src_columns_lower
                ]

            fileops.copy_layer(
                src=src_path,
                dst=tmp_dst,
                write_mode=write_mode,
                src_layer=src_layer,
                dst_layer=output_layer,
                columns=columns_local,
                explodecollections=explodecollections,
                create_spatial_index=False,
                force=force_local,
            )

            if is_first:
                is_first = False

        # Add a spatial index if needed
        if create_spatial_index:
            fileops.create_spatial_index(tmp_dst, output_layer)

        fileops.move(tmp_dst, output_path)

    finally:
        if ConfigOptions.remove_temp_files:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    logger.info(f"Ready, took {datetime.now() - start_time}")


def difference(
    input1_path: Union[str, "os.PathLike[Any]"],
    input2_path: Union[str, "os.PathLike[Any]", None],
    output_path: Union[str, "os.PathLike[Any]"],
    input1_layer: str | None = None,
    input1_columns: list[str] | None = None,
    input2_layer: str | None = None,
    output_layer: str | None = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 2000,
    force: bool = False,
):
    """Calculate the difference of the input1 layer and input2 layer.

    Notes:
        - Every row in the input layer will result in maximum one row in the
          output layer.
        - The output will contain the columns from the 1st no columns from the 2nd
          layer. The attribute values wont't be changed, so columns like area,...
          will have to be recalculated manually.
        - If ``input2_path`` is None, the 1st input layer is used for both inputs but
          interactions between the same rows in this layer will be ignored. The output
          will be the (pieces of) features in this layer that don't have any
          intersections with other features in this layer.
        - To speed up processing, complex input geometries are subdivided by default.
          For these geometries, the output geometries will contain extra collinear
          points where the subdividing occured. This behaviour can be controlled via the
          ``subdivide_coords`` parameter.

    Alternative names:
        - ArcMap: erase

    Args:
        input1_path (PathLike): The file to remove/difference from.
        input2_path (PathLike, optional): The file with the geometries to remove from
            input1. If None, the 1st input layer is used for both inputs but interactions
            between the same rows in this layer will be ignored. The output will be the
            (pieces of) features in this layer that don't have any intersections with
            other features in this layer.
        output_path (PathLike): the file to write the result to.
        input1_layer (str, optional): input layer name. If None, ``input1_path`` should
            contain only one layer. Defaults to None.
        input1_columns (List[str], optional): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased eg. to "fid_1". Defaults to None.
        input2_layer (str, optional): input2 layer name. If None, ``input2_path`` should
            contain only one layer. Defaults to None.
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        explodecollections (bool, optional): True to convert all multi-geometries to
            singular ones after the dissolve. Defaults to False.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): SQL filter to apply after all other processing,
            including e.g. ``explodecollections``. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        subdivide_coords (int, optional): the input geometries will be subdivided to
            parts with about ``subdivide_coords`` coordinates during processing which
            can offer a large speed up for complex geometries. Subdividing can result in
            extra collinear points being added to the boundaries of the output. If 0, no
            subdividing is applied. Defaults to 2000.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    See Also:
        * :func:`identity`: calculate the identity of two layers
        * :func:`intersection`: calculate the intersection of two layers
        * :func:`symmetric_difference`: calculate the symmetric difference of two layers
        * :func:`union`: calculate the union of two layers

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    logger = logging.getLogger("geofileops.difference")
    logger.info(f"Start, on {input1_path} with {input2_path} to {output_path}")

    # If input2_path is None, we are doing a self-overlay
    overlay_self = False
    if input2_path is None:
        if input2_layer is not None:
            raise ValueError("input2_layer must be None if input2_path is None")
        input2_path = input1_path
        input2_layer = input1_layer
        overlay_self = True

    return _geoops_sql.difference(
        input1_path=Path(input1_path),
        input2_path=Path(input2_path),
        output_path=Path(output_path),
        overlay_self=overlay_self,
        input1_layer=input1_layer,
        input1_columns=input1_columns,
        input2_layer=input2_layer,
        output_layer=output_layer,
        explodecollections=explodecollections,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        subdivide_coords=subdivide_coords,
        force=force,
    )


def erase(
    input_path: Union[str, "os.PathLike[Any]"],
    erase_path: Union[str, "os.PathLike[Any]", None],
    output_path: Union[str, "os.PathLike[Any]"],
    input_layer: str | None = None,
    input_columns: list[str] | None = None,
    erase_layer: str | None = None,
    output_layer: str | None = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 2000,
    force: bool = False,
):
    """DEPRECATED: please use difference."""
    warnings.warn(  # pragma: no cover
        "erase is deprecated because it was renamed to difference. "
        "Will be removed in a (distant) future version",
        FutureWarning,
        stacklevel=2,
    )
    return difference(
        input1_path=input_path,
        input2_path=erase_path,
        output_path=output_path,
        input1_layer=input_layer,
        input1_columns=input_columns,
        input2_layer=erase_layer,
        output_layer=output_layer,
        explodecollections=explodecollections,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        subdivide_coords=subdivide_coords,
        force=force,
    )


def export_by_location(
    input_to_select_from_path: Union[str, "os.PathLike[Any]"],
    input_to_compare_with_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    spatial_relations_query: str = "intersects is True",
    min_area_intersect: float | None = None,
    area_inters_column_name: str | None = None,
    input1_layer: str | None = None,
    input1_columns: list[str] | None = None,
    input2_layer: str | None = None,
    output_layer: str | None = None,
    gridsize: float = 0.0,
    where_post: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 7500,
    force: bool = False,
):
    """Exports all features filtered by the specified spatial query.

    All features in ``input_to_select_from_path`` that comply to the
    ``spatial_relations_query`` compared with the features in
    ``input_to_compare_with_path`` are exported.

    The ``spatial_relations_query`` has a specific format. For most cases can use the
    following "named spatial predicates": contains, coveredby, covers, crosses,
    disjoint, equals, intersects, overlaps, touches and within.
    If you want even more control, you can also use "spatial masks" as defined by the
    |DE-9IM| model.

    Some examples of valid ``spatial_relations_query`` values:

        - "touches is True or within is True"
        - "intersects is True and touches is False"
        - "(T*T***T** is True or 1*T***T** is True) and T*****FF* is False"


    Alternative names:
        - QGIS: extract by location

    Args:
        input_to_select_from_path (PathLike): the 1st input file
        input_to_compare_with_path (PathLike): the 2nd input file
        output_path (PathLike): the file to write the result to
        spatial_relations_query (str, optional): a query that specifies the spatial
            relations to match between the 2 layers. Defaults to "intersects is True".
        min_area_intersect (float, optional): minimum area of the intersection.
            Defaults to None.
        area_inters_column_name (str, optional): column name of the intersect
            area. If None, no area column is added. Defaults to None.
        input1_layer (str, optional): 1st input layer name. If None,
            ``input_to_select_from_path`` should only contain one layer.
            Defaults to None.
        input1_columns (List[str], optional): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased eg. to "fid_1". Defaults to None.
        input2_layer (str, optional): 2nd input layer name. If None,
            ``input_to_compare_with_path`` should contain only one layer.
            Defaults to None.
        input2_columns (List[str], optional): NA.
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): SQL filter to apply after all other processing,
            including e.g. ``explodecollections``. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        subdivide_coords (int, optional): the input geometries in the input to compare
            with layer will be subdivided to parts with about ``subdivide_coords``
            coordinates during processing which can offer a large speed up for complex
            geometries. If 0, no subdividing is applied. Defaults to 7.500.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    See Also:
        * :func:`export_by_bounds`: export features that intersect with the bounds
          specified
        * :func:`export_by_distance`: export features that are within a certain distance
          of features of another layer
        * :func:`export_by_location`: export features that e.g. intersect with features
          of another layer
        * :func:`join_by_location`: join features that e.g. intersect with features of
          another layer

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    .. |DE-9IM| raw:: html

        <a href="https://en.wikipedia.org/wiki/DE-9IM" target="_blank">DE-9IM</a>

    """  # noqa: E501
    logger = logging.getLogger("geofileops.export_by_location")
    logger.info(
        f"export_by_location: select from {input_to_select_from_path} "
        f"interacting with {input_to_compare_with_path} to {output_path}"
    )
    return _geoops_sql.export_by_location(
        input_path=Path(input_to_select_from_path),
        input_to_compare_with_path=Path(input_to_compare_with_path),
        output_path=Path(output_path),
        spatial_relations_query=spatial_relations_query,
        min_area_intersect=min_area_intersect,
        area_inters_column_name=area_inters_column_name,
        input_layer=input1_layer,
        input_columns=input1_columns,
        input_to_compare_with_layer=input2_layer,
        output_layer=output_layer,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        subdivide_coords=subdivide_coords,
        force=force,
    )


def export_by_distance(
    input_to_select_from_path: Union[str, "os.PathLike[Any]"],
    input_to_compare_with_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    max_distance: float,
    input1_layer: str | None = None,
    input1_columns: list[str] | None = None,
    input2_layer: str | None = None,
    output_layer: str | None = None,
    gridsize: float = 0.0,
    where_post: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """Exports all features within the distance specified.

    Features in ``input_to_select_from_path`` that are within the distance specified of
    any features in ``input_to_compare_with_path``.

    Args:
        input_to_select_from_path (PathLike): the 1st input file
        input_to_compare_with_path (PathLike): the 2nd input file
        output_path (PathLike): the file to write the result to
        max_distance (float): maximum distance
        input1_layer (str, optional): 1st input layer name. If None,
            ``input_to_select_from_path`` should contain only one layer.
            Defaults to None.
        input1_columns (List[str], optional): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased eg. to "fid_1". Defaults to None.
        input2_layer (str, optional): 2nd input layer name. If None,
            ``input_to_compare_with_path`` should contain only one layer.
            Defaults to None.
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): SQL filter to apply after all other processing,
            including e.g. ``explodecollections``. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    See Also:
        * :func:`export_by_bounds`: export features that intersect with the bounds
          specified
        * :func:`export_by_location`: export features that e.g. intersect with features
          of another layer

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    logger = logging.getLogger("geofileops.export_by_distance")
    logger.info(
        f"select from {input_to_select_from_path} within "
        f"max_distance of {max_distance} from {input_to_compare_with_path} "
        f"to {output_path}"
    )
    return _geoops_sql.export_by_distance(
        input_to_select_from_path=Path(input_to_select_from_path),
        input_to_compare_with_path=Path(input_to_compare_with_path),
        output_path=Path(output_path),
        max_distance=max_distance,
        input1_layer=input1_layer,
        input1_columns=input1_columns,
        input2_layer=input2_layer,
        output_layer=output_layer,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def identity(
    input1_path: Union[str, "os.PathLike[Any]"],
    input2_path: Union[str, "os.PathLike[Any]", None],
    output_path: Union[str, "os.PathLike[Any]"],
    input1_layer: str | None = None,
    input1_columns: list[str] | None = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: str | None = None,
    input2_columns: list[str] | None = None,
    input2_columns_prefix: str = "l2_",
    output_layer: str | None = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 2000,
    force: bool = False,
):
    r"""Calculates the pairwise identity of the two input layers.

    The result is the equivalent of the intersection between the two layers + layer 1
    differenced with layer 2.

    Notes:
        - The result will contain the attribute columns from both input layers. The
          attribute values wont't be changed, so columns like area,... will have to be
          recalculated manually if this is wanted.
        - If ``input2_path`` is None, the 1st input layer is used for both inputs but
          interactions between the same rows in this layer will be ignored.
        - To speed up processing, complex input geometries are subdivided by default.
          For these geometries, the output geometries will contain extra collinear
          points where the subdividing occured. This behaviour can be controlled via the
          ``subdivide_coords`` parameter.

    Args:
        input1_path (PathLike): the 1st input file.
        input2_path (PathLike, optional): the 2nd input file. If None, the 1st input
            layer is used for both inputs but interactions between the same rows in this
            layer will be ignored.
        output_path (PathLike): the file to write the result to
        input1_layer (str, optional): 1st input layer name. If None, ``input1_path``
            should contain only one layer. Defaults to None.
        input1_columns (List[str], optional): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased even if ``input1_columns_prefix`` is "", eg.
            to "fid_1". Defaults to None.
        input1_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l1\_".
        input2_layer (str, optional): 2nd input layer name. If None, ``input2_path``
            should contain only one layer. Defaults to None.
        input2_columns (List[str], optional): columns to select. If None is specified,
            all columns are selected. As explained for ``input1_columns``, it is also
            possible to specify "fid". Defaults to None.
        input2_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l2\_".
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        explodecollections (bool, optional): True to convert all multi-geometries to
            singular ones after the dissolve. Defaults to False.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): SQL filter to apply after all other processing,
            including e.g. ``explodecollections``. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        subdivide_coords (int, optional): the input geometries will be subdivided to
            parts with about ``subdivide_coords`` coordinates during processing which
            can offer a large speed up for complex geometries. Subdividing can result in
            extra collinear points being added to the boundaries of the output. If 0, no
            subdividing is applied. Defaults to 2000.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    See Also:
        * :func:`difference`: calculate the difference between two layers
        * :func:`intersection`: calculate the intersection of two layers
        * :func:`symmetric_difference`: calculate the symmetric difference of two layers
        * :func:`union`: calculate the union of two layers

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    logger = logging.getLogger("geofileops.identity")
    logger.info(f"Start, between {input1_path} and {input2_path} to {output_path}")

    # In input2_path is None, we are doing a self-overlay
    overlay_self = False
    if input2_path is None:
        if input2_layer is not None:
            raise ValueError("input2_layer must be None if input2_path is None")
        input2_path = input1_path
        input2_layer = input1_layer
        overlay_self = True

    return _geoops_sql.identity(
        input1_path=Path(input1_path),
        input2_path=Path(input2_path),
        output_path=Path(output_path),
        overlay_self=overlay_self,
        input1_layer=input1_layer,
        input1_columns=input1_columns,
        input1_columns_prefix=input1_columns_prefix,
        input2_layer=input2_layer,
        input2_columns=input2_columns,
        input2_columns_prefix=input2_columns_prefix,
        output_layer=output_layer,
        explodecollections=explodecollections,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        subdivide_coords=subdivide_coords,
        force=force,
    )


def split(
    input1_path: Union[str, "os.PathLike[Any]"],
    input2_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    input1_layer: str | None = None,
    input1_columns: list[str] | None = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: str | None = None,
    input2_columns: list[str] | None = None,
    input2_columns_prefix: str = "l2_",
    output_layer: str | None = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 2000,
    force: bool = False,
):
    """DEPRECATED: please use identity."""
    warnings.warn(
        "split is deprecated because it was renamed to identity. "
        "Will be removed in a future version.",
        FutureWarning,
        stacklevel=2,
    )
    logger = logging.getLogger("geofileops.identity")
    logger.info(f"Start,  between {input1_path} and {input2_path} to {output_path}")
    return _geoops_sql.identity(
        input1_path=Path(input1_path),
        input2_path=Path(input2_path),
        output_path=Path(output_path),
        overlay_self=False,
        input1_layer=input1_layer,
        input1_columns=input1_columns,
        input1_columns_prefix=input1_columns_prefix,
        input2_layer=input2_layer,
        input2_columns=input2_columns,
        input2_columns_prefix=input2_columns_prefix,
        output_layer=output_layer,
        explodecollections=explodecollections,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        subdivide_coords=subdivide_coords,
        force=force,
    )


def intersect(
    input1_path: Union[str, "os.PathLike[Any]"],
    input2_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    input1_layer: str | None = None,
    input1_columns: list[str] | None = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: str | None = None,
    input2_columns: list[str] | None = None,
    input2_columns_prefix: str = "l2_",
    output_layer: str | None = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """DEPRECATED: please use intersection."""
    warnings.warn(  # pragma: no cover
        "intersect is deprecated because it was renamed intersection. "
        "Will be removed in a future version",
        FutureWarning,
        stacklevel=2,
    )
    return intersection(  # pragma: no cover
        input1_path=input1_path,
        input2_path=input2_path,
        output_path=output_path,
        input1_layer=input1_layer,
        input1_columns=input1_columns,
        input1_columns_prefix=input1_columns_prefix,
        input2_layer=input2_layer,
        input2_columns=input2_columns,
        input2_columns_prefix=input2_columns_prefix,
        output_layer=output_layer,
        explodecollections=explodecollections,
        gridsize=gridsize,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def intersection(
    input1_path: Union[str, "os.PathLike[Any]"],
    input2_path: Union[str, "os.PathLike[Any]", None],
    output_path: Union[str, "os.PathLike[Any]"],
    input1_layer: str | None = None,
    input1_columns: list[str] | None = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: str | None = None,
    input2_columns: list[str] | None = None,
    input2_columns_prefix: str = "l2_",
    output_layer: str | None = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 15000,
    force: bool = False,
):
    r"""Calculates the pairwise intersection of the two input layers.

    Notes:
        - The result will contain the attribute columns from both input layers. The
          attribute values wont't be changed, so columns like area,... will have to be
          recalculated manually if this is wanted.
        - If ``input2_path`` is None, the 1st input layer is used for both inputs but
          intersections between the same rows in this layer will be omitted from the
          result.
        - To speed up processing, complex input geometries are subdivided by default.
          For these geometries, the output geometries will contain extra collinear
          points where the subdividing occured. This behaviour can be controlled via the
          ``subdivide_coords`` parameter.

    Alternative names:
        - GeoPandas: overlay(how="intersection")

    Args:
        input1_path (PathLike): the 1st input file
        input2_path (PathLike): the 2nd input file. If None, the 1st input layer is used
            for both inputs but intersections between the same rows in this layer will
            be omitted from the result.
        output_path (PathLike): the file to write the result to
        input1_layer (str, optional): 1st input layer name. If None, ``input1_path``
            should contain only one layer. Defaults to None.
        input1_columns (List[str], optional): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased even if ``input1_columns_prefix`` is "", eg.
            to "fid_1". Defaults to None.
        input1_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l1\_".
        input2_layer (str, optional): 2nd input layer name. If None, ``input2_path``
            should contain only one layer. Defaults to None.
        input2_columns (List[str], optional): columns to select. If None is specified,
            all columns are selected. As explained for ``input1_columns``, it is also
            possible to specify "fid". Defaults to None.
        input2_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l2\_".
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        explodecollections (bool, optional): True to convert all multi-geometries to
            singular ones after the dissolve. Defaults to False.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): SQL filter to apply after all other processing,
            including e.g. ``explodecollections``. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        subdivide_coords (int, optional): the input geometries will be subdivided to
            parts with about ``subdivide_coords`` coordinates during processing which
            can offer a large speed up for complex geometries. Subdividing can result in
            extra collinear points being added to the boundaries of the output. If 0, no
            subdividing is applied. Defaults to 15000.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    See Also:
        * :func:`difference`: calculate the difference between two layers
        * :func:`identity`: calculate the identity of two layers
        * :func:`symmetric_difference`: calculate the symmetric difference of two layers
        * :func:`union`: calculate the union of two layers

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    logger = logging.getLogger("geofileops.intersection")
    logger.info(f"Start, between {input1_path} and {input2_path} to {output_path}")

    # In input2_path is None, we are doing a self-overlay
    overlay_self = False
    if input2_path is None:
        if input2_layer is not None:
            raise ValueError("input2_layer must be None if input2_path is None")
        input2_path = input1_path
        input2_layer = input1_layer
        overlay_self = True

    return _geoops_sql.intersection(
        input1_path=Path(input1_path),
        input2_path=Path(input2_path),
        output_path=Path(output_path),
        overlay_self=overlay_self,
        input1_layer=input1_layer,
        input1_columns=input1_columns,
        input1_columns_prefix=input1_columns_prefix,
        input2_layer=input2_layer,
        input2_columns=input2_columns,
        input2_columns_prefix=input2_columns_prefix,
        output_layer=output_layer,
        explodecollections=explodecollections,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        subdivide_coords=subdivide_coords,
        force=force,
    )


def join_by_location(
    input1_path: Union[str, "os.PathLike[Any]"],
    input2_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    spatial_relations_query: str = "intersects is True",
    discard_nonmatching: bool = True,
    min_area_intersect: float | None = None,
    area_inters_column_name: str | None = None,
    input1_layer: str | None = None,
    input1_columns: list[str] | None = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: str | None = None,
    input2_columns: list[str] | None = None,
    input2_columns_prefix: str = "l2_",
    output_layer: str | None = None,
    gridsize: float = 0.0,
    where_post: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    r"""Joins all features in input1 with all features in input2.

    The output will contain the geometries of input1. The ``spatial_relations_query``
    and ``min_area_intersect`` parameters will determine which geometries of input1 will
    be matched with input2.

    The ``spatial_relations_query`` has a specific format. Most cases can be covered
    using the following "named spatial predicates": contains, coveredby, covers,
    crosses, equals, intersects, overlaps, touches and within.
    If you want even more control, you can also use "spatial masks" as defined by the
    |DE-9IM| model.
    It is important to note that the query is used as the matching criterium for the
    join. Hence, it should not evaluate to True for disjoint features, as this would
    lead to a cartesian product of both layers. If it does, a warning will be triggered
    and "intersects is True" is added to the query.

    Some examples of valid ``spatial_relations_query`` values:

        - "intersects is True and touches is False"
        - "within is True or contains is True"
        - "(T*T***T** is True or 1*T***T** is True) and T*****FF* is False"


    Alternative names:
        - GeoPandas: sjoin
        - ArcGIS: spatial join

    Args:
        input1_path (PathLike): the 1st input file
        input2_path (PathLike): the 2nd input file
        output_path (PathLike): the file to write the result to
        spatial_relations_query (str, optional): a query that specifies the
            spatial relations to match between the 2 layers.
            Defaults to "intersects is True".
        discard_nonmatching (bool, optional): True to only keep rows that match with the
            spatial_relations_query. False to keep rows all rows in the ``input1_layer``
            (=left outer join). Defaults to True (=inner join).
        min_area_intersect (float, optional): minimum area of the intersection
            to match. Defaults to None.
        area_inters_column_name (str, optional): column name of the intersect
            area. If None no area column is added. Defaults to None.
        input1_layer (str, optional): 1st input layer name. If None, ``input1_path``
            should contain only one layer. Defaults to None.
        input1_columns (List[str], optional): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased even if ``input1_columns_prefix`` is "", eg.
            to "fid_1". Defaults to None.
        input1_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l1\_".
        input2_layer (str, optional): 2nd input layer name. If None, ``input2_path``
            should contain only one layer. Defaults to None.
        input2_columns (List[str], optional): columns to select. If None is specified,
            all columns are selected. As explained for input1_columns, it is also
            possible to specify "fid". Defaults to None.
        input2_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l2\_".
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): SQL filter to apply after all other processing,
            including e.g. ``explodecollections``. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    See Also:
        * :func:`export_by_location`: export features that e.g. intersect with features
          of another layer
        * :func:`join_by_distance`: join features that are within a certain distance of
          features of another layer

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    .. |DE-9IM| raw:: html

        <a href="https://en.wikipedia.org/wiki/DE-9IM" target="_blank">DE-9IM</a>

    """  # noqa: E501
    logger = logging.getLogger("geofileops.join_by_location")
    logger.info(f"select from {input1_path} joined with {input2_path} to {output_path}")
    return _geoops_sql.join_by_location(
        input1_path=Path(input1_path),
        input2_path=Path(input2_path),
        output_path=Path(output_path),
        spatial_relations_query=spatial_relations_query,
        discard_nonmatching=discard_nonmatching,
        min_area_intersect=min_area_intersect,
        area_inters_column_name=area_inters_column_name,
        input1_layer=input1_layer,
        input1_columns=input1_columns,
        input1_columns_prefix=input1_columns_prefix,
        input2_layer=input2_layer,
        input2_columns=input2_columns,
        input2_columns_prefix=input2_columns_prefix,
        output_layer=output_layer,
        explodecollections=False,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def join_nearest(
    input1_path: Union[str, "os.PathLike[Any]"],
    input2_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    nb_nearest: int,
    distance: float | None = None,
    expand: bool | None = None,
    input1_layer: str | None = None,
    input1_columns: list[str] | None = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: str | None = None,
    input2_columns: list[str] | None = None,
    input2_columns_prefix: str = "l2_",
    output_layer: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    r"""Joins features of ``input1`` with the ``nb_nearest`` ones in ``input2``.

    In addition to the columns requested via the ``input*_columns`` parameters, the
    following columns will be in the output file as well:
        - pos (int): relative rank (sorted by distance): the closest item will be #1,
          the second closest item will be #2 and so on.
        - distance (float): if the dataset is in a planar (= projected) crs,
          ``distance`` will be in the unit defined by the projection (meters, feet,
          chains etc.). For a geographic dataset (longitude and latitude degrees),
          ``distance`` will be in meters, with the most precise geodetic formulas being
          applied.
        - distance_crs (float): if the dataset is in a planar (= projected) crs,
          ``distance_crs`` will be in the unit defined by the projection (meters, feet,
          chains etc.). For a geographic dataset (longitude and latitude degrees),
          ``distance_crs`` will be in angles. Only available with spatialite >= 5.1.

    Note: if spatialite version >= 5.1 is used, parameters ``distance`` and ``expand``
    are mandatory.

    Args:
        input1_path (PathLike): the input file to join to nb_nearest features.
        input2_path (PathLike): the file where nb_nearest features are looked for.
        output_path (PathLike): the file to write the result to
        nb_nearest (int): the number of nearest features from input 2 to join
            to input1.
        distance (float): maximum distance to search for the nearest items. If
            ``expand`` is True, this is the initial search distance, which will be
            gradually expanded (doubled) till ``nb_nearest`` are found. For optimal
            performance, it is important to choose the typical value that will be needed
            to find ``nb_nearest`` items. If ``distance`` is too large, performance can
            be bad. Parameter is only relevant if spatialite version >= 5.1 is used.
        expand (bool): True to keep searching till ``nb_nearest`` items are found. If
            False, only items found within ``distance`` are returned (False is only
            supported if spatialite version >= 5.1 is used).
        input1_layer (str, optional): 1st input layer name. If None, ``input1_path``
            should contain only one layer. Defaults to None.
        input1_columns (List[str], optional): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased even if ``input1_columns_prefix`` is "", eg.
            to "fid_1". Defaults to None.
        input1_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l1\_".
        input2_layer (str, optional): 2nd input layer name. If None, ``input2_path``
            should contain only one layer. Defaults to None.
        input2_columns (List[str], optional): columns to select. If None is specified,
            all columns are selected. As explained for ``input1_columns``, it is also
            possible to specify "fid". Defaults to None.
        input2_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l2\_".
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    See Also:
        * :func:`export_by_distance`: export features that are within a certain distance
          of features of another layer
        * :func:`join_by_location`: join features that e.g. intersect with features of
          another layer

    """
    logger = logging.getLogger("geofileops.join_nearest")
    logger.info(f"select from {input1_path} joined with {input2_path} to {output_path}")
    return _geoops_sql.join_nearest(
        input1_path=Path(input1_path),
        input2_path=Path(input2_path),
        output_path=Path(output_path),
        nb_nearest=nb_nearest,
        distance=distance,
        expand=expand,
        input1_layer=input1_layer,
        input1_columns=input1_columns,
        input1_columns_prefix=input1_columns_prefix,
        input2_layer=input2_layer,
        input2_columns=input2_columns,
        input2_columns_prefix=input2_columns_prefix,
        output_layer=output_layer,
        explodecollections=False,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def select_two_layers(
    input1_path: Union[str, "os.PathLike[Any]"],
    input2_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    sql_stmt: str,
    input1_layer: str | None = None,
    input1_columns: list[str] | None = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: str | None = None,
    input2_columns: list[str] | None = None,
    input2_columns_prefix: str = "l2_",
    output_layer: str | None = None,
    explodecollections: bool = False,
    force_output_geometrytype: GeometryType | None = None,
    gridsize: float = 0.0,
    where_post: str | None = None,
    nb_parallel: int = 1,
    batchsize: int = -1,
    force: bool = False,
):
    r'''Execute a SELECT SQL statement on the input files.

    The ``sql_stmt`` must be in SQLite dialect and can contain placeholders that will be
    replaced automatically. More details can be found in the notes and examples below.

    The result is written to the output file specified.

    Args:
        input1_path (PathLike): the 1st input file.
        input2_path (PathLike): the 2nd input file.
        output_path (PathLike): the file to write the result to.
        sql_stmt (str): the SELECT SQL statement to be executed. Must be in SQLite
            dialect.
        input1_layer (str, optional): 1st input layer name. If None, ``input1_path``
            should contain only one layer. Defaults to None.
        input1_columns (List[str], optional): list of columns to retain if one of the
            {layer1\_columns_...} placeholders is used in ``sql_stmt``. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased even if ``input1_columns_prefix`` is "", eg.
            to "fid_1". Defaults to None.
        input1_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l1\_".
        input2_layer (str, optional): 2nd input layer name. If None, ``input2_path``
            should contain only one layer. Defaults to None.
        input2_columns (List[str], optional): list of columns to retain if one of the
            {layer2\_columns_...} placeholders is used in ``sql_stmt``. If None is
            specified, all columns are selected. As explained for ``input1_columns``, it
            is also possible to specify "fid". Defaults to None.
        input2_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l2\_".
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        explodecollections (bool, optional): True to convert all multi-geometries to
            singular ones after the dissolve. Defaults to False.
        force_output_geometrytype (GeometryType, optional): The output geometry
            type to force. Defaults to None, and then the geometry type of the
            input1 layer is used.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): SQL filter to apply after all other processing,
            including e.g. ``explodecollections``. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use. If -1, all
            available cores are used. Defaults to 1. If ``nb_parallel`` != 1, make sure
            your query still returns correct results if it is executed per batch of rows
            instead of in one go on the entire layer.
        batchsize (int, optional): indicative number of rows to process per batch.
            A smaller batch size, possibly in combination with a smaller
            ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    Notes:
        By convention, the ``sql_stmt`` can contain following placeholders that
        will be automatically replaced for you:

        * {input1_layer}: name of input layer 1
        * {input1_geometrycolumn}: name of input geometry column 1
        * {layer1_columns_prefix_str}: komma seperated columns of
          layer 1, prefixed with "layer1"
        * {layer1_columns_prefix_alias_str}: komma seperated columns of
          layer 1, prefixed with "layer1" and with column name aliases
        * {layer1_columns_from_subselect_str}: komma seperated columns of
          layer 1, prefixed with "sub"
        * {input1_databasename}: the database alias for input 1
        * {input2_layer}: name of input layer 1
        * {input2_geometrycolumn}: name of input geometry column 2
        * {layer2_columns_prefix_str}: komma seperated columns of
          layer 2, prefixed with "layer2"
        * {layer2_columns_prefix_alias_str}: komma seperated columns of
          layer 2, prefixed with "layer2" and with column name aliases
        * {layer2_columns_from_subselect_str}: komma seperated columns of
          layer 2, prefixed with "sub"
        * {layer2_columns_prefix_alias_null_str}: komma seperated columns of
          layer 2, but with NULL for all values and with column aliases
        * {input2_databasename}: the database alias for input 2
        * {batch_filter}: the filter to be applied per batch when using parallel
          processing

        Example: left outer join all features in input1 layer with all rows
        in input2 on join_id.

        .. code-block:: python

            minimum_area = 100
            sql_stmt = f"""
                SELECT layer1.{{input1_geometrycolumn}}
                      {{layer1_columns_prefix_alias_str}}
                      {{layer2_columns_prefix_alias_str}}
                  FROM {{input1_databasename}}."{{input1_layer}}" layer1
                  LEFT OUTER JOIN {{input2_databasename}}."{{input2_layer}}" layer2
                       ON layer1.join_id = layer2.join_id
                 WHERE 1=1
                   {{batch_filter}}
                   AND ST_Area(layer1.{{input1_geometrycolumn}}) > {minimum_area}
            """
            gfo.select_two_layers(
                input1_path="input1.gpkg",
                input2_path="input2.gpkg",
                output_path="output.gpkg",
                sql_stmt=sql_stmt,
            )

        Some important remarks:

        * Because some SQL statements won't give the same result when parallelized
          (eg. when using a group by statement), ``nb_parallel`` is 1 by default.
          If you do want to use parallel processing, specify ``nb_parallel`` + make
          sure to include the placeholder {batch_filter} in your ``sql_stmt``.
          This placeholder will be replaced with a filter of the form
          "AND rowid >= x AND rowid < y".
        * Table names are best double quoted as in the example, because some
          characters are otherwise not supported in the table name, eg. "-".
        * When using supported placeholders, make sure you give the tables you
          select from the appropriate table aliases (layer1, layer2).
        * Besides the standard sqlite SQL syntacs, you can use the spatialite
          functions as documented here: |spatialite_reference_link|
        * It is supported to use attribute tables (= table without geometry column)
          as input layers and/or not to include the geometry column in the selected
          columns. Note though that if the column placeholders are used (e.g.
          {layer1_columns_prefix_str}), they will start with a "," and if no column
          precedes it the SQL statement will be invalid.

    See Also:
        * :func:`select`: select features from a layer based on a SQL query

    Examples:
        An ideal place to get inspiration to write you own advanced queries
        is in the following source code file: |geoops_sql_link|.

        Additionally, there are some examples listed here that highlight
        other features/possibilities.

        **Join nearest features with filter**

        To join nearest features, geofileops has a specific :meth:`~join_nearest`
        function. This provides a fast way to find the nearest feature(s) if there
        doesn't need to be a filter on the features to be found.

        For a use case where for each element in layer 1, you want to find the nearest
        features in layer 2 while applying a filter that eliminates many kandidates,
        the query below will be a better solution.

        Note: Using ``MIN(ST_Distance(layer1.geom, layer2.geom)`` sometimes seems to
        round the distances calculated slightly resulting in some nearest features not
        being found. Using ``RANK`` avoids this issue.

        .. code-block:: python

            sql_stmt = f"""
                WITH join_with_dist AS (
                    SELECT layer1.{{input1_geometrycolumn}} AS geom
                          {{layer1_columns_prefix_alias_str}}
                          {{layer2_columns_prefix_alias_str}}
                          ,ST_Distance(
                                layer1.{{input1_geometrycolumn}},
                                layer2.{{input2_geometrycolumn}}
                           ) AS distance
                          ,RANK() OVER ( PARTITION BY layer1.rowid ORDER BY ST_Distance(
                                            layer1.{{input1_geometrycolumn}},
                                            layer2.{{input2_geometrycolumn}}
                                       )
                           ) AS pos
                      FROM {{input1_databasename}}."{{input1_layer}}" layer1
                      JOIN {{input2_databasename}}."{{input2_layer}}" layer2
                        ON layer1.join_id = layer2.join_id
                     WHERE 1=1
                       {{batch_filter}}
                )
                SELECT *
                  FROM join_with_dist jwd
                 WHERE pos = 1
            """

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    .. |geoops_sql_link| raw:: html

        <a href="https://github.com/geofileops/geofileops/blob/main/geofileops/util/_geoops_sql.py" target="_blank">_geoops_sql.py</a>

    '''  # noqa: E501
    logger = logging.getLogger("geofileops.select_two_layers")
    logger.info(f"select from {input1_path} and {input2_path} to {output_path}")
    return _geoops_sql.select_two_layers(
        input1_path=Path(input1_path),
        input2_path=Path(input2_path),
        output_path=Path(output_path),
        sql_stmt=sql_stmt,
        input1_layer=input1_layer,
        input1_columns=input1_columns,
        input1_columns_prefix=input1_columns_prefix,
        input2_layer=input2_layer,
        input2_columns=input2_columns,
        input2_columns_prefix=input2_columns_prefix,
        output_layer=output_layer,
        explodecollections=explodecollections,
        force_output_geometrytype=force_output_geometrytype,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def symmetric_difference(
    input1_path: Union[str, "os.PathLike[Any]"],
    input2_path: Union[str, "os.PathLike[Any]", None],
    output_path: Union[str, "os.PathLike[Any]"],
    input1_layer: str | None = None,
    input1_columns: list[str] | None = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: str | None = None,
    input2_columns: list[str] | None = None,
    input2_columns_prefix: str = "l2_",
    output_layer: str | None = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 2000,
    force: bool = False,
):
    r"""Calculates the pairwise symmetric difference of the two input layers.

    The result will be a layer containing features from both the input and overlay
    layers but with the overlapping areas between the two layers removed.

    Notes:
        - The result will contain the attribute columns from both input layers. The
          attribute values wont't be changed, so columns like area,... will have to be
          recalculated manually if this is wanted.
        - If ``input2_path`` is None, the 1st input layer is used for both inputs but
          interactions between the same rows in this layer will be ignored.
        - To speed up processing, complex input geometries are subdivided by default.
          For these geometries, the output geometries will contain extra collinear
          points where the subdividing occured. This behaviour can be controlled via the
          ``subdivide_coords`` parameter.


    Alternative names:
        - GeoPandas: overlay(how="symmetric_difference")
        - QGIS, ArcMap: symmetrical difference

    Args:
        input1_path (PathLike): the 1st input file.
        input2_path (PathLike): the 2nd input file. If None, the 1st input layer is used
          for both inputs but interactions between the same rows in this layer will be
          ignored.
        output_path (PathLike): the file to write the result to
        input1_layer (str, optional): 1st input layer name. If None, ``input1_path``
            should contain only one layer. Defaults to None.
        input1_columns (List[str], optional): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased even if ``input1_columns_prefix`` is "", eg. to
            "fid_1". Defaults to None.
        input1_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l1\_".
        input2_layer (str, optional): 2nd input layer name. If None, ``input2_path``
            should contain only one layer. Defaults to None.
        input2_columns (List[str], optional): columns to select. If None is specified,
            all columns are selected. As explained for input1_columns, it is also
            possible to specify "fid". Defaults to None.
        input2_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l2\_".
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        explodecollections (bool, optional): True to convert all multi-geometries to
            singular ones after the dissolve. Defaults to False.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): SQL filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        subdivide_coords (int, optional): the input geometries will be subdivided to
            parts with about ``subdivide_coords`` coordinates during processing which
            can offer a large speed up for complex geometries. Subdividing can result in
            extra collinear points being added to the boundaries of the output. If 0, no
            subdividing is applied. Defaults to 2000.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    See Also:
        * :func:`difference`: calculate the difference between two layers
        * :func:`identity`: calculate the identity of two layers
        * :func:`intersection`: calculate the intersection of two layers
        * :func:`union`: calculate the union of two layers

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    logger = logging.getLogger("geofileops.symmetric_difference")
    logger.info(
        f"Start, with input1: {input1_path}, "
        f"input2 {input2_path}, output: {output_path}"
    )

    # In input2_path is None, we are doing a self-overlay
    overlay_self = False
    if input2_path is None:
        if input2_layer is not None:
            raise ValueError("input2_layer must be None if input2_path is None")
        input2_path = input1_path
        input2_layer = input1_layer
        overlay_self = True

    return _geoops_sql.symmetric_difference(
        input1_path=Path(input1_path),
        input2_path=Path(input2_path),
        output_path=Path(output_path),
        overlay_self=overlay_self,
        input1_layer=input1_layer,
        input1_columns=input1_columns,
        input1_columns_prefix=input1_columns_prefix,
        input2_layer=input2_layer,
        input2_columns=input2_columns,
        input2_columns_prefix=input2_columns_prefix,
        output_layer=output_layer,
        explodecollections=explodecollections,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        subdivide_coords=subdivide_coords,
        force=force,
    )


def union(
    input1_path: Union[str, "os.PathLike[Any]"],
    input2_path: Union[str, "os.PathLike[Any]", None],
    output_path: Union[str, "os.PathLike[Any]"],
    input1_layer: str | None = None,
    input1_columns: list[str] | None = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: str | None = None,
    input2_columns: list[str] | None = None,
    input2_columns_prefix: str = "l2_",
    output_layer: str | None = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 2000,
    force: bool = False,
):
    r"""Calculates the pairwise union of the two input layers.

    Union needs to be interpreted here as such: the output layer will contain the
    combination of all of the following operations:
        - The pairwise intersection between the two layers.
        - The (parts of) features of layer 1 that don't have any intersection with layer
          2.
        - The (parts of) features of layer 2 that don't have any intersection with layer
          1.

    Notes:
        - The result will contain the attribute columns from both input layers. The
          attribute values wont't be changed, so columns like area,... will have to be
          recalculated manually if this is wanted.
        - If ``input2_path`` is None, the 1st input layer is used for both inputs but
          interactions between the same rows in this layer will be ignored.
        - To speed up processing, complex input geometries are subdivided by default.
          For these geometries, the output geometries will contain extra collinear
          points where the subdividing occured. This behaviour can be controlled via the
          ``subdivide_coords`` parameter.


    Alternative names:
        - GeoPandas: overlay(how="union")

    Args:
        input1_path (PathLike): the 1st input file.
        input2_path (PathLike, optional): the 2nd input file. If None, the 1st input
            layer is used for both inputs but interactions between the same rows in this
            layer will be ignored.
        output_path (PathLike): the file to write the result to
        input1_layer (str, optional): 1st input layer name. If None, ``input1_path``
            should contain only one layer. Defaults to None.
        input1_columns (List[str], optional): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased even if ``input1_columns_prefix`` is "", eg.
            to "fid_1". Defaults to None.
        input1_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l1\_".
        input2_layer (str, optional): 2nd input layer name. If None, ``input2_path``
            should contain only one layer. Defaults to None.
        input2_columns (List[str], optional): columns to select. If None is specified,
            all columns are selected. As explained for ``input1_columns``, it is also
            possible to specify "fid". Defaults to None.
        input2_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l2\_".
        output_layer (str, optional): output layer name. If None, the ``output_path``
            stem is used. Defaults to None.
        explodecollections (bool, optional): True to convert all multi-geometries to
            singular ones after the dissolve. Defaults to False.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): SQL filter to apply after all other processing,
            including e.g. ``explodecollections``. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller ``nb_parallel``, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        subdivide_coords (int, optional): the input geometries will be subdivided to
            parts with about ``subdivide_coords`` coordinates during processing which
            can offer a large speed up for complex geometries. Subdividing can result in
            extra collinear points being added to the boundaries of the output. If 0, no
            subdividing is applied. Defaults to 2000.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    See Also:
        * :func:`difference`: calculate the difference between two layers
        * :func:`identity`: calculate the identity of two layers
        * :func:`intersection`: calculate the intersection of two layers
        * :func:`symmetric_difference`: calculate the symmetric difference of two layers

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    logger = logging.getLogger("geofileops.union")
    logger.info(
        f"Start, with input1: {input1_path}, input2: {input2_path}, output: "
        f"{output_path}"
    )

    # In input2_path is None, we are doing a self-overlay
    overlay_self = False
    if input2_path is None:
        if input2_layer is not None:
            raise ValueError("input2_layer must be None if input2_path is None")
        input2_path = input1_path
        input2_layer = input1_layer
        overlay_self = True

    return _geoops_sql.union(
        input1_path=Path(input1_path),
        input2_path=Path(input2_path),
        output_path=Path(output_path),
        overlay_self=overlay_self,
        input1_layer=input1_layer,
        input1_columns=input1_columns,
        input1_columns_prefix=input1_columns_prefix,
        input2_layer=input2_layer,
        input2_columns=input2_columns,
        input2_columns_prefix=input2_columns_prefix,
        output_layer=output_layer,
        explodecollections=explodecollections,
        gridsize=gridsize,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        subdivide_coords=subdivide_coords,
        force=force,
    )
