# geofileops 

[![Actions Status](https://github.com/geofileops/geofileops/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/geofileops/geofileops/actions/workflows/tests.yml?query=workflow%3ATests) 
[![Coverage Status](https://codecov.io/gh/geofileops/geofileops/branch/main/graph/badge.svg)](https://codecov.io/gh/geofileops/geofileops)
[![PyPI version](https://img.shields.io/pypi/v/geofileops.svg)](https://pypi.org/project/geofileops)
[![Conda version](https://anaconda.org/conda-forge/geofileops/badges/version.svg)](https://anaconda.org/conda-forge/geofileops)

This python library aims to make it easier and faster to develop spatial analysis on
large vector GIS files.

It provides an easy to use API that can accomplish a lot with few lines of code. Most
typical GIS operations are available: e.g. 
[buffer](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.buffer), 
[dissolve](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.dissolve),
[erase](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.erase)/difference, 
[intersection](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.intersection),...
[union](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.union),
Check out the [API reference](https://geofileops.readthedocs.io/en/stable/reference.html)
for a full list.

Geofileops is tested on geopackage and shapefile input files. However, geopackage
is recommended as it will give better performance for most operations.

The aim is that there is no size limit on the files that can be processed on standard
hardware. To make processing faster, the operations can use all available CPU's. In
some cases (complex) geometries will be cut in smaller tiles to speed up processing
further. For operations like buffer this won't make a big difference as it doesn't need
a lot of CPU power, but calculating the intersection between two large files, dissolving
large files,... will be a lot faster.

The following chart gives an impression of the speed improvement that can be expected
when processing larger files (including I/O!) with 10 CPU's available. More information
about this benchmark can be found [here](https://github.com/geofileops/geobenchmark).

![Geo benchmark](https://github.com/geofileops/geobenchmark/blob/main/results_vector_ops/GeoBenchmark.png)
