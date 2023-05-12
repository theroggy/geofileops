.. currentmodule:: geofileops

User guide
==========

The main objective of geofileops is to provide a simple to use but powerful API to do
fast spatial operations on large vector GIS files.

To get the most out of geofileops, these are some things to note:

  * Geofileops is tested on geopackage and shapefile input/output files. However,
    geopackage is highly recommended because it will offer better performance in
    geofileops as well as for the reasons listed here: |www.switchfromshapefile.org|.
  * A typical use case for geofileops is to script complex GIS analysis involving many
    spatial operations on multiple large input files. To support this use case, if an
    output file already exists, all spatial operations will by default just return
    without error or further processing. This way it is easy to incrementally develop/
    run the script and only new/missing output files (or output files you remove) will
    be (re)processed.
  * Because of the previous point, it is typically not supported for spatial operations
    to directly append a layer in an existing Geopackage file. If wanted, it is
    possible to append it in a seperate step using :meth:`~append_to`.
  


Spatial operations on one layer
-------------------------------

The first type of supported operations are operations that target one 
file/layer. The output is always written to a seperate output file.

The typical spatial operations are supported, eg. :meth:`~buffer`, 
:meth:`~simplify`, :meth:`~dissolve`,... 

You can also execute an sqlite sql statement (including  
|spatialite functions|) on an input file using the :meth:`~select` operation. 

A full list of operations can be found in the 
:ref:`API reference<API-reference-single-layer>`. 

This is how eg. a buffer operation can be applied on a file/layer:

.. code-block:: python

    import geofileops as gfo
    
    gfo.buffer(input_path='...', output_path='...', distance=2)

Most spatial operations in geofileops have the same optional parameters:

    * input_layer: if the file contains 1 layer, you don't need to specify a 
      layer. For a file with multiple layers, use the "layer" parameter. 
    * output_layer: if not specified, the output layer name will be 
      output_path.stem.
    * columns: if not specified, all standard attribute columns will be retained in the
      output file. If you don't need all columns, specify the ones you want to keep. 
      You can retain a copy of the special "fid" column in the output file by specifing
      "fid" in addition to the standard attribute columns you want to retain.
    * explodecollections: the output features will be "exploded", so multipart
      features will be converted to single parts.
    * gridsize: the size of the grid the coordinates of the ouput will be rounded to.
      Eg. 0.001 to keep 3 decimals. If eg. a polygon is narrower than the gridsize, it
      will be removed. Value 0.0, the default, doesn't change the precision.
    * nb_parallel: specify the number of CPU's to be used. By default all 
      CPU's are used.
    * batchsize: indication of the number of rows to be processed per batch. You can
      use this parameter to reduce memory usage. 
    * force: by default, if the output_path already exists, geofileops will  
      just log that this is the fact and return without throwing a error. 
      To overwrite the existing output_path, specify force=True.
    
Spatial operations between two files/layers
-------------------------------------------

For operations between two layers, obviously 2 input files/layers need to be 
specified.

The standard spatial operations are supported, eg. :meth:`~intersection`, 
:meth:`~erase`, :meth:`~union`,...

More specific features are:

    * :meth:`~select_two_layers`: execute a select statement (including  
      |spatialite functions|) on the input files. 
    * :meth:`~join_nearest`: find the n nearest features from one layer 
      compared the other.

The full list of operations can be found in the 
:ref:`API reference<API-reference-two-layers>`.

This is a code example for the intersection operation:

.. code-block:: python

    import geofileops as gfo

    gfo.intersection(input1_path='...', input2_path='...', output_path='...')


The two-layer operations will have about the same optional parameters as the single
layer operations, but where applicable they are duplicated for input1 and input2.


General file/layer operations
-----------------------------

Finally there are also some functions available to manipulate geo files or 
layers. Eg. :meth:`~copy`, :meth:`~move`, :meth:`~get_layerinfo`, 
:meth:`~add_column`,...  

For the full list of functions, check out the 
:ref:`API reference<API-general-layer-ops>`.

This is an example to get information about the (only) layer in a geo file: 

.. code-block:: python

    import geofileops as gfo

    layerinfo = gfo.get_layerinfo(path='...')
    print(f"Layer {layerinfo.name} contains {layerinfo.featurecount} features")

Remark: some functions might only work on Geopackage files, not on 
shapefiles.

.. |spatialite functions| raw:: html

   <a href="https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html" target="_blank">spatialite functions</a>

.. |www.switchfromshapefile.org| raw:: html

   <a href="http://www.switchfromshapefile.org" target="_blank">www.switchfromshapefile.org</a>
