# -*- coding: utf-8 -*-
"""
Module containing utilities regarding the usage of ogr functionalities.
"""

# -------------------------------------
# Import/init needed modules
# -------------------------------------
from io import StringIO
import logging
import os
from pathlib import Path
import pprint
import re
import subprocess
import tempfile
from threading import Lock
import time
from typing import List, Optional, Tuple, Union

import geopandas as gpd
from osgeo import gdal

gdal.UseExceptions()
gdal.ConfigurePythonLogging(logger_name="gdal", enable_debug=False)

import geofileops as gfo
from geofileops.util.geofiletype import GeofileType
from geofileops.util.geometry_util import GeometryType

#####################################################################
# First define/init some general variables/constants
#####################################################################

# Make sure only one instance per process is running
lock = Lock()

# Get a logger...
logger = logging.getLogger(__name__)

#####################################################################
# The real work
#####################################################################


def get_drivers() -> dict:
    drivers = {}
    for i in range(gdal.GetDriverCount()):
        driver = gdal.GetDriver(i)
        drivers[driver.ShortName] = driver.GetDescription()
    return drivers


class VectorTranslateInfo:
    def __init__(
        self,
        input_path: Path,
        output_path: Path,
        input_layers: Union[List[str], str, None] = None,
        output_layer: Optional[str] = None,
        input_srs: Union[int, str, None] = None,
        output_srs: Union[int, str, None] = None,
        reproject: bool = False,
        spatial_filter: Optional[Tuple[float, float, float, float]] = None,
        clip_bounds: Optional[Tuple[float, float, float, float]] = None,
        sql_stmt: Optional[str] = None,
        sql_dialect: Optional[str] = None,
        transaction_size: int = 65536,
        append: bool = False,
        update: bool = False,
        explodecollections: bool = False,
        force_output_geometrytype: Optional[GeometryType] = None,
        options: dict = {},
    ):
        self.input_path = input_path
        self.output_path = output_path
        self.input_layers = input_layers
        self.output_layer = output_layer
        self.input_srs = input_srs
        self.output_srs = output_srs
        self.reproject = reproject
        self.spatial_filter = spatial_filter
        self.clip_bounds = clip_bounds
        self.sql_stmt = sql_stmt
        self.sql_dialect = sql_dialect
        self.transaction_size = transaction_size
        self.append = append
        self.update = update
        self.explodecollections = explodecollections
        self.force_output_geometrytype = force_output_geometrytype
        self.options = options


def vector_translate_by_info(info: VectorTranslateInfo):

    return vector_translate(
        input_path=info.input_path,
        output_path=info.output_path,
        input_layers=info.input_layers,
        output_layer=info.output_layer,
        input_srs=info.input_srs,
        output_srs=info.output_srs,
        reproject=info.reproject,
        spatial_filter=info.spatial_filter,
        clip_bounds=info.clip_bounds,
        sql_stmt=info.sql_stmt,
        sql_dialect=info.sql_dialect,
        transaction_size=info.transaction_size,
        append=info.append,
        update=info.update,
        explodecollections=info.explodecollections,
        force_output_geometrytype=info.force_output_geometrytype,
        options=info.options,
    )


