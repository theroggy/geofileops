"""Module containing utilities regarding the usage of ogr/gdal functionalities."""

import logging
import os
import tempfile
import warnings
from collections.abc import Iterable
from pathlib import Path
from threading import Lock
from typing import Any, Literal, Union

from osgeo import gdal, ogr
from pygeoops import GeometryType

import geofileops as gfo
from geofileops import _compat, fileops
from geofileops.util import _geopath_util, _io_util
from geofileops.util._general_util import MissingRuntimeDependencyError

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


def spatialite_version_info() -> dict[str, str]:
    """Returns the versions of the spatialite module used in gdal.

    Versions returned: spatialite_version, geos_version.

    Raises:
        RuntimeError: if a runtime dependency is not available.

    Returns:
        Dict[str, str]: a dict with the version of the runtime dependencies.
    """
    datasource = None
    try:
        test_path = Path(__file__).resolve().parent / "test.gpkg"
        datasource = gdal.OpenEx(str(test_path))
        result = datasource.ExecuteSQL("SELECT spatialite_version(), geos_version()")
        row = result.GetNextFeature()
        spatialite_version = row.GetField(0)
        geos_version = row.GetField(1)
        datasource.ReleaseResultSet(result)

    except Exception as ex:  # pragma: no cover
        message = f"error getting spatialite_version: {ex}"
        raise MissingRuntimeDependencyError(message) from ex

    finally:
        datasource = None

    if not spatialite_version:  # pragma: no cover
        warnings.warn(
            "empty gdal spatialite version: probably a geofileops dependency was "
            "not installed correctly: check the installation instructions in the "
            "geofileops docs.",
            stacklevel=1,
        )
    if not geos_version:  # pragma: no cover
        warnings.warn(
            "empty gdal spatialite GEOS version: probably a geofileops dependency was "
            "not installed correctly: check the installation instructions in the "
            "geofileops docs.",
            stacklevel=1,
        )

    versions = {
        "spatialite_version": spatialite_version,
        "geos_version": geos_version,
    }
    return versions


def ogrtype_to_name(ogrtype: int | None) -> str:
    if ogrtype is None:
        return "NONE"
    else:
        geometrytypename = ogr.GeometryTypeToName(ogrtype).replace(" ", "").upper()

    if geometrytypename == "NONE":
        return geometrytypename

    if geometrytypename == "UNKNOWN(ANY)":
        return "GEOMETRY"

    if geometrytypename.startswith("3D"):
        geometrytypename = geometrytypename[2:]
        geometrytypename = f"{geometrytypename}Z"

    if geometrytypename.startswith("MEASURED"):
        geometrytypename = geometrytypename[8:]
        geometrytypename = f"{geometrytypename}M"

    return geometrytypename


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

    with path.open() as logfile:
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


def StartTransaction(datasource: gdal.Dataset) -> bool:
    """Starts a transaction on an open datasource.

    Args:
        datasource (gdal.Dataset): the datasource to start the transaction on.

    Raises:
        ValueError: if datasource is None.

    Returns:
        bool: True if the transaction was started successfully.
    """
    if datasource is None:
        raise ValueError("datasource is None")

    if datasource.TestCapability(ogr.ODsCTransactions):
        datasource.StartTransaction()

    return True


def CommitTransaction(datasource: gdal.Dataset | None) -> bool:
    """Commits a transaction on an open datasource.

    Args:
        datasource (gdal.Dataset): the datasource to commit the transaction on. If None,
            no commit is executed.

    Returns:
        bool: True if the transaction was committed successfully.
    """
    if datasource is None:
        return False

    if datasource.TestCapability(ogr.ODsCTransactions):
        datasource.CommitTransaction()

    return True


def RollbackTransaction(datasource: gdal.Dataset | None) -> bool:
    """Rolls back a transaction on an open datasource.

    Args:
        datasource (gdal.Dataset): the datasource to roll back the transaction on. If
            None, no rollback is executed.

    Returns:
        bool: True if the transaction was rolled back successfully.
    """
    if datasource is None:
        return False

    if datasource.TestCapability(ogr.ODsCTransactions):
        datasource.RollbackTransaction()

    return True


