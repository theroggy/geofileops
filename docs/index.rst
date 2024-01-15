.. geofileops documentation master file, created by
   sphinx-quickstart on Thu Nov  5 20:17:22 2020.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

.. currentmodule:: geofileops

====================
GeofileOps |version|
====================

GeofileOps is a python toolbox to process large vector files faster.

Most typical GIS operations are available: e.g. :meth:`~buffer`, :meth:`~simplify`,
:meth:`~dissolve`, :meth:`~intersection`,... You can also run custom logic by using
:meth:`~apply`, :meth:`~select` or :meth:`~select_two_layers`.

The spatial operations are tested on geopackage and shapefile input files, but
geopackage is recommended as it will give better performance. General layer and file
operations can be used on the file formats supported by `GDAL <https://gdal.org>`_.

Different techniques are used under the hood to be able to process large files as fast
as possible:

* process data in batches
* subdivide/merge complex geometries on the fly
* process data in different passes
* use all available CPUs

The following chart gives an impression of the speed improvement that can be expected
when processing larger files. The `benchmarks <https://github.com/geofileops/geobenchmark>`_
ran on a Windows PC with 12 cores and include I/O.

.. image:: https://github.com/geofileops/geobenchmark/blob/main/results_vector_ops/GeoBenchmark.png?raw=true
   :alt: geobenchmark spatial vector operations performance chart
   


.. toctree::
   :maxdepth: 1

   Home <self>
   Getting started <getting_started>
   User guide <user_guide>
   API reference <reference>
   Development <development>