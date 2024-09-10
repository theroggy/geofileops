"""Module containing utilities regarding the usage of ogr/gdal functionalities."""

import logging
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path
from threading import Lock
from typing import Literal, Optional, Union

from osgeo import gdal, ogr
from pygeoops import GeometryType

import geofileops as gfo
from geofileops import fileops

# Make sure only one instance per process is running
lock = Lock()

# Get a logger...
logger = logging.getLogger(__name__)


class GDALError(Exception):
    """Error with extra gdal info."""

    def __init__(
        self,
        message: str,
        log_details: list[str] = [],
        error_details: list[str] = [],
    ):
        self.message = message
        self.log_details = log_details
        self.error_details = error_details
        super().__init__(self.message)

    def __str__(self):
        retstring = ""
        if len(self.error_details) > 0:
            retstring += "\n    GDAL CPL_LOG ERRORS"
            retstring += "\n    -------------------"
            retstring += "\n    "
            retstring += "\n    ".join(self.error_details)
        if len(self.log_details) > 0:
            retstring += "\n    GDAL CPL_LOG ALL"
            retstring += "\n    ----------------"
            retstring += "\n    "
            retstring += "\n    ".join(self.log_details)

        if len(retstring) > 0:
            return f"{retstring}\n{super().__str__()}"
        else:
            return super().__str__()


ogrtype_to_geometrytype = {
    ogr.wkbNone: None,
    ogr.wkbUnknown: GeometryType.GEOMETRY,
    ogr.wkbPoint: GeometryType.POINT,
    ogr.wkbLineString: GeometryType.LINESTRING,
    ogr.wkbPolygon: GeometryType.POLYGON,
    ogr.wkbTriangle: GeometryType.TRIANGLE,
    ogr.wkbMultiPoint: GeometryType.MULTIPOINT,
    ogr.wkbMultiLineString: GeometryType.MULTILINESTRING,
    ogr.wkbMultiPolygon: GeometryType.MULTIPOLYGON,
    ogr.wkbGeometryCollection: GeometryType.GEOMETRYCOLLECTION,
    ogr.wkbPolyhedralSurface: GeometryType.POLYHEDRALSURFACE,
    ogr.wkbTIN: GeometryType.TIN,
    ogr.wkbPoint25D: GeometryType.POINTZ,
    ogr.wkbLineString25D: GeometryType.LINESTRINGZ,
    ogr.wkbPolygon25D: GeometryType.POLYGONZ,
    ogr.wkbTriangleZ: GeometryType.TRIANGLEZ,
    ogr.wkbMultiPoint25D: GeometryType.MULTIPOINTZ,
    ogr.wkbMultiLineString25D: GeometryType.MULTILINESTRINGZ,
    ogr.wkbMultiPolygon25D: GeometryType.MULTIPOLYGONZ,
    ogr.wkbGeometryCollection25D: GeometryType.GEOMETRYCOLLECTIONZ,
    ogr.wkbPolyhedralSurfaceZ: GeometryType.POLYHEDRALSURFACEZ,
    ogr.wkbTINZ: GeometryType.TINZ,
    ogr.wkbPointM: GeometryType.POINTM,
    ogr.wkbLineStringM: GeometryType.LINESTRINGM,
    ogr.wkbPolygonM: GeometryType.POLYGONM,
    ogr.wkbTriangleM: GeometryType.TRIANGLEM,
    ogr.wkbMultiPointM: GeometryType.MULTIPOINTM,
    ogr.wkbMultiLineStringM: GeometryType.MULTILINESTRINGM,
    ogr.wkbMultiPolygonM: GeometryType.MULTIPOLYGONM,
    ogr.wkbGeometryCollectionM: GeometryType.GEOMETRYCOLLECTIONM,
    ogr.wkbPolyhedralSurfaceM: GeometryType.POLYHEDRALSURFACEM,
    ogr.wkbTINM: GeometryType.TINM,
    ogr.wkbPointZM: GeometryType.POINTZM,
    ogr.wkbLineStringZM: GeometryType.LINESTRINGZM,
    ogr.wkbPolygonZM: GeometryType.POLYGONZM,
    ogr.wkbTriangleZM: GeometryType.TRIANGLEZM,
    ogr.wkbMultiPointZM: GeometryType.MULTIPOINTZM,
    ogr.wkbMultiLineStringZM: GeometryType.MULTILINESTRINGZM,
    ogr.wkbMultiPolygonZM: GeometryType.MULTIPOLYGONZM,
    ogr.wkbGeometryCollectionZM: GeometryType.GEOMETRYCOLLECTIONZM,
    ogr.wkbPolyhedralSurfaceZM: GeometryType.POLYHEDRALSURFACEZM,
    ogr.wkbTINZM: GeometryType.TINZM,
}


