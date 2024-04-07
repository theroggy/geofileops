"""
Module to prepare test data for benchmarking geo operations.
"""

import enum
import logging
from pathlib import Path
import pprint
import shutil
import tempfile
from typing import Optional, Tuple

import geopandas as gpd
import shapely
import urllib.request
import zipfile

import geofileops as gfo

################################################################################
# Some inits
################################################################################

logger = logging.getLogger(__name__)

################################################################################
# The real work
################################################################################


class TestFile(enum.Enum):
    """
    Class to create benchmarking test files.

    Args:
        enum (_type_): _description_

    Raises:
        ValueError: _description_
        RuntimeError: _description_

    Returns:
        _type_: _description_
    """

    AGRIPRC_2018 = (
        0,
        "https://www.landbouwvlaanderen.be/bestanden/gis/Landbouwgebruikspercelen_2018_-_Definitief_(extractie_23-03-2022)_GPKG.zip",
        "agriprc_2018.gpkg",
    )
    AGRIPRC_2019 = (
        1,
        "https://www.landbouwvlaanderen.be/bestanden/gis/Landbouwgebruikspercelen_2019_-_Definitief_(extractie_20-03-2020)_GPKG.zip",
        "agriprc_2019.gpkg",
    )
    COMPLEX_POLYS = (2, None, "complexpolys.gpkg")

    def __init__(self, value, url, filename):
        """
        Create a test file.

        Args:
            value (_type_): _description_
            url (_type_): _description_
            filename (_type_): _description_
        """
        self._value_ = value
        self.url = url
        self.filename = filename

    def get_file(self, output_dir: Path) -> Tuple[Path, str]:
        """
        Creates the test file.

        Args:
            output_dir (Path): the directory to write the file to.

        Returns:
            _type_: The path to the file + a description of the test file.
        """
        if self.url is not None:
            testfile_path = _download_samplefile(
                url=self.url, dst_name=self.filename, dst_dir=output_dir
            )
            testfile_info = gfo.get_layerinfo(testfile_path)
            logger.debug(
                f"TestFile {self.name} contains {testfile_info.featurecount} rows."
            )
            description = f"agri parcels, {testfile_info.featurecount} rows"

        elif self.name == "COMPLEX_POLYS":
            # Prepare some complex polygons to test with
            xmin_start = 30000
            step = 20000
            nb_polys = 10
            polys_complex = [
                create_complex_poly(
                    xmin=xmin,
                    ymin=170000.123,
                    width=15000,
                    height=15000,
                    line_distance=500,
                    max_segment_length=100,
                )
                for xmin in range(xmin_start, xmin_start + (nb_polys * step), step)
            ]
            logger.debug(
                f"polys_complex: {len(polys_complex)} polys with num_coordinates: "
                f"{shapely.get_num_coordinates(polys_complex[0])}"
            )
            testfile_path = output_dir / self.filename
            complex_gdf = gpd.GeoDataFrame(geometry=polys_complex, crs="epsg:31370")
            complex_gdf.to_file(testfile_path, engine="pyogrio")
            description = (
                f"{len(polys_complex)} complex polys "
                f"(each {shapely.get_num_coordinates(polys_complex[0])} coords)"
            )

        else:
            raise RuntimeError(f"get_file not implemented for {self.name}")

        return (testfile_path, description)


def create_complex_poly(
    xmin: float,
    ymin: float,
    width: int,
    height: int,
    line_distance: int,
    max_segment_length: int,
) -> shapely.Polygon:
    """Create complex polygon of a ~grid-shape the size specified."""
    lines = []

    # Vertical lines
    for x_offset in range(0, 0 + width, line_distance):
        lines.append(
            shapely.LineString(
                [(xmin + x_offset, ymin), (xmin + x_offset, ymin + height)]
            )
        )

    # Horizontal lines
    for y_offset in range(0, 0 + height, line_distance):
        lines.append(
            shapely.LineString(
                [(xmin, ymin + y_offset), (xmin + width, ymin + y_offset)]
            )
        )

    poly_complex = shapely.unary_union(shapely.MultiLineString(lines).buffer(2))
    poly_complex = shapely.segmentize(
        poly_complex, max_segment_length=max_segment_length
    )
    assert len(shapely.get_parts(poly_complex)) == 1

    return poly_complex


def _download_samplefile(
    url: str, dst_name: str, dst_dir: Optional[Path] = None
) -> Path:
    """
    Download a sample file to dest_path.

    If it is zipped, it will be unzipped. If needed, it will be converted to
    the file type as determined by the suffix of dst_name.

    Args:
        url (str): the url of the file to download.
        dst_name (str): the name of the destination file.
        dst_dir (Path): the dir to downloaded the sample file to.
            If it is None, a dir in the default tmp location will be
            used. Defaults to None.

    Returns:
        Path: the path to the downloaded sample file.
    """
    # If the destination path is a directory, use the default file name
    dst_path = _prepare_dst_path(dst_name, dst_dir)
    # If the sample file already exists, return
    if dst_path.exists():
        return dst_path
    # Make sure the destination directory exists
    dst_path.parent.mkdir(parents=True, exist_ok=True)

    # If the url points to a file with the same suffix as the dst_path,
    # just download
    url_path = Path(url)
    if url_path.suffix.lower() == dst_path.suffix.lower():
        logger.info(f"Download to {dst_path}")
        urllib.request.urlretrieve(url, dst_path)
    else:
        # The file downloaded is different that the destination wanted, so some
        # converting will need to be done
        tmp_dir = dst_path.parent / "tmp"

        try:
            # Remove tmp dir if it exists already
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir)
            tmp_dir.mkdir(parents=True, exist_ok=True)

            # Download file
            tmp_path = tmp_dir / f"{dst_path.stem}{url_path.suffix.lower()}"
            logger.info(f"Download tmp data to {tmp_path}")
            urllib.request.urlretrieve(url, tmp_path)

            # If the temp file is a .zip file, unzip to dir
            if tmp_path.suffix == ".zip":
                # Unzip
                unzippedzip_dir = dst_path.parent / tmp_path.stem
                logger.info(f"Unzip to {unzippedzip_dir}")
                with zipfile.ZipFile(tmp_path, "r") as zip_ref:
                    zip_ref.extractall(unzippedzip_dir)

                # Look for the file
                tmp_paths = []
                for suffix in [".shp", ".gpkg"]:
                    tmp_paths.extend(list(unzippedzip_dir.rglob(f"*{suffix}")))
                if len(tmp_paths) == 1:
                    tmp_path = tmp_paths[0]
                else:
                    raise Exception(
                        f"Should find 1 geofile, found {len(tmp_paths)}: \n"
                        f"{pprint.pformat(tmp_paths)}"
                    )

            if dst_path.suffix == tmp_path.suffix:
                gfo.move(tmp_path, dst_path)
            else:
                logger.info(f"Convert tmp file to {dst_path}")
                gfo.makevalid(tmp_path, dst_path, keep_empty_geoms=False)
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    return dst_path


def _prepare_dst_path(dst_name: str, dst_dir: Optional[Path] = None):
    if dst_dir is None:
        return Path(tempfile.gettempdir()) / "geofileops_sampledata" / dst_name
    else:
        return dst_dir / dst_name