def vector_translate(
    input_path: Union[Path, str],
    output_path: Path,
    input_layers: Union[List[str], str, None] = None,
    output_layer: Optional[str] = None,
    input_srs: Union[int, str, None] = None,
    output_srs: Union[int, str, None] = None,
    reproject: bool = False,
    spatial_filter: Optional[Tuple[float, float, float, float]] = None,
    clip_bounds: Optional[Tuple[float, float, float, float]] = None,
    sql_stmt: Optional[str] = None,
    sql_dialect: Optional[str] = None,
    transaction_size: int = 65536,
    append: bool = False,
    update: bool = False,
    explodecollections: bool = False,
    force_output_geometrytype: Optional[GeometryType] = None,
    options: dict = {},
) -> bool:

    # Remark: when executing a select statement, I keep getting error that
    # there are two columns named "geom" as he doesnt see the "geom" column
    # in the select as a geometry column. Probably a version issue. Maybe
    # try again later.
    args = []
    if isinstance(input_path, str):
        input_path = Path(input_path)
    gdal_options = _prepare_gdal_options(options, split_by_option_type=True)

    # Input file parameters
    # Cleanup the input_layers variable.
    if input_path.suffix.lower() == ".shp":
        # For shapefiles, having input_layers not None gives issues
        input_layers = None
    elif sql_stmt is not None:
        # If a sql statement is passed, the input layers are not relevant,
        # and ogr2ogr will give a warning, so clear it.
        input_layers = None

    # SRS
    if input_srs is not None and isinstance(input_srs, int):
        input_srs = f"EPSG:{input_srs}"

    # Sql'ing, Filtering, clipping
    if spatial_filter is not None:
        args.extend(
            [
                "-spat",
                str(spatial_filter[0]),
                str(spatial_filter[1]),
                str(spatial_filter[2]),
                str(spatial_filter[3]),
            ]
        )
    if clip_bounds is not None:
        args.extend(
            [
                "-clipsrc",
                str(clip_bounds[0]),
                str(clip_bounds[1]),
                str(clip_bounds[2]),
                str(clip_bounds[3]),
            ]
        )

    # Input dataset open options
    for option_name, value in gdal_options["INPUT_OPEN"].items():
        args.extend(["-oo", f"{option_name}={value}"])

    # Output file parameters
    # Get output format from the filename
    output_filetype = GeofileType(output_path)
    input_filetype = GeofileType(input_path)

    # SRS
    if output_srs is not None and isinstance(output_srs, int):
        output_srs = f"EPSG:{output_srs}"

    # Output basic options
    if output_path.exists() is True:
        if append is True:
            args.append("-append")
        if update is True:
            args.append("-update")

    datasetCreationOptions = []
    # Output dataset creation options are only applicable if a new output file
    # will be created
    if output_path.exists() is False or update is False:
        dataset_creation_options = gdal_options["DATASET_CREATION"]
        if output_filetype == GeofileType.SQLite:
            # If SQLite file, use the spatialite type of sqlite by default
            if "SPATIALITE" not in dataset_creation_options:
                dataset_creation_options["SPATIALITE"] = "YES"
        for option_name, value in dataset_creation_options.items():
            datasetCreationOptions.extend([f"{option_name}={value}"])

    # Output layer options
    if explodecollections is True:
        args.append("-explodecollections")
    if output_layer is not None:
        args.extend(["-nln", output_layer])
    if force_output_geometrytype is not None:
        args.extend(["-nlt", force_output_geometrytype.name])
    args.extend(["-nlt", "PROMOTE_TO_MULTI"])
    if transaction_size is not None:
        args.extend(["-gt", str(transaction_size)])

    # Output layer creation options are only applicable if a new layer will be
    # created
    layerCreationOptions = []
    if output_path.exists() is False or (update is True and append is False):
        for option_name, value in gdal_options["LAYER_CREATION"].items():
            layerCreationOptions.extend([f"{option_name}={value}"])

    # General configuration options
    # Remark: they cannot be passed on as parameter, but are set as
    # environment variables later on (using a context manager).
    config_options = gdal_options["CONFIG"]
    if input_filetype.is_spatialite_based or output_filetype.is_spatialite_based:
        # If spatialite based file, increase SQLITE cache size by default
        if "OGR_SQLITE_CACHE" not in config_options:
            config_options["OGR_SQLITE_CACHE"] = "128"

    # Consolidate all parameters
    options = gdal.VectorTranslateOptions(
        options=args,
        format=output_filetype.ogrdriver,
        accessMode=None,
        srcSRS=input_srs,
        dstSRS=output_srs,
        reproject=reproject,
        SQLStatement=sql_stmt,
        SQLDialect=sql_dialect,
        where=None,  # "geom IS NOT NULL",
        selectFields=None,
        addFields=False,
        forceNullable=False,
        spatFilter=spatial_filter,
        spatSRS=None,
        datasetCreationOptions=datasetCreationOptions,
        layerCreationOptions=layerCreationOptions,
        layers=input_layers,
        layerName=output_layer,
        geometryType=None,
        dim=None,
        segmentizeMaxDist=None,
        zField=None,
        skipFailures=False,
        limit=None,
        callback=None,
        callback_data=None,
    )

    # Now we can really get to work
    input_ds = None
    try:
        # In some cases gdal only raises the last exception instead of the stack in VectorTranslate,
        # so you lose necessary details! -> uncomment gdal.DontUseExceptions() when debugging!

        # gdal.DontUseExceptions()
        gdal.UseExceptions()
        gdal.ConfigurePythonLogging(logger_name="gdal", enable_debug=False)

        logger.debug(f"Execute {sql_stmt} on {input_path}")
        with set_config_options(config_options):
            input_ds = gdal.OpenEx(str(input_path))

            # TODO: memory output support might be interesting to support
            result_ds = gdal.VectorTranslate(
                destNameOrDestDS=str(output_path), srcDS=input_ds, options=options
            )

        if result_ds is None:
            raise Exception("BOOM")
        else:
            if result_ds.GetLayerCount() == 0:
                del result_ds
                if output_path.exists():
                    gfo.remove(output_path)
    except Exception as ex:
        message = f"Error executing {sql_stmt}"
        logger.exception(message)
        raise Exception(message) from ex
    finally:
        if input_ds is not None:
            del input_ds

    return True


