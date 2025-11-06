"""Some performance tests in context of processing many small files."""

import cProfile
import io
import pstats
import urllib.request
import warnings
from pstats import SortKey
from time import perf_counter

from osgeo import gdal

import geofileops as gfo

gdal.UseExceptions()


def test_perf_gdal_openex(tmp_path):
    gfo_uri = "https://github.com/geofileops/geofileops/raw/refs/heads/main"
    remote_src = f"{gfo_uri}/tests/data/polygon-parcel.gpkg"
    src = tmp_path / "input.gpkg"
    urllib.request.urlretrieve(remote_src, src)

    # Test!
    start = perf_counter()

    for _i in range(5000):
        with gdal.OpenEx(str(src), gdal.OF_VECTOR):
            pass

    elapsed = perf_counter() - start
    warnings.warn(f"Elapsed time: {elapsed}", stacklevel=1)


def test_perf_gdal_vectortranslate(tmp_path):
    gfo_uri = "https://github.com/geofileops/geofileops/raw/refs/heads/main"
    remote_src = f"{gfo_uri}/tests/data/polygon-parcel.gpkg"
    src = tmp_path / "input.gpkg"
    dst = tmp_path / "output.gpkg"
    urllib.request.urlretrieve(remote_src, src)

    # Test!
    start = perf_counter()

    for _i in range(500):
        gdal.VectorTranslate(destNameOrDestDS=dst, srcDS=src)
        dst.unlink()

    elapsed = perf_counter() - start
    warnings.warn(f"Elapsed time: {elapsed}", stacklevel=1)


def test_perf_gfo_buffer(tmp_path):
    gfo_uri = "https://github.com/geofileops/geofileops/raw/refs/heads/main"
    remote_src = f"{gfo_uri}/tests/data/polygon-parcel.gpkg"
    input_path = tmp_path / "input.gpkg"
    urllib.request.urlretrieve(remote_src, input_path)

    # Test!
    output = tmp_path / "output.gpkg"
    start = perf_counter()

    with cProfile.Profile() as pr:
        for _i in range(100):
            gfo.buffer(input_path, output, distance=10)
            output.unlink()

        s = io.StringIO()
        sortby = SortKey.CUMULATIVE
        ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
        ps.print_stats(50)

    elapsed = perf_counter() - start
    warnings.warn(f"Elapsed time: {elapsed}", stacklevel=1)
    warnings.warn(s.getvalue(), stacklevel=1)


def test_perf_gfo_intersection(tmp_path):
    gfo_uri = "https://github.com/geofileops/geofileops/raw/refs/heads/main"
    remote_src = f"{gfo_uri}/tests/data/polygon-parcel.gpkg"
    input1 = tmp_path / "input1.gpkg"
    urllib.request.urlretrieve(remote_src, input1)
    input2 = tmp_path / "input2.gpkg"
    gfo.copy(input1, input2)

    # Test!
    output = tmp_path / "output.gpkg"
    start = perf_counter()

    with cProfile.Profile() as pr:
        for _i in range(10):
            gfo.intersection(input1, input2, output)
            output.unlink()

        s = io.StringIO()
        sortby = SortKey.CUMULATIVE
        ps = pstats.Stats(pr, stream=s).sort_stats(sortby)
        ps.print_stats(30)

    elapsed = perf_counter() - start
    warnings.warn(f"Elapsed time: {elapsed}", stacklevel=1)
    warnings.warn(s.getvalue(), stacklevel=1)


def test_perf_gfo_layerinfo(tmp_path):
    gfo_uri = "https://github.com/geofileops/geofileops/raw/refs/heads/main"
    remote_src = f"{gfo_uri}/tests/data/polygon-parcel.gpkg"
    src = tmp_path / "input.gpkg"
    urllib.request.urlretrieve(remote_src, src)

    # Test!
    start = perf_counter()

    for _i in range(5000):
        gfo.get_layerinfo(src)

    elapsed = perf_counter() - start
    warnings.warn(f"Elapsed time: {elapsed}", stacklevel=1)
