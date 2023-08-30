"""
Module with information about the supported geofiletypes.
"""

import ast
import csv
from dataclasses import dataclass
import enum
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class GeofileTypeInfo:
    """
    Class with properties of a GeofileType.
    """

    geofiletype: str
    ogrdriver: str
    suffixes: Optional[List[str]]
    is_fid_zerobased: bool
    is_spatialite_based: bool
    suffixes_extrafiles: Optional[List[str]]


geofiletypes: Dict[str, GeofileTypeInfo] = {}


def _init_geofiletypes():
    geofiletypes_path = Path(__file__).resolve().parent / "geofiletypes.csv"
    with open(geofiletypes_path) as file:
        # Set skipinitialspace to True so the csv can be formatted for readability
        csv.register_dialect("geofiletype_dialect", skipinitialspace=True, strict=True)
        reader = csv.DictReader(file, dialect="geofiletype_dialect")

        for row in reader:
            # Prepare optional values that need eval first
            suffixes = None
            if row["suffixes"] is not None and row["suffixes"] != "":
                suffixes = ast.literal_eval(row["suffixes"])
            suffixes_extrafiles = None
            if (
                row["suffixes_extrafiles"] is not None
                and row["suffixes_extrafiles"] != ""
            ):
                suffixes_extrafiles = ast.literal_eval(row["suffixes_extrafiles"])

            # Add geofiletype
            geofiletypes[row["geofiletype"]] = GeofileTypeInfo(
                geofiletype=row["geofiletype"],
                ogrdriver=row["ogrdriver"],
                suffixes=suffixes,
                is_fid_zerobased=ast.literal_eval(row["is_fid_zerobased"]),
                is_spatialite_based=ast.literal_eval(row["is_spatialite_based"]),
                suffixes_extrafiles=suffixes_extrafiles,
            )


class GeofileType(enum.Enum):
    """
    Enumeration of relevant geo file types and their properties.
    """

    ESRIShapefile = enum.auto()
    GeoJSON = enum.auto()
    GPKG = enum.auto()
    SQLite = enum.auto()
    FlatGeobuf = enum.auto()

    @classmethod
    def _missing_(cls, value):
        """
        Expand options in the GeofileType() constructor.

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
            for geofiletype in geofiletypes:
                suffixes = geofiletypes[geofiletype].suffixes
                if suffixes is not None and suffix_lower in suffixes:
                    return GeofileType[geofiletype]
            raise ValueError(f"Unknown extension {suffix}")

        def get_geofiletype_for_ogrdriver(ogrdriver: str):
            for geofiletype in geofiletypes:
                driver = geofiletypes[geofiletype].ogrdriver
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
    def suffixes_extrafiles(self) -> List[str]:
        """Returns a list of suffixes for the extra files for this GeofileType."""
        suffixes = geofiletypes[self.name].suffixes_extrafiles
        if suffixes is None:
            return []
        return suffixes

    @property
    def is_singlelayer(self) -> bool:
        """Returns True if a file of this GeofileType can only have one layer."""
        if self.is_spatialite_based:
            return False
        else:
            return True


# Init!
_init_geofiletypes()
