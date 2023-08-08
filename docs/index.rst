.. geofileops documentation master file, created by
   sphinx-quickstart on Thu Nov  5 20:17:22 2020.
   You can adapt this file completely to your liking, but it should at least
   contain the root `toctree` directive.

.. currentmodule:: geofileops

GeofileOps |version|
====================

This python library aims to make spatial operations on large geo files faster 
and easier. 

It provides an easy to use API that can accomplish a lot with few lines of 
code. To make processing faster, geofileops can use all available CPU's for 
spatial operations.
For operations like buffer this won't make a big difference as it doesn't need 
a lot of CPU power, but calculating the intersection between two large files, 
dissolving large files,... will be a lot faster.
The aim is that there is no size limit on the files that can be processed. 

Most typical operations are available: :meth:`~buffer`, :meth:`~simplify`,
:meth:`~dissolve`, :meth:`~union`, :meth:`~erase`, :meth:`~intersection`,... 

Geofileops is tested on geopackage and shapefile input files. However, geopackage
is recommended as it will give better performance for most operations.

.. toctree::
   :maxdepth: 1

   Home <self>
   Getting started <getting_started>
   User guide <user_guide>
   API reference <reference>
   Development <development>