def _prepare_gdal_options(options: dict, split_by_option_type: bool = False) -> dict:
    """
    Prepares the options so they are ready to pass on to gdal.

        - Uppercase the option key
        - Check if the option types are on of the supported ones:

            - LAYER_CREATION: layer creation option (lco)
            - DATASET_CREATION: dataset creation option (dsco)
            - INPUT_OPEN: input dataset open option (oo)
            - DESTINATION_OPEN: destination dataset open option (doo)
            - CONFIG: config option (config)
        - Prepare the option values
            - convert bool to YES/NO
            - convert all values to str

    Args:
        options (dict): options to pass to gdal.
        split_by_option_type (optional, bool): True to split the options in a
            seperate dict per option type. Defaults to False.

    Returns:
        dict: prepared options. If split_by_option_type: a dict of dicts for each
            occuring option type.
    """
    # Init prepared options with all existing option types
    option_types = [
        "LAYER_CREATION",
        "DATASET_CREATION",
        "INPUT_OPEN",
        "DESTINATION_OPEN",
        "CONFIG",
    ]
    prepared_options = {option_type: {} for option_type in option_types}

    # Loop through options specified to add them
    for option, value in options.items():
        # Prepare option type and name
        option_type, option_name = option.split(".")
        option_type = option_type.strip().upper()
        option_name = option_name.strip().upper()
        if option_type not in option_types:
            raise ValueError(
                f"Unsupported option type: {option_type}, should be one of {option_types}"
            )

        # Prepare value
        if isinstance(value, bool):
            value = "YES" if value is True else "NO"

        # Add to prepared options
        if option_name in prepared_options[option_type]:
            raise ValueError(
                f"option {option_type}.{option_name} specified more than once"
            )
        prepared_options[option_type][option_name] = str(value)

    # If no split is asked, convert back to original format
    if split_by_option_type is True:
        result = prepared_options
    else:
        result = {}
        for option_type in prepared_options:
            for option_name, value in prepared_options[option_type].items():
                result[f"{option_type}.{option_name}"] = value

    return result


class set_config_options(object):
    """
    Context manager to set config options.

    Args:
        config_options (dict): dict with config options to set.
            `Eg. { "OGR_SQLITE_CACHE", 128 }`
    """

    def __init__(self, config_options: dict):
        self.config_options = config_options

    def __enter__(self):
        # TODO: uncomment if GetConfigOptions() is supported
        # self.config_options_backup = gdal.GetConfigOptions()
        for name, value in self.config_options.items():
            # Prepare value
            if isinstance(value, bool):
                value = "YES" if value is True else "NO"
            gdal.SetConfigOption(str(name), str(value))

    def __exit__(self, type, value, traceback):
        # Remove config options that were set
        # TODO: delete loop + uncomment if SetConfigOptions() is supported
        for name, value in self.config_options.items():
            gdal.SetConfigOption(name, None)
        # gdal.SetConfigOptions(self.config_options_backup)


