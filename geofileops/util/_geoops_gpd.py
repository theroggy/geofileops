"""Module containing the implementation of Geofile operations using GeoPandas."""

import copy
import enum
import json
import logging
import logging.config
import math
import multiprocessing
import pickle
import time
import warnings
from collections.abc import Callable, Iterable
from concurrent import futures
from datetime import datetime
from pathlib import Path
from typing import Any

import cloudpickle
import geopandas as gpd
import numpy as np
import pandas as pd
import psutil
import pygeoops
import shapely
import shapely.geometry as sh_geom
from pygeoops import GeometryType, PrimitiveType
from pyproj import Transformer

import geofileops as gfo
from geofileops import LayerInfo, fileops
from geofileops._compat import PANDAS_GTE_22
from geofileops.helpers import _general_helper, _parameter_helper
from geofileops.helpers._configoptions_helper import ConfigOptions
from geofileops.util import (
    _general_util,
    _geoops_sql,
    _geoseries_util,
    _io_util,
    _ogr_util,
    _processing_util,
)
from geofileops.util._geofileinfo import GeofileInfo
from geofileops.util._geometry_util import (
    BufferEndCapStyle,
    BufferJoinStyle,
    SimplifyAlgorithm,
)
from geofileops.util._geopath_util import GeoPath

# Don't show this geopandas warning...
warnings.filterwarnings("ignore", "GeoSeries.isna", UserWarning)

logger = logging.getLogger(__name__)


class ParallelizationConfig:
    """Heuristics for geopandas based geo operations.

    Heuristics meant to be able to optimize the parallelisation parameters for
    geopandas based geo operation.
    """

    def __init__(
        self,
        bytes_basefootprint: int = 50 * 1024 * 1024,
        bytes_per_row: int = 1000,
        min_rows_per_batch: int = 1000,
        max_rows_per_batch: int = 100000,
        bytes_min_per_process: int | None = None,
        bytes_usable: int | None = None,
        cpu_count: int = -1,
    ):
        """Heuristics for geopandas based geo operations.

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
    parallelization_config: ParallelizationConfig | None = None,
) -> tuple[int, int]:
    """Determines recommended parallelization params.

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
    nb_parallel = min(nb_parallel, nb_rows_total)

    # If batchsize is specified, use it to determine number of batches.
    if batchsize > 0:
        nb_batches = math.ceil(nb_rows_total / batchsize)

        # No use to have more workers than number of batches
        nb_parallel = min(nb_parallel, nb_batches)

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
    nb_parallel = min(nb_parallel, nb_batches)

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
        batches: list[str],
        batchsize: int,
    ):
        self.nb_rows_to_process = nb_rows_to_process
        self.nb_parallel = nb_parallel
        self.batches = batches
        self.batchsize = batchsize

    def to_json(self, path: Path):
        prepared = _general_util.prepare_for_serialize(vars(self))
        with path.open("w") as file:
            file.write(json.dumps(prepared, indent=4, sort_keys=True))


def _prepare_processing_params(
    input_path: Path,
    input_layer: LayerInfo,
    nb_parallel: int,
    batchsize: int,
    parallelization_config: ParallelizationConfig | None = None,
    tmp_dir: Path | None = None,
) -> ProcessingParams:
    fid_column = input_layer.fid_column if input_layer.fid_column != "" else "fid"
    nb_parallel, nb_batches = _determine_nb_batches(
        nb_rows_total=input_layer.featurecount,
        nb_parallel=nb_parallel,
        batchsize=batchsize,
        parallelization_config=parallelization_config,
    )

    # Prepare batches to process
    batches: list[str] = []
    if nb_batches == 1:
        # If only one batch, no filtering is needed
        batches.append("")
    else:
        # Determine the min_fid and max_fid
        # Remark: SELECT MIN(fid), MAX(fid) FROM ... is a lot slower than UNION ALL!
        sql_stmt = f"""
            SELECT MIN({fid_column}) minmax_fid FROM "{input_layer.name}"
            UNION ALL
            SELECT MAX({fid_column}) minmax_fid FROM "{input_layer.name}"
        """
        batch_info_df = gfo.read_file(path=input_path, sql_stmt=sql_stmt)
        min_fid = pd.to_numeric(batch_info_df["minmax_fid"][0]).item()
        max_fid = pd.to_numeric(batch_info_df["minmax_fid"][1]).item()

        # Determine the exact batches to use
        if ((max_fid - min_fid) / input_layer.featurecount) < 1.1:
            # If the fid's are quite consecutive, use an imperfect, but
            # fast distribution in batches
            batch_info_list = []
            nb_rows_per_batch = round(input_layer.featurecount / nb_batches)
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
                        FROM "{input_layer.name}"
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
    nb_parallel = min(len(batches), nb_parallel)

    returnvalue = ProcessingParams(
        nb_rows_to_process=input_layer.featurecount,
        nb_parallel=nb_parallel,
        batches=batches,
        batchsize=int(input_layer.featurecount / len(batches)),
    )

    if tmp_dir is not None:
        returnvalue.to_json(tmp_dir / "processing_params.json")
    return returnvalue


class GeoOperation(enum.Enum):
    SIMPLIFY = "simplify"
    BUFFER = "buffer"
    CONVEXHULL = "convexhull"
    APPLY = "apply"
    APPLY_VECTORIZED = "apply_vectorized"


def apply(
    input_path: Path,
    output_path: Path,
    func: Callable[[Any], Any],
    operation_name: str | None = None,
    only_geom_input: bool = True,
    input_layer: str | LayerInfo | None = None,
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
    parallelization_config: ParallelizationConfig | None = None,
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
        tmp_basedir=None,
        parallelization_config=parallelization_config,
    )


