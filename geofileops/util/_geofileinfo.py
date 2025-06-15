"""Module with information about geofile types."""

import ast
import csv
import enum
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Union

from osgeo import gdal
from osgeo_utils.auxiliary.util import GetOutputDriversFor

if TYPE_CHECKING:  # pragma: no cover
    import os

# Enable exceptions for GDAL
gdal.UseExceptions()
gdal.ogr.UseExceptions()


@dataclass
class GeofileTypeInfo:
    """Class with properties of a GeofileType."""

    geofiletype: str
    ogrdriver: str
    suffixes: list[str]
    is_fid_zerobased: bool
    is_spatialite_based: bool
    default_spatial_index: bool
    suffixes_extrafiles: list[str]


geofiletypes: dict[str, GeofileTypeInfo] = {}


def _init_geofiletypes():
    geofiletypes_path = Path(__file__).resolve().parent / "geofiletypes.csv"
    with geofiletypes_path.open() as file:
        # Set skipinitialspace to True so the csv can be formatted for readability
        csv.register_dialect("geofiletype_dialect", skipinitialspace=True, strict=True)
        reader = csv.DictReader(file, dialect="geofiletype_dialect")

        for row in reader:
            # Determine suffixes
            if row["suffixes"] is not None and row["suffixes"] != "":
                suffixes = ast.literal_eval(row["suffixes"])
            else:
                suffixes = []

            # Determine suffixes_extrafiles
            if (
                row["suffixes_extrafiles"] is not None
                and row["suffixes_extrafiles"] != ""
            ):
                suffixes_extrafiles = ast.literal_eval(row["suffixes_extrafiles"])
            else:
                suffixes_extrafiles = []

            # Add geofiletype
            geofiletypes[row["geofiletype"]] = GeofileTypeInfo(
                geofiletype=row["geofiletype"],
                ogrdriver=row["ogrdriver"],
                suffixes=suffixes,
                is_fid_zerobased=ast.literal_eval(row["is_fid_zerobased"]),
                is_spatialite_based=ast.literal_eval(row["is_spatialite_based"]),
                default_spatial_index=ast.literal_eval(row["default_spatial_index"]),
                suffixes_extrafiles=suffixes_extrafiles,
            )


class GeofileType(enum.Enum):
    """DEPRECATED Enumeration of relevant geo file types and their properties."""

    ESRIShapefile = enum.auto()
    GeoJSON = enum.auto()
    GPKG = enum.auto()
    SQLite = enum.auto()
    FlatGeobuf = enum.auto()

    @classmethod
    def _missing_(cls, value):
        """Expand options in the GeofileType() constructor.

        Args:
            value (Union[str, int, Driver, Path]):
                * case insensitive lookup based on suffix
                * case insensitive lookup based on path
                * case insensitive lookup based on driver name
                * GeofileType: create the same GeometryType as the one passed in

        Returns:
            [GeofileType]: The corresponding GeometryType.
        """

        def get_geofiletype_for_suffix(suffix: str):
            suffix_lower = suffix.lower()
            for geofiletype, geofiletype_info in geofiletypes.items():
                if suffix_lower in geofiletype_info.suffixes:
                    return GeofileType[geofiletype]
            raise ValueError(f"Unknown extension {suffix}")

        def get_geofiletype_for_ogrdriver(ogrdriver: str):
            for geofiletype, geofiletype_info in geofiletypes.items():
                driver = geofiletype_info.ogrdriver
                if driver is not None and driver == ogrdriver:
                    return GeofileType[geofiletype]
            raise ValueError(f"Unknown ogr driver {ogrdriver}")

        if value is None:
            return None
        elif isinstance(value, Path):
            # If it is a Path, return Driver based on the suffix
            return get_geofiletype_for_suffix(value.suffix)
        elif isinstance(value, str):
            if value.startswith("."):
                # If it start with a point, it is a suffix
                return get_geofiletype_for_suffix(value)
            else:
                # it's probably an ogr driver
                return get_geofiletype_for_ogrdriver(value)
        elif isinstance(value, GeofileType):
            # If a GeofileType is passed in, return same GeofileType.
            # TODO: why create a new one?
            return cls(value.value)
        # Default behaviour (= lookup based on int value)
        return super()._missing_(value)

    @property
    def is_fid_zerobased(self) -> bool:
        """Returns True if the fid is zero based for this GeofileType."""
        return geofiletypes[self.name].is_fid_zerobased

    @property
    def is_spatialite_based(self) -> bool:
        """Returns True if this GeofileType is based on spatialite."""
        return geofiletypes[self.name].is_spatialite_based

    @property
    def ogrdriver(self) -> str:
        """Returns the ogr driver for this GeofileType."""
        return geofiletypes[self.name].ogrdriver

    @property
    def suffixes_extrafiles(self) -> list[str]:
        """Returns a list of suffixes for the extra files for this GeofileType."""
        return geofiletypes[self.name].suffixes_extrafiles

    @property
    def is_singlelayer(self) -> bool:
        """Returns True if a file of this GeofileType can only have one layer."""
        if self.is_spatialite_based:
            return False
        else:
            return True


