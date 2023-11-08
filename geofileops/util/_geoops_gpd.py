"""
Module containing the implementation of Geofile operations using GeoPandas.
"""

from concurrent import futures
import copy
from datetime import datetime
import enum
import json
import logging
import logging.config
import math
import multiprocessing
from pathlib import Path
import pickle
import re
import shutil
import time
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple, Union
import warnings

import cloudpickle
import geopandas as gpd
import numpy as np
import pandas as pd
import pygeoops
import psutil

from pygeoops import GeometryType, PrimitiveType
import shapely
import shapely.geometry as sh_geom

import geofileops as gfo
from geofileops import fileops
from geofileops.helpers import _parameter_helper
from geofileops.util import _general_util
from geofileops.util import _geoops_sql
from geofileops.util import _geoseries_util
from geofileops.util import _io_util
from geofileops.util import _ogr_util
from geofileops.util import _processing_util
from geofileops.util._geometry_util import SimplifyAlgorithm
from geofileops.util._geometry_util import BufferEndCapStyle, BufferJoinStyle

# Don't show this geopandas warning...
warnings.filterwarnings("ignore", "GeoSeries.isna", UserWarning)

logger = logging.getLogger(__name__)


class ParallelizationConfig:
    """
    Heuristics for geopandas based geo operations.

    Heuristics meant to be able to optimize the parallelisation parameters for
    geopandas based geo operation.
    """

    def __init__(
        self,
        bytes_basefootprint: int = 50 * 1024 * 1024,
        bytes_per_row: int = 1000,
        min_rows_per_batch: int = 1000,
        max_rows_per_batch: int = 100000,
        bytes_min_per_process: Optional[int] = None,
        bytes_usable: Optional[int] = None,
        cpu_count: int = -1,
    ):
        """
        Heuristics for geopandas based geo operations.

        Heuristics meant to be able to optimize the parallelisation parameters for
        geopandas based geo operation.

        Args:
            bytes_basefootprint (int, optional): The base memory usage of a geofileops
                worker process. Defaults to 50 MB.
            bytes_per_row (int, optional): The number if bytes needed to store/process
                one row of data. Defaults to 1000.
            min_rows_per_batch (int, optional): The minimum number of rows to aim for in
                one batch. Defaults to 1000.
            max_rows_per_batch (int, optional): The maximum number of rows to aim for in
                a batch. Defaults to 100000.
            bytes_min_per_process (Optional[int], optional): The minimum number of bytes
                needed for a geofileops worker process. Defaults to None.
            bytes_usable (Optional[int], optional): the memory available for processing.
                Defaults to None, then the free memory is automatically determined.
            cpu_count (int, optional): the number of CPU's available. Defaults to -1,
                then the cpu_count is determined automatically.
        """
        self.bytes_basefootprint = bytes_basefootprint
        self.bytes_per_row = bytes_per_row
        self.min_rows_per_batch = min_rows_per_batch
        self.max_rows_per_batch = max_rows_per_batch

        # Needs some logic to get value if not set explicitly...
        self._bytes_min_per_process = bytes_min_per_process
        # If not specified, determine yourself
        self.bytes_usable = (
            bytes_usable
            if bytes_usable is not None
            else int(psutil.virtual_memory().available * 0.9)
        )
        # If not specified, determine yourself
        self.cpu_count = cpu_count if cpu_count > 0 else multiprocessing.cpu_count()

    @property
    def bytes_min_per_process(self):
        if self._bytes_min_per_process is not None:
            return self._bytes_min_per_process
        else:
            return (
                self.bytes_basefootprint + self.bytes_per_row * self.min_rows_per_batch
            )

    @bytes_min_per_process.setter
    def bytes_min_per_process(self, value):
        self._bytes_min_per_process = value


def _determine_nb_batches(
    nb_rows_total: int,
    nb_parallel: int = -1,
    batchsize: int = -1,
    parallelization_config: Optional[ParallelizationConfig] = None,
) -> Tuple[int, int]:
    """
    Determines recommended parallelization params.

    Args:
        nb_rows_total (int): The total number of rows that will be processed
        nb_parallel (int): The level of parallelization requested.
            If -1, tries to use all resources available.
        batchsize (int): indicative number of rows to process per batch.
            If -1: (try to) determine optimal size automatically using the heuristics in
            'parallelization_config'.
        parallelization_config (ParallelizationConfig, optional): Configuration
            parameters to use to suggest parallelisation parameters.

    Returns:
        Tuple[int, int]: Tuple of (nb_parallel, nb_batches)
    """
    # If 0 or 1 rows to process, one batch
    if nb_rows_total <= 1:
        return (1, 1)

    # If config is None, use default config
    if parallelization_config is None:
        config_local = ParallelizationConfig()
    else:
        config_local = copy.deepcopy(parallelization_config)

    # If the number of rows is really low, just use one batch
    if nb_parallel < 1 and batchsize < 1:
        if nb_rows_total <= config_local.min_rows_per_batch:
            return (1, 1)

    if nb_parallel <= 0:
        nb_parallel = config_local.cpu_count

    if logger.isEnabledFor(logging.DEBUG):
        mem_usable = _general_util.formatbytes(config_local.bytes_usable)
        logger.debug(f"memory_usable: {mem_usable}, with:")
        mem_available = _general_util.formatbytes(psutil.virtual_memory().available)
        logger.debug(f"  -> mem.available: {mem_available}")
        swap_free = _general_util.formatbytes(psutil.swap_memory().free)
        logger.debug(f"  -> swap.free: {swap_free}")

    # If not enough memory for the amount of parallellism asked, reduce
    if (nb_parallel * config_local.bytes_min_per_process) > config_local.bytes_usable:
        nb_parallel = int(
            config_local.bytes_usable / config_local.bytes_min_per_process
        )
        logger.debug(f"Nb_parallel reduced to {nb_parallel} to reduce memory usage")

    # Having more workers than rows doesn't make sense
    if nb_parallel > nb_rows_total:
        nb_parallel = nb_rows_total

    # If batchsize is specified, use it to determine number of batches.
    if batchsize > 0:
        nb_batches = math.ceil(nb_rows_total / batchsize)

        # No use to have more workers than number of batches
        if nb_parallel > nb_batches:
            nb_parallel = nb_batches

        return (nb_parallel, nb_batches)

    # No batchsize specified, so use heuristics.
    # Start with 1 batch per worker
    nb_batches = nb_parallel

    # If the batches < min_rows_per_batch, decrease number batches
    if nb_rows_total / nb_batches < config_local.min_rows_per_batch:
        nb_batches = math.ceil(nb_rows_total / config_local.min_rows_per_batch)

    # If the batches > max_rows_per_batch, increase number batches
    if nb_rows_total / nb_batches > config_local.max_rows_per_batch:
        nb_batches = math.ceil(nb_rows_total / config_local.max_rows_per_batch)
        # Round nb_batches up to the nearest multiple of nb_parallel
        nb_batches = math.ceil(nb_batches / nb_parallel) * nb_parallel

    # Having more workers than batches isn't logical...
    if nb_parallel > nb_batches:
        nb_parallel = nb_batches

    # Finally, make sure there are enough batches to avoid memory issues:
    #   = total memory usage for all rows /
    #     (free memory - base memory used by all parallel processes)
    nb_batches_min = math.ceil(
        (nb_rows_total * config_local.bytes_per_row)
        / (config_local.bytes_usable - config_local.bytes_basefootprint * nb_parallel)
    )
    if nb_batches < nb_batches_min:
        # Round nb_batches up to the nearest multiple of nb_parallel
        nb_batches = math.ceil(nb_batches_min / nb_parallel) * nb_parallel

    # Log result
    if logger.isEnabledFor(logging.DEBUG):
        batchsize = math.ceil(nb_rows_total / nb_batches)
        mem_predicted = (
            config_local.bytes_basefootprint + batchsize * config_local.bytes_per_row
        ) * nb_batches

        logger.debug(
            f"nb_batches_recommended: {nb_batches}, rows_per_batch: {batchsize}"
        )
        logger.debug(f" -> nb_rows_input_layer: {nb_rows_total}")
        logger.debug(f" -> mem_predicted: {_general_util.formatbytes(mem_predicted)}")

    return (nb_parallel, nb_batches)


class ProcessingParams:
    def __init__(
        self,
        nb_rows_to_process: int,
        nb_parallel: int,
        batches: List[str],
        batchsize: int,
    ):
        self.nb_rows_to_process = nb_rows_to_process
        self.nb_parallel = nb_parallel
        self.batches = batches
        self.batchsize = batchsize

    def to_json(self, path: Path):
        prepared = _general_util.prepare_for_serialize(vars(self))
        with open(path, "w") as file:
            file.write(json.dumps(prepared, indent=4, sort_keys=True))


