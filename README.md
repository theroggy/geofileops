# geofileops 

[![Actions Status](https://github.com/geofileops/geofileops/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/geofileops/geofileops/actions/workflows/tests.yml?query=workflow%3ATests) 
[![Coverage Status](https://codecov.io/gh/geofileops/geofileops/branch/main/graph/badge.svg)](https://codecov.io/gh/geofileops/geofileops)
[![PyPI version](https://img.shields.io/pypi/v/geofileops.svg)](https://pypi.org/project/geofileops)
[![Conda version](https://anaconda.org/conda-forge/geofileops/badges/version.svg)](https://anaconda.org/conda-forge/geofileops)
[![DOI](https://zenodo.org/badge/203202318.svg)](https://zenodo.org/doi/10.5281/zenodo.10340100)

Geofileops is a python toolbox to process large vector files faster.

Most typical GIS operations are available: e.g.
[buffer](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.buffer), 
[dissolve](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.dissolve),
[erase](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.erase)/difference, 
[intersection](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.intersection), 
[union](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.union),... 

The spatial operations are tested on geopackage and shapefile input files, but
geopackage is recommended as it will give better performance. General 
[layer](https://geofileops.readthedocs.io/en/stable/reference.html#general-layer-operations)
and [file operations](https://geofileops.readthedocs.io/en/stable/reference.html#general-file-operations) can be used on the file formats supported by 
[GDAL](https://gdal.org/).

The full documentation is available on [readthedocs](https://geofileops.readthedocs.io).

Different techniques are used under the hood to be able to process large files as fast
as possible:

* process data in batches
* subdivide/merge complex geometries on the fly
* process data in different passes
* use all available CPUs

The following chart gives an impression of the speed improvement that can be expected
when processing larger files. The [benchmarks](https://github.com/geofileops/geobenchmark)
typically use input file(s) with 500K polygons, ran on a Windows PC with 12 cores and include I/O.

![Geo benchmark](https://github.com/geofileops/geobenchmark/blob/main/results_vector_ops/GeoBenchmark.png)