# Init!
_init_geofiletypes()


class GeofileInfo:
    """A data object containing meta-information about a geofile.

    Attributes:
        driver (str): the relevant gdal driver for the file.
    """

    def __init__(self, path: Union[str, "os.PathLike[Any]"]):
        """Constructor of Layerinfo.

        Args:
            path (Path): the path to the file.
        """
        self.path = path
        self.driver = get_driver(path=path)
        self.geofiletype_info = geofiletypes.get(self.driver.replace(" ", ""))

    def __repr__(self):
        """Overrides the representation property of GeofileInfo."""
        return f"{self.__class__}({self.__dict__})"

    @property
    def is_fid_zerobased(self) -> bool:
        """Returns True if the fid is zero based."""
        if self.geofiletype_info is not None:
            return self.geofiletype_info.is_fid_zerobased
        else:
            # Default, not zero-based (at least the case for CSV)
            return False

    @property
    def is_spatialite_based(self) -> bool:
        """Returns True if file driver is based on spatialite."""
        if self.geofiletype_info is not None:
            return self.geofiletype_info.is_spatialite_based
        else:
            return False

    @property
    def is_singlelayer(self) -> bool:
        """Returns True if this geofile can only have one layer."""
        if (
            self.geofiletype_info is not None
            and self.geofiletype_info.is_spatialite_based
        ):
            return False
        else:
            return True

    @property
    def default_spatial_index(self) -> bool:
        """Returns True if this geofile can only have one layer."""
        if self.geofiletype_info is not None:
            return self.geofiletype_info.default_spatial_index
        else:
            return False

    @property
    def suffixes_extrafiles(self) -> list[str]:
        """Returns a list of suffixes for the extra files for this GeofileType."""
        if self.geofiletype_info is not None:
            return self.geofiletype_info.suffixes_extrafiles
        else:
            return []


def get_driver(path: Union[str, "os.PathLike[Any]"]) -> str:
    """Get the gdal driver name for the file specified.

    Args:
        path (PathLike): The file path. |GDAL_vsi| paths are also supported.

    Returns:
        str: The OGR driver name.

    .. |GDAL_vsi| raw:: html

        <a href="https://gdal.org/en/stable/user/virtual_file_systems.html" target="_blank">GDAL vsi</a>

    """  # noqa: E501
    # gdal.OpenEx is relatively slow on windows, so for straightforward cases, avoid it.
    suffix = Path(path).suffix.lower()
    if suffix == ".gpkg":
        return "GPKG"
    elif suffix == ".shp":
        return "ESRI Shapefile"

    def get_driver_for_path(input_path: Union[str, "os.PathLike[Any]"]) -> str:
        # If there is no suffix, possibly it is only a suffix, so prefix with filename
        local_path = input_path
        if Path(input_path).suffix == "":
            local_path = f"temp{input_path}"

        drivers = GetOutputDriversFor(local_path, is_raster=False)
        if len(drivers) == 1:
            return drivers[0]
        else:
            raise ValueError(
                "Could not infer driver from path. Please specify driver explicitly by "
                "prefixing the file path with '<DRIVER>:', e.g. 'GPKG:path'. "
                f"Path: {input_path}"
            )

    # Try to determine the driver by opening the file.
    try:
        datasource = gdal.OpenEx(
            str(path), nOpenFlags=gdal.OF_VECTOR | gdal.OF_READONLY | gdal.OF_SHARED
        )
        driver = datasource.GetDriver()
        drivername = driver.ShortName
    except Exception as ex:
        ex_str = str(ex).lower()
        if (
            "no such file or directory" in ex_str
            or "not recognized as being in a supported file format" in ex_str
            or "not recognized as a supported file format" in ex_str
        ):
            # If the file does not exist or if, for some cases like a csv file,
            # it is e.g. an empty file that was not recognized yet, try to get the
            # driver based on only the path.
            try:
                drivername = get_driver_for_path(path)
            except Exception:
                ex.args = (f"get_driver error for {path}: {ex}",)
                raise
        else:
            ex.args = (f"get_driver error for {path}: {ex}",)
            raise
    finally:
        datasource = None

    return drivername


def get_geofileinfo(path: Union[str, "os.PathLike[Any]"]) -> GeofileInfo:
    """Get information about a geofile.

    Not a public function, as the properties are for internal use and might change in
    the future.

    Args:
        path (Union[str, PathLike): the path to the file.

    Returns:
        GeofileInfo: _description_
    """
    return GeofileInfo(path=path)