def get_drivers() -> dict:
    drivers = {}
    for i in range(gdal.GetDriverCount()):
        driver = gdal.GetDriver(i)
        drivers[driver.ShortName] = driver.GetDescription()
    return drivers


def read_cpl_log(path: Path) -> tuple[list[str], list[str]]:
    """Reads a cpl_log file and returns a list with log lines and errors.

    Args:
        path (Path): the file path to the cpl_log file.

    Returns:
        Tuple[List[str], List[str]]: tuple with a list of all log lines and a list of
            errors.
    """
    if not path.exists() or path.stat().st_size == 0:
        return ([], [])

    with open(path) as logfile:
        log_lines = logfile.readlines()

    # Cleanup + check for errors
    lines_cleaned = []
    lines_error = []
    for line in log_lines:
        line = line.strip("\0\n ")
        if line != "":
            lines_cleaned.append(line)
            if line.startswith("ERROR"):
                lines_error.append(line)

    return (lines_cleaned, lines_error)


class VectorTranslateInfo:
    def __init__(
        self,
        input_path: Path,
        output_path: Path,
        input_layers: Union[list[str], str, None] = None,
        output_layer: Optional[str] = None,
        input_srs: Union[int, str, None] = None,
        output_srs: Union[int, str, None] = None,
        reproject: bool = False,
        spatial_filter: Optional[tuple[float, float, float, float]] = None,
        clip_geometry: Optional[Union[tuple[float, float, float, float], str]] = None,
        sql_stmt: Optional[str] = None,
        sql_dialect: Optional[Literal["SQLITE", "OGRSQL"]] = None,
        where: Optional[str] = None,
        transaction_size: int = 65536,
        append: bool = False,
        update: bool = False,
        explodecollections: bool = False,
        force_output_geometrytype: Union[GeometryType, str, None] = None,
        options: dict = {},
        columns: Optional[Iterable[str]] = None,
        warp: Optional[dict] = None,
        preserve_fid: Optional[bool] = None,
        dst_dimensions: Optional[str] = None,
    ):
        self.input_path = input_path
        self.output_path = output_path
        self.input_layers = input_layers
        self.output_layer = output_layer
        self.input_srs = input_srs
        self.output_srs = output_srs
        self.reproject = reproject
        self.spatial_filter = spatial_filter
        self.clip_geometry = clip_geometry
        self.sql_stmt = sql_stmt
        self.sql_dialect = sql_dialect
        self.where = where
        self.transaction_size = transaction_size
        self.append = append
        self.update = update
        self.explodecollections = explodecollections
        self.force_output_geometrytype = force_output_geometrytype
        self.options = options
        self.columns = columns
        self.warp = warp
        self.preserve_fid = preserve_fid
        self.dst_dimensions = dst_dimensions


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
        clip_geometry=info.clip_geometry,
        sql_stmt=info.sql_stmt,
        sql_dialect=info.sql_dialect,
        where=info.where,
        transaction_size=info.transaction_size,
        append=info.append,
        update=info.update,
        explodecollections=info.explodecollections,
        force_output_geometrytype=info.force_output_geometrytype,
        options=info.options,
        columns=info.columns,
        warp=info.warp,
        preserve_fid=info.preserve_fid,
        dst_dimensions=info.dst_dimensions,
    )


