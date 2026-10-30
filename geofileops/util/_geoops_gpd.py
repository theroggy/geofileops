"""Module containing the implementation of Geofile operations using GeoPandas."""

import copy
import enum
import json
import logging
import logging.config
import math
import multiprocessing
import pickle
import warnings
from collections.abc import Callable
from concurrent import futures
from datetime import datetime
from pathlib import Path
from typing import Any

import cloudpickle
import pandas as pd
import psutil
import pygeoops
import shapely
from pygeoops import GeometryType
from shapely.geometry.base import BaseGeometry

import geofileops as gfo
from geofileops import LayerInfo, fileops
from geofileops.helpers import _general_helper
from geofileops.helpers._options import ConfigOptions
from geofileops.util import (
    _general_util,
    _geoseries_util,
    _io_util,
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
        *,
        bytes_basefootprint: int = 50 * 1024 * 1024,
        bytes_per_row: int = 1000,
        min_rows_per_batch: int = 1000,
        max_rows_per_batch: int = 100000,
        bytes_min_per_process: int | None = None,
        bytes_usable: int | None = None,
        cpu_count: int = -1,
    ) -> None:
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
    def bytes_min_per_process(self) -> int:
        if self._bytes_min_per_process is not None:
            return self._bytes_min_per_process
        else:
            return (
                self.bytes_basefootprint + self.bytes_per_row * self.min_rows_per_batch
            )

    @bytes_min_per_process.setter
    def bytes_min_per_process(self, value: int) -> None:
        self._bytes_min_per_process = value


def _determine_nb_batches(
    nb_rows_total: int,
    nb_parallel: int | None = None,
    batchsize: int = -1,
    parallelization_config: ParallelizationConfig | None = None,
) -> tuple[int, int]:
    """Determines recommended parallelization params.

    Args:
        nb_rows_total (int): The total number of rows that will be processed
        nb_parallel (int | None, optional): the number of parallel workers to use.
            If None, the preference set in the nb_parallel configuration option is used,
            which defaults to the number of CPU cores available. For more information,
            see :func:`options.set_nb_parallel`. Defaults to None.
        batchsize (int, optional): indicative number of rows to process per batch.
            If -1: (try to) determine optimal size automatically using the heuristics in
            'parallelization_config'. Defaults to -1.
        parallelization_config (ParallelizationConfig, optional): Configuration
            parameters to use to suggest parallelisation parameters. If None, default
            parameters are used. Defaults to None.

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
    if (
        (nb_parallel is None or nb_parallel <= 0)
        and batchsize < 1
        and nb_rows_total <= config_local.min_rows_per_batch
    ):
        return (1, 1)

    nb_parallel = ConfigOptions.get_nb_parallel(
        nb_parallel_overrule=nb_parallel, nb_cpu_cores=config_local.cpu_count
    )

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
    ) -> None:
        self.nb_rows_to_process = nb_rows_to_process
        self.nb_parallel = nb_parallel
        self.batches = batches
        self.batchsize = batchsize

    def to_json(self, path: Path) -> None:
        prepared = _general_util.prepare_for_serialize(vars(self))
        with path.open("w", encoding="utf-8") as file:
            json.dump(prepared, file, indent=4, sort_keys=True)


def _prepare_processing_params(
    input_path: Path,
    input_layer: LayerInfo,
    *,
    nb_parallel: int | None,
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
    *,
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
    nb_parallel: int | None = None,
    batchsize: int = -1,
    force: bool = False,
    parallelization_config: ParallelizationConfig | None = None,
) -> None:
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
    nb_parallel: int | None,
    batchsize: int,
    force: bool,
    parallelization_config: ParallelizationConfig | None,
    tmp_basedir: Path | None,
) -> None:
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
    *,
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
    nb_parallel: int | None = None,
    batchsize: int = -1,
    force: bool = False,
    operation_prefix: str = "",
    tmp_basedir: Path | None = None,
) -> None:
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
    *,
    input_layer: str | None = None,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = False,
    where_post: str | None = None,
    nb_parallel: int | None = None,
    batchsize: int = -1,
    force: bool = False,
) -> None:
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
    *,
    input_layer: str | LayerInfo | None = None,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    explodecollections: bool = False,
    force_output_geometrytype: str | GeometryType | None = None,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = False,
    where_post: str | None = None,
    validate_attribute_data: bool = False,  # noqa: ARG001
    nb_parallel: int | None = None,
    batchsize: int = -1,
    force: bool = False,
) -> None:
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

    def makevalid_func(geom: BaseGeometry) -> BaseGeometry:
        return shapely.remove_repeated_points(
            pygeoops.make_valid(
                geom, keep_collapsed=keep_collapsed, only_if_invalid=True
            )
        )

    apply_vectorized(
        input_path=Path(input_path),
        output_path=Path(output_path),
        operation_name="makevalid",
        func=makevalid_func,
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
    *,
    lookahead: int = 8,
    input_layer: str | None = None,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    explodecollections: bool = False,
    gridsize: float = 0.0,
    keep_empty_geoms: bool = False,
    where_post: str | None = None,
    nb_parallel: int | None = None,
    batchsize: int = -1,
    force: bool = False,
) -> None:
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
    *,
    input_layer: str | LayerInfo | None,  # = None
    columns: list[str] | None,  # = None
    output_layer: str | None,  # = None
    explodecollections: bool,  # = False
    force_output_geometrytype: GeometryType | str | None,  # = None
    gridsize: float,  # = 0.0
    keep_empty_geoms: bool,  # = False
    where_post: str | None,  # = None
    nb_parallel: int | None,  # = -1
    batchsize: int,  # = -1
    force: bool,  # = False
    tmp_basedir: Path | None,
    parallelization_config: ParallelizationConfig | None = None,
) -> None:
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
        nb_parallel (int | None): the number of parallel workers to use.
            If None, the preference set in the nb_parallel configuration option is used,
            which defaults to the number of CPU cores available. For more information,
            see :func:`options.set_nb_parallel`.
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
        # Warn about low memory availability if needed
        _general_helper.warn_if_low_mem(called_from=operation_name)

        with _processing_util.PooledExecutorFactory(
            worker_type=worker_type,
            max_workers=process_params.nb_parallel,
            initializer=_processing_util.initialize_worker,
            initargs=(worker_type,),
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

            # Warn about low memory availability if needed
            _general_helper.warn_if_low_mem(called_from=f"{operation_name}_loop")

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
                and tmp_output_path.suffix.lower() != ".zip"
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
    *,
    input_layer: LayerInfo,
    output_layer: str | None = None,
    columns: list[str] | None = None,
    where: str | None = None,
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