class VectorTranslateInfo:
    def __init__(
        self,
        input_path: Union[str, "os.PathLike[Any]"],
        output_path: Union[str, "os.PathLike[Any]"],
        input_layers: list[str] | str | None = None,
        output_layer: str | None = None,
        access_mode: str | None = None,
        input_srs: int | str | None = None,
        output_srs: int | str | None = None,
        reproject: bool = False,
        spatial_filter: tuple[float, float, float, float] | None = None,
        clip_geometry: tuple[float, float, float, float] | str | None = None,
        sql_stmt: str | None = None,
        sql_dialect: Literal["SQLITE", "OGRSQL"] | None = None,
        where: str | None = None,
        transaction_size: int = 65536,
        explodecollections: bool = False,
        force_output_geometrytype: GeometryType | str | Iterable[str] | None = None,
        options: dict = {},
        columns: Iterable[str] | None = None,
        warp: dict | None = None,
        preserve_fid: bool | None = None,
        dst_dimensions: str | None = None,
        add_fields: bool = False,
    ):
        self.input_path = input_path
        self.output_path = output_path
        self.input_layers = input_layers
        self.output_layer = output_layer
        self.access_mode = access_mode
        self.input_srs = input_srs
        self.output_srs = output_srs
        self.reproject = reproject
        self.spatial_filter = spatial_filter
        self.clip_geometry = clip_geometry
        self.sql_stmt = sql_stmt
        self.sql_dialect = sql_dialect
        self.where = where
        self.transaction_size = transaction_size
        self.explodecollections = explodecollections
        self.force_output_geometrytype = force_output_geometrytype
        self.options = options
        self.columns = columns
        self.warp = warp
        self.preserve_fid = preserve_fid
        self.dst_dimensions = dst_dimensions
        self.add_fields = add_fields


def vector_translate_by_info(info: VectorTranslateInfo):
    return vector_translate(
        input_path=info.input_path,
        output_path=info.output_path,
        input_layers=info.input_layers,
        output_layer=info.output_layer,
        access_mode=info.access_mode,
        input_srs=info.input_srs,
        output_srs=info.output_srs,
        reproject=info.reproject,
        spatial_filter=info.spatial_filter,
        clip_geometry=info.clip_geometry,
        sql_stmt=info.sql_stmt,
        sql_dialect=info.sql_dialect,
        where=info.where,
        transaction_size=info.transaction_size,
        explodecollections=info.explodecollections,
        force_output_geometrytype=info.force_output_geometrytype,
        options=info.options,
        columns=info.columns,
        warp=info.warp,
        preserve_fid=info.preserve_fid,
        dst_dimensions=info.dst_dimensions,
        add_fields=info.add_fields,
    )