def apply_vectorized(  # noqa: D417
    input_path: Path,
    output_path: Path,
    operation_name: str | None,
    func: Callable[[Any], Any],
    *,
    input_layer: str | LayerInfo | None,
    output_layer: str | None,
    columns: list[str] | None,
    explodecollections: bool,
    force_output_geometrytype: GeometryType | str | None,
    gridsize: float,
    keep_empty_geoms: bool,
    where_post: str | None,
    nb_parallel: int,
    batchsize: int,
    force: bool,
    parallelization_config: ParallelizationConfig | None,
    tmp_basedir: Path | None,
):
    """Applies a vectorized function to all geometries in a layer.

    Only arguments specific to the internal difference operation are documented here.
    For the other arguments, check out the corresponding function in geoops.py.

    Args:
        operation_name (str, optional): The name of the operation. Will be used in
            logging,... if specified.
        tmp_basedir (Optional[Path], optional): The directory to create the temporary
            directory in for this operation call. If None, it is created in the default
            geofileops temporary directory. Useful to keep all temporary files for an
            operation that uses multiple steps in one temporary directory.

    """
    # Init
    operation_params = {"pickled_func": cloudpickle.dumps(func)}
    if operation_name is not None:
        operation_params["operation_name"] = operation_name

    # Go!
    return _apply_geooperation_to_layer(
        input_path=input_path,
        output_path=output_path,
        operation=GeoOperation.APPLY_VECTORIZED,
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
        parallelization_config=parallelization_config,
        tmp_basedir=tmp_basedir,
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
    operation_prefix: str = "",
    tmp_basedir: Path | None = None,
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
        tmp_basedir=tmp_basedir,
    )


def convexhull(
    input_path: Path,
    output_path: Path,
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
    # Init
    operation_params: dict[str, Any] = {}

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
        tmp_basedir=None,
    )


def makevalid(
    input_path: Path,
    output_path: Path,
    input_layer: str | LayerInfo | None = None,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    explodecollections: bool = False,
    force_output_geometrytype: str | None | GeometryType = None,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = False,
    where_post: str | None = None,
    validate_attribute_data: bool = False,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
):
    if _io_util.output_exists(path=output_path, remove_if_exists=force):
        return

    # Determine if collapsed parts need to be kept after makevalid or not
    keep_collapsed = True
    if force_output_geometrytype is None:
        keep_collapsed = False
    else:
        if isinstance(force_output_geometrytype, GeometryType):
            force_output_geometrytype = force_output_geometrytype.name
        if not isinstance(input_layer, LayerInfo):
            input_layer = fileops.get_layerinfo(input_path, input_layer)
        if force_output_geometrytype.startswith(
            input_layer.geometrytypename
        ) or input_layer.geometrytypename.startswith(force_output_geometrytype):
            keep_collapsed = False

    apply_vectorized(
        input_path=Path(input_path),
        output_path=Path(output_path),
        operation_name="makevalid",
        func=lambda geom: pygeoops.make_valid(
            geom, keep_collapsed=keep_collapsed, only_if_invalid=True
        ),
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
        parallelization_config=None,
        tmp_basedir=None,
    )


def simplify(
    input_path: Path,
    output_path: Path,
    tolerance: float,
    algorithm: SimplifyAlgorithm = SimplifyAlgorithm.RAMER_DOUGLAS_PEUCKER,
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
        tmp_basedir=None,
    )


