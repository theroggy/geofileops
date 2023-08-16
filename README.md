# geofileops 

[![Actions Status](https://github.com/geofileops/geofileops/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/geofileops/geofileops/actions/workflows/tests.yml?query=workflow%3ATests) 
[![Coverage Status](https://codecov.io/gh/geofileops/geofileops/branch/main/graph/badge.svg)](https://codecov.io/gh/geofileops/geofileops)
[![PyPI version](https://img.shields.io/pypi/v/geofileops.svg)](https://pypi.org/project/geofileops)
[![Conda version](https://anaconda.org/conda-forge/geofileops/badges/version.svg)](https://anaconda.org/conda-forge/geofileops)

This python library aims to make spatial operations on large geo files faster 
and easier. 

It provides an easy to use API that can accomplish a lot with few lines of 
code. To make processing faster, geofileops can use all available CPU's for 
spatial operations.
For operations like buffer this won't make a big difference as it doesn't need 
a lot of CPU power, but calculating the intersection between two large files, 
dissolving large files,... will be a lot faster.
The aim is that there is no size limit on the files that can be processed. 

Most typical operations are available: 
[buffer](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.buffer), 
[simplify](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.simplify),
[dissolve](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.dissolve),
[union](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.union),
[erase](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.erase)/difference, 
[intersection](https://geofileops.readthedocs.io/en/stable/api/geofileops.apply.html#geofileops.intersection),...

Geofileops is tested on geopackage and shapefile input files. However, geopackage
is recommended as it will give better performance for most operations.

Documentation on how to use geofileops can be found [here](https://geofileops.readthedocs.io).

The following chart gives an impression of the speed improvement that can be expected
when processing larger files (including I/O!). More information about this benchmark can
be found [here](https://github.com/geofileops/geobenchmark).

![Geo benchmark](https://github.com/geofileops/geobenchmark/blob/main/results_vector_ops/GeoBenchmark.png)