def _prepare_processing_params(
    input_path: Path,
    input_layer: str,
    nb_parallel: int,
    batchsize: int,
    parallelization_config: Optional[ParallelizationConfig] = None,
    tmp_dir: Optional[Path] = None,
) -> ProcessingParams:
    input_info = gfo.get_layerinfo(input_path, input_layer)
    fid_column = input_info.fid_column if input_info.fid_column != "" else "fid"
    nb_parallel, nb_batches = _determine_nb_batches(
        nb_rows_total=input_info.featurecount,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        parallelization_config=parallelization_config,
    )

    # Prepare batches to process
    batches: List[str] = []
    if nb_batches == 1:
        # If only one batch, no filtering is needed
        batches.append("")
    else:
        # Determine the min_fid and max_fid
        # Remark: SELECT MIN(fid), MAX(fid) FROM ... is a lot slower than UNION ALL!
        sql_stmt = f"""
            SELECT MIN({fid_column}) minmax_fid FROM "{input_info.name}"
            UNION ALL
            SELECT MAX({fid_column}) minmax_fid FROM "{input_info.name}"
        """
        batch_info_df = gfo.read_file(path=input_path, sql_stmt=sql_stmt)
        min_fid = pd.to_numeric(batch_info_df["minmax_fid"][0]).item()
        max_fid = pd.to_numeric(batch_info_df["minmax_fid"][1]).item()

        # Determine the exact batches to use
        if ((max_fid - min_fid) / input_info.featurecount) < 1.1:
            # If the fid's are quite consecutive, use an imperfect, but
            # fast distribution in batches
            batch_info_list = []
            nb_rows_per_batch = round(input_info.featurecount / nb_batches)
            offset = 0
            offset_per_batch = round((max_fid - min_fid) / nb_batches)
            for batch_id in range(nb_batches):
                start_fid = offset
                if batch_id < (nb_batches - 1):
                    # End fid for this batch is the next start_fid - 1
                    end_fid = offset + offset_per_batch - 1
                else:
                    # For the last batch, take the max_fid so no fid's are
                    # 'lost' due to rounding errors
                    end_fid = max_fid
                batch_info_list.append(
                    (batch_id, nb_rows_per_batch, start_fid, end_fid)
                )
                offset += offset_per_batch
            batch_info_df = pd.DataFrame(
                batch_info_list, columns=["batch_id", "nb_rows", "start_fid", "end_fid"]
            )
        else:
            # The fids are not consecutive, so determine the optimal fid
            # ranges for each batch so each batch has same number of elements
            # Remark: - this might take some seconds for larger datasets!
            #         - (batch_id - 1) AS id to make the id zero-based
            sql_stmt = f"""
                SELECT (batch_id_1 - 1) AS batch_id
                      ,COUNT(*) AS nb_rows
                      ,MIN({fid_column}) AS start_fid
                      ,MAX({fid_column}) AS end_fid
                  FROM
                    ( SELECT {fid_column}
                            ,NTILE({nb_batches}) OVER (ORDER BY {fid_column}) batch_id_1
                        FROM "{input_info.name}"
                    )
                 GROUP BY batch_id_1;
            """
            batch_info_df = gfo.read_file(path=input_path, sql_stmt=sql_stmt)

        # Now loop over all batch ranges to build up the necessary filters
        for batch_info in batch_info_df.itertuples():
            # The batch filter
            if batch_info.batch_id < nb_batches - 1:
                batches.append(
                    f"({fid_column} >= {batch_info.start_fid} "
                    f"AND {fid_column} <= {batch_info.end_fid}) "
                )
            else:
                batches.append(f"{fid_column} >= {batch_info.start_fid} ")

    # No use starting more processes than the number of batches...
    if len(batches) < nb_parallel:
        nb_parallel = len(batches)

    returnvalue = ProcessingParams(
        nb_rows_to_process=input_info.featurecount,
        nb_parallel=nb_parallel,
        batches=batches,
        batchsize=int(input_info.featurecount / len(batches)),
    )

    if tmp_dir is not None:
        returnvalue.to_json(tmp_dir / "processing_params.json")
    return returnvalue


class GeoOperation(enum.Enum):
    SIMPLIFY = "simplify"
    BUFFER = "buffer"
    CONVEXHULL = "convexhull"
    APPLY = "apply"