def _apply_geooperation_to_layer(
    input_path: Path,
    output_path: Path,
    operation: GeoOperation,
    operation_params: dict,
    input_layer: str | LayerInfo | None,  # = None
    columns: list[str] | None,  # = None
    output_layer: str | None,  # = None
    explodecollections: bool,  # = False
    force_output_geometrytype: GeometryType | str | None,  # = None
    gridsize: float,  # = 0.0
    keep_empty_geoms: bool,  # = False
    where_post: str | None,  # = None
    nb_parallel: int,  # = -1
    batchsize: int,  # = -1
    force: bool,  # = False
    tmp_basedir: Path | None,
    parallelization_config: ParallelizationConfig | None = None,
):
    """Applies a geo operation on a layer.

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
            in the output. Defaults to False.
        where_post (str, optional): sql filter to apply after all other processing,
            including e.g. explodecollections. It should be in sqlite syntax and
            |spatialite_reference_link| functions can be used. Defaults to None.
        nb_parallel (int, optional): [description]. Defaults to -1.
        batchsize (int, optional): indicative number of rows to process per
            batch. A smaller batch size, possibly in combination with a
            smaller nb_parallel, will reduce the memory usage.
            Defaults to -1: (try to) determine optimal size automatically.
        force (bool, optional): [description]. Defaults to False.
        tmp_basedir (Optional[Path], optional): The directory to create the temporary
            directory in for this operation call. If None, it is created in the default
            geofileops temporary directory. Useful to keep all temporary files for an
            operation that uses multiple steps in one temporary directory.
        parallelization_config (ParallelizationConfig, optional): Defaults to None.

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
    if _io_util.output_exists(path=output_path, remove_if_exists=force):
        return

    if input_path == output_path:
        raise ValueError(f"{operation_name}: output_path must not equal input_path")
    if not input_path.exists():
        raise FileNotFoundError(f"{operation_name}: input_path not found: {input_path}")

    if not isinstance(input_layer, LayerInfo):
        input_layer = gfo.get_layerinfo(input_path, input_layer)
    if output_layer is None:
        output_layer = gfo.get_default_layer(output_path)
    if isinstance(force_output_geometrytype, GeometryType):
        force_output_geometrytype = force_output_geometrytype.name
    if isinstance(columns, str):
        # If a string is passed, convert to list
        columns = [columns]

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

    with _general_helper.create_gfo_tmp_dir(operation.value, tmp_basedir) as tmp_dir:
        # Calculate the best number of parallel processes and batches for
        # the available resources
        process_params = _prepare_processing_params(
            input_path=input_path,
            input_layer=input_layer,
            nb_parallel=nb_parallel,
            batchsize=batchsize,
            parallelization_config=parallelization_config,
            tmp_dir=tmp_dir,
        )

        # Prepare temp output filename
        # If output is a zip file, drop the .zip suffix
        tmp_output_path = tmp_dir / GeoPath(output_path).name_nozip

        # Start processing
        worker_type = _general_helper.worker_type_to_use(
            process_params.nb_rows_to_process
        )
        logger.info(
            f"Start processing ({process_params.nb_parallel} "
            f"{worker_type}, batch size: {process_params.batchsize})"
        )
        with _processing_util.PooledExecutorFactory(
            worker_type=worker_type,
            max_workers=process_params.nb_parallel,
            initializer=_processing_util.initialize_worker(worker_type),
        ) as calculate_pool:
            batches: dict[int, dict] = {}
            future_to_batch_id = {}

            for batch_id, batch_filter in enumerate(process_params.batches):
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
                    force_output_geometrytype=force_output_geometrytype,
                    gridsize=gridsize,
                    keep_empty_geoms=keep_empty_geoms,
                    preserve_fid=preserve_fid,
                    create_spatial_index=False,
                    force=force,
                )
                future_to_batch_id[future] = batch_id

            # Loop till all parallel processes are ready, but process each one
            # that is ready already
            # Remark: calculating can be done in parallel, but only one process
            # can write to the same output file at the time...
            start_time = datetime.now()
            nb_done = 0
            nb_batches = len(process_params.batches)
            _general_util.report_progress(
                start_time,
                nb_done,
                nb_todo=nb_batches,
                operation=operation.value,
                nb_parallel=process_params.nb_parallel,
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
                        # Remark: force_output_geometrytype and explodecollections have
                        # already been applied in the calculation step.
                        if (
                            where_post is None
                            and tmp_partial_output_path.suffix == tmp_output_path.suffix
                            and not tmp_output_path.exists()
                        ):
                            gfo.move(tmp_partial_output_path, tmp_output_path)
                        else:
                            fileops.copy_layer(
                                src=tmp_partial_output_path,
                                dst=tmp_output_path,
                                src_layer=output_layer,
                                dst_layer=output_layer,
                                write_mode="append",
                                create_spatial_index=False,
                                where=where_post,
                                preserve_fid=preserve_fid,
                            )
                            gfo.remove(tmp_partial_output_path)

                except Exception as ex:  # pragma: no cover
                    batch_id = future_to_batch_id[future]
                    message = f"Error {ex} executing {batches[batch_id]}"
                    logger.exception(message)
                    raise RuntimeError(message) from ex

                # Log the progress and prediction speed
                nb_done += 1
                _general_util.report_progress(
                    start_time,
                    nb_done,
                    nb_todo=nb_batches,
                    operation=operation.value,
                    nb_parallel=process_params.nb_parallel,
                )

        # Round up and clean up
        # Now create spatial index and move to output location
        if tmp_output_path.exists():
            # Create spatial index if needed
            if GeofileInfo(tmp_output_path).default_spatial_index:
                gfo.create_spatial_index(path=tmp_output_path, layer=output_layer)

            # Zip if needed
            if (
                output_path.suffix.lower() == ".zip"
                and not tmp_output_path.suffix.lower() == ".zip"
            ):
                zipped_path = Path(f"{tmp_output_path.as_posix()}.zip")
                fileops.zip_geofile(tmp_output_path, zipped_path)
                tmp_output_path = zipped_path

            # Move to final location
            gfo.move(tmp_output_path, output_path)
        else:
            logger.debug("Result was empty")

    logger.info(f"Ready, took {datetime.now() - start_time_global}")


def _apply_geooperation(
    input_path: Path,
    output_path: Path,
    operation: GeoOperation,
    operation_params: dict,
    input_layer: LayerInfo,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    where=None,
    explodecollections: bool = False,
    force_output_geometrytype: GeometryType | str | None = None,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = False,
    preserve_fid: bool = False,
    create_spatial_index: bool = False,
    force: bool = False,
) -> str:
    # Init
    if not output_path.parent.exists():
        raise ValueError(f"Output directory does not exist: {output_path.parent}")
    if output_path.exists():
        if not force:
            message = f"Stop, output already exists {output_path}"
            return message
        else:
            gfo.remove(output_path)

    # Now go!
    start_time = datetime.now()
    data_gdf = gfo.read_file(
        path=input_path,
        layer=input_layer.name,
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
        elif operation is GeoOperation.APPLY_VECTORIZED:
            func = pickle.loads(operation_params["pickled_func"])
            data_gdf.geometry = func(data_gdf.geometry)
        else:
            raise ValueError(f"operation not supported: {operation}")

    # If there is an fid column in the dataset, rename it, because the fid column is a
    # "special case" in gdal that should not be written.
    columns_lower_lookup = {column.lower(): column for column in data_gdf.columns}
    if "fid" in columns_lower_lookup:
        fid_column = columns_lower_lookup["fid"]
        for fid_number in range(1, 100):
            new_name = f"{fid_column}_{fid_number}"
            if new_name not in columns_lower_lookup:
                data_gdf = data_gdf.rename(columns={fid_column: new_name}, copy=False)

    if gridsize != 0.0:
        data_gdf.geometry = _geoseries_util.set_precision(
            data_gdf.geometry, grid_size=gridsize, raise_on_topoerror=False
        )

    if explodecollections:
        data_gdf = data_gdf.explode(ignore_index=True)

    # Set empty geometries to None
    data_gdf.loc[data_gdf.geometry.is_empty, data_gdf.geometry.name] = None

    if not keep_empty_geoms:
        # Remove rows where geometry is None
        data_gdf = data_gdf[~data_gdf.geometry.isna()]

    # If the result is empty, and no output geometrytype specified, use input
    # geometrytype
    if force_output_geometrytype is None and len(data_gdf) == 0:
        if explodecollections:
            force_output_geometrytype = input_layer.geometrytype.to_singletype
        else:
            force_output_geometrytype = input_layer.geometrytype.to_multitype

    # If the index is still unique, save it to fid column so to_file can save it
    if preserve_fid:
        data_gdf = data_gdf.reset_index(drop=False)

    # Use force_multitype if explodecollections=False to avoid warnings/issues when some
    # batches contain singletype and some contain multitype geometries
    gfo.to_file(
        gdf=data_gdf,
        path=output_path,
        layer=output_layer,
        index=False,
        force_output_geometrytype=force_output_geometrytype,
        force_multitype=not explodecollections,
        create_spatial_index=create_spatial_index,
    )

    message = f"Took {datetime.now() - start_time} for {len(data_gdf)} rows ({where})"
    return message


def dissolve(  # noqa: D417
    input_path: Path,
    output_path: Path,
    groupby_columns: list[str] | str | None = None,
    agg_columns: dict | None = None,
    explodecollections: bool = True,
    tiles_path: Path | None = None,
    nb_squarish_tiles: int = 1,
    input_layer: str | LayerInfo | None = None,
    output_layer: str | None = None,
    gridsize: float = 0.0,
    where_post: str | None = None,
    nb_parallel: int = -1,
    batchsize: int = -1,
    force: bool = False,
    operation_prefix: str = "",
    tmp_basedir: Path | None = None,
):
    """Function that applies a dissolve.

    End user documentation can be found in module geoops!

    Remark: keep_empty_geoms is not implemented because this is not so easy because
    (for polygon dissolve) the batches are location based, and null/empty geometries
    don't have a location. It could be implemented, but as long as nobody needs it...

    The attribute data aggregation logic is a bit more complex to be able to process
    per tile and in multiple passed for large datasets:
      - Note that a geometry that lies on the edge of 2 (or more) tiles will be split up
        on the tile boundary(ies) and each part will be further treated in the
        respective tile.
      - To be able to correctly perform attribute aggregations, they can only be
        determined after all tiles and passes have been finished, as the information
        from multiple tiles over multiple passes might have to be combined.
      - Hence, all needed data (columns and values) is stored in intermediate/temporary
        results so it can be all combined at the end.
      - In practice, during the first calculation pass, all relevant columns and values
        as well as the original fid of the geometries are serialized as a JSON string
        for each input geometry. When a geometry is dissolved with another geometry in
        this pass, their json strings are concatenated to a list. This way, all data is
        retained. An example of a JSON string list for 2 dissolved geometries:
            [{"fid_orig": 1, "area": 10.0}, {"fid_orig": 2, "area": 5.0}]
      - When geometries are merged in a following dissolve pass, the lists of JSON
        strings will be concatenated so all data is always retained. If a geometry was
        on the border of 2 tiles, this can result in multiple identical JSON strings. In
        the following example, fid_orig 1 was on the border of 2 tiles and was dissolved
        again in a following pass, leading to the following JSON string list:
            [
                {"fid_orig": 1, "area": 10.0},
                {"fid_orig": 1, "area": 10.0},
                {"fid_orig": 2, "area": 5.0},
            ]
      - When all passes are done, meaning everything is glued together and all attribute
        JSON strings are combined in one big list for each final geometry, the attribute
        aggregations can be performed.
      - When an original geometry was on the boundary of 2 (or more) tiles in the first
        pass, like in the example above, the aggregation has to ignore the resulting
        duplicate atttribute JSON strings. Otherwise a e.g. "SUM" aggregate will
        double-count values.
      - The `fid_orig` with the original `fid` from the source file is included for this
        reason. The `fid_orig` and all attributes of such split geometries will be the
        same. The `fid_orig` of other geometries that were actually dissolved will
        always be different. Hence, a simple "distinct" on the JSON strings will result
        in the correct list of JSON strings that should be used to base the agregations
        on. The only caveat is that the order of the columns in the JSON strings always
        needs to be the same.

    Only arguments specific to the internal dissolve operation are documented here.
    For the other arguments, check out the corresponding function in geoops.py.

    Args:
        tmp_basedir (Optional[Path], optional): The directory to create the temporary
            directory in for this operation call. If None, it is created in the default
            geofileops temporary directory. Useful to keep all temporary files for an
            operation that uses multiple steps in one temporary directory.
            Defaults to None.
    """
    # Init and validate input parameters
    # ----------------------------------
    operation_name = f"{operation_prefix}dissolve"
    logger = logging.getLogger(f"geofileops.{operation_name}")

    # Check if we need to calculate anyway
    if _io_util.output_exists(path=output_path, remove_if_exists=force):
        return

    # Standardize parameter to simplify the rest of the code
    if groupby_columns is not None:
        if isinstance(groupby_columns, str):
            # If a string is passed, convert to list
            groupby_columns = [groupby_columns]
        elif len(groupby_columns) == 0:
            # If an empty list of geometry columns is passed, convert it to None
            groupby_columns = None

    if input_path == output_path:
        raise ValueError("output_path must not equal input_path")
    if not input_path.exists():
        raise FileNotFoundError(f"input_path not found: {input_path}")

    if not isinstance(input_layer, LayerInfo):
        input_layer = gfo.get_layerinfo(input_path, input_layer)

    if input_layer.geometrytype.to_primitivetype in [
        PrimitiveType.POINT,
        PrimitiveType.LINESTRING,
    ]:
        if tiles_path is not None or nb_squarish_tiles > 1:
            raise ValueError(
                f"Dissolve to tiles is not supported for {input_layer.geometrytype}"
                ", so tiles_path should be None and nb_squarish_tiles should be 1)"
            )

    if output_layer is None:
        output_layer = gfo.get_default_layer(output_path)

    # Check columns in groupby_columns
    columns_available = list(input_layer.columns) + ["fid"]
    if groupby_columns is not None:
        columns_in_layer_upper = [column.upper() for column in columns_available]
        for column in groupby_columns:
            if column.upper() not in columns_in_layer_upper:
                raise ValueError(
                    f"column in groupby_columns not available in layer: {column}"
                )
        columns_available = _general_util.align_casing_list(
            columns_available, groupby_columns, raise_on_missing=False
        )

    # Check agg_columns param
    if agg_columns is not None:
        # Validate the dict structure, so we can assume everything is OK further on
        _parameter_helper.validate_agg_columns(agg_columns)

        # First take a deep copy, as values can be changed further on to treat columns
        # case insensitive
        agg_columns = copy.deepcopy(agg_columns)
        if "json" in agg_columns:
            if agg_columns["json"] is None:
                agg_columns["json"] = [
                    c for c in columns_available if c.lower() not in ("index", "fid")
                ]
            else:
                # Align casing of column names to data
                agg_columns["json"] = _general_util.align_casing_list(
                    agg_columns["json"], columns_available
                )
        elif "columns" in agg_columns:
            # Loop through all rows
            for agg_column in agg_columns["columns"]:
                # Check if column exists + set casing same as in data
                agg_column["column"] = _general_util.align_casing(
                    agg_column["column"], columns_available
                )

    # Check what we need to do in an error occurs
    on_data_error = ConfigOptions.on_data_error

    # Now start dissolving
    # --------------------
    # Empty or Line and point layers are:
    #   * not so large (memory-wise)
    #   * aren't computationally heavy
    # Additionally line layers are a pain to handle correctly because of
    # rounding issues at the borders of tiles... so just dissolve them in one go.
    if input_layer.featurecount == 0 or input_layer.geometrytype.to_primitivetype in [
        PrimitiveType.POINT,
        PrimitiveType.LINESTRING,
    ]:
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
            tmp_basedir=tmp_basedir,
        )

    elif input_layer.geometrytype.to_primitivetype is PrimitiveType.POLYGON:
        start_time = datetime.now()

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
            if input_layer.crs is not None and not input_layer.crs.is_projected:
                # If geographic crs, 1 degree = 111 km or 111000 m
                margin /= 111000
            bounds = input_layer.total_bounds
            bounds = (
                bounds[0] - margin,
                bounds[1] - margin,
                bounds[2] + margin,
                bounds[3] + margin,
            )
            result_tiles_gdf = gpd.GeoDataFrame(
                geometry=pygeoops.create_grid2(bounds, nb_squarish_tiles),
                crs=input_layer.crs,
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
        with _general_helper.create_gfo_tmp_dir(operation_name, tmp_basedir) as tmp_dir:
            if output_layer is None:
                output_layer = gfo.get_default_layer(output_path)
            output_tmp_path = tmp_dir / "output_tmp.gpkg"
            prev_nb_batches = None
            last_pass = False
            pass_id = 0
            geoindex_column = "__tmp_geoindex_column__"

            logger.info(f"Start, with input {input_path}")
            input_pass_path = input_path
            input_pass_layer = input_layer
            while True:
                # Get info of the current file that needs to be dissolved
                nb_rows_total = input_pass_layer.featurecount

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
                    grid_total_bounds = (
                        input_pass_layer.total_bounds[0] - 0.000001,
                        input_pass_layer.total_bounds[1] - 0.000001,
                        input_pass_layer.total_bounds[2] + 0.000001,
                        input_pass_layer.total_bounds[3] + 0.000001,
                    )
                    tiles_gdf = gpd.GeoDataFrame(
                        geometry=pygeoops.create_grid2(
                            total_bounds=grid_total_bounds,
                            nb_squarish_tiles=nb_batches,
                            nb_squarish_tiles_max=nb_squarish_tiles_max,
                        ),
                        crs=input_pass_layer.crs,
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
                gfo.to_file(tiles_gdf, tmp_dir / f"output_{pass_id}_tiles.gpkg")

                # If the number of tiles ends up as 1, it is the last pass anyway...
                if len(tiles_gdf) == 1:
                    last_pass = True

                # If we are not in the last pass, onborder parcels will need extra
                # processing still in further passes, so are saved in a seperate
                # gfo. The notonborder rows are final immediately
                if last_pass is not True:
                    output_tmp_onborder_path = (
                        tmp_dir / f"output_{pass_id}_onborder.gpkg"
                    )
                else:
                    output_tmp_onborder_path = output_tmp_path

                # Now go!
                logger.info(
                    f"Start pass {pass_id} to {len(tiles_gdf)} tiles "
                    f"(batch size: {int(nb_rows_total / len(tiles_gdf))})"
                )
                pass_start = datetime.now()
                _ = _dissolve_polygons_pass(
                    input_path=input_pass_path,
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
                    geoindex_column=geoindex_column,
                    on_data_error=on_data_error,
                )
                logger.info(f"Pass {pass_id} ready, took {datetime.now() - pass_start}")

                # If this was the last pass, if the last pass didn't have any onborder
                # polygons as result, we are ready dissolving.
                if last_pass or not output_tmp_onborder_path.exists():
                    break

                # Prepare the next pass
                prev_nb_batches = len(tiles_gdf)
                input_pass_path = output_tmp_onborder_path
                input_pass_layer = gfo.get_layerinfo(input_pass_path)
                pass_id += 1

            # Calculation ready! Now finalise output!
            logger.info("Finalize result")
            # If there is a result on border, append it to the rest
            if (
                str(output_tmp_onborder_path) != str(output_tmp_path)
                and output_tmp_onborder_path.exists()
            ):
                gfo.copy_layer(
                    output_tmp_onborder_path,
                    output_tmp_path,
                    dst_layer=output_layer,
                    write_mode="append",
                    preserve_fid=False,
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
                                f"'$.{agg_column['column']}')"
                            )

                            # Now put everything together
                            agg_columns_str += (
                                f", {aggregation_str}({distinct_str}{column_str}"
                                f'{extra_param_str}) AS "{agg_column["as"]}"'
                            )

                # Prepare SQL statement for final output file if one is needed.

                # All tiles are already dissolved to groups, but now the results from
                # all tiles could still need to be grouped/collected together.
                if agg_columns is None:
                    # If there are no aggregation columns, things are not too
                    # complicated.
                    if explodecollections:
                        # As explodecollections is also true, no grouping nor collecting
                        # needed.
                        sql_stmt = f"""
                            SELECT {{geometrycolumn}}
                                  {groupby_select_prefixed_str.format(prefix="layer.")}
                              FROM "{{input_layer}}" layer
                             ORDER BY layer.{geoindex_column}
                        """
                    else:
                        # No explodecollections, so collect to one geometry
                        # (per groupby if applicable).
                        sql_stmt = f"""
                            SELECT ST_Collect({{geometrycolumn}}) AS {{geometrycolumn}}
                                  {groupby_select_prefixed_str.format(prefix="layer.")}
                              FROM "{{input_layer}}" layer
                              {groupby_groupby_prefixed_str.format(prefix="layer.")}
                             ORDER BY MIN(layer.{geoindex_column})
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
                                  ,MIN(layer_geo.{geoindex_column}) as {geoindex_column}
                              FROM "{{input_layer}}" layer_geo
                              {groupby_groupby_prefixed_str.format(prefix="layer_geo.")}
                            ) geo_data
                          JOIN (
                            SELECT DISTINCT json_rows_table.value as json_row
                                {groupby_select_prefixed_str.format(prefix="layer_for_json.")}
                              FROM "{{input_layer}}" layer_for_json
                              CROSS JOIN json_each(
                                  layer_for_json.__DISSOLVE_TOJSON, '$') json_rows_table
                            ) json_data
                         WHERE 1=1
                            {groupby_filter_str}
                          {groupby_groupby_prefixed_str.format(prefix="geo_data.")}
                          ORDER BY geo_data.{geoindex_column}
                    """

                # Apply where_post parameter if needed/possible
                if where_post is not None and not explodecollections:
                    # explodecollections is not True, so we can add it to sql_stmt.
                    # If explodecollections would be True, we need to wait to apply the
                    # where_post till after explodecollections is applied to be sure it
                    # gives correct results.
                    where_post = where_post.format(geometrycolumn="geom")
                    sql_stmt = f"""
                        SELECT * FROM
                            ( {sql_stmt}
                            )
                         WHERE {where_post}
                    """
                    # where_post has been applied already so set to None.
                    where_post = None

                # Execute the prepared sql statement
                output_geometrytype = (
                    input_layer.geometrytype.to_singletype
                    if explodecollections
                    else input_layer.geometrytype.to_multitype
                )
                sql_stmt = sql_stmt.format(
                    geometrycolumn="geom", input_layer=output_layer
                )

                options = {}
                if where_post is None:
                    name = GeoPath(output_path).name_nozip
                else:
                    # where_post still needs to be ran, so no index + to gpkg
                    name = "output_tmp2_final.gpkg"
                    options["LAYER_CREATION.SPATIAL_INDEX"] = False
                output_tmp_final_path = tmp_dir / name

                _ogr_util.vector_translate(
                    input_path=output_tmp_path,
                    output_path=output_tmp_final_path,
                    output_layer=output_layer,
                    sql_stmt=sql_stmt,
                    sql_dialect="SQLITE",
                    force_output_geometrytype=output_geometrytype,
                    explodecollections=explodecollections,
                    options=options,
                )

                # We still need to apply the where_post filter
                if where_post is not None:
                    name = f"output_tmp3_where_{GeoPath(output_path).suffix_full}"
                    output_tmp_local_path = tmp_dir / name
                    tmp_info = gfo.get_layerinfo(output_tmp_final_path, output_layer)
                    where_post = where_post.format(
                        geometrycolumn=tmp_info.geometrycolumn
                    )
                    sql_stmt = f"""
                        SELECT * FROM "{output_layer}"
                         WHERE {where_post}
                    """
                    sql_stmt = sql_stmt.format(geometrycolumn=tmp_info.geometrycolumn)
                    _ogr_util.vector_translate(
                        input_path=output_tmp_final_path,
                        output_path=output_tmp_local_path,
                        output_layer=output_layer,
                        force_output_geometrytype=output_geometrytype,
                        sql_stmt=sql_stmt,
                        sql_dialect="SQLITE",
                    )
                    output_tmp_final_path = output_tmp_local_path

                # Zip if needed
                if (
                    output_path.suffix.lower() == ".zip"
                    and not output_tmp_final_path.suffix.lower() == ".zip"
                ):
                    zipped_path = Path(f"{output_tmp_final_path.as_posix()}.zip")
                    fileops.zip_geofile(output_tmp_final_path, zipped_path)
                    output_tmp_final_path = zipped_path

                # Now we are ready to move the result to the final spot...
                gfo.move(output_tmp_final_path, output_path)

        logger.info(f"Ready, full dissolve took {datetime.now() - start_time}")

    else:
        raise NotImplementedError(
            f"Unsupported input geometrytype: {input_layer.geometrytype}"
        )


def _dissolve_polygons_pass(
    input_path: Path,
    output_notonborder_path: Path,
    output_onborder_path: Path,
    explodecollections: bool,
    groupby_columns: Iterable[str] | None,
    agg_columns: dict | None,
    tiles_gdf: gpd.GeoDataFrame,
    input_layer: str | LayerInfo | None,
    output_layer: str | None,
    gridsize: float,
    keep_empty_geoms: bool,
    nb_parallel: int,
    geoindex_column: str,
    on_data_error: str = "raise",
):
    start_time = datetime.now()
    if not isinstance(input_layer, LayerInfo):
        input_layer = gfo.get_layerinfo(input_path, input_layer)

    # Make sure the input file has a spatial index
    tmp_dir = output_onborder_path.parent
    # If it is not a .gpkg.zip that already has a spatial index, unzip the file if it is
    # zipped and create a spatial index on it if it doesn't have one.
    if not (
        input_path.name.lower().endswith(".gpkg.zip")
        and fileops.has_spatial_index(input_path)
    ):
        if GeoPath(input_path).is_multi_suffix:
            # Unzip, as we can't create a spatial index on a zipped file
            unzipped_dir = tmp_dir / "input_unzipped"
            input_path = fileops.unzip_geofile(input_path, unzipped_dir)
        gfo.create_spatial_index(input_path, layer=input_layer, exist_ok=True)

    # Start calculation in parallel# Start processing
    worker_type = _general_helper.worker_type_to_use(input_layer.featurecount)
    with _processing_util.PooledExecutorFactory(
        worker_type=worker_type,
        max_workers=nb_parallel,
        initializer=_processing_util.initialize_worker(worker_type),
    ) as calculate_pool:
        batches: dict[int, dict] = {}
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
            output_notonborder_tmp_partial_path = tmp_dir / name
            batches[batch_id]["output_notonborder_tmp_partial_path"] = (
                output_notonborder_tmp_partial_path
            )
            name = f"{output_onborder_path.stem}_{batch_id}{suffix}"
            output_onborder_tmp_partial_path = tmp_dir / name
            batches[batch_id]["output_onborder_tmp_partial_path"] = (
                output_onborder_tmp_partial_path
            )

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
                input_geometrytype=input_layer.geometrytype,
                input_layer=input_layer,
                output_layer=output_layer,
                bbox=tile_row.geometry.bounds,
                tile_id=tile_id,
                gridsize=gridsize,
                keep_empty_geoms=keep_empty_geoms,
                geoindex_column=geoindex_column,
                on_data_error=on_data_error,
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
                        if not output_notonborder_path.exists():
                            fileops.move(
                                src=output_notonborder_tmp_partial_path,
                                dst=output_notonborder_path,
                            )
                        else:
                            fileops.copy_layer(
                                src=output_notonborder_tmp_partial_path,
                                dst=output_notonborder_path,
                                src_layer=output_layer,
                                dst_layer=output_layer,
                                write_mode="append",
                                create_spatial_index=False,
                                preserve_fid=False,
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
                        if not output_onborder_path.exists():
                            fileops.move(
                                src=output_onborder_tmp_partial_path,
                                dst=output_onborder_path,
                            )
                        else:
                            fileops.copy_layer(
                                src=output_onborder_tmp_partial_path,
                                dst=output_onborder_path,
                                src_layer=output_layer,
                                dst_layer=output_layer,
                                write_mode="append",
                                create_spatial_index=False,
                                preserve_fid=False,
                            )
                            gfo.remove(output_onborder_tmp_partial_path)

            except Exception as ex:  # pragma: no cover
                batch_id = future_to_batch_id[future]
                message = f"Error executing {batches[batch_id]}: {ex}"
                logger.exception(message)
                calculate_pool.shutdown()
                raise RuntimeError(message) from ex

            # Log the progress and prediction speed
            _general_util.report_progress(
                start_time, nb_batches_done, nb_batches, "dissolve"
            )


def _dissolve_polygons(
    input_path: Path,
    output_notonborder_path: Path,
    output_onborder_path: Path,
    explodecollections: bool,
    groupby_columns: Iterable[str] | None,
    agg_columns: dict | None,
    input_geometrytype: GeometryType,
    input_layer: str | LayerInfo | None,
    output_layer: str | None,
    bbox: tuple[float, float, float, float],
    tile_id: int | None,
    gridsize: float,
    keep_empty_geoms: bool,
    geoindex_column: str | None,
    on_data_error: str = "raise",
) -> dict:
    # Init
    perfinfo: dict[str, float] = {}
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
    groupby_columns = list(groupby_columns) if groupby_columns is not None else None
    while True:
        try:
            columns_to_read: set[str] = set()
            if not isinstance(input_layer, LayerInfo):
                input_layer = gfo.get_layerinfo(input_path, input_layer)
            if groupby_columns is not None:
                columns_to_read.update(groupby_columns)
            fid_as_index = False
            if agg_columns is not None:
                fid_as_index = True
                if "__DISSOLVE_TOJSON" in input_layer.columns:
                    # If we are not in the first pass, the columns to be read
                    # are already in the json column
                    columns_to_read.add("__DISSOLVE_TOJSON")
                else:
                    # The first pass, so read all relevant columns to code them in json
                    if "json" in agg_columns:
                        agg_columns_needed = list(agg_columns["json"])
                    elif "columns" in agg_columns:
                        agg_columns_needed = [
                            agg_column["column"]
                            for agg_column in agg_columns["columns"]
                        ]

                        # Avoid reading/saving needed columns multiple times.
                        # The order of the columns should always be the same in the json
                        # to be able to filter distinct rows efficiently, so sort them,
                        # as a set gives a different order from run to run.
                        agg_columns_needed = sorted(set(agg_columns_needed))
                    if agg_columns_needed is not None:
                        columns_to_read.update(agg_columns_needed)

            input_gdf = gfo.read_file(
                path=input_path,
                layer=input_layer.name,
                bbox=bbox,
                columns=columns_to_read,
                fid_as_index=fid_as_index,
            )

            if agg_columns is not None and agg_columns_needed is not None:
                # The fid should be added as well, but make name unique
                fid_orig_column = "fid_orig"
                for idx in range(99999):
                    if idx != 0:
                        fid_orig_column = f"fid_orig{idx}"
                    if fid_orig_column not in agg_columns_needed:
                        break

                input_gdf[fid_orig_column] = input_gdf.index
                agg_columns_needed.insert(0, fid_orig_column)

            break
        except Exception as ex:  # pragma: no cover
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
    aggfunc: str | dict | None = None
    if agg_columns is not None:
        if "__DISSOLVE_TOJSON" not in input_gdf.columns:
            # First pass -> put relevant columns in json field.
            aggfunc = {"to_json": agg_columns_needed}
        else:
            # Columns already coded in a json column, so merge json lists
            aggfunc = "merge_json_lists"
    else:
        aggfunc = "first"

    start_dissolve = datetime.now()
    try:
        diss_gdf = _dissolve(
            df=input_gdf,
            by=groupby_columns,
            aggfunc=aggfunc,
            as_index=False,
            dropna=False,
            grid_size=gridsize,
        )
    except Exception as ex:  # pragma: no cover
        # If a GEOS exception occurs, check on_data_error on how to proceed.
        if on_data_error == "warn":
            message = f"Error processing tile, ENTIRE TILE LOST!!!: {ex}"
            warnings.warn(message, UserWarning, stacklevel=3)

            # Return
            return_info["perfinfo"] = perfinfo
            return_info["message"] = message
            return return_info
        else:
            raise ex

    perfinfo["time_dissolve"] = (datetime.now() - start_dissolve).total_seconds()

    if "index" in diss_gdf.columns and (
        groupby_columns is None or "index" not in groupby_columns
    ):
        diss_gdf.drop("index", axis=1, inplace=True)

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
        bbox_gdf = gpd.GeoDataFrame(geometry=[sh_geom.box(*bbox)], crs=input_gdf.crs)

        # keep_geom_type=True gave sometimes error, and still does in 0.9.0
        # so use own implementation of keep_geom_type
        diss_gdf = gpd.clip(diss_gdf, bbox_gdf)  # , keep_geom_type=True)

        # Only keep geometries of the primitive type specified after clip...
        diss_gdf.geometry = pygeoops.collection_extract(
            diss_gdf.geometry, primitivetype=input_geometrytype.to_primitivetype
        )

        perfinfo["time_clip"] = (datetime.now() - start_clip).total_seconds()

    # Set empty geometries to None
    assert isinstance(diss_gdf.geometry, gpd.GeoSeries)
    diss_gdf.loc[diss_gdf.geometry.is_empty, diss_gdf.geometry.name] = None

    if not keep_empty_geoms:
        # Remove rows where geom is None
        diss_gdf = diss_gdf[~diss_gdf.geometry.isna()]

    # If there is no result, return
    if len(diss_gdf) == 0:
        message = f"Result is empty for {input_path}"
        return_info["message"] = message
        return_info["perfinfo"] = perfinfo
        return_info["total_time"] = (datetime.now() - start_time).total_seconds()
        return return_info

    # Split up in onborder and notonborder geometries
    if str(output_notonborder_path) == str(output_onborder_path):
        # If tiles don't need to be merged afterwards, treat everything as notonborder.
        onborder_gdf = None
        notonborder_gdf = diss_gdf
    else:
        # If not, save the polygons on the border seperately
        bbox_lines = pygeoops.explode(
            shapely.boundary(sh_geom.box(bbox[0], bbox[1], bbox[2], bbox[3]))
        )
        bbox_lines_gdf = gpd.GeoDataFrame(geometry=bbox_lines, crs=input_gdf.crs)
        onborder_gdf = gpd.sjoin(diss_gdf, bbox_lines_gdf, predicate="intersects")
        onborder_gdf.drop("index_right", axis=1, inplace=True)

        notonborder_gdf = diss_gdf[~diss_gdf.index.isin(onborder_gdf.index)].copy()

    # Save the result to destination file(s)
    start_to_file = datetime.now()

    # If explodecollections is False, force multitype to avoid warnings when some
    # batches contain singletype and some contain multitype geometries.
    force_multitype = not explodecollections
    if onborder_gdf is not None and len(onborder_gdf) > 0:
        gfo.to_file(
            onborder_gdf,
            output_onborder_path,
            layer=output_layer,
            force_multitype=force_multitype,
            create_spatial_index=False,
        )

    if len(notonborder_gdf) > 0:
        # Add tile_id to the notonborder_gdf if relevant
        if tile_id is not None:
            notonborder_gdf["tile_id"] = tile_id

        # Add geoindex_column to the notonborder_gdf if asked
        if geoindex_column is not None:
            crs = notonborder_gdf.crs
            transformer = Transformer.from_crs(crs.geodetic_crs, crs, always_xy=True)
            crs_bounds = transformer.transform_bounds(*crs.area_of_use.bounds)
            notonborder_gdf[geoindex_column] = notonborder_gdf.hilbert_distance(
                crs_bounds
            )

        gfo.to_file(
            notonborder_gdf,
            output_notonborder_path,
            layer=output_layer,
            force_multitype=force_multitype,
            index=False,
            create_spatial_index=False,
        )

    perfinfo["time_to_file"] = (datetime.now() - start_to_file).total_seconds()

    # Finalise...
    message = (
        f"dissolve_polygons: ready in {datetime.now() - start_time} on {input_path}"
    )
    logger.debug(message)

    # Collect perfinfo
    total_perf_time = 0.0
    perfstring = ""
    for perfcode, perfvalue in perfinfo.items():
        total_perf_time += perfvalue
        perfstring += f"{perfcode}: {perfvalue:.2f}, "
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
    aggfunc: str | dict | None = "first",
    as_index=True,
    level=None,
    sort=True,
    observed=False,
    dropna=True,
    grid_size: float = 0.0,
) -> gpd.GeoDataFrame:
    """Dissolve geometries within `groupby` into single observation.

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
        agg_columns = list(aggfunc["to_json"])
        agg_data = (
            data.groupby(**groupby_kwargs)[agg_columns]
            .apply(lambda g: g[agg_columns].to_json(orient="records"))
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

        # Starting from pandas 2.2, include_groups=False should be passed to avoid
        # warnings
        kwargs = {"include_groups": False} if PANDAS_GTE_22 else {}
        agg_data = (
            data.groupby(**groupby_kwargs)
            .apply(lambda g: group_flatten_json_list(g), **kwargs)
            .to_frame(name="__DISSOLVE_TOJSON")
        )
    else:
        agg_data = data.groupby(**groupby_kwargs).agg(aggfunc)  # type: ignore[arg-type]
        # Check if all columns were properly aggregated
        columns_to_agg = [column for column in data.columns if column not in by_local]
        if len(columns_to_agg) != len(agg_data.columns):
            dropped_columns = [
                column for column in columns_to_agg if column not in agg_data.columns
            ]
            raise ValueError(
                f"Column(s) {dropped_columns} are not supported for aggregation, stop"
            )

    # Process spatial component
    def merge_geometries(block):
        return shapely.union_all(block, grid_size=grid_size)

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

    return aggregated