def vector_translate(
    input_path: Union[str, "os.PathLike[Any]"],
    output_path: Union[str, "os.PathLike[Any]"],
    input_layers: list[str] | str | None = None,
    output_layer: str | None = None,
    access_mode: str | None = None,
    input_srs: int | str | None = None,
    output_srs: int | str | None = None,
    reproject: bool = False,
    spatial_filter: tuple[float, float, float, float] | None = None,
    clip_geometry: tuple[float, float, float, float] | str | None = None,
    sql_stmt: str | None = None,
    sql_dialect: Literal["SQLITE", "OGRSQL"] | None = None,
    where: str | None = None,
    transaction_size: int = 65536,
    explodecollections: bool = False,
    force_output_geometrytype: GeometryType | str | Iterable[str] | None = None,
    options: dict = {},
    columns: Iterable[str] | None = None,
    warp: dict | None = None,
    preserve_fid: bool | None = None,
    dst_dimensions: str | None = None,
    add_fields: bool = False,
) -> bool:
    # API Doc of VectorTranslateOptions:
    #   https://gdal.org/en/stable/api/python/utilities.html#osgeo.gdal.VectorTranslateOptions
    args = []
    if isinstance(input_path, Path):
        input_path = input_path.as_posix()
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
    if isinstance(input_layers, str):
        input_layers = [input_layers]
    elif isinstance(input_layers, list) and len(input_layers) == 0:
        input_layers = None

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
    input_open_options = []
    for option_name, value in gdal_options["INPUT_OPEN"].items():
        input_open_options.append(f"{option_name}={value!s}")

    # Output file parameters
    # Get driver for the output_path
    output_info = fileops._geofileinfo.get_geofileinfo(output_path)

    # Shapefiles only can have one layer, and the layer name == the stem of the file
    if output_info.driver == "ESRI Shapefile":
        output_layer = _geopath_util.stem(output_path)

    # SRS
    if output_srs is not None and isinstance(output_srs, int):
        output_srs = f"EPSG:{output_srs}"

    # Output basic options
    datasetCreationOptions = []
    if access_mode is None:
        dataset_creation_options = gdal_options["DATASET_CREATION"]
        if output_info.driver == "SQLite":
            # If SQLite file, use the spatialite type of sqlite by default
            if "SPATIALITE" not in dataset_creation_options:
                dataset_creation_options["SPATIALITE"] = "YES"
        for option_name, value in dataset_creation_options.items():
            datasetCreationOptions.extend([f"{option_name}={value}"])

    # Output layer options
    if explodecollections:
        args.append("-explodecollections")
    output_geometrytypes = []
    if force_output_geometrytype is not None:
        if isinstance(force_output_geometrytype, GeometryType):
            output_geometrytypes.append(force_output_geometrytype.name)
        elif isinstance(force_output_geometrytype, str):
            output_geometrytypes.append(force_output_geometrytype)
        elif isinstance(force_output_geometrytype, Iterable):
            for geotype in force_output_geometrytype:
                if isinstance(geotype, GeometryType):
                    output_geometrytypes.append(geotype.name)
                elif isinstance(geotype, str):
                    output_geometrytypes.append(geotype)
                else:
                    raise ValueError(f"invalid type in {force_output_geometrytype=}")
        else:
            raise ValueError(f"invalid type for {force_output_geometrytype=}")
    elif (
        not explodecollections
        and input_info.driver == "ESRI Shapefile"
        and output_info.driver != "ESRI Shapefile"
    ):
        # Shapefiles are always reported as singlepart type but can also contain
        # multiparts geometries, so promote to multi
        output_geometrytypes.append("PROMOTE_TO_MULTI")

    if transaction_size is not None:
        args.extend(["-gt", str(transaction_size)])
    if preserve_fid is None:
        if explodecollections:
            # If explodecollections is specified, explicitly disable fid to avoid errors
            args.append("-unsetFid")
    elif preserve_fid:
        args.append("-preserve_fid")
    else:
        args.append("-unsetFid")

    # Prepare output layer creation options
    layerCreationOptions = []
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
        gdal_cpl_log_dir = _io_util.get_tempdir() / "geofileops/gdal_cpl_log"
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
    input_has_geom_attribute = False
    input_has_geometry_attribute = False
    try:
        # Till gdal 3.10 datetime columns can be interpreted wrongly with arrow.
        # Additionally, enabling arrow seems to lead to (rare) random crashes, so
        # for now, disable it by default.
        use_arrow_key = "OGR2OGR_USE_ARROW_API"
        if use_arrow_key not in config_options and use_arrow_key not in os.environ:
            config_options[use_arrow_key] = False

        # Go!
        with set_config_options(config_options):
            # Open input datasource already
            try:
                input_ds = gdal.OpenEx(
                    str(input_path),
                    nOpenFlags=gdal.OF_VECTOR | gdal.OF_READONLY | gdal.OF_SHARED,
                    open_options=input_open_options,
                )
            except Exception as ex:
                if "no such file or directory" in str(ex).lower():
                    raise FileNotFoundError(f"File not found: {input_path}") from ex

                raise

            # if sql_stmt is None, input_layers must be specified if the input file has
            # multiple layers.
            if sql_stmt is None and input_layers is None:
                nb_layers = input_ds.GetLayerCount()
                if nb_layers == 1:
                    input_layers = [input_ds.GetLayer(0).GetName()]
                elif nb_layers > 1:
                    raise ValueError(
                        f"input has > 1 layers: a layer must be specified: {input_path}"
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
            if input_layers is None or len(input_layers) == 1:
                if input_layers is None:
                    datasource_layer = input_ds.GetLayer()
                else:
                    datasource_layer = input_ds.GetLayerByName(input_layers[0])
                layer_defn = datasource_layer.GetLayerDefn()
                for field in range(layer_defn.GetFieldCount()):
                    field_name_lower = layer_defn.GetFieldDefn(field).GetName().lower()
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
                accessMode=access_mode,
                srcSRS=input_srs,
                dstSRS=output_srs,
                reproject=reproject,
                SQLStatement=sql_stmt,
                SQLDialect=sql_dialect,
                where=where,
                selectFields=None,
                addFields=add_fields,
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

    except FileNotFoundError:
        raise
    except ValueError:
        raise
    except Exception as ex:
        output_ds = None

        # Prepare exception message
        message = f"Error {ex} while creating/updating {output_path}"
        if sql_stmt is not None:
            message = f"{message} using sql_stmt {sql_stmt}"

        # Read cpl_log file
        log_lines, log_errors = read_cpl_log(gdal_cpl_log_path)

        raise GDALError(
            message, log_details=log_lines, error_details=log_errors
        ).with_traceback(ex.__traceback__) from None

    finally:
        output_ds = None
        input_ds = None

        # Fix/remove invalid files that were written.
        output_ds = None
        _validate_file(
            output_path,
            output_layer,
            input_has_geometry_attribute,
            input_has_geom_attribute,
        )

        if gdal_cpl_log_path.exists():
            # Truncate the cpl log file already, because sometimes it is locked and
            # cannot be unlinked.
            with gdal_cpl_log_path.open("r+") as logfile:
                logfile.truncate(0)  # size '0' necessary when using r+
            try:
                gdal_cpl_log_path.unlink(missing_ok=True)
            except Exception:
                pass

    return True


def _validate_file(
    path: Union[str, "os.PathLike[Any]"],
    layer: str | None,
    input_has_geometry_attribute: bool,
    input_has_geom_attribute: bool,
):
    """Validate and fix a GPKG file.

    Two things are checked and fixed if needed:
      - the featurecount of the layer in gpkg_ogr_contents should not be NULL.
      - when the first row of the input layer has an NULL geometry, a redundant column
        is sometimes present.

    Args:
        path (PathLike): the file to check.
        layer (Optional[str]): the output layer name.
        input_has_geometry_attribute (bool): True if the input file has a geometry
            attribute column.
        input_has_geom_attribute (bool): True if the input file has a geom attribute
            column.
    """
    if not fileops._vsi_exists(path):
        return

    try:
        try:
            # First try to open file in update mode. If OK, we can fix if needed.
            output_ds = gdal.OpenEx(
                str(path), nOpenFlags=gdal.OF_VECTOR | gdal.OF_UPDATE
            )
            fix = True
        except Exception:
            # Opening in update mode failed, so try to open in read-only mode.
            output_ds = gdal.OpenEx(
                str(path), nOpenFlags=gdal.OF_VECTOR | gdal.OF_READONLY
            )
            fix = False

        assert isinstance(output_ds, gdal.Dataset)

        # Get the output layer
        if layer is not None:
            result_layer = output_ds.GetLayer(layer)
        elif output_ds.GetLayerCount() == 1:
            result_layer = output_ds.GetLayerByIndex(0)
        elif output_ds.GetLayerCount() == 0:
            # At least a GPKG file with no layers gives issues when opened read-only.
            # So remove it.
            # This was raised as an issue in https://github.com/OSGeo/gdal/issues/12284
            # but apparently there are reasons to keep this behaviour.
            logger.warning(
                "Output file has layercount=0, so remove it as opening it read/only"
                "will lead to an error. Probably the input file was empty, "
                "no rows were selected, geom was NULL or the SQL was invalid."
            )

            output_ds = None
            gfo.remove(path)
            return False

        else:
            result_layer = None

        # In some cases output files ended up with NULL featurecount in GDAL < 3.10.1.
        # This was fixed in https://github.com/OSGeo/gdal/pull/11275, but getting the
        # featurecount of the layer will fix this.
        if result_layer is not None and not _compat.GDAL_GTE_3101:
            result_layer.GetFeatureCount()

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
            # Output layer was found, so check it
            if result_layer is not None:
                layer_defn = result_layer.GetLayerDefn()
                for field_idx in range(layer_defn.GetFieldCount()):
                    name = layer_defn.GetFieldDefn(field_idx).GetName().lower()
                    if (name == "geom" and not input_has_geom_attribute) or (
                        name == "geometry" and not input_has_geometry_attribute
                    ):
                        if fix:
                            result_layer.DeleteField(field_idx)
                        else:
                            return False

                        break

            else:
                logger.warning(
                    "Unable to determine output layer, so not able to remove "
                    "possibly incorrect geom and geometry text columns, with "
                    f"{path=}"
                )

    except Exception as ex:  # pragma: no cover
        # In gdal 3.10, invalid gpkg files are still written when an invalid sql
        # is used if a new file is created or an existing one is overwritten.
        logger.warning(
            "Opening output file gave error, so remove it. Probably the input file was "
            f"empty, no rows were selected, geom was NULL or the SQL was invalid: {ex}"
        )
        gfo.remove(path)

    finally:
        output_ds = None


def _prepare_gdal_options(options: dict, split_by_option_type: bool = False) -> dict:
    """Prepares the options so they are ready to pass on to gdal.

        - Uppercase the option key
        - Check if the option types are one of the supported ones:

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
        for option_type_key, option_type_value in prepared_options.items():
            for option_name, value in option_type_value.items():
                result[f"{option_type_key}.{option_name}"] = value

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