def vector_translate(
    input_path: Union[Path, str],
    output_path: Path,
    input_layers: Union[list[str], str, None] = None,
    output_layer: Optional[str] = None,
    input_srs: Union[int, str, None] = None,
    output_srs: Union[int, str, None] = None,
    reproject: bool = False,
    spatial_filter: Optional[tuple[float, float, float, float]] = None,
    clip_geometry: Optional[Union[tuple[float, float, float, float], str]] = None,
    sql_stmt: Optional[str] = None,
    sql_dialect: Optional[Literal["SQLITE", "OGRSQL"]] = None,
    where: Optional[str] = None,
    transaction_size: int = 65536,
    append: bool = False,
    update: bool = False,
    explodecollections: bool = False,
    force_output_geometrytype: Union[GeometryType, str, None] = None,
    options: dict = {},
    columns: Optional[Iterable[str]] = None,
    warp: Optional[dict] = None,
    preserve_fid: Optional[bool] = None,
    dst_dimensions: Optional[str] = None,
) -> bool:
    # API Doc of VectorTranslateOptions:
    #   https://gdal.org/api/python/osgeo.gdal.html#osgeo.gdal.VectorTranslateOptions
    args = []
    if isinstance(input_path, str):
        input_path = Path(input_path)
    if isinstance(columns, str):
        # If a string is passed, convert to list
        columns = [columns]

    gdal_options = _prepare_gdal_options(options, split_by_option_type=True)

    # Input file parameters
    input_info = fileops._geofileinfo.get_geofileinfo(input_path)
    # Cleanup the input_layers variable.
    if input_info.driver == "ESRI Shapefile":
        # For shapefiles, having input_layers not None gives issues
        input_layers = None
    elif sql_stmt is not None:
        # If a sql statement is passed, the input layers are not relevant,
        # and ogr2ogr will give a warning, so clear it.
        input_layers = None
    if input_layers is not None and isinstance(input_layers, str):
        input_layers = [input_layers]

    # SRS
    if input_srs is not None and isinstance(input_srs, int):
        input_srs = f"EPSG:{input_srs}"

    # Sql'ing, Filtering, clipping
    if sql_stmt is not None:
        # If sql_stmt starts with "\n" or "\t" for gpkg or with " " for a shp,
        # VectorTranslate outputs no or an invalid file if the statement doesn't return
        # any rows...
        sql_stmt = sql_stmt.lstrip("\n\t ")
    if clip_geometry is not None:
        args.extend(["-clipsrc"])
        if isinstance(clip_geometry, str):
            args.extend([clip_geometry])
        else:
            bounds = [str(coord) for coord in clip_geometry]
            args.extend(bounds)
    if columns is not None:
        args.extend(["-select", ",".join(columns)])
    if sql_stmt is not None and where is not None:
        raise ValueError("it is not supported to specify both sql_stmt and where")

    # Warp
    if warp is not None:
        gcps = warp.get("gcps", [])
        for gcp in gcps:
            args.extend(["-gcp"])
            args.extend([str(coord) for coord in gcp if coord is not None])
        algorithm = warp.get("algorithm", "polynomial")
        if algorithm == "polynomial":
            order = warp.get("order", None)
            if order is not None:
                args.extend(["-order", order])
        elif algorithm == "tps":
            args.extend(["-tps"])
        else:
            raise ValueError(f"unsupported warp algorithm: {algorithm}")

    # Input dataset open options
    for option_name, value in gdal_options["INPUT_OPEN"].items():
        args.extend(["-oo", f"{option_name}={value}"])

    # Output file parameters
    # Get driver for the output_path
    output_info = fileops._geofileinfo.get_geofileinfo(output_path)

    # Shapefiles only can have one layer, and the layer name == the stem of the file
    if output_info.driver == "ESRI Shapefile":
        output_layer = output_path.stem

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
        if output_info.driver == "SQLite":
            # If SQLite file, use the spatialite type of sqlite by default
            if "SPATIALITE" not in dataset_creation_options:
                dataset_creation_options["SPATIALITE"] = "YES"
        for option_name, value in dataset_creation_options.items():
            datasetCreationOptions.extend([f"{option_name}={value}"])

    # Output layer options
    if explodecollections is True:
        args.append("-explodecollections")
    output_geometrytypes = []
    if force_output_geometrytype is not None:
        if isinstance(force_output_geometrytype, GeometryType):
            output_geometrytypes.append(force_output_geometrytype.name)
        else:
            output_geometrytypes.append(force_output_geometrytype)
    else:
        if not explodecollections:
            output_geometrytypes.append("PROMOTE_TO_MULTI")
    if transaction_size is not None:
        args.extend(["-gt", str(transaction_size)])
    if preserve_fid is None:
        if explodecollections:
            # If explodecollections is specified, explicitly disable fid to avoid errors
            args.append("-unsetFid")
    else:
        if preserve_fid:
            args.append("-preserve_fid")
        else:
            args.append("-unsetFid")

    # Output layer creation options are only applicable if a new layer will be
    # created
    layerCreationOptions = []
    if output_path.exists() is False or (update is True and append is False):
        for option_name, value in gdal_options["LAYER_CREATION"].items():
            layerCreationOptions.extend([f"{option_name}={value}"])

    # General configuration options
    # Remark: passing them as parameter using --config doesn't work, but they are set as
    # runtime config options later on (using a context manager).
    config_options = dict(gdal_options["CONFIG"])
    if input_info.is_spatialite_based or output_info.is_spatialite_based:
        # If spatialite based file, increase SQLITE cache size by default
        if "OGR_SQLITE_CACHE" not in config_options:
            config_options["OGR_SQLITE_CACHE"] = "128"

    # Have gdal throw exception on error
    gdal.UseExceptions()

    # In some cases gdal only raises the last exception instead of the stack in
    # VectorTranslate, so you then you would lose necessary details!
    # Solution: have gdal log everything to a file using the CPL_LOG config setting,
    # and if an error occurs, add the contents of the log file to the exception.
    # I also tried using gdal.ConfigurePythonLogging, but with enable_debug=True all
    # gdal debug logging is always logged, which is quite verbose and messy, and
    # with enable_debug=True nothing is logged. In addition, after
    # gdal.ConfigurePythonLogging is called, the CPL_LOG config setting is ignored.
    if "CPL_LOG" not in config_options:
        gdal_cpl_log_dir = Path(tempfile.gettempdir()) / "geofileops/gdal_cpl_log"
        gdal_cpl_log_dir.mkdir(parents=True, exist_ok=True)
        fd, gdal_cpl_log = tempfile.mkstemp(suffix=".log", dir=gdal_cpl_log_dir)
        os.close(fd)
        config_options["CPL_LOG"] = gdal_cpl_log
        gdal_cpl_log_path = Path(gdal_cpl_log)
    else:
        gdal_cpl_log_path = Path(config_options["CPL_LOG"])
    if "CPL_LOG_ERRORS" not in config_options:
        config_options["CPL_LOG_ERRORS"] = "ON"
    if "CPL_DEBUG" not in config_options:
        config_options["CPL_DEBUG"] = "ON"

    # Now we can really get to work
    output_ds = None
    try:
        # Go!
        with set_config_options(config_options):
            # Open input datasource already
            input_ds = gdal.OpenEx(
                str(input_path),
                nOpenFlags=gdal.OF_VECTOR | gdal.OF_READONLY | gdal.OF_SHARED,
            )

            # If output_srs is not specified and the result has 0 rows, gdal creates the
            # output file without srs.
            # documented in https://github.com/geofileops/geofileops/issues/313
            if output_srs is None:
                set_output_srs = True
                datasource_layer = None
                if input_layers is not None and len(input_layers) == 1:
                    datasource_layer = input_ds.GetLayer(input_layers[0])
                else:
                    nb_layers = input_ds.GetLayerCount()
                    if nb_layers == 1:
                        datasource_layer = input_ds.GetLayerByIndex(0)
                    elif nb_layers == 0:
                        # We never actually get here, because opening a file without
                        # layers already gives an error.
                        raise ValueError(f"no layers found in {input_path}")
                    else:
                        # If multiple layers and not explicitly specified, it is in the
                        # sql statement so difficult to determine... so pass
                        set_output_srs = False

                if set_output_srs:
                    # If the layer doesn't exist, return
                    if datasource_layer is None:
                        raise RuntimeError(
                            f"input_layers {input_layers} not found in: {input_path}"
                        )
                    spatialref = datasource_layer.GetSpatialRef()
                    if spatialref is not None:
                        output_srs = spatialref.ExportToWkt()

            # If the output is a shapefile and the input geometries are NULL, gdal
            # creates an attribute column "geometry" in the output file. To be able to
            # detect this case later on, check here if the input file already has an
            # attribute column "geometry".
            input_has_geom_attribute = False
            input_has_geometry_attribute = False
            input_layer = input_ds.GetLayer()
            layer_defn = input_layer.GetLayerDefn()
            for field_idx in range(layer_defn.GetFieldCount()):
                field_name_lower = layer_defn.GetFieldDefn(field_idx).GetName().lower()
                if field_name_lower == "geom":
                    input_has_geom_attribute = True
                elif field_name_lower == "geometry":
                    input_has_geometry_attribute = True

            # Consolidate all parameters
            # First take copy of args, because gdal.VectorTranslateOptions adds all
            # other parameters to the list passed (by ref)!!!
            args_copy = list(args)
            options = gdal.VectorTranslateOptions(
                options=args_copy,
                format=output_info.driver,
                accessMode=None,
                srcSRS=input_srs,
                dstSRS=output_srs,
                reproject=reproject,
                SQLStatement=sql_stmt,
                SQLDialect=sql_dialect,
                where=where,
                selectFields=None,
                addFields=False,
                forceNullable=False,
                spatFilter=spatial_filter,
                spatSRS=None,
                datasetCreationOptions=datasetCreationOptions,
                layerCreationOptions=layerCreationOptions,
                layers=input_layers,
                layerName=output_layer,
                geometryType=output_geometrytypes,
                dim=dst_dimensions,
                segmentizeMaxDist=None,
                zField=None,
                skipFailures=False,
                limit=None,
                callback=None,
                callback_data=None,
            )

            output_ds = gdal.VectorTranslate(
                destNameOrDestDS=str(output_path), srcDS=input_ds, options=options
            )

        # If the resulting datasource is None, something went wrong
        if output_ds is None:
            raise RuntimeError("output_ds is None")

        # Sometimes an invalid output file is written, so close and try to reopen it.
        output_ds = None
        if output_path.exists():
            try:
                output_ds = gdal.OpenEx(
                    str(output_path), nOpenFlags=gdal.OF_VECTOR | gdal.OF_UPDATE
                )

                # If the (first) output row contains NULL as geom/geometry, gdal will
                # add an attribute column with the name of the (alias of) the geometry
                # column: so "geometry" or "geom".
                # To fix this, delete the "geom" or "geometry" attribute column if
                # present if the input file didn't have an attribute column with this
                # name.
                # Bug documented in https://github.com/geofileops/geofileops/issues/313
                #
                # Remark: this check must be done on the reopened output file because
                # in some cases the "geometrycolumn" is incorrectly listed in the field
                # list of the Dataset returned by VectorTranslate. E.g. when the input
                # file is empty.
                if not input_has_geometry_attribute or not input_has_geom_attribute:
                    assert isinstance(output_ds, gdal.Dataset)
                    if output_layer is not None:
                        result_layer = output_ds.GetLayer(output_layer)
                    elif output_ds.GetLayerCount() == 1:
                        result_layer = output_ds.GetLayerByIndex(0)
                    else:
                        result_layer = None
                        logger.warning(
                            "Unable to determine output layer, so not able to remove "
                            "possibly incorrect geom and geometry text columns, with "
                            f"input_path: {input_path}, output_path: {output_path}"
                        )

                    # Output layer was found, so check it
                    if result_layer is not None:
                        layer_defn = result_layer.GetLayerDefn()
                        for field_idx in range(layer_defn.GetFieldCount()):
                            name = layer_defn.GetFieldDefn(field_idx).GetName().lower()
                            if (name == "geom" and not input_has_geom_attribute) or (
                                name == "geometry" and not input_has_geometry_attribute
                            ):
                                result_layer.DeleteField(field_idx)
                                break

            except Exception as ex:
                logger.info(
                    f"Opening output file gave error, probably the input file was "
                    f"empty, no rows were selected or geom was NULL: {ex}"
                )
                gfo.remove(output_path)
            finally:
                output_ds = None

    except Exception as ex:
        output_ds = None

        # Prepare exception message
        message = f"Error {ex} while creating/updating {output_path}"
        if sql_stmt is not None:
            message = f"{message} using sql_stmt {sql_stmt}"

        # Read cpl_log file
        log_lines, log_errors = read_cpl_log(gdal_cpl_log_path)

        # Raise
        raise GDALError(
            message, log_details=log_lines, error_details=log_errors
        ).with_traceback(ex.__traceback__)

    finally:
        output_ds = None
        input_ds = None

        if gdal_cpl_log_path.exists():
            # Truncate the cpl log file already, because sometimes it is locked and
            # cannot be unlinked.
            with open(gdal_cpl_log_path, "r+") as logfile:
                logfile.truncate(0)  # size '0' necessary when using r+
            try:
                gdal_cpl_log_path.unlink(missing_ok=True)
            except Exception:
                pass

    return True


def _prepare_gdal_options(options: dict, split_by_option_type: bool = False) -> dict:
    """Prepares the options so they are ready to pass on to gdal.

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
    prepared_options: dict[str, dict] = {
        option_type: {} for option_type in option_types
    }

    # Loop through options specified to add them
    for option, value in options.items():
        # Prepare option type and name
        option_type, option_name = option.split(".")
        option_type = option_type.strip().upper()
        option_name = option_name.strip().upper()
        if option_type not in option_types:
            raise ValueError(
                f"Unsupported option type: {option_type}, not one of {option_types}"
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


class set_config_options:
    """Context manager to set config options.

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
            if value is None:
                pass
            elif isinstance(value, bool):
                value = "YES" if value is True else "NO"
            else:
                value = str(value)
            gdal.SetConfigOption(str(name), value)

    def __exit__(self, type, value, traceback):
        # Remove config options that were set
        # TODO: delete loop + uncomment if SetConfigOptions() is supported
        for name, _ in self.config_options.items():
            gdal.SetConfigOption(name, None)
        # gdal.SetConfigOptions(self.config_options_backup)