def _getfileinfo(path: Path, readonly: bool = True, verbose: bool = False) -> dict:

    # Get info
    info_str = vector_info(path=path, readonly=readonly, verbose=verbose)

    # Prepare result
    result_dict = {}
    result_dict["info_str"] = info_str
    result_dict["layers"] = []
    info_strio = StringIO(str(info_str))
    for line in info_strio.readlines():
        line = line.strip()
        if re.match(r"\A\d: ", line):
            # It is a layer, now extract only the layer name
            logger.debug(f"This is a layer: {line}")
            layername_with_geomtype = re.sub(r"\A\d: ", "", line)
            layername = re.sub(r" [(][a-zA-Z ]+[)]\Z", "", layername_with_geomtype)
            result_dict["layers"].append(layername)

    return result_dict


def vector_info(
    path: Path,
    task_description=None,
    layer: Optional[str] = None,
    readonly: bool = False,
    report_summary: bool = False,
    sql_stmt: Optional[str] = None,
    sql_dialect: Optional[str] = None,
    skip_health_check: bool = False,
    verbose: bool = False,
):
    """ "Run a command"""

    # Init
    if not path.exists():
        raise Exception(f"File does not exist: {path}")
    if os.name == "nt":
        ogrinfo_exe = "ogrinfo.exe"
    else:
        ogrinfo_exe = "ogrinfo"

    # Add all parameters to args list
    args = [str(ogrinfo_exe)]
    # args.extend(['--config', 'OGR_SQLITE_PRAGMA', 'journal_mode=WAL'])
    if readonly is True:
        args.append("-ro")
    if report_summary is True:
        args.append("-so")
    if sql_stmt is not None:
        args.extend(["-sql", sql_stmt])
    if sql_dialect is not None:
        args.extend(["-dialect", sql_dialect])

    # File and optionally the layer
    args.append(str(path))
    if layer is not None:
        # ogrinfo doesn't like + need quoted layer names, so remove single and
        # double quotes
        layer_stripped = layer.strip("'\"")
        args.append(layer_stripped)

    # TODO: ideally, the child processes would die when the parent is killed!

    # Run ogrinfo
    # Geopackage/sqlite files are very sensitive for being locked, so retry till
    # file is not locked anymore...
    sleep_time = 1
    returncode = None
    for retry_count in range(10):
        process = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=-1,
            encoding="utf-8",
        )

        output, err = process.communicate()
        returncode = process.returncode

        # If an error occured
        if returncode > 0:
            if str(err).startswith("ERROR 1: database is locked"):
                logger.warn(f"'ERROR 1: database is locked', retry nb: {retry_count}")
                time.sleep(sleep_time)
                sleep_time += 1
                continue
            else:
                raise Exception(
                    f"Error executing {pprint.pformat(args)}\n"
                    f"\t-> Return code: {returncode}\n"
                    f"\t-> Error: {err}\n\t->Output: {output}"
                )
        elif err is not None and err != "":
            # ogrinfo apparently sometimes give a wrong returncode, so if data
            # in stderr, treat as error as well
            raise Exception(
                f"Error executing {pprint.pformat(args)}\n"
                f"\t->Return code: {returncode}\n"
                f"\t->Error: {err}\n\t->Output: {output}"
            )
        elif verbose is True:
            logger.info(f"Ready executing {pprint.pformat(args)}")

        return output

    # If we get here, the retries didn't suffice to get it executed properly
    raise Exception(
        f"Error executing {pprint.pformat(args)}\n\t-> Return code: {returncode}"
    )


def _execute_sql(
    path: Path, sqlite_stmt: str, sql_dialect: Optional[str] = None
) -> gpd.GeoDataFrame:

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir) / "ogr_util_execute_sql_tmp_file.gpkg"
        vector_translate(
            input_path=path,
            output_path=tmp_path,
            sql_stmt=sqlite_stmt,
            sql_dialect=sql_dialect,
        )

        # Return result
        install_info_gdf = gfo.read_file(tmp_path)
        return install_info_gdf
