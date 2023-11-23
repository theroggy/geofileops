"""
Module exposing all supported operations on geomatries in geofiles.
"""

from datetime import datetime
import logging
import logging.config
from pathlib import Path
import shutil
from typing import Any, Callable, List, Literal, Optional, Tuple, Union, TYPE_CHECKING
import warnings

from pygeoops import GeometryType

from geofileops._compat import SPATIALITE_GTE_51
from geofileops import fileops
from geofileops.util import _geofileinfo
from geofileops.util import _geoops_gpd
from geofileops.util import _geoops_sql
from geofileops.util import _geoops_ogr
from geofileops.util import _io_util
from geofileops.util import _sqlite_util
from geofileops.util._geometry_util import (
    BufferEndCapStyle,
    BufferJoinStyle,
    SimplifyAlgorithm,
)

if TYPE_CHECKING:
    import os

logger = logging.getLogger(__name__)


def dissolve_within_distance(
    input_path: Path,
    output_path: Path,
    distance: float,
    gridsize: float,
    close_internal_gaps: bool = False,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """
    Dissolve geometries that are within the distance specified.

    The output layer will contain the dissolved geometries where all gaps between the
    input geometries up to `distance` are closed.

    Notes:
      - Only tested on polygon input.
      - Gaps between the individual polygons of multipolygon input features will also
        be closed.
      - The polygons in the output file are exploded to simple geometries.
      - No attributes from the input layer are retained.
      - If `close_internal_gaps` is False, the default, a `gridsize` > 0
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
            the precision. If `close_boundary_gaps` is False, the default, a
            `gridsize` > 0 (E.g. 0.000001) should be specified, otherwise some boundary
            gaps in the input geometries could still be closed due to rounding side
            effects.
        close_internal_gaps (bool, optional): also close gaps, strips or holes in the
            input geometries that are narrower than the `distance` specified. E.g. small
            holes, narrow strips starting at the boundary,... Defaults to False.
        input_layer (str, optional): input layer name. Optional if the input
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the input
            file only contains one layer.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.
    """
    start_time = datetime.now()
    operation_name = "dissolve_within_distance"
    logger = logging.getLogger(f"geofileops.{operation_name}")
    nb_steps = 4
    if not close_internal_gaps:
        # 3 extra steps if boundary gaps not to be closed.
        nb_steps += 3

    # Already check here if it is useful to continue
    if output_path.exists():
        if force is False:
            logger.info(f"Stop, output exists already {output_path}")
            return
        else:
            fileops.remove(output_path)

    tempdir = _io_util.create_tempdir(f"geofileops/{operation_name}")
    try:
        # First dissolve the input.
        #
        # Note: this reduces the complexity of operations to be executed later on.
        # Note2: this already applies the gridsize, which needs to be applied anyway to
        # avoid issues when determining the addedpieces_1neighbour later on.
        logger.info(f"Start, with input file {input_path}")
        step = 1
        logger.info(f"Step {step} of {nb_steps}")
        diss_path = tempdir / "100_diss.gpkg"
        _geoops_gpd.dissolve(
            input_path=input_path,
            output_path=diss_path,
            explodecollections=True,
            input_layer=input_layer,
            gridsize=gridsize,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix=f"{operation_name}-",
        )

        # Positive buffer of distance / 2 to close all gaps.
        #
        # Note: gridsize is not applied to preserve all possible accuracy for these
        # temporary boundaries, otherwise the polygons are sometimes enlarged slightly,
        # which isn't wanted + creates issues when determining the
        # addedpieces_1neighbour later on.
        step += 1
        logger.info(f"Step {step} of {nb_steps}")
        buff_path = tempdir / "110_diss_bufp.gpkg"
        _geoops_gpd.buffer(
            input_path=diss_path,
            output_path=buff_path,
            distance=distance / 2,
            endcap_style=BufferEndCapStyle.SQUARE,
            join_style=BufferJoinStyle.MITRE,
            mitre_limit=1.25,
            # gridsize=gridsize,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix=f"{operation_name}-",
        )

        # Dissolve the buffered input
        #
        # Note: gridsize is not applied to preserve all possible accuracy for these
        # temporary boundaries, otherwise the polygons are sometimes enlarged slightly,
        # which isn't wanted + creates issues when determining the
        # addedpieces_1neighbour later on.
        step += 1
        logger.info(f"Step {step} of {nb_steps}")
        buff_diss_path = tempdir / "120_diss_bufp_diss.gpkg"
        _geoops_gpd.dissolve(
            input_path=buff_path,
            output_path=buff_diss_path,
            explodecollections=True,
            # gridsize=gridsize,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix=f"{operation_name}-",
        )

        # Negative buffer to get back to the borders of the input geometries
        # Use a larger mitre limit, otherwise there are a lot of small triangles that
        # don't dissappear again.
        step += 1
        logger.info(f"Step {step} of {nb_steps}")
        buff_diss_bufm_path = tempdir / "130_diss_bufp_diss_bufm.gpkg"
        _geoops_gpd.buffer(
            input_path=buff_diss_path,
            output_path=buff_diss_bufm_path,
            distance=-(distance / 2),
            endcap_style=BufferEndCapStyle.SQUARE,
            join_style=BufferJoinStyle.MITRE,
            mitre_limit=2,
            gridsize=gridsize,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix=f"{operation_name}-",
        )

        # Determine which parts that were added were actually gaps within 'distance' in
        # the original polygons, so they can be removed again.

        # Determine all pieces added to the input in the process above.
        step += 1
        logger.info(f"Step {step} of {nb_steps}")
        added_pieces_path = tempdir / "200_addedpieces.gpkg"
        _geoops_sql.erase(
            input_path=buff_diss_bufm_path,
            erase_path=diss_path,
            output_path=added_pieces_path,
            explodecollections=True,
            gridsize=gridsize,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix=f"{operation_name}-",
        )

        # Build a filter to select the pieces that we want to erase again from the
        # result because they were incorrectly added.
        # The filter will depend on input parameters.
        if close_internal_gaps:
            # True, so also gaps in the original input boundaries should be closed.
            # This means that in theory all pieces can be retained, but in practice
            # there are some cases where the above algorithm adds unwanted area, so that
            # needs to be erased again.
            #
            # Parameters that indicate that added pieces won't need to be erased:
            #   - large areas (>= distance²) seem OK.
            #   - if > 1 neighbour, seems OK.
            #
            # For all pieces that don't comply to the above, the following parameters
            # indicate that they need to be selected to erase them:
            #   - pieces can be very narrow slivers. E.g. alongside a long boundary with
            #     a small bend, probably due to rounding side effects in the +/- buffer.
            #   - pieces can be spikes. E.g. when a "road" of ~ 'distance' width is not
            #     filled up between two input geometries has a bend. Depending on the
            #     angle, the mitre of the negative buffer can leave a spike in place.
            pieces_to_erase_filter = f"""
                neighbours_count_distinct <= 1
                AND geom_area < {distance} * {distance}
                AND neighbours_perimeter/2 + neighbours_length <= 0.8 * geom_perimeter
            """
        else:
            # False, so we want to keep all pieces that intersect with only 1 neighbour
            # in the input, so they can be remove again from the result.
            pieces_to_erase_filter = "neighbours_count_distinct <= 1"

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
               AND ({pieces_to_erase_filter})
        """

        step += 1
        logger.info(f"Step {step} of {nb_steps}")
        added_pieces_to_be_erased_input = tempdir / "210_addedpieces_to_be_erased.gpkg"
        _geoops_sql.select_two_layers(
            input1_path=added_pieces_path,
            input2_path=input_path,
            output_path=added_pieces_to_be_erased_input,
            sql_stmt=sql_stmt,
            input2_layer=input_layer,
            # gridsize=gridsize,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            operation_prefix=f"{operation_name}-",
        )

        step += 1
        logger.info(f"Step {step} of {nb_steps}")
        _geoops_sql.erase(
            input_path=buff_diss_bufm_path,
            erase_path=added_pieces_to_be_erased_input,
            output_path=output_path,
            output_layer=output_layer,
            explodecollections=True,
            gridsize=gridsize,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            force=force,
            operation_prefix=f"{operation_name}-",
        )

    finally:
        shutil.rmtree(tempdir, ignore_errors=True)

    logger.info(f"Ready, took {datetime.now()-start_time}")


def apply(
    input_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    func: Callable[[Any], Any],
    only_geom_input: bool = True,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    force_output_geometrytype: Union[GeometryType, str, None] = None,
    gridsize: float = 0.0,
    keep_empty_geoms: Optional[bool] = None,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """
    Apply a python lambda function on the geometry column of the input file.

    The result is written to the output file specified.

    Examples for the func parameter:
        * if only_geom_input is True:
            ``func=lambda geom: pygeoops.remove_inner_rings(``
                    ``geom, min_area_to_keep=1)``

        * if only_geom_input is False:
            ``func=lambda row: pygeoops.remove_inner_rings(``
                    ``row.geometry, min_area_to_keep=1)``

    If ``explodecollections`` is False and the input and output file type is GeoPackage,
    the fid will be preserved. In other cases this will typically not be the case.

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        func (Callable): lambda function to apply to the geometry column.
        only_geom_input (bool, optional): If True, only the geometry
            column is available. If False, the entire row is input.
            Remark: when False, the operation is 50% slower. Defaults to True.
        input_layer (str, optional): input layer name. Optional if the input
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the input
            file only contains one layer.
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
        where_post (str, optional): sql filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

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


def buffer(
    input_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    distance: float,
    quadrantsegments: int = 5,
    endcap_style: BufferEndCapStyle = BufferEndCapStyle.ROUND,
    join_style: BufferJoinStyle = BufferJoinStyle.ROUND,
    mitre_limit: float = 5.0,
    single_sided: bool = False,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: Optional[bool] = None,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """
    Applies a buffer operation on geometry column of the input file.

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
                flat at the end points, but elongated by "distance"
        join_style (BufferJoinStyle, optional): buffer style to use for
            corners in a line or a polygon boundary. Defaults to ROUND.

              * ROUND: corners in the result are rounded
              * MITRE: corners in the result are sharp
              * BEVEL: are flattened
        mitre_limit (float, optional): in case of join_style MITRE, if the
            spiky result for a sharp angle becomes longer than this ratio limit, it
            is "beveled" using this maximum ratio. Defaults to 5.0.
        single_sided (bool, optional): only one side of the line is buffered,
            if distance is negative, the left side, if distance is positive,
            the right hand side. Only relevant for line geometries.
            Defaults to False.
        input_layer (str, optional): input layer name. Optional if the input
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the input
            file only contains one layer.
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
        where_post (str, optional): sql filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite</a>

    **Buffer style options**

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
        # If default buffer options for spatialite, use the faster sql version
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
    clip_geometry: Union[Tuple[float, float, float, float], str],
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    force: bool = False,
):
    """
    Clip all geometries in the imput file by the geometry provided.

    If ``explodecollections`` is False and the input and output file type is GeoPackage,
    the fid will be preserved. In other cases this will typically not be the case.

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        clip_geometry (Union[Tuple[float, float, float, float], str]): the bounds
            or WKT geometry to clip with.
        input_layer (str, optional): input layer name. Optional if the
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the
            file only contains one layer.
        columns (List[str], optional): list of columns to retain. If None, all standard
            columns are retained. In addition to standard columns, it is also possible
            to specify "fid", a unique index available in all input files. Note that the
            "fid" will be aliased eg. to "fid_1". Defaults to None.
        explodecollections (bool, optional): True to output only simple geometries.
            Defaults to False.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.
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
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: Optional[bool] = None,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """
    Applies a convexhull operation on the input file.

    The result is written to the output file specified.

    If ``explodecollections`` is False and the input and output file type is GeoPackage,
    the fid will be preserved. In other cases this will typically not be the case.

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        input_layer (str, optional): input layer name. Optional if the input
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the input
            file only contains one layer.
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
        where_post (str, optional): sql filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage.
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
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    keep_empty_geoms: Optional[bool] = None,
    where_post: Optional[str] = None,
    force: bool = False,
):
    """
    Copy all rows to the output file, except for duplicate geometries.

    If ``explodecollections`` is False and the input and output file type is GeoPackage,
    the fid will be preserved. In other cases this will typically not be the case.

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        input_layer (str, optional): input layer name. Optional if the input
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the input
            file only contains one layer.
        columns (List[str], optional): list of columns to retain. If None, all standard
            columns are retained. In addition to standard columns, it is also possible
            to specify "fid", a unique index available in all input files. Note that the
            "fid" will be aliased eg. to "fid_1". Defaults to None.
        explodecollections (bool, optional): True to output only simple geometries.
            Defaults to False.
        keep_empty_geoms (bool, optional): True to keep rows with empty/null geometries
            in the output. Defaults to False.
        where_post (str, optional): sql filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
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
        explodecollections=explodecollections,
        keep_empty_geoms=keep_empty_geoms,
        where_post=where_post,
        force=force,
    )


def dissolve(
    input_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    explodecollections: bool,
    groupby_columns: Union[List[str], str, None] = None,
    agg_columns: Optional[dict] = None,
    tiles_path: Union[str, "os.PathLike[Any]", None] = None,
    nb_squarish_tiles: int = 1,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """
    Applies a dissolve operation on the input file.

    If columns are specified with ``groupby_columns``, the data is first grouped
    on those columns before the geometries are merged.

    Data in other columns can be retained in the output by specifying the
    ``agg_columns`` parameter.

    Because the input layer is tiled using a grid to speed up, extra collinear points
    will typically be present in the output geometries. Rows with null or empty
    geometries are ignored.

    This is an example of how data in the columns that isn't grouped on can be
    aggregated to be added to the output file:
    ::

        import geofileops as gfo

        gfo.dissolve(
            input_path=...,
            output_path=...,
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
    ::

        import geofileops as gfo

        gfo.dissolve(
            input_path=...,
            output_path=...,
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
            especially if no groupby_columns are specified.
        groupby_columns (Union[List[str], str], optional): columns (case insensitive) to
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
        input_layer (str, optional): input layer name. Optional if the
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the
            file only contains one layer.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): sql filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    # Init
    if tiles_path is not None:
        tiles_path = Path(tiles_path)

    # Standardize parameter to simplify the rest of the code
    if groupby_columns is not None:
        if isinstance(groupby_columns, str):
            # If a string is passed, convert to list
            groupby_columns = [groupby_columns]
        elif len(groupby_columns) == 0:
            # If an empty list of geometry columns is passed, convert it to None
            groupby_columns = None

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
    bounds: Tuple[float, float, float, float],
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    force: bool = False,
):
    """
    Export the rows that intersect with the bounds specified.

    If ``explodecollections`` is False and the input and output file type is GeoPackage,
    the fid will be preserved. In other cases this will typically not be the case.

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        bounds (Tuple[float, float, float, float]): the bounds to filter on.
        input_layer (str, optional): input layer name. Optional if the
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the
            file only contains one layer.
        columns (List[str], optional): list of columns to retain. If None, all standard
            columns are retained. In addition to standard columns, it is also possible
            to specify "fid", a unique index available in all input files. Note that the
            "fid" will be aliased eg. to "fid_1". Defaults to None.
        explodecollections (bool, optional): True to output only simple geometries.
            Defaults to False.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.
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
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    validate_attribute_data: bool = False,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
) -> bool:
    """
    Checks for all geometries in the geofile if they are valid.

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
        input_layer (str, optional): input layer name. Optional if the
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the
            file only contains one layer.
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
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    Returns:
        bool: True if all geometries were valid.
    """
    # Check parameters
    if output_path is not None:
        output_path = Path(output_path)
    else:
        input_path = Path(input_path)
        output_path = (
            input_path.parent / f"{input_path.stem}_isvalid{input_path.suffix}"
        )

    # Go!
    logger = logging.getLogger("geofileops.isvalid")
    logger.info(f"Start, on {input_path}")
    return _geoops_sql.isvalid(
        input_path=Path(input_path),
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
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    force_output_geometrytype: Union[str, None, GeometryType] = None,
    gridsize: float = 0.0,
    keep_empty_geoms: Optional[bool] = None,
    where_post: Optional[str] = None,
    precision: Optional[float] = None,
    validate_attribute_data: bool = False,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """
    Makes all geometries in the input file valid.

    Writes the result to the output path.

    Alternative names:
        - QGIS: fix geometries
        - shapely, geopandas: make_valid

    If ``explodecollections`` is False and the input and output file type is GeoPackage,
    the fid will be preserved. In other cases this will typically not be the case.

    Args:
        input_path (PathLike): The input file.
        output_path (PathLike): The file to write the result to.
        input_layer (str, optional): input layer name. Optional if the
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the
            file only contains one layer.
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
        precision (float, optional): deprecated. Use gridsize.
        keep_empty_geoms (bool, optional): True to keep rows with empty/null geometries
            in the output. Defaults to False.
        where_post (str, optional): sql filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        validate_attribute_data (bool, optional): True to validate if all attribute data
            can be read. Raises an exception if an error is found, as this type of error
            cannot be fixed using makevalid. Defaults to False.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    logger = logging.getLogger("geofileops.makevalid")
    logger.info(f"Start, on {input_path}")

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

    if SPATIALITE_GTE_51 and gridsize == 0.0:
        # If spatialite >= 5.1 available use faster/less memory using sql implementation
        # Only use this version if gridsize is 0.0, because when gridsize applied it is
        # less robust than the gpd implementation.
        _geoops_sql.makevalid(
            input_path=Path(input_path),
            output_path=Path(output_path),
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
            input_path=Path(input_path),
            output_path=Path(output_path),
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
        if output_geofileinfo.is_spatialite_based:
            _sqlite_util.test_data_integrity(path=input_path)


def warp(
    input_path: Path,
    output_path: Path,
    gcps: List[Tuple[float, float, float, float, Optional[float]]],
    algorithm: str = "polynomial",
    order: Optional[int] = None,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    force: bool = False,
):
    """
    Warp all input features to the output file according to the gcps specified.

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
        input_layer (str, optional): input layer name. Optional if the
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the
            file only contains one layer.
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
    sql_dialect: Optional[Literal["SQLITE", "OGRSQL"]] = "SQLITE",
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    force_output_geometrytype: Union[GeometryType, str, None] = None,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = True,
    nb_parallel: int = 1,
    batchsize: int = -1,
    force: bool = False,
):
    """
    Execute an SQL query on the file.

    By convention, the sqlite query can contain following placeholders that
    will be automatically replaced for you:

      * {geometrycolumn}: the column where the primary geometry is stored.
      * {columns_to_select_str}: if 'columns' is not None, those columns, otherwise all
        columns of the layer.
      * {input_layer}: the layer name of the input layer.
      * {batch_filter}: the filter used to process in parallel per batch.

    Hint: often you will want to use f"" formatting on the sql statement to fill out
    some parameters of your own as well. You can easily escape the placeholders above by
    doubling the "{" and "}", e.g. use {{geometrycolumn}} for {geometrycolumn}. Also
    check out the example below.

    Example: buffer all rows with a certain minimum area to the output file.
    ::

        import geofileops as gfo

        minimum_area = 100
        sql_stmt = f'''
                SELECT ST_Buffer({{geometrycolumn}}, 1) AS {{geometrycolumn}}
                      {{columns_to_select_str}}
                  FROM "{{input_layer}}" layer
                 WHERE 1=1
                   {{batch_filter}}
                   AND ST_Area({{geometrycolumn}}) > {minimum_area}
                '''
        gfo.select(
                input_path=...,
                output_path=...,
                sql_stmt=sql_stmt)

    Some important remarks:

    * The name of the geometry column depends on the file format of the input file. E.g.
      for .shp files the column will be called "geometry", for .gpkg files the default
      name is "geom". If you use the {geometrycolumn} placeholder, geofileops will
      replace it with the correct column name for the input file.
    * If you apply (spatialite) functions on the geometry column always alias them again
      to its original column name, e.g. with "AS {geometrycolumn}".
    * Some sql statements won't give correct results when parallelized/ran in
      multiple batches, e.g. when using a group by statement. This is why the default
      value for nb_parallel is 1. If you want to parallelize or run the query in
      multiple batches (by specifying nb_parallel != 1 or batchsize > 0), you should
      make sure your query will give correct results if it is executed per batch of
      rows instead of once on the entire layer.
      Additionally, if you do so, make sure to include the placeholder {batch_filter}
      in your sql_stmt. This placeholder will be replaced with a filter of the form
      'AND rowid >= x AND rowid < y' and will ensure every row is only treated once.
    * Table names are best double quoted as in the example, because some
      characters are otherwise not supported in the table name, eg. '-'.
    * It is recommend to give the table you select from "layer" as alias. If
      you use the {batch_filter} placeholder this is even mandatory.
    * When using the (default) "SQLITE" sql dialect, you can also use the spatialite
      functions as documented here: |spatialite_reference_link|.
    * It is supported to use an attribute table (= table without geometry column) as
      input layer and/or not to include the geometry column in the selected columns.
      Note though that if the {columns_to_select_str} placeholder is used, it will
      start with a "," and if no column precedes it the SQL statement will be invalid.

    The result is written to the output file specified.

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        sql_stmt (str): the statement to execute
        sql_dialect (str, optional): the sql dialect to use. If None, the default sql
            dialect of the underlying source is used. Defaults to "SQLITE".
        input_layer (str, optional): input layer name. Optional if the input
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the input
            file only contains one layer.
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
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to 1. If nb_parallel != 1, make sure your query still returns
            correct results if it is executed per batch of rows instead of in one go
            on the entire layer. To use all available cores, pass -1.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage. If batchsize != -1,
            make sure your query still returns correct results if it is executed per
            batch of rows instead of in one go on the entire layer.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s). Defaults to False.

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
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
    algorithm: Union[str, SimplifyAlgorithm] = "rdp",
    lookahead: int = 8,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: Optional[bool] = None,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """
    Applies a simplify operation on geometry column of the input file.

    The result is written to the output file specified.

    If ``explodecollections`` is False and the input and output file type is GeoPackage,
    the fid will be preserved. In other cases this will typically not be the case.

    Args:
        input_path (PathLike): the input file
        output_path (PathLike): the file to write the result to
        tolerance (float): mandatory for the following algorithms:

                * RAMER_DOUGLAS_PEUCKER: distance to use as tolerance.
                * LANG: distance to use as tolerance.
                * VISVALINGAM_WHYATT: area to use as tolerance.

            In projected coordinate systems this tolerance will typically be
            in meter, in geodetic systems this is typically in degrees.
        algorithm (str, optional): algorithm to use. Defaults to "rdp"
            (Ramer Douglas Peucker).
        lookahead (int, optional): used for LANG algorithm. Defaults to 8.
        input_layer (str, optional): input layer name. Optional if the input
            file only contains one layer.
        output_layer (str, optional): input layer name. Optional if the input
            file only contains one layer.
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
        where_post (str, optional): sql filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage.
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


# ------------------------
# Operations on two layers
# ------------------------


def clip(
    input_path: Union[str, "os.PathLike[Any]"],
    clip_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    input_layer: Optional[str] = None,
    input_columns: Optional[List[str]] = None,
    clip_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """
    Clip the input layer with the clip layer.

    The resulting layer will contain the parts of the geometries in the
    input layer that overlap with the dissolved geometries in the clip layer.

    Clarifications:
        - every row in the input layer will result in maximum one row in the
          output layer.
        - geometries in the input layer that overlap with multiple adjacent
          geometries in the clip layer won't result in the input geometries
          getting split.

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
        input_layer (str, optional): input layer name. Optional if the
            file only contains one layer.
        input_columns (List[str], optional): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased eg. to "fid_1". Defaults to None.
        clip_layer (str, optional): clip layer name. Optional if the
            file only contains one layer.
        output_layer (str, optional): output layer name. Optional if the
            file only contains one layer.
        explodecollections (bool, optional): True to convert all multi-geometries to
            singular ones after the dissolve. Defaults to False.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): sql filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

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
        force=force,
    )


def erase(
    input_path: Union[str, "os.PathLike[Any]"],
    erase_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    input_layer: Optional[str] = None,
    input_columns: Optional[List[str]] = None,
    erase_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 2000,
    force: bool = False,
):
    """
    Erase all geometries in the erase layer from the input layer.

    Clarifications:
        - every row in the input layer will result in maximum one row in the
          output layer.
        - columns from the erase layer cannot be retained.

    Alternative names:
        - QGIS: difference

    Args:
        input_path (PathLike): The file to erase from.
        erase_path (PathLike): The file with the geometries to erase with.
        output_path (PathLike): the file to write the result to
        input_layer (str, optional): input layer name. Optional if the
            file only contains one layer.
        input_columns (List[str], optional): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased eg. to "fid_1". Defaults to None.
        erase_layer (str, optional): erase layer name. Optional if the
            file only contains one layer.
        output_layer (str, optional): output layer name. Optional if the
            file only contains one layer.
        explodecollections (bool, optional): True to convert all multi-geometries to
            singular ones after the dissolve. Defaults to False.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): sql filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        subdivide_coords (int, optional): the input geometries will be subdivided to
            parts with about subdivide_coords coordinates during processing which can
            offer a large speed up for complex geometries. Subdividing can result in
            extra collinear points being added to the boundaries of the output. If < 0,
            no subdividing is applied. Defaults to 2000.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    logger = logging.getLogger("geofileops.erase")
    logger.info(f"Start, on {input_path} with {erase_path} to {output_path}")
    return _geoops_sql.erase(
        input_path=Path(input_path),
        erase_path=Path(erase_path),
        output_path=Path(output_path),
        input_layer=input_layer,
        input_columns=input_columns,
        erase_layer=erase_layer,
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
    min_area_intersect: Optional[float] = None,
    area_inters_column_name: Optional[str] = None,
    input1_layer: Optional[str] = None,
    input1_columns: Optional[List[str]] = None,
    input2_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """
    Exports all intersecting features.

    All features in input_to_select_from_path that intersect with any features in
    input_to_compare_with_path are exported.

    Alternative names:
        - QGIS: extract by location

    Args:
        input_to_select_from_path (PathLike): the 1st input file
        input_to_compare_with_path (PathLike): the 2nd input file
        output_path (PathLike): the file to write the result to
        min_area_intersect (float, optional): minimum area of the intersection.
            Defaults to None.
        area_inters_column_name (str, optional): column name of the intersect
            area. If None, no area column is added. Defaults to None.
        input1_layer (str, optional): input layer name. Optional if the
            file only contains one layer.
        input1_columns (List[str], optional): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased eg. to "fid_1". Defaults to None.
        input2_layer (str, optional): input layer name. Optional if the
            file only contains one layer.
        input2_columns (List[str], optional): NA.
        output_layer (str, optional): output layer name. Optional if the
            file only contains one layer.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): sql filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

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
        force=force,
    )


def export_by_distance(
    input_to_select_from_path: Union[str, "os.PathLike[Any]"],
    input_to_compare_with_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    max_distance: float,
    input1_layer: Optional[str] = None,
    input1_columns: Optional[List[str]] = None,
    input2_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """
    Exports all features within the distance specified.

    Features in input_to_select_from_path that are within the distance specified of any
    features in input_to_compare_with_path.

    Args:
        input_to_select_from_path (PathLike): the 1st input file
        input_to_compare_with_path (PathLike): the 2nd input file
        output_path (PathLike): the file to write the result to
        max_distance (float): maximum distance
        input1_layer (str, optional): input layer name. Optional if the
            file only contains one layer.
        input1_columns (List[str], optional): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased eg. to "fid_1". Defaults to None.
        input2_layer (str, optional): input layer name. Optional if the
            file only contains one layer.
        output_layer (str, optional): output layer name. Optional if the
            file only contains one layer.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): sql filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

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
    input2_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    input1_layer: Optional[str] = None,
    input1_columns: Optional[List[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[List[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 2000,
    force: bool = False,
):
    """
    Intersection of the input layers, but retain the non-intersecting parts of input1.

    The result is the equivalent of an intersect between the two layers + layer
    1 erased with layer 2.

    Args:
        input1_path (PathLike): the 1st input file
        input2_path (PathLike): the 2nd input file
        output_path (PathLike): the file to write the result to
        input1_layer (str, optional): input layer name. Optional if the
            file only contains one layer. Defaults to None.
        input1_columns (List[str], optional): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased even if input1_columns_prefix is "", eg. to
            "fid_1". Defaults to None.
        input1_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l1_".
        input2_layer (str, optional): input layer name. Optional if the
            file only contains one layer. Defaults to None.
        input2_columns (List[str], optional): columns to select. If None is specified,
            all columns are selected. As explained for input1_columns, it is also
            possible to specify "fid". Defaults to None.
        input2_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l2_".
        output_layer (str, optional): output layer name. If None, the output_path stem
            is used. Defaults to None.
        explodecollections (bool, optional): True to convert all multi-geometries to
            singular ones after the dissolve. Defaults to False.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): sql filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        subdivide_coords (int, optional): the input geometries will be subdivided to
            parts with about subdivide_coords coordinates during processing which can
            offer a large speed up for complex geometries. Subdividing can result in
            extra collinear points being added to the boundaries of the output. If < 0,
            no subdividing is applied. Defaults to 2000.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    logger = logging.getLogger("geofileops.identity")
    logger.info(f"Start, between {input1_path} and {input2_path} to {output_path}")
    return _geoops_sql.identity(
        input1_path=Path(input1_path),
        input2_path=Path(input2_path),
        output_path=Path(output_path),
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
    input1_layer: Optional[str] = None,
    input1_columns: Optional[List[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[List[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 2000,
    force: bool = False,
):
    """
    DEPRECATED: please use identity.
    """
    warnings.warn(
        "split() is deprecated because it was renamed to identity(). "
        "Will be removed in a future version",
        FutureWarning,
        stacklevel=2,
    )
    logger = logging.getLogger("geofileops.identity")
    logger.info(f"Start,  between {input1_path} and {input2_path} to {output_path}")
    return _geoops_sql.identity(
        input1_path=Path(input1_path),
        input2_path=Path(input2_path),
        output_path=Path(output_path),
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
    input1_layer: Optional[str] = None,
    input1_columns: Optional[List[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[List[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """
    DEPRECATED: please use intersection.
    """
    warnings.warn(  # pragma: no cover
        "intersect() is deprecated because it was renamed intersection(). "
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
    input2_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    input1_layer: Optional[str] = None,
    input1_columns: Optional[List[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[List[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """
    Calculate the pairwise intersection of alle features.

    Alternative names:
        - GeoPandas: overlay(how="intersection")

    Args:
        input1_path (PathLike): the 1st input file
        input2_path (PathLike): the 2nd input file
        output_path (PathLike): the file to write the result to
        input1_layer (str, optional): input layer name. Optional if the
            file only contains one layer. Defaults to None.
        input1_columns (List[str], optional): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased even if input1_columns_prefix is "", eg. to
            "fid_1". Defaults to None.
        input1_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l1_".
        input2_layer (str, optional): input layer name. Optional if the
            file only contains one layer. Defaults to None.
        input2_columns (List[str], optional): columns to select. If None is specified,
            all columns are selected. As explained for input1_columns, it is also
            possible to specify "fid". Defaults to None.
        input2_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l2_".
        output_layer (str, optional): output layer name. If None, the output_path stem
            is used. Defaults to None.
        explodecollections (bool, optional): True to convert all multi-geometries to
            singular ones after the dissolve. Defaults to False.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): sql filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    logger = logging.getLogger("geofileops.intersection")
    logger.info(f"Start, between {input1_path} and {input2_path} to {output_path}")
    return _geoops_sql.intersection(
        input1_path=Path(input1_path),
        input2_path=Path(input2_path),
        output_path=Path(output_path),
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
        force=force,
    )


def join_by_location(
    input1_path: Union[str, "os.PathLike[Any]"],
    input2_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    spatial_relations_query: str = "intersects is True",
    discard_nonmatching: bool = True,
    min_area_intersect: Optional[float] = None,
    area_inters_column_name: Optional[str] = None,
    input1_layer: Optional[str] = None,
    input1_columns: Optional[List[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[List[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """
    Joins all features in input1 with all features in input2.

    The output will contain the geometries of input1. The spatial_relations_query and
    min_area_intersect parameters will determine which geometries of input1 will be
    matched with input2.

    The spatial_relations_query is a filter string where you can use the following
    "named spatial predicates": equals, touches, within, overlaps, crosses, intersects,
    contains, covers, coveredby.

    If you want even more control, you can also use "spatial masks" as defined by the
    [DE-9IM](https://en.wikipedia.org/wiki/DE-9IM) model.

    Examples for valid spatial_relations_query values:

        - "overlaps is True and contains is False"
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
        discard_nonmatching (bool, optional): True to only keep rows that
            match with the spatial_relations_query. False to keep rows all
            rows in the input1_layer (=left outer join). Defaults to True
            (=inner join).
        min_area_intersect (float, optional): minimum area of the intersection
            to match. Defaults to None.
        area_inters_column_name (str, optional): column name of the intersect
            area. If None no area column is added. Defaults to None.
        input1_layer (str, optional): input layer name. Optional if the
            file only contains one layer. Defaults to None.
        input1_columns (List[str], optional): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased even if input1_columns_prefix is "", eg. to
            "fid_1". Defaults to None.
        input1_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l1_".
        input2_layer (str, optional): input layer name. Optional if the
            file only contains one layer. Defaults to None.
        input2_columns (List[str], optional): columns to select. If None is specified,
            all columns are selected. As explained for input1_columns, it is also
            possible to specify "fid". Defaults to None.
        input2_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l2_".
        output_layer (str, optional): output layer name. If None, the output_path stem
            is used. Defaults to None.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): sql filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

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
    distance: Optional[float] = None,
    expand: Optional[bool] = None,
    input1_layer: Optional[str] = None,
    input1_columns: Optional[List[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[List[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    """
    Joins features of `input1` with the `nb_nearest` closest features of `input2`.

    In addition to the columns requested via the `input*_columns` parameters, the
    following columns will be in the output file as well:
        - pos (int): relative rank (sorted by distance): the closest item will be #1,
          the second closest item will be #2 and so on.
        - distance (float): if the dataset is in a planar (= projected) crs, `distance`
          will be in the unit defined by the projection (meters, feet, chains etc.).
          For a geographic dataset (longitude and latitude degrees), `distance` will be
          in meters, with the most precise geodetic formulas being applied.
        - distance_crs (float): if the dataset is in a planar (= projected) crs,
          `distance_crs` will be in the unit defined by the projection (meters, feet,
          chains etc.). For a geographic dataset (longitude and latitude degrees),
          `distance_crs` will be in angles. Only available with spatialite >= 5.1.

    Note: if spatialite version >= 5.1 is used, parameters `distance` and `expand` are
    mandatory.

    Args:
        input1_path (PathLike): the input file to join to nb_nearest features.
        input2_path (PathLike): the file where nb_nearest features are looked for.
        output_path (PathLike): the file to write the result to
        nb_nearest (int): the number of nearest features from input 2 to join
            to input1.
        distance (float): maximum distance to search for the nearest items. If `expand`
            is True, this is the initial search distance, which will be gradually
            expanded (doubled) till `nb_nearest` are found. For optimal performance,
            it is important to choose the typical value that will be needed to find
            `nb_nearest` items. If `distance` is too large, performance can be bad.
            Parameter is only relevant if spatialite version >= 5.1 is used.
        expand (bool): `True` to keep searching till nb_nearest items are found. If
            `False`, only items found within `distance` are returned (`False` is only
            supported if spatialite version >= 5.1 is used).
        input1_layer (str, optional): input layer name. Optional if the
            file only contains one layer. Defaults to `None`.
        input1_columns (List[str], optional): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased even if input1_columns_prefix is "", eg. to
            "fid_1". Defaults to None.
        input1_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l1_".
        input2_layer (str, optional): input layer name. Optional if the
            file only contains one layer. Defaults to None.
        input2_columns (List[str], optional): columns to select. If None is specified,
            all columns are selected. As explained for input1_columns, it is also
            possible to specify "fid". Defaults to None.
        input2_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l2_".
        output_layer (str, optional): output layer name. If None, the output_path stem
            is used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.
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
    input1_layer: Optional[str] = None,
    input1_columns: Optional[List[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[List[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    force_output_geometrytype: Optional[GeometryType] = None,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = 1,
    batchsize: int = -1,
    force: bool = False,
):
    """
    Executes the sqlite query specified on the 2 input layers specified.

    By convention, the sqlite query can contain following placeholders that
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
      * {batch_filter}: the filter to be applied per batch when using
        parallel processing

    Example: left outer join all features in input1 layer with all rows
    in input2 on join_id.
    ::

        import geofileops as gfo

        minimum_area = 100
        sql_stmt = f'''
                SELECT layer1.{{input1_geometrycolumn}}
                      {{layer1_columns_prefix_alias_str}}
                      {{layer2_columns_prefix_alias_str}}
                  FROM {{input1_databasename}}."{{input1_layer}}" layer1
                  LEFT OUTER JOIN {{input2_databasename}}."{{input2_layer}}" layer2
                    ON layer1.join_id = layer2.join_id
                 WHERE 1=1
                   {{batch_filter}}
                   AND ST_Area(layer1.{{input1_geometrycolumn}}) > {minimum_area}
                '''
        gfo.select_two_layers(
                input1_path=...,
                input2_path=...,
                output_path=...,
                sql_stmt=sql_stmt)

    Some important remarks:

    * Because some sql statement won't give the same result when parallelized
      (eg. when using a group by statement), nb_parallel is 1 by default.
      If you do want to use parallel processing, specify nb_parallel + make
      sure to include the placeholder {batch_filter} in your sql_stmt.
      This placeholder will be replaced with a filter of the form
      'AND rowid >= x AND rowid < y'.
    * Table names are best double quoted as in the example, because some
      characters are otherwise not supported in the table name, eg. '-'.
    * When using supported placeholders, make sure you give the tables you
      select from the appropriate table aliases (layer1, layer2).
    * Besides the standard sqlite sql syntacs, you can use the spatialite
      functions as documented here: |sqlite_reference_link|
    * It is supported to use attribute tables (= table without geometry column) as
      input layers and/or not to include the geometry column in the selected columns.
      Note though that if the column placeholders are used (e.g.
      {layer1_columns_prefix_str}), they will start with a "," and if no column precedes
      it the SQL statement will be invalid.


    .. |sqlite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    The result is written to the output file specified.

    Args:
        input1_path (PathLike): the 1st input file.
        input2_path (PathLike): the 2nd input file.
        output_path (PathLike): the file to write the result to.
        sql_stmt (str): the SELECT sql statement to be executed.
        input1_layer (str, optional): input layer name. Optional if the
            file only contains one layer. Defaults to None.
        input1_columns (List[str], optional): list of columns to retain if one of the
            {layer1_columns_...} placeholders is used in sql_stmt. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased even if input1_columns_prefix is "", eg. to
            "fid_1". Defaults to None.
        input1_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l1_".
        input2_layer (str, optional): input layer name. Optional if the
            file only contains one layer. Defaults to None.
        input2_columns (List[str], optional): list of columns to retain if one of the
            {layer2_columns_...} placeholders is used in sql_stmt. If None is specified,
            all columns are selected. As explained for input1_columns, it is also
            possible to specify "fid". Defaults to None.
        input2_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l2_".
        output_layer (str, optional): output layer name. If None, the output_path stem
            is used. Defaults to None.
        explodecollections (bool, optional): True to convert all multi-geometries to
            singular ones after the dissolve. Defaults to False.
        force_output_geometrytype (GeometryType, optional): The output geometry
            type to force. Defaults to None, and then the geometry type of the
            input1 layer is used.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): sql filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    **Some more advanced example queries**

    An ideal place to get inspiration to write you own advanced queries
    is in the following source code file: |geofileops_sql_link|.

    Additionally, there are some examples listed here that highlight
    other features/possibilities.

    *Join nearest features*

    For each feature in layer1, get the nearest feature of layer2 with the
    same values for the column join_id.

        .. code-block:: sqlite3

            WITH join_with_dist AS (
                SELECT layer2.{{input2_geometrycolumn}}
                      {{layer1_columns_prefix_alias_str}}
                      {{layer2_columns_prefix_alias_str}}
                      ,ST_Distance(layer2.{{input2_geometrycolumn}}
                      ,layer1.{{input1_geometrycolumn}}) AS distance
                 FROM {{input1_databasename}}."{{input1_layer}}" layer1
                 JOIN {{input2_databasename}}."{{input2_layer}}" layer2
                   ON layer1.join_id = layer2.join_id
                )
            SELECT *
              FROM join_with_dist jwd
             WHERE distance = (
                   SELECT MIN(distance) FROM join_with_dist jwd_sub
                    WHERE jwd_sub.l1_join_id = jwd.l1_join_id)
             ORDER BY distance DESC

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    .. |geofileops_sql_link| raw:: html

        <a href="https://github.com/geofileops/geofileops/blob/main/geofileops/util/geofileops_sql.py" target="_blank">geofileops_sql.py</a>

    """  # noqa: E501
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
    input2_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    input1_layer: Optional[str] = None,
    input1_columns: Optional[List[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[List[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 2000,
    force: bool = False,
):
    """
    Calculates the "symmetric difference" of the two input layers.

    Alternative names:
        - GeoPandas: overlay(how="symmetric_difference")
        - QGIS, ArcMap: symmetrical difference

    Args:
        input1_path (PathLike): the 1st input file
        input2_path (PathLike): the 2nd input file
        output_path (PathLike): the file to write the result to
        input1_layer (str, optional): input layer name. Optional if the
            file only contains one layer. Defaults to None.
        input1_columns (List[str], optional): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased even if input1_columns_prefix is "", eg. to
            "fid_1". Defaults to None.
        input1_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l1_".
        input2_layer (str, optional): input layer name. Optional if the
            file only contains one layer. Defaults to None.
        input2_columns (List[str], optional): columns to select. If None is specified,
            all columns are selected. As explained for input1_columns, it is also
            possible to specify "fid". Defaults to None.
        input2_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l2_".
        output_layer (str, optional): output layer name. If None, the output_path stem
            is used. Defaults to None.
        explodecollections (bool, optional): True to convert all multi-geometries to
            singular ones after the dissolve. Defaults to False.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): sql filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduc
            e the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        subdivide_coords (int, optional): the input geometries will be subdivided to
            parts with about subdivide_coords coordinates during processing which can
            offer a large speed up for complex geometries. Subdividing can result in
            extra collinear points being added to the boundaries of the output. If < 0,
            no subdividing is applied. Defaults to 2000.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    logger = logging.getLogger("geofileops.symmetric_difference")
    logger.info(
        f"Start, with input1: {input1_path}, "
        f"input2 {input2_path}, output: {output_path}"
    )
    return _geoops_sql.symmetric_difference(
        input1_path=Path(input1_path),
        input2_path=Path(input2_path),
        output_path=Path(output_path),
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
    input1_path: Path,
    input2_path: Path,
    output_path: Path,
    input1_layer: Optional[str] = None,
    input1_columns: Optional[List[str]] = None,
    input1_columns_prefix: str = "l1_",
    input2_layer: Optional[str] = None,
    input2_columns: Optional[List[str]] = None,
    input2_columns_prefix: str = "l2_",
    output_layer: Optional[str] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    subdivide_coords: int = 2000,
    force: bool = False,
):
    """
    Calculates the pairwise "union" of the two input layers.

    Alternative names:
        - GeoPandas: overlay(how="union")

    Args:
        input1_path (PathLike): the 1st input file
        input2_path (PathLike): the 2nd input file
        output_path (PathLike): the file to write the result to
        input1_layer (str, optional): input layer name. Optional if the
            file only contains one layer. Defaults to None.
        input1_columns (List[str], optional): list of columns to retain. If None, all
            standard columns are retained. In addition to standard columns, it is also
            possible to specify "fid", a unique index available in all input files. Note
            that the "fid" will be aliased even if input1_columns_prefix is "", eg. to
            "fid_1". Defaults to None.
        input1_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l1_".
        input2_layer (str, optional): input layer name. Optional if the
            file only contains one layer. Defaults to None.
        input2_columns (List[str], optional): columns to select. If None is specified,
            all columns are selected. As explained for input1_columns, it is also
            possible to specify "fid". Defaults to None.
        input2_columns_prefix (str, optional): prefix to use in the column aliases.
            Defaults to "l2_".
        output_layer (str, optional): output layer name. If None, the output_path stem
            is used. Defaults to None.
        explodecollections (bool, optional): True to convert all multi-geometries to
            singular ones after the dissolve. Defaults to False.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        where_post (str, optional): sql filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): the number of parallel processes to use.
            Defaults to -1: use all available CPUs.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        subdivide_coords (int, optional): the input geometries will be subdivided to
            parts with about subdivide_coords coordinates during processing which can
            offer a large speed up for complex geometries. Subdividing can result in
            extra collinear points being added to the boundaries of the output. If < 0,
            no subdividing is applied. Defaults to 2000.
        force (bool, optional): overwrite existing output file(s).
            Defaults to False.

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    logger = logging.getLogger("geofileops.union")
    logger.info(
        f"Start, with input1: {input1_path}, input2: {input2_path}, output: "
        f"{output_path}"
    )
    return _geoops_sql.union(
        input1_path=Path(input1_path),
        input2_path=Path(input2_path),
        output_path=Path(output_path),
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