def apply(
    input_path: Path,
    output_path: Path,
    func: Callable[[Any], Any],
    operation_name: Optional[str] = None,
    only_geom_input: bool = True,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    force_output_geometrytype: Union[GeometryType, str, None] = None,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = True,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    # Init
    operation_params = {
        "only_geom_input": only_geom_input,
        "pickled_func": cloudpickle.dumps(func),
    }
    if operation_name is not None:
        operation_params["operation_name"] = operation_name

    # Go!
    return _apply_geooperation_to_layer(
        input_path=input_path,
        output_path=output_path,
        operation=GeoOperation.APPLY,
        operation_params=operation_params,
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
    input_path: Path,
    output_path: Path,
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
    keep_empty_geoms: bool = True,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
    operation_prefix: str = "",
):
    # Init
    operation_params = {
        "operation_name": f"{operation_prefix}buffer",
        "distance": distance,
        "quadrantsegments": quadrantsegments,
        "endcap_style": endcap_style,
        "join_style": join_style,
        "mitre_limit": mitre_limit,
        "single_sided": single_sided,
    }

    # Buffer operation always results in polygons...
    if explodecollections:
        force_output_geometrytype = GeometryType.POLYGON.name
    else:
        force_output_geometrytype = GeometryType.MULTIPOLYGON.name

    # Go!
    return _apply_geooperation_to_layer(
        input_path=input_path,
        output_path=output_path,
        operation=GeoOperation.BUFFER,
        operation_params=operation_params,
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


def convexhull(
    input_path: Path,
    output_path: Path,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = True,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    # Init
    operation_params: Dict[str, Any] = {}

    # Go!
    return _apply_geooperation_to_layer(
        input_path=input_path,
        output_path=output_path,
        operation=GeoOperation.CONVEXHULL,
        operation_params=operation_params,
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        force_output_geometrytype=None,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def makevalid(
    input_path: Path,
    output_path: Path,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    force_output_geometrytype: Optional[GeometryType] = None,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = True,
    where_post: Optional[str] = None,
    validate_attribute_data: bool = False,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    # Determine if collapsed parts need to be kept after makevalid or not
    keep_collapsed = True
    if force_output_geometrytype is None:
        keep_collapsed = False
    else:
        if isinstance(force_output_geometrytype, GeometryType):
            force_output_geometrytype = force_output_geometrytype.name
        info = fileops.get_layerinfo(input_path)
        if force_output_geometrytype.startswith(
            info.geometrytypename
        ) or info.geometrytypename.startswith(force_output_geometrytype):
            keep_collapsed = False

    apply(
        input_path=Path(input_path),
        output_path=Path(output_path),
        func=lambda geom: pygeoops.make_valid(
            geom, keep_collapsed=keep_collapsed, only_if_invalid=True
        ),
        operation_name="makevalid",
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


def simplify(
    input_path: Path,
    output_path: Path,
    tolerance: float,
    algorithm: SimplifyAlgorithm = SimplifyAlgorithm.RAMER_DOUGLAS_PEUCKER,
    lookahead: int = 8,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[List[str]] = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = True,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    # Init
    operation_params = {
        "tolerance": tolerance,
        "algorithm": algorithm,
        "step": lookahead,
    }

    # Go!
    return _apply_geooperation_to_layer(
        input_path=input_path,
        output_path=output_path,
        operation=GeoOperation.SIMPLIFY,
        operation_params=operation_params,
        input_layer=input_layer,
        output_layer=output_layer,
        columns=columns,
        explodecollections=explodecollections,
        force_output_geometrytype=None,
        gridsize=gridsize,
        keep_empty_geoms=keep_empty_geoms,
        where_post=where_post,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        force=force,
    )


def _apply_geooperation_to_layer(
    input_path: Path,
    output_path: Path,
    operation: GeoOperation,
    operation_params: dict,
    input_layer: Optional[str],  # = None
    columns: Optional[List[str]],  # = None
    output_layer: Optional[str],  # = None
    explodecollections: bool,  # = False
    force_output_geometrytype: Union[GeometryType, str, None],  # = None
    gridsize: float,  # = 0.0
    keep_empty_geoms: bool,  # = True
    where_post: Optional[str],  # = None
    nb_parallel: int,  # = -1
    batchsize: int,  # = -1
    force: bool,  # = False
):
    """
    Applies a geo operation on a layer.

    The operation to apply can be one of the the following:
      - BUFFER: apply a buffer. Operation parameters:
          - distance: distance to buffer
          - quadrantsegments: number of points used to represent 1/4 of a circle
          - endcap_style: buffer style to use for a point or the end points of
            a line:
            - ROUND: for points and lines the ends are buffered rounded.
            - FLAT: a point stays a point, a buffered line will end flat
              at the end points
            - SQUARE: a point becomes a square, a buffered line will end
              flat at the end points, but elongated by "distance"
        - join_style: buffer style to use for corners in a line or a polygon
          boundary:
            - ROUND: corners in the result are rounded
            - MITRE: corners in the result are sharp
            - BEVEL: are flattened
        - mitre_limit: in case of join_style MITRE, if the
            spiky result for a sharp angle becomes longer than this limit, it
            is "beveled" at this distance. Defaults to 5.0.
        - single_sided: only one side of the line is buffered,
            if distance is negative, the left side, if distance is positive,
            the right hand side. Only relevant for line geometries.
      - CONVEXHULL: appy a convex hull.
      - SIMPLIFY: simplify the geometry. Operation parameters:
          - algorithm: vector_util.SimplifyAlgorithm
          - tolerance: maximum distance to simplify.
          - lookahead: for LANG, the number of points to forward-look
      - APPLY: apply a lambda function. Operation parameter:
          - pickled_func: lambda function to apply, pickled to bytes.
          - only_geom_input: if True, only the geometry is available as
            input for the lambda function. If false, the row is the input.

    Args:
        input_path (Path): [description]
        output_path (Path): [description]
        operation (GeoOperation): the geo operation to apply.
        operation_params (dict, optional): the parameters for the geo operation.
            Defaults to None.
        input_layer (str, optional): [description]. Defaults to None.
        output_layer (str, optional): [description]. Defaults to None.
        columns (List[str], optional): If not None, only output the columns
            specified. Defaults to None.
        explodecollections (bool, optional): True to convert all multi-geometries to
            singular ones during the geooperation. Defaults to False.
        force_output_geometrytype (GeometryType, optional): The output geometry type to
            force. If None, a best-effort guess is made. Defaults to None.
        gridsize (float, optional): the size of the grid the coordinates of the ouput
            will be rounded to. Eg. 0.001 to keep 3 decimals. Value 0.0 doesn't change
            the precision. Defaults to 0.0.
        keep_empty_geoms (bool, optional): True to keep rows with empty/null geometries
            in the output. Defaults to True.
        where_post (str, optional): sql filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): [description]. Defaults to -1.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): [description]. Defaults to False.

    Technical remarks:
        - Retaining None geometry values in the output files is hard, because when
          calculating partial files, a partial file can have only None geometries which
          makes it impossible to know the geometry type. Once an output file is created,
          it is also impossible to change the type afterwards (without making a copy).
          If force_output_type is specified, the problem is gone.

    .. |spatialite_reference_link| raw:: html

        <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite reference</a>

    """  # noqa: E501
    # Init
    start_time_global = datetime.now()
    operation_name = operation_params.get("operation_name")
    if operation_name is None:
        operation_name = operation.value
    logger = logging.getLogger(f"geofileops.{operation_name}")

    # Check input parameters...
    if not input_path.exists():
        raise ValueError(f"{operation_name}: input_path doesn't exist: {input_path}")
    if input_path == output_path:
        raise ValueError(f"{operation_name}: output_path must not equal input_path")
    if input_layer is None:
        input_layer = gfo.get_only_layer(input_path)
    if output_path.exists():
        if force is False:
            logger.info(f"Stop, output exists already {output_path}")
            return
        else:
            gfo.remove(output_path)
    if input_layer is None:
        input_layer = gfo.get_only_layer(input_path)
    if output_layer is None:
        output_layer = gfo.get_default_layer(output_path)
    if isinstance(force_output_geometrytype, GeometryType):
        force_output_geometrytype = force_output_geometrytype.name

    # Check if we want to preserve the fid in the output
    preserve_fid = False
    if not explodecollections and gfo.get_driver(output_path) == "GPKG":
        preserve_fid = True

    # Prepare where_to_apply and filter_null_geoms
    if where_post is not None:
        if where_post == "":
            where_post = None
        else:
            # Always set geometrycolumn to "geom", because where_post parameter for shp
            # doesn't seem to work... so create temp partial files always as gpkg.
            where_post = where_post.format(geometrycolumn="geom")

    # Prepare tmp files
    tmp_dir = _io_util.create_tempdir(f"geofileops/{operation.value}")
    logger.debug(f"Start calculation to temp files in {tmp_dir}")

    try:
        # Calculate the best number of parallel processes and batches for
        # the available resources
        processing_params = _prepare_processing_params(
            input_path=input_path,
            input_layer=input_layer,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            parallelization_config=None,
            tmp_dir=tmp_dir,
        )
        assert processing_params.batches is not None

        logger.info(
            f"Start processing ({processing_params.nb_parallel} "
            f"parallel workers, batch size: {processing_params.batchsize})"
        )
        # Processing in threads is 2x faster for small datasets (on Windows)
        calculate_in_threads = (
            True if processing_params.nb_rows_to_process <= 100 else False
        )
        with _processing_util.PooledExecutorFactory(
            threadpool=calculate_in_threads,
            max_workers=processing_params.nb_parallel,
            initializer=_processing_util.initialize_worker(),
        ) as calculate_pool:
            # Prepare output filename
            tmp_output_path = tmp_dir / output_path.name

            batches: Dict[int, dict] = {}
            future_to_batch_id = {}
            nb_batches = len(processing_params.batches)
            nb_done = 0

            for batch_id, batch_filter in enumerate(processing_params.batches):
                batches[batch_id] = {}
                batches[batch_id]["layer"] = output_layer

                # Output each batch to a seperate temporary file, otherwise there
                # are timeout issues when processing large files
                output_tmp_partial_path = (
                    tmp_dir / f"{output_path.stem}_{batch_id}.gpkg"
                )
                batches[batch_id]["tmp_partial_output_path"] = output_tmp_partial_path
                batches[batch_id]["filter"] = batch_filter

                # Remark: this temp file doesn't need spatial index
                # Remark: because force_output_geometrytype for GeoDataFrame
                # operations is (a lot) more limited than gdal-based, the gdal version
                # is used later on when the results are merged to the result file.
                future = calculate_pool.submit(
                    _apply_geooperation,
                    input_path=input_path,
                    output_path=output_tmp_partial_path,
                    operation=operation,
                    operation_params=operation_params,
                    input_layer=input_layer,
                    columns=columns,
                    output_layer=output_layer,
                    where=batch_filter,
                    explodecollections=explodecollections,
                    gridsize=gridsize,
                    keep_empty_geoms=keep_empty_geoms,
                    preserve_fid=preserve_fid,
                    force=force,
                )
                future_to_batch_id[future] = batch_id

            # Loop till all parallel processes are ready, but process each one
            # that is ready already
            # Remark: calculating can be done in parallel, but only one process
            # can write to the same output file at the time...
            start_time = datetime.now()
            _general_util.report_progress(
                start_time,
                nb_done,
                nb_todo=nb_batches,
                operation=operation.value,
                nb_parallel=processing_params.nb_parallel,
            )
            for future in futures.as_completed(future_to_batch_id):
                try:
                    message = future.result()
                    logger.debug(message)

                    # If the calculate gave results, copy to output
                    batch_id = future_to_batch_id[future]
                    tmp_partial_output_path = batches[batch_id][
                        "tmp_partial_output_path"
                    ]
                    if (
                        tmp_partial_output_path.exists()
                        and tmp_partial_output_path.stat().st_size > 0
                    ):
                        # Remark: because force_output_geometrytype for GeoDataFrame
                        # operations is (a lot) more limited than gdal-based, use the
                        # gdal version via _append_to_nolock.
                        if (
                            nb_batches == 1
                            and force_output_geometrytype is None
                            and tmp_partial_output_path.suffix == tmp_output_path.suffix
                            and where_post is None
                        ):
                            gfo.move(tmp_partial_output_path, tmp_output_path)
                        else:
                            fileops._append_to_nolock(
                                src=tmp_partial_output_path,
                                dst=tmp_output_path,
                                explodecollections=explodecollections,
                                create_spatial_index=False,
                                force_output_geometrytype=force_output_geometrytype,
                                where=where_post,
                                preserve_fid=preserve_fid,
                            )
                            gfo.remove(tmp_partial_output_path)

                except Exception as ex:
                    batch_id = future_to_batch_id[future]
                    message = f"Error {ex} executing {batches[batch_id]}"
                    logger.exception(message)
                    raise RuntimeError(message) from ex

                # Log the progress and prediction speed
                nb_done += 1
                _general_util.report_progress(
                    start_time, nb_done, nb_batches, operation.value, nb_parallel
                )

        # Round up and clean up
        # Now create spatial index and move to output location
        if tmp_output_path.exists():
            gfo.create_spatial_index(path=tmp_output_path, layer=output_layer)
            gfo.move(tmp_output_path, output_path)
        else:
            logger.debug("Result was empty")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    logger.info(f"Ready, took {datetime.now()-start_time_global}")


def _apply_geooperation(
    input_path: Path,
    output_path: Path,
    operation: GeoOperation,
    operation_params: dict,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    columns: Optional[List[str]] = None,
    where=None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = True,
    preserve_fid: bool = False,
    force: bool = False,
) -> str:
    # Init
    if output_path.exists():
        if force is False:
            message = f"Stop, output exists already {output_path}"
            return message
        else:
            gfo.remove(output_path)

    # Now go!
    start_time = datetime.now()
    data_gdf = gfo.read_file(
        path=input_path,
        layer=input_layer,
        columns=columns,
        where=where,
        fid_as_index=preserve_fid,
    )

    # Run operation if data read
    if len(data_gdf) > 0:
        if operation is GeoOperation.BUFFER:
            data_gdf.geometry = data_gdf.geometry.buffer(
                distance=operation_params["distance"],
                resolution=operation_params["quadrantsegments"],
                cap_style=operation_params["endcap_style"].value,
                join_style=operation_params["join_style"].value,
                mitre_limit=operation_params["mitre_limit"],
                single_sided=operation_params["single_sided"],
            )
        elif operation is GeoOperation.CONVEXHULL:
            data_gdf.geometry = data_gdf.geometry.convex_hull
        elif operation is GeoOperation.SIMPLIFY:
            data_gdf.geometry = pygeoops.simplify(
                data_gdf.geometry,
                algorithm=operation_params["algorithm"].value,
                tolerance=operation_params["tolerance"],
                lookahead=operation_params["step"],
            )
        elif operation is GeoOperation.APPLY:
            func = pickle.loads(operation_params["pickled_func"])
            if operation_params["only_geom_input"] is True:
                data_gdf.geometry = data_gdf.geometry.apply(func)
            else:
                data_gdf.geometry = data_gdf.apply(func, axis=1)
        else:
            raise ValueError(f"operation not supported: {operation}")

    # Set empty geometries to null/None
    assert data_gdf.geometry is not None
    data_gdf.loc[data_gdf.geometry.is_empty, ["geometry"]] = None

    # If there is an fid column in the dataset, rename it, because the fid column is a
    # "special case" in gdal that should not be written.
    assert isinstance(data_gdf, gpd.GeoDataFrame)
    columns_lower_lookup = {column.lower(): column for column in data_gdf.columns}
    if "fid" in columns_lower_lookup:
        fid_column = columns_lower_lookup["fid"]
        for fid_number in range(1, 100):
            new_name = f"{fid_column}_{fid_number}"
            if new_name not in columns_lower_lookup:
                data_gdf = data_gdf.rename(columns={fid_column: new_name}, copy=False)
    if explodecollections:
        data_gdf = data_gdf.explode(ignore_index=True)

    if gridsize != 0.0:
        data_gdf.geometry = _geoseries_util.set_precision(
            data_gdf.geometry, grid_size=gridsize, raise_on_topoerror=False
        )

    # Remove rows where geom is None/null/empty
    if not keep_empty_geoms:
        assert isinstance(data_gdf, gpd.GeoDataFrame)
        data_gdf = data_gdf[~data_gdf.geometry.isna()]
        data_gdf = data_gdf[~data_gdf.geometry.is_empty]

    # If the result is empty, and no output geometrytype specified, use input
    # geometrytype
    force_output_geometrytype = None
    if len(data_gdf) == 0:
        input_layerinfo = gfo.get_layerinfo(input_path, input_layer)
        force_output_geometrytype = input_layerinfo.geometrytype.to_multitype.name

    # If the index is still unique, save it to fid column so to_file can save it
    if preserve_fid:
        data_gdf = data_gdf.reset_index(drop=False)

    # Use force_multitype, to avoid warnings when some batches contain
    # singletype and some contain multitype geometries
    gfo.to_file(
        gdf=data_gdf,
        path=output_path,
        layer=output_layer,
        index=False,
        force_output_geometrytype=force_output_geometrytype,
        force_multitype=True,
        create_spatial_index=False,
    )

    message = f"Took {datetime.now()-start_time} for {len(data_gdf)} rows ({where})"
    return message


def dissolve(
    input_path: Path,
    output_path: Path,
    groupby_columns: Optional[Iterable[str]] = None,
    agg_columns: Optional[dict] = None,
    explodecollections: bool = True,
    tiles_path: Optional[Path] = None,
    nb_squarish_tiles: int = 1,
    input_layer: Optional[str] = None,
    output_layer: Optional[str] = None,
    gridsize: float = 0.0,
    where_post: Optional[str] = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
    operation_prefix: str = "",
) -> dict:
    """
    Function that applies a dissolve.

    More detailed documentation in module geoops!

    Remark: keep_empty_geoms is not implemented because this is not so easy because
    (for polygon dissolve) the batches are location based, and null/empty geometries
    don't have a location. It could be implemented, but as long as nobody needs it...
    """
    # Init and validate input parameters
    # ----------------------------------
    start_time = datetime.now()
    operation_name = f"{operation_prefix}dissolve"
    logger = logging.getLogger(f"geofileops.{operation_name}")
    result_info = {}

    # Check input parameters
    if groupby_columns is not None and len(list(groupby_columns)) == 0:
        raise ValueError("groupby_columns=[] is not supported. Use None.")
    if not input_path.exists():
        raise ValueError(f"input_path doesn't exist: {input_path}")
    if input_path == output_path:
        raise ValueError("output_path must not equal input_path")

    input_layerinfo = gfo.get_layerinfo(input_path, input_layer)
    if input_layerinfo.geometrytype.to_primitivetype in [
        PrimitiveType.POINT,
        PrimitiveType.LINESTRING,
    ]:
        if tiles_path is not None or nb_squarish_tiles > 1:
            raise ValueError(
                f"Dissolve to tiles is not supported for {input_layerinfo.geometrytype}"
                ", so tiles_path should be None and nb_squarish_tiles should be 1)"
            )

    if input_layer is None:
        input_layer = gfo.get_only_layer(input_path)
    if output_layer is None:
        output_layer = gfo.get_default_layer(output_path)

    # Check columns in groupby_columns
    if groupby_columns is not None:
        columns_in_layer_upper = [
            column.upper() for column in list(input_layerinfo.columns) + ["fid"]
        ]
        for column in groupby_columns:
            if column.upper() not in columns_in_layer_upper:
                raise ValueError(
                    f"column in groupby_columns not available in layer: {column}"
                )

    # Check agg_columns param
    if agg_columns is not None:
        # Validate the dict structure, so we can assume everything is OK further on
        _parameter_helper.validate_agg_columns(agg_columns)

        # First take a deep copy, as values can be changed further on to treat columns
        # case insensitive
        agg_columns = json.loads(json.dumps(agg_columns))
        assert agg_columns is not None
        if "json" in agg_columns:
            if agg_columns["json"] is None:
                agg_columns["json"] = [
                    col for col in input_layerinfo.columns if col.upper() != "INDEX"
                ]
            else:
                # Align casing of column names to data
                agg_columns["json"] = _general_util.align_casing_list(
                    agg_columns["json"], list(input_layerinfo.columns) + ["fid"]
                )
        elif "columns" in agg_columns:
            # Loop through all rows
            for agg_column in agg_columns["columns"]:
                # Check if column exists + set casing same as in data
                agg_column["column"] = _general_util.align_casing(
                    agg_column["column"], list(input_layerinfo.columns) + ["fid"]
                )

    # Now input parameters are checked, check if we need to calculate anyway
    if output_path.exists():
        if force is False:
            result_info[
                "message"
            ] = f"Stop, output exists already {output_path} and force is false"
            logger.info(result_info["message"])
            return result_info
        else:
            gfo.remove(output_path)

    # Now start dissolving
    # --------------------
    # Empty or Line and point layers are:
    #   * not so large (memory-wise)
    #   * aren't computationally heavy
    # Additionally line layers are a pain to handle correctly because of
    # rounding issues at the borders of tiles... so just dissolve them in one go.
    if (
        input_layerinfo.featurecount == 0
        or input_layerinfo.geometrytype.to_primitivetype
        in [
            PrimitiveType.POINT,
            PrimitiveType.LINESTRING,
        ]
    ):
        _geoops_sql.dissolve_singlethread(
            input_path=input_path,
            output_path=output_path,
            explodecollections=explodecollections,
            groupby_columns=groupby_columns,
            agg_columns=agg_columns,
            input_layer=input_layer,
            output_layer=output_layer,
            gridsize=gridsize,
            keep_empty_geoms=False,
            where_post=where_post,
            force=force,
        )

    elif input_layerinfo.geometrytype.to_primitivetype is PrimitiveType.POLYGON:
        # Prepare where_post
        if where_post is not None:
            if where_post == "":
                where_post = None
            else:
                # Set geometrycolumn to "geom", because temp files are saved as gpkg.
                where_post = where_post.format(geometrycolumn="geom")

        # If a tiles_path is specified, read those tiles...
        result_tiles_gdf = None
        if tiles_path is not None:
            result_tiles_gdf = gfo.read_file(tiles_path)
            if nb_parallel == -1:
                nb_cpu = multiprocessing.cpu_count()
                nb_parallel = nb_cpu  # int(1.25 * nb_cpu)
                logger.debug(f"Nb cpus found: {nb_cpu}, nb_parallel: {nb_parallel}")
        else:
            # Else, create a grid based on the number of tiles wanted as result
            # Use a margin of 1 meter around the bounds
            margin = 1.0
            if input_layerinfo.crs is not None and not input_layerinfo.crs.is_projected:
                # If geographic crs, 1 degree = 111 km or 111000 m
                margin /= 111000
            bounds = input_layerinfo.total_bounds
            bounds = (
                bounds[0] - margin,
                bounds[1] - margin,
                bounds[2] + margin,
                bounds[3] + margin,
            )
            result_tiles_gdf = gpd.GeoDataFrame(
                geometry=pygeoops.create_grid2(bounds, nb_squarish_tiles),
                crs=input_layerinfo.crs,
            )

        # Apply gridsize tolerance on tiles, otherwise the border polygons can't be
        # unioned properly because gaps appear after rounding coordinates.
        if gridsize != 0.0:
            result_tiles_gdf.geometry = shapely.set_precision(
                result_tiles_gdf.geometry, grid_size=gridsize
            )
        if len(result_tiles_gdf) > 1:
            gfo.to_file(
                result_tiles_gdf,
                output_path.parent / f"{output_path.stem}_tiles.gpkg",
            )

        # If a tiled result is asked, add tile_id to group on for the result
        if len(result_tiles_gdf) > 1:
            result_tiles_gdf["tile_id"] = result_tiles_gdf.reset_index().index

        # The dissolve for polygons is done in several passes, and after the first
        # pass, only the 'onborder' features are further dissolved, as the
        # 'notonborder' features are already OK.
        tempdir = _io_util.create_tempdir(f"geofileops/{operation_name}")
        try:
            if output_layer is None:
                output_layer = gfo.get_default_layer(output_path)
            output_tmp_path = tempdir / "output_tmp.gpkg"
            prev_nb_batches = None
            last_pass = False
            pass_id = 0
            logger.info(f"Start, with input {input_path}")
            input_pass_layer: Optional[str] = input_layer
            while True:
                # Get info of the current file that needs to be dissolved
                input_pass_layerinfo = gfo.get_layerinfo(input_path, input_pass_layer)
                nb_rows_total = input_pass_layerinfo.featurecount

                # Calculate the best number of parallel processes and batches for
                # the available resources for the current pass
                # Limit the nb of rows per batch, as dissolve slows down with more rows.
                nb_parallel, nb_batches = _determine_nb_batches(
                    nb_rows_total=nb_rows_total,
                    nb_parallel=nb_parallel,
                    batchsize=batchsize,
                    parallelization_config=ParallelizationConfig(
                        max_rows_per_batch=10000
                    ),
                )

                # If the ideal number of batches is close to the nb. result tiles asked,
                # dissolve towards the asked result!
                # If not, a temporary result is created using smaller tiles
                if nb_batches <= len(result_tiles_gdf) * 1.1:
                    tiles_gdf = result_tiles_gdf
                    last_pass = True
                    nb_parallel = min(len(result_tiles_gdf), nb_parallel)
                elif len(result_tiles_gdf) == 1:
                    # Create a grid based on the ideal number of batches, but make
                    # sure the number is smaller than the maximum...
                    nb_squarish_tiles_max = None
                    if prev_nb_batches is not None:
                        nb_squarish_tiles_max = max(prev_nb_batches - 1, 1)
                        nb_batches = min(nb_batches, nb_squarish_tiles_max)
                    tiles_gdf = gpd.GeoDataFrame(
                        geometry=pygeoops.create_grid2(
                            total_bounds=input_pass_layerinfo.total_bounds,
                            nb_squarish_tiles=nb_batches,
                            nb_squarish_tiles_max=nb_squarish_tiles_max,
                        ),
                        crs=input_pass_layerinfo.crs,
                    )
                else:
                    # If a grid is specified already, add extra columns/rows instead of
                    # creating new one...
                    tiles_gdf = pygeoops.split_tiles(result_tiles_gdf, nb_batches)

                # Apply gridsize tolerance on tiles, otherwise the border polygons can't
                # be unioned properly because gaps appear after rounding coordinates.
                if gridsize != 0.0:
                    tiles_gdf.geometry = shapely.set_precision(
                        tiles_gdf.geometry, grid_size=gridsize
                    )
                gfo.to_file(tiles_gdf, tempdir / f"output_{pass_id}_tiles.gpkg")

                # If the number of tiles ends up as 1, it is the last pass anyway...
                if len(tiles_gdf) == 1:
                    last_pass = True

                # If we are not in the last pass, onborder parcels will need extra
                # processing still in further passes, so are saved in a seperate
                # gfo. The notonborder rows are final immediately
                if last_pass is not True:
                    output_tmp_onborder_path = (
                        tempdir / f"output_{pass_id}_onborder.gpkg"
                    )
                else:
                    output_tmp_onborder_path = output_tmp_path

                # Now go!
                logger.info(
                    f"Start pass {pass_id} to {len(tiles_gdf)} tiles "
                    f"(batch size: {int(nb_rows_total/len(tiles_gdf))})"
                )
                pass_start = datetime.now()
                _ = _dissolve_polygons_pass(
                    input_path=input_path,
                    output_notonborder_path=output_tmp_path,
                    output_onborder_path=output_tmp_onborder_path,
                    explodecollections=explodecollections,
                    groupby_columns=groupby_columns,
                    agg_columns=agg_columns,
                    tiles_gdf=tiles_gdf,
                    input_layer=input_pass_layer,
                    output_layer=output_layer,
                    gridsize=gridsize,
                    keep_empty_geoms=False,
                    nb_parallel=nb_parallel,
                )
                logger.info(f"Pass {pass_id} ready, took {datetime.now()-pass_start}")

                # Prepare the next pass
                # The input path is the onborder file
                prev_nb_batches = len(tiles_gdf)
                input_path = output_tmp_onborder_path
                pass_id += 1
                input_pass_layer = None

                # If we are ready...
                if last_pass is True:
                    break

            # Calculation ready! Now finalise output!
            # If there is a result on border, append it to the rest
            if (
                str(output_tmp_onborder_path) != str(output_tmp_path)
                and output_tmp_onborder_path.exists()
            ):
                gfo.append_to(
                    output_tmp_onborder_path, output_tmp_path, dst_layer=output_layer
                )

            # If there is a result...
            if output_tmp_path.exists():
                # If tiled output asked, add "tile_id" to groupby_columns
                if len(result_tiles_gdf) > 1:
                    if groupby_columns is None:
                        groupby_columns = ["tile_id"]
                    else:
                        groupby_columns = list(groupby_columns).copy()
                        groupby_columns.append("tile_id")

                # Prepare strings to use in select based on groupby_columns
                if groupby_columns is not None:
                    groupby_prefixed_list = [
                        f'{{prefix}}"{column}"' for column in groupby_columns
                    ]
                    groupby_select_prefixed_str = (
                        f", {', '.join(groupby_prefixed_list)}"
                    )
                    groupby_groupby_prefixed_str = (
                        f"GROUP BY {', '.join(groupby_prefixed_list)}"
                    )

                    groupby_filter_list = [
                        f' AND geo_data."{column}" = json_data."{column}"'
                        for column in groupby_columns
                    ]
                    groupby_filter_str = " ".join(groupby_filter_list)
                else:
                    groupby_select_prefixed_str = ""
                    groupby_groupby_prefixed_str = ""
                    groupby_filter_str = ""

                # Prepare strings to use in select based on agg_columns
                agg_columns_str = ""
                if agg_columns is not None:
                    if "json" in agg_columns:
                        # The aggregation is to a json column, so add
                        agg_columns_str += (
                            ",json_group_array(DISTINCT json_data.json_row) as json"
                        )
                    elif "columns" in agg_columns:
                        for agg_column in agg_columns["columns"]:
                            # Init
                            distinct_str = ""
                            extra_param_str = ""

                            # Prepare aggregation keyword.
                            if agg_column["agg"].lower() in [
                                "count",
                                "sum",
                                "min",
                                "max",
                                "median",
                            ]:
                                aggregation_str = agg_column["agg"]
                            elif agg_column["agg"].lower() in ["mean", "avg"]:
                                aggregation_str = "avg"
                            elif agg_column["agg"].lower() == "concat":
                                aggregation_str = "group_concat"
                                if "sep" in agg_column:
                                    extra_param_str = f", '{agg_column['sep']}'"
                            else:
                                raise ValueError(
                                    f"aggregation {agg_column['agg']} is not supported"
                                )

                            # If distinct is specified, add the distinct keyword
                            if (
                                "distinct" in agg_column
                                and agg_column["distinct"] is True
                            ):
                                distinct_str = "DISTINCT "

                            # Prepare column name string.
                            column_str = (
                                "json_extract(json_data.json_row, "
                                f'"$.{agg_column["column"]}")'
                            )

                            # Now put everything together
                            agg_columns_str += (
                                f", {aggregation_str}({distinct_str}{column_str}"
                                f'{extra_param_str}) AS "{agg_column["as"]}"'
                            )

                # Add a column to order the result by to avoid having all
                # complex geometries together in the output file.
                orderby_column = "temp_ordercolumn_geohash"
                _add_orderby_column(
                    path=output_tmp_path, layer=output_layer, name=orderby_column
                )

                # Prepare SQL statement for final output file.
                # All tiles are already dissolved to groups, but now the
                # results from all tiles still need to be
                # grouped/collected together.
                logger.info("Finalize result")
                if agg_columns is None:
                    # If there are no aggregation columns, things are not too
                    # complicated.
                    if explodecollections is True:
                        # If explodecollections is true, it is useless to
                        # first group them here, as they will be exploded again
                        # in the select() call later on... so just order them.
                        # If a tiled result is asked, also don't collect.
                        sql_stmt = f"""
                            SELECT {{geometrycolumn}}
                                  {groupby_select_prefixed_str.format(prefix="layer.")}
                              FROM "{{input_layer}}" layer
                             ORDER BY layer.{orderby_column}
                        """
                    else:
                        # No explodecollections, so collect to one geometry
                        # (per groupby if applicable).
                        sql_stmt = f"""
                            SELECT ST_Collect({{geometrycolumn}}) AS {{geometrycolumn}}
                                  {groupby_select_prefixed_str.format(prefix="layer.")}
                              FROM "{{input_layer}}" layer
                              {groupby_groupby_prefixed_str.format(prefix="layer.")}
                             ORDER BY MIN(layer.{orderby_column})
                        """
                else:
                    # If agg_columns specified, postprocessing is a bit more
                    # complicated.
                    sql_stmt = f"""
                        SELECT geo_data.{{geometrycolumn}}
                              {groupby_select_prefixed_str.format(prefix="geo_data.")}
                              {agg_columns_str}
                          FROM (
                            SELECT ST_Collect(layer_geo.{{geometrycolumn}}
                                   ) AS {{geometrycolumn}}
                                  {groupby_select_prefixed_str.format(prefix="layer_geo.")}
                                  ,MIN(layer_geo.{orderby_column}) as {orderby_column}
                              FROM "{{input_layer}}" layer_geo
                              {groupby_groupby_prefixed_str.format(prefix="layer_geo.")}
                            ) geo_data
                          JOIN (
                            SELECT DISTINCT json_rows_table.value as json_row
                                {groupby_select_prefixed_str.format(prefix="layer_for_json.")}
                              FROM "{{input_layer}}" layer_for_json
                              CROSS JOIN json_each(
                                  layer_for_json.__DISSOLVE_TOJSON, "$") json_rows_table
                            ) json_data
                         WHERE 1=1
                            {groupby_filter_str}
                          {groupby_groupby_prefixed_str.format(prefix="geo_data.")}
                          ORDER BY geo_data.{orderby_column}
                    """

                # Apply where_post parameter if needed/possible
                if where_post is not None and not not explodecollections:
                    # explodecollections is not True, so we can add it to sql_stmt.
                    # If explodecollections would be True, we need to wait to apply the
                    # where_post till after explodecollections is applied, so when
                    # appending the partial results to the output file.
                    where_post = where_post.format(geometrycolumn="geom")
                    sql_stmt = f"""
                        SELECT * FROM
                            ( {sql_stmt}
                            )
                        WHERE {where_post}
                    """
                    # where_post has been applied already so set to None.
                    where_post = None

                if where_post is None:
                    name = f"output_tmp2_final{output_path.suffix}"
                else:
                    name = f"output_tmp2_final{output_tmp_path.suffix}"
                output_tmp2_final_path = tempdir / name
                sql_stmt = sql_stmt.format(
                    geometrycolumn="geom", input_layer=output_layer
                )
                create_spatial_index = True if where_post is None else False
                _ogr_util.vector_translate(
                    input_path=output_tmp_path,
                    output_path=output_tmp2_final_path,
                    output_layer=output_layer,
                    sql_stmt=sql_stmt,
                    sql_dialect="SQLITE",
                    force_output_geometrytype=input_layerinfo.geometrytype,
                    explodecollections=explodecollections,
                    options={"LAYER_CREATION.SPATIAL_INDEX": create_spatial_index},
                )

                # We still need to apply the where_post filter
                if where_post is not None:
                    name = f"output_tmp3_where{output_path.suffix}"
                    output_tmp3_where_path = tempdir / name
                    output_tmp2_info = gfo.get_layerinfo(output_tmp2_final_path)
                    where_post = where_post.format(
                        geometrycolumn=output_tmp2_info.geometrycolumn
                    )
                    sql_stmt = f"""
                        SELECT * FROM "{output_layer}"
                         WHERE {where_post}
                    """
                    tmp_info = gfo.get_layerinfo(output_tmp2_final_path, output_layer)
                    sql_stmt = sql_stmt.format(geometrycolumn=tmp_info.geometrycolumn)
                    _ogr_util.vector_translate(
                        input_path=output_tmp2_final_path,
                        output_path=output_tmp3_where_path,
                        output_layer=output_layer,
                        force_output_geometrytype=input_layerinfo.geometrytype,
                        sql_stmt=sql_stmt,
                        sql_dialect="SQLITE",
                        options={"LAYER_CREATION.SPATIAL_INDEX": True},
                    )
                    output_tmp2_final_path = output_tmp3_where_path

                # Now we are ready to move the result to the final spot...
                gfo.move(output_tmp2_final_path, output_path)

        finally:
            shutil.rmtree(tempdir, ignore_errors=True)
    else:
        raise NotImplementedError(
            f"Unsupported input geometrytype: {input_layerinfo.geometrytype}"
        )

    # Return result info
    result_info["message"] = f"Ready, took {datetime.now()-start_time}"
    logger.info(result_info["message"])
    return result_info


def _dissolve_polygons_pass(
    input_path: Path,
    output_notonborder_path: Path,
    output_onborder_path: Path,
    explodecollections: bool,
    groupby_columns: Optional[Iterable[str]],
    agg_columns: Optional[dict],
    tiles_gdf: gpd.GeoDataFrame,
    input_layer: Optional[str],
    output_layer: Optional[str],
    gridsize: float,
    keep_empty_geoms: bool,
    nb_parallel: int,
):
    start_time = datetime.now()

    # Make sure the input file has a spatial index
    gfo.create_spatial_index(input_path, layer=input_layer, exist_ok=True)

    # Start calculation in parallel
    input_layerinfo = gfo.get_layerinfo(input_path, input_layer)

    # Processing in threads is 2x faster for small datasets (on Windows)
    calculate_in_threads = True if input_layerinfo.featurecount <= 100 else False
    with _processing_util.PooledExecutorFactory(
        threadpool=calculate_in_threads,
        max_workers=nb_parallel,
        initializer=_processing_util.initialize_worker(),
    ) as calculate_pool:
        # Prepare output filename
        tempdir = output_onborder_path.parent

        batches: Dict[int, dict] = {}
        nb_batches = len(tiles_gdf)
        nb_batches_done = 0
        future_to_batch_id = {}
        nb_rows_done = 0
        for batch_id, tile_row in enumerate(tiles_gdf.itertuples()):
            batches[batch_id] = {}
            batches[batch_id]["layer"] = output_layer
            batches[batch_id]["bounds"] = tile_row.geometry.bounds

            # Output each batch to a seperate temporary file, otherwise there
            # are timeout issues when processing large files
            suffix = output_notonborder_path.suffix
            name = f"{output_notonborder_path.stem}_{batch_id}{suffix}"
            output_notonborder_tmp_partial_path = tempdir / name
            batches[batch_id][
                "output_notonborder_tmp_partial_path"
            ] = output_notonborder_tmp_partial_path
            name = f"{output_onborder_path.stem}_{batch_id}{suffix}"
            output_onborder_tmp_partial_path = tempdir / name
            batches[batch_id][
                "output_onborder_tmp_partial_path"
            ] = output_onborder_tmp_partial_path

            # Get tile_id if present
            tile_id = tile_row.tile_id if "tile_id" in tile_row._fields else None

            future = calculate_pool.submit(
                _dissolve_polygons,
                input_path=input_path,
                output_notonborder_path=output_notonborder_tmp_partial_path,
                output_onborder_path=output_onborder_tmp_partial_path,
                explodecollections=explodecollections,
                groupby_columns=groupby_columns,
                agg_columns=agg_columns,
                input_geometrytype=input_layerinfo.geometrytype,
                input_layer=input_layer,
                output_layer=output_layer,
                bbox=tile_row.geometry.bounds,
                tile_id=tile_id,
                gridsize=gridsize,
                keep_empty_geoms=keep_empty_geoms,
            )
            future_to_batch_id[future] = batch_id

        # Loop till all parallel processes are ready, but process each one
        # that is ready already
        _general_util.report_progress(
            start_time, nb_batches_done, nb_batches, "dissolve"
        )
        for future in futures.as_completed(future_to_batch_id):
            try:
                # If the calculate gave results
                nb_batches_done += 1
                batch_id = future_to_batch_id[future]
                result = future.result()

                if result is not None:
                    nb_rows_done += result["nb_rows_done"]
                    if result["nb_rows_done"] > 0 and result["total_time"] > 0:
                        rows_per_sec = round(
                            result["nb_rows_done"] / result["total_time"]
                        )
                        logger.debug(
                            f"Batch {batch_id} processed {result['nb_rows_done']} rows "
                            f"({rows_per_sec}/sec)"
                        )
                        if "perfstring" in result:
                            logger.debug(f"Perfstring: {result['perfstring']}")

                    # Start copy of the result to a common file
                    batch_id = future_to_batch_id[future]

                    # If calculate gave notonborder results, append to output
                    output_notonborder_tmp_partial_path = batches[batch_id][
                        "output_notonborder_tmp_partial_path"
                    ]
                    if (
                        output_notonborder_tmp_partial_path.exists()
                        and output_notonborder_tmp_partial_path.stat().st_size > 0
                    ):
                        fileops._append_to_nolock(
                            src=output_notonborder_tmp_partial_path,
                            dst=output_notonborder_path,
                            create_spatial_index=False,
                        )
                        gfo.remove(output_notonborder_tmp_partial_path)

                    # If calculate gave onborder results, append to output
                    output_onborder_tmp_partial_path = batches[batch_id][
                        "output_onborder_tmp_partial_path"
                    ]
                    if (
                        output_onborder_tmp_partial_path.exists()
                        and output_onborder_tmp_partial_path.stat().st_size > 0
                    ):
                        fileops._append_to_nolock(
                            src=output_onborder_tmp_partial_path,
                            dst=output_onborder_path,
                            create_spatial_index=False,
                        )
                        gfo.remove(output_onborder_tmp_partial_path)

            except Exception as ex:
                batch_id = future_to_batch_id[future]
                message = f"Error executing {batches[batch_id]}: {ex}"
                logger.exception(message)
                calculate_pool.shutdown()
                raise Exception(message) from ex

            # Log the progress and prediction speed
            _general_util.report_progress(
                start_time, nb_batches_done, nb_batches, "dissolve"
            )


def _dissolve_polygons(
    input_path: Path,
    output_notonborder_path: Path,
    output_onborder_path: Path,
    explodecollections: bool,
    groupby_columns: Optional[Iterable[str]],
    agg_columns: Optional[dict],
    input_geometrytype: GeometryType,
    input_layer: Optional[str],
    output_layer: Optional[str],
    bbox: Tuple[float, float, float, float],
    tile_id: Optional[int],
    gridsize: float,
    keep_empty_geoms: bool,
) -> dict:
    # Init
    perfinfo: Dict[str, float] = {}
    start_time = datetime.now()
    return_info = {
        "input_path": input_path,
        "output_notonborder_path": output_notonborder_path,
        "output_onborder_path": output_onborder_path,
        "bbox": bbox,
        "tile_id": tile_id,
        "gridsize": gridsize,
        "nb_rows_done": 0,
        "total_time": 0,
        "perfinfo": "",
    }

    # Read all records that are in the bbox
    retry_count = 0
    start_read = datetime.now()
    agg_columns_needed = None
    while True:
        try:
            columns_to_read: Set[str] = set()
            info = gfo.get_layerinfo(input_path, input_layer)
            if groupby_columns is not None:
                columns_to_read.update(groupby_columns)
            fid_as_index = False
            if agg_columns is not None:
                fid_as_index = True
                if "__DISSOLVE_TOJSON" in info.columns:
                    # If we are not in the first pass, the columns to be read
                    # are already in the json column
                    columns_to_read.add("__DISSOLVE_TOJSON")
                else:
                    # The first pass, so read all relevant columns to code
                    # them in json
                    if "json" in agg_columns:
                        agg_columns_needed = agg_columns["json"]
                    elif "columns" in agg_columns:
                        agg_columns_needed = [
                            agg_column["column"]
                            for agg_column in agg_columns["columns"]
                        ]
                    if agg_columns_needed is not None:
                        columns_to_read.update(agg_columns_needed)

            input_gdf = gfo.read_file(
                path=input_path,
                layer=input_layer,
                bbox=bbox,
                columns=columns_to_read,
                fid_as_index=fid_as_index,
            )

            if agg_columns is not None:
                input_gdf["fid_orig"] = input_gdf.index
                if agg_columns_needed is not None:
                    agg_columns_needed.append("fid_orig")

            break
        except Exception as ex:
            if str(ex) == "database is locked":
                if retry_count < 10:
                    retry_count += 1
                    time.sleep(1)
                else:
                    raise Exception("retried 10 times, database still locked") from ex
            else:
                raise ex

    # Check result
    perfinfo["time_read"] = (datetime.now() - start_read).total_seconds()
    return_info["nb_rows_done"] = len(input_gdf)
    if return_info["nb_rows_done"] == 0:
        message = f"dissolve_polygons: no input geometries found in {input_path}"
        logger.info(message)
        return_info["message"] = message
        return_info["total_time"] = (datetime.now() - start_time).total_seconds()
        return return_info

    # Now the real processing
    aggfunc: Union[str, dict, None] = None
    if agg_columns is not None:
        if "__DISSOLVE_TOJSON" not in input_gdf.columns:
            # First pass -> put relevant columns in json field
            aggfunc = {"to_json": agg_columns_needed}
        else:
            # Columns already coded in a json column, so merge json lists
            aggfunc = "merge_json_lists"
    else:
        aggfunc = "first"
    start_dissolve = datetime.now()
    diss_gdf = _dissolve(
        df=input_gdf, by=groupby_columns, aggfunc=aggfunc, as_index=False, dropna=False
    )
    perfinfo["time_dissolve"] = (datetime.now() - start_dissolve).total_seconds()

    # If explodecollections is True and For polygons, explode multi-geometries.
    # If needed they will be 'collected' afterwards to multipolygons again.
    if explodecollections is True or input_geometrytype in [
        GeometryType.POLYGON,
        GeometryType.MULTIPOLYGON,
    ]:
        diss_gdf = diss_gdf.explode(ignore_index=True)

    # Clip the result on the borders of the bbox not to have overlaps
    # between the different tiles.
    # If this is not applied, this results in some geometries not being merged
    # or in duplicates.
    # REMARK: for (multi)linestrings, the endpoints created by the clip are not
    # always the same due to rounding, so dissolving in a next pass doesn't
    # always result in linestrings being re-connected... Because dissolving
    # lines isn't so computationally heavy anyway, drop support here.
    if bbox is not None:
        start_clip = datetime.now()
        bbox_polygon = sh_geom.Polygon(
            [
                (bbox[0], bbox[1]),
                (bbox[0], bbox[3]),
                (bbox[2], bbox[3]),
                (bbox[2], bbox[1]),
                (bbox[0], bbox[1]),
            ]
        )
        bbox_gdf = gpd.GeoDataFrame(
            data=[1], geometry=[bbox_polygon], crs=input_gdf.crs
        )

        # Catch irrelevant pandas future warning
        # TODO: when removed in later version of pandas, can be removed here
        with warnings.catch_warnings():
            message = (
                "In a future version, `df.iloc[:, i] = newvals` will attempt to "
                "set the values inplace instead of always setting a new array."
            )
            warnings.filterwarnings(
                action="ignore", category=FutureWarning, message=re.escape(message)
            )
            # keep_geom_type=True gave sometimes error, and still does in 0.9.0
            # so use own implementation of keep_geom_type
            diss_gdf = gpd.clip(diss_gdf, bbox_gdf)  # , keep_geom_type=True)
            assert isinstance(diss_gdf, gpd.GeoDataFrame)

        # Only keep geometries of the primitive type specified after clip...
        assert isinstance(diss_gdf, gpd.GeoDataFrame)
        diss_gdf.geometry = pygeoops.collection_extract(
            diss_gdf.geometry, primitivetype=input_geometrytype.to_primitivetype
        )

        perfinfo["time_clip"] = (datetime.now() - start_clip).total_seconds()

    # Set empty geometries to null/None
    assert diss_gdf.geometry is not None
    diss_gdf.loc[
        diss_gdf.geometry.is_empty, ["geometry"]  # type: ignore[union-attr]
    ] = None

    # Remove rows where geom is None/null/empty
    if not keep_empty_geoms:
        assert isinstance(diss_gdf, gpd.GeoDataFrame)
        diss_gdf = diss_gdf[~diss_gdf.geometry.isna()]  # type: ignore[union-attr]

    # If there is no result, return
    if len(diss_gdf) == 0:
        message = f"Result is empty for {input_path}"
        return_info["message"] = message
        return_info["perfinfo"] = perfinfo
        return_info["total_time"] = (datetime.now() - start_time).total_seconds()
        return return_info

    # Add column with tile_id
    assert isinstance(diss_gdf, gpd.GeoDataFrame)
    if tile_id is not None:
        diss_gdf["tile_id"] = tile_id

    if gridsize != 0.0:
        diss_gdf.geometry = _geoseries_util.set_precision(
            diss_gdf.geometry, grid_size=gridsize, raise_on_topoerror=False
        )

    # Save the result to destination file(s)
    start_to_file = datetime.now()

    # If the tiles don't need to be merged afterwards, we can just save the result as
    # it is.
    if str(output_notonborder_path) == str(output_onborder_path):
        # assert to avoid pyLance warning
        assert isinstance(diss_gdf, gpd.GeoDataFrame)
        # Use force_multitype, to avoid warnings when some batches contain
        # singletype and some contain multitype geometries
        gfo.to_file(
            diss_gdf,
            output_notonborder_path,
            layer=output_layer,
            force_multitype=True,
            index=False,
            create_spatial_index=False,
        )
    else:
        # If not, save the polygons on the border seperately
        bbox_lines = pygeoops.explode(
            shapely.boundary(sh_geom.box(bbox[0], bbox[1], bbox[2], bbox[3]))
        )
        bbox_lines_gdf = gpd.GeoDataFrame(geometry=bbox_lines, crs=input_gdf.crs)
        onborder_gdf = gpd.sjoin(diss_gdf, bbox_lines_gdf, predicate="intersects")
        onborder_gdf.drop("index_right", axis=1, inplace=True)
        if len(onborder_gdf) > 0:
            # Use force_multitype, to avoid warnings when some batches contain
            # singletype and some contain multitype geometries
            gfo.to_file(
                onborder_gdf,
                output_onborder_path,
                layer=output_layer,
                force_multitype=True,
                create_spatial_index=False,
            )

        notonborder_gdf = diss_gdf[~diss_gdf.index.isin(onborder_gdf.index)]
        if len(notonborder_gdf) > 0:
            # Use force_multitype, to avoid warnings when some batches contain
            # singletype and some contain multitype geometries
            gfo.to_file(
                notonborder_gdf,
                output_notonborder_path,
                layer=output_layer,
                force_multitype=True,
                index=False,
                create_spatial_index=False,
            )
    perfinfo["time_to_file"] = (datetime.now() - start_to_file).total_seconds()

    # Finalise...
    message = f"dissolve_polygons: ready in {datetime.now()-start_time} on {input_path}"
    logger.debug(message)

    # Collect perfinfo
    total_perf_time = 0.0
    perfstring = ""
    for perfcode in perfinfo:
        total_perf_time += perfinfo[perfcode]
        perfstring += f"{perfcode}: {perfinfo[perfcode]:.2f}, "
    return_info["total_time"] = (datetime.now() - start_time).total_seconds()
    perfinfo["unaccounted"] = (
        return_info["total_time"] - total_perf_time  # type: ignore[operator]
    )
    perfstring += f"unaccounted: {perfinfo['unaccounted']:.2f}"

    # Return
    return_info["perfinfo"] = perfinfo
    return_info["perfstring"] = perfstring
    return_info["message"] = message
    return return_info


def _dissolve(
    df: gpd.GeoDataFrame,
    by=None,
    aggfunc: Optional[Union[str, dict]] = "first",
    as_index=True,
    level=None,
    sort=True,
    observed=False,
    dropna=True,
) -> gpd.GeoDataFrame:
    """
    Dissolve geometries within `groupby` into single observation.

    This is accomplished by applying the `unary_union` method
    to all geometries within a groupself.
    Observations associated with each `groupby` group will be aggregated
    using the `aggfunc`.
    Parameters
    ----------
    by : string, default None
        Column whose values define groups to be dissolved. If None,
        whole GeoDataFrame is considered a single group.
    aggfunc : function, string or dict, default "first"
        Aggregation function for manipulation of data associated
        with each group. Passed to pandas `groupby.agg` method.
    as_index : boolean, default True
        If true, groupby columns become index of result.
    level : int or str or sequence of int or sequence of str, default None
        If the axis is a MultiIndex (hierarchical), group by a
        particular level or levels.
        .. versionadded:: 0.9.0
    sort : bool, default True
        Sort group keys. Get better performance by turning this off.
        Note this does not influence the order of observations within
        each group. Groupby preserves the order of rows within each group.
        .. versionadded:: 0.9.0
    observed : bool, default False
        This only applies if any of the groupers are Categoricals.
        If True: only show observed values for categorical groupers.
        If False: show all values for categorical groupers.
        .. versionadded:: 0.9.0
    dropna : bool, default True
        If True, and if group keys contain NA values, NA values
        together with row/column will be dropped. If False, NA
        values will also be treated as the key in groups.
        This parameter is not supported for pandas < 1.1.0.
        A warning will be emitted for earlier pandas versions
        if a non-default value is given for this parameter.
        .. versionadded:: 0.9.0

    Returns:
    -------
    GeoDataFrame

    Examples:
    --------
    >>> from shapely.geometry import Point
    >>> d = {
    ...     "col1": ["name1", "name2", "name1"],
    ...     "geometry": [Point(1, 2), Point(2, 1), Point(0, 1)],
    ... }
    >>> gdf = geopandas.GeoDataFrame(d, crs=4326)
    >>> gdf
        col1                 geometry
    0  name1  POINT (1.00000 2.00000)
    1  name2  POINT (2.00000 1.00000)
    2  name1  POINT (0.00000 1.00000)
    >>> dissolved = gdf.dissolve('col1')
    >>> dissolved  # doctest: +SKIP
                                                geometry
    col1
    name1  MULTIPOINT (0.00000 1.00000, 1.00000 2.00000)
    name2                        POINT (2.00000 1.00000)

    See Also:
    --------
    GeoDataFrame.explode : explode multi-part geometries into single geometries
    """
    if by is None and level is None:
        by_local = np.zeros(len(df), dtype="int64")
    else:
        by_local = by

    groupby_kwargs = {
        "by": by_local,
        "level": level,
        "sort": sort,
        "observed": observed,
        "dropna": dropna,
    }
    """
    if not compat.PANDAS_GE_11:
        groupby_kwargs.pop("dropna")

        if not dropna:  # If they passed a non-default dropna value
            warnings.warn("dropna kwarg is not supported for pandas < 1.1.0")
    """

    # Process non-spatial component
    data = pd.DataFrame(df.drop(columns=df.geometry.name))

    if aggfunc is not None and isinstance(aggfunc, dict) and "to_json" in aggfunc:
        agg_columns = list(set(aggfunc["to_json"]))
        agg_data = (
            data.groupby(**groupby_kwargs)
            .apply(
                lambda g: g[agg_columns].to_json(orient="records")
            )  # type: ignore[index]
            .to_frame(name="__DISSOLVE_TOJSON")
        )
    elif isinstance(aggfunc, str) and aggfunc == "merge_json_lists":
        # Merge and flatten the json lists in the groups
        def group_flatten_json_list(g):
            # Evaluate all grouped rows to json objects. This results in a list of
            # lists of json objects.
            json_nested_lists = [
                json.loads(json_values) for json_values in g["__DISSOLVE_TOJSON"]
            ]

            # Extract the rows from the nested lists + put in a flat list as strings
            jsonstr_flat = [
                json.dumps(json_value)
                for json_values in json_nested_lists
                for json_value in json_values
            ]

            # Remove duplicates
            jsonsstr_distinct = set(jsonstr_flat)

            # Convert the data again to a list of json objects
            json_distinct = [json.loads(json_value) for json_value in jsonsstr_distinct]

            # Return as json string
            return json.dumps(json_distinct)

        agg_data = (
            data.groupby(**groupby_kwargs)
            .apply(lambda g: group_flatten_json_list(g))
            .to_frame(name="__DISSOLVE_TOJSON")
        )
    else:
        agg_data = data.groupby(**groupby_kwargs).agg(aggfunc)  # type: ignore[arg-type]
        # Check if all columns were properly aggregated
        assert by_local is not None
        columns_to_agg = [column for column in data.columns if column not in by_local]
        if len(columns_to_agg) != len(agg_data.columns):
            dropped_columns = [
                column for column in columns_to_agg if column not in agg_data.columns
            ]
            raise Exception(
                f"Column(s) {dropped_columns} are not supported for aggregation, stop"
            )

    # Process spatial component
    def merge_geometries(block):
        merged_geom = block.unary_union
        return merged_geom

    g = df.groupby(group_keys=False, **groupby_kwargs)[df.geometry.name].agg(
        merge_geometries
    )

    # Aggregate
    aggregated_geometry = gpd.GeoDataFrame(
        data=g, geometry=df.geometry.name, crs=df.crs
    )
    # Recombine
    aggregated = aggregated_geometry.join(agg_data)

    # Reset if requested
    if not as_index:
        aggregated = aggregated.reset_index()

    # Make sure output types of grouped columns are the same as input types.
    # E.g. object columns become float if all values are None.
    if by is not None:
        if isinstance(by, str):
            if by in aggregated.columns and df[by].dtype != aggregated[by].dtype:
                aggregated[by] = aggregated[by].astype(df[by].dtype)
        elif isinstance(by, Iterable):
            for col in by:
                if col in aggregated.columns and df[col].dtype != aggregated[col].dtype:
                    aggregated[col] = aggregated[col].astype(df[col].dtype)

    assert isinstance(aggregated, gpd.GeoDataFrame)
    return aggregated


def _add_orderby_column(path: Path, layer: str, name: str):
    # Prepare the expression to calculate the orderby column.
    # In a spatial file, a spatial order will make later use more efficiënt,
    # so use a geohash.
    layerinfo = gfo.get_layerinfo(path)
    if layerinfo.crs is not None and layerinfo.crs.is_geographic:
        # If the coordinates are geographic (in lat/lon degrees), ok
        expression = f"ST_GeoHash({layerinfo.geometrycolumn}, 10)"
    else:
        # If they are not geographic (in lat/lon degrees), they need to be
        # converted to ~ degrees to be able to calculate a geohash.

        # Properly calculating the transformation to eg. WGS is terribly slow...
        # expression = f"""ST_GeoHash(ST_Transform(MakePoint(
        #       (MbrMaxX(geom)+MbrMinX(geom))/2,
        #       (MbrMinY(geom)+MbrMaxY(geom))/2, ST_SRID(geom)), 4326), 10)"""
        # So, do something else that's faster and still gives a good
        # geographic clustering.
        to_geographic_factor_approx = 90 / max(layerinfo.total_bounds)
        expression = f"""ST_GeoHash(MakePoint(
                ((MbrMaxX({layerinfo.geometrycolumn})
                  +MbrMinX({layerinfo.geometrycolumn}))/2
                )*{to_geographic_factor_approx},
                ((MbrMinY({layerinfo.geometrycolumn})
                  +MbrMaxY({layerinfo.geometrycolumn}))/2
                )*{to_geographic_factor_approx}, 4326), 10)"""

    # Now we can actually add the column.
    gfo.add_column(path=path, name=name, type=gfo.DataType.TEXT, expression=expression)
    sqlite_stmt = f'CREATE INDEX {name}_idx ON "{layer}"({name})'
    gfo.execute_sql(path=path, sql_stmt=sqlite_stmt)
