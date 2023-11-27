# geofileops 

[![Actions Status](https://github.com/geofileops/geofileops/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/geofileops/geofileops/actions/workflows/tests.yml?query=workflow%3ATests) 
[![Coverage Status](https://codecov.io/gh/geofileops/geofileops/branch/main/graph/badge.svg)](https://codecov.io/gh/geofileops/geofileops)
[![PyPI version](https://img.shields.io/pypi/v/geofileops.svg)](https://pypi.org/project/geofileops)
[![Conda version](https://anaconda.org/conda-forge/geofileops/badges/version.svg)](https://anaconda.org/conda-forge/geofileops)

Geofileops aims to speed up spatial analysis on large/complex vector datasets.

It provides an easy to use API that can accomplish a lot with few lines of code. Most
typical GIS operations are available: e.g. 
[buffer](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.buffer), 
[dissolve](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.dissolve),
[erase](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.erase)/difference, 
[intersection](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.intersection), 
[union](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.union),... 
Check out the [API reference](https://geofileops.readthedocs.io/en/stable/reference.html)
for a full list.

The spatial operations are tested on geopackage and shapefile input files, but geopackage is recommended as it will give better performance. Basic operations like [copy_layer](https://geofileops.readthedocs.io/en/stable/api/geofileops.copy_layer.html#geofileops.copy_layer) can be used on the file formats supported by [GDAL](https://gdal.org/).

Different techniques are used under the hood to be able to process large files as fast as possible:
- process data in batches
- subdivide/merge complex geometries on the fly
- process data in different passes
- use all available CPUs

The following chart gives an impression of the speed improvement that can be expected when processing larger files. The [benchmarks](https://github.com/geofileops/geobenchmark) ran on a Windows PC with 12 cores and include I/O.

![Geo benchmark](https://github.com/geofileops/geobenchmark/blob/main/results_vector_ops/GeoBenchmark.png)
