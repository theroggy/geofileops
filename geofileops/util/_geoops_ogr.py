from datetime import datetime
import logging
from pathlib import Path
from typing import List, Literal, Optional, Tuple, Union

from pygeoops import GeometryType
from shapely import wkt

import geofileops as gfo
from geofileops.util import _ogr_util

logger = logging.getLogger(__name__)


def clip_by_geometry(
    input_path: Path,
    output_path: Path,
    clip_geometry: Union[Tuple[float, float, float, float], str],
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    force: bool = False,
):
    spatial_filter = None
    if isinstance(clip_geometry, str):
        geom = wkt.loads(clip_geometry)
        spatial_filter = tuple(geom.bounds)

    _run_ogr(
        operation="clip_by_geometry",
        input_path=input_path,
        output_path=output_path,
        spatial_filter=spatial_filter,  # type: ignore[arg-type]
        clip_geometry=clip_geometry,
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        force=force,
    )


def export_by_bounds(
    input_path: Path,
    output_path: Path,
    bounds: Tuple[float, float, float, float],
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    force: bool = False,
):
    _run_ogr(
        operation="export_by_bounds",
        input_path=input_path,
        output_path=output_path,
        spatial_filter=bounds,
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        force=force,
    )


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
    warp = {
        "gcps": gcps,
        "algorithm": algorithm,
        "order": order,
    }

    _run_ogr(
        operation="warp",
        input_path=input_path,
        output_path=output_path,
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        warp=warp,
        force=force,
    )


def _run_ogr(
    operation: str,
    input_path: Path,
    output_path: Path,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    input_srs: Union[int, str, None] = None,
    output_srs: Union[int, str, None] = None,
    reproject: bool = False,
    spatial_filter: Optional[Tuple[float, float, float, float]] = None,
    clip_geometry: Optional[Union[Tuple[float, float, float, float], str]] = None,
    sql_stmt: Optional[str] = None,
    sql_dialect: Optional[Literal["SQLITE", "OGRSQL"]] = None,
    transaction_size: int = 65536,
    append: bool = False,
    update: bool = False,
    explodecollections: bool = False,
    force_output_geometrytype: Optional[GeometryType] = None,
    options: dict = {},
    columns: Optional[List[str]] = None,
    warp: Optional[dict] = None,
    force: bool = False,
) -> bool:
    # Init
    logger = logging.getLogger(f"geofileops.{operation}")
    start_time = datetime.now()
    if input_layer is None:
        input_layer = gfo.get_only_layer(input_path)
    if output_path.exists():
        if force:
            gfo.remove(output_path)
        else:
            logger.info(f"Stop, output exists already {output_path}")
            return True

    if input_layer is None:
        input_layer = gfo.get_only_layer(input_path)
    if output_layer is None:
        output_layer = gfo.get_default_layer(output_path)

    info = _ogr_util.VectorTranslateInfo(
        input_path=input_path,
        output_path=output_path,
        input_layers=input_layer,
        output_layer=output_layer,
        input_srs=input_srs,
        output_srs=output_srs,
        reproject=reproject,
        spatial_filter=spatial_filter,
        clip_geometry=clip_geometry,
        sql_stmt=sql_stmt,
        sql_dialect=sql_dialect,
        transaction_size=transaction_size,
        append=append,
        update=update,
        explodecollections=explodecollections,
        force_output_geometrytype=force_output_geometrytype,
        options=options,
        columns=columns,
        warp=warp,
    )

    # Run + return result
    result = _ogr_util.vector_translate_by_info(info)
    logger.info(f"Ready, took {datetime.now()-start_time}")
    return result
