.. currentmodule:: geofileops

==========
User guide
==========

The main objective of geofileops is to provide a simple to use but powerful API to do
fast spatial operations on large vector GIS files.


General  
-------

To speed up processing, geofileops uses multiprocessing under the hood. Because of that,
you should always use the ``if __name__ == "__main__":`` block in standalone Python
scripts. More information: :ref:`FAQ - Standalone scripts<FAQ-standalone-scripts>`.

Also interesting to know: because processing large files can take some time, geofileops
logs progress info using the standard logging module.

Combining both, a basic script using geofileops can look like this:

.. code-block:: python

    import logging
    import geofileops as gfo
    
    if __name__ == "__main__":
        logging.basicConfig(level=logging.INFO)
        gfo.buffer(input_path="input.gpkg", output_path="output.gpkg", distance=2)


Finally, for the spatial tools, only geopackage (".gpkg", ".gpkg.zip") and shapefile
(".shp", ".shp.zip") files are supported as input and output formats.
However, (unzipped) geopackage files (".gpkg") are **very** recommended because they
will lead to significantly better performance because no conversions will be needed
under the hood. There are also :ref:`many other reasons <FAQ-supported-file-formats>`
to use Geopackage files.

Most general file/layer operations like :meth:`~get_layerinfo`, :meth:`~read_file`,...
can be used on any file format supported by GDAL as well as on paths using
`GDAL VSI handlers <https://gdal.org/en/stable/user/virtual_file_systems.html>`_.


Geometry tools  
--------------

The typical :ref:`geometry tools <reference-geometry-tools>` are directly
supported, eg. :meth:`~buffer`, :meth:`~simplify`, :meth:`~convexhull`,
:meth:`~dissolve`, ...

.. code-block:: python

    gfo.simplify(
        input_path="input.gpkg", output_path="output.gpkg", algorythm="vw", tolerance=1
    )


Some more exotic ones are e.g. :meth:`dissolve_within_distance` and :meth:`warp`.

For more advanced uses, you can execute any sqlite SQL statement on an input file using
:meth:`~select`. Because 
`spatialite functions <https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html>`_ 
are also supported, this is quite powerful. To simplify the SQL statements, there are
some placeholders you can use that will be filled out by geofileops:

.. code-block:: python

    # When evaluating an f-string, Python replaces double curly braces with a single
    # curly brace. Hence, e.g. "{{input_layer}}" becomes "{input_layer}" so it is ready
    # to be filled out by geofileops.
    city = "Brussels"
    sql_stmt = f"""
        SELECT ST_OrientedEnvelope({{geometrycolumn}}) AS geom
              {{columns_to_select_str}}
          FROM "{{input_layer}}" layer
         WHERE city_name = '{city}'
    """
    gfo.select(
        input_path="input.gpkg",
        output_path="output.gpkg",
        columns=["city_name", "city_code"],
        sql_stmt=sql_stmt,
    )

Finally, you can apply any python function on the geometry column using :meth:`~apply`.

.. code-block:: python

    import pygeoops

    def cleanup(geom, min_area_to_keep):
        new_geom = pygeoops.remove_inner_rings(geom, min_area_to_keep=min_area_to_keep)
        return new_geom

    gfo.apply(
        input_path="input.gpkg",
        output_path="output.gpkg",
        func=lambda geom: cleanup(geom, min_area_to_keep=1),
    )

Most functions in geofileops have some similar optional parameters. These are the
most interesting ones:

* **columns**: if not specified, all standard attribute columns will be retained in the
  output file. If you don't need all columns, specify the ones you want to keep. 
  You can retain a copy of the special "fid" column in the output file by specifing
  "fid" in addition to the standard attribute columns you want to retain.
* **explodecollections**: the output features will be "exploded", so multipart
  features will be converted to single parts.
* **gridsize**: the size of the grid the coordinates of the ouput will be rounded to.
  Eg. 0.001 to keep 3 decimals. If eg. a polygon is narrower than the ``gridsize``, it
  will be removed. Value 0.0, the default, doesn't change the precision.
* **force**: by default, if the ``output_path`` already exists, geofileops will just log
  this and return. To overwrite the existing ``output_path``, specify ``force=True``.
    

Spatial overlays
----------------

The standard :ref:`spatial overlays <reference-spatial-overlays-joins>` are
available: :meth:`~intersection`, :meth:`~difference`, :meth:`~clip`, :meth:`~identity`,
:meth:`~union`, ...

An example:

.. code-block:: python

    gfo.identity(
        input1_path="input1.gpkg", input2_path="input2.gpkg", output_path="output.gpkg"
    )


In addition, if you specify ``input2_path=None``, the result will be the self-overlay of
the 1st input layer. E.g. for ``intersection`` this will result in an output with all
pairwise intersections between the features in this layer. The intersection of features
with itself is omitted.


Spatial joins
-------------

There are several options available to do
:ref:`spatial joins <reference-spatial-overlays-joins>`.

The most typical one is :meth:`~join_by_location`. This allows you to join the features
in two layers with either "named spatial predicates" (e.g. equals, touches,
intersects, ...) or with a "spatial mask" as defined by the
`DE-9IM <https://en.wikipedia.org/wiki/DE-9IM>`_ model.

Another option is to look for the n nearest features for all features from one layer
compared to all features from the second layer using :meth:`~join_nearest`.

If you only want to export rows from a layer that have some spatial relationship with
features in another layer you can use :meth:`~export_by_location` or
:meth:`~export_by_distance`.

Finally, if you want full control, you can use SQL statements to build your own overlay
and/or join logic. Check out the examples for :meth:`~select_two_layers` to get some
inspiration.


General file/layer operations
-----------------------------

Finally there are also some :ref:`general functions <reference-general-layer-ops>`
available to manipulate geo files or layers. Eg. :meth:`~copy`, :meth:`~move`,
:meth:`~get_layerinfo`, :meth:`~add_column`, ...

A common need is to get general information about a layer, like the number of features,
the columns,... , without reading the entire file. If there is only one layer in the
file, the `layer` doesn't need to be specified:

.. code-block:: python

    layerinfo = gfo.get_layerinfo("file.gpkg")
    print(f"Layer {layerinfo.name} contains {layerinfo.featurecount} features")


You can also add, update, ... columns directly to a file layer using
:meth:`~add_column`, :meth:`~update_column`, ... The values can be filled out using a
SQL expression. The SQLexpression should use the SQLite dialect and you can also use
spatialite function 
(`spatialite functions <https://www.gaia-gis.it/gaia-sins/spatialite-sql-latest.html>`_).

A typical example is to add a column with the area of the geometry to the layer. 
This uses the `ST_Area` spatialite function. Note that such an "area" column won't be
updated automatically if you change the geometry of the features in the layer, e.g. by
applying a buffer. You can use :meth:`~update_column` to update the area if needed after
such operations:

.. code-block:: python

    gfo.add_column("file.gpkg", name="area", type="REAL", expression="ST_Area(geom)")
    gfo.update_column("file.gpkg", name="area", expression="ST_Area(geom)")


For string/text type columns, note that in SQL it is mandatory to use single
quotes around the string value. For example:

.. code-block:: python

    gfo.add_column("file.gpkg", type="TEXT", name="text_column", expression="'Hello!'")


Geofileops also has some functions to read and write GeoDataFrames. They are very
similar to the geopandas equivalents with some small differences. For example, you can
use some placeholders in the SQL statements that will be filled out by geofileops to
make it easier to reuse statements:

.. code-block:: python

    sql_stmt = """
        SELECT {geometrycolumn}
              {columns_to_select_str}
              ,ST_Area({geometrycolumn}) AS area
          FROM "{input_layer}" layer
         WHERE ST_Area({geometrycolumn}) > 100
    """
    gdf = gfo.read_file(
        path="file.gpkg", sql_stmt=sql_stmt, columns=["city_name", "city_code"]
    )
    gfo.write_file(gdf, path="file2.gpkg")


Because you can use any SQL statement, you can also easily run some statistics on a
dataset like this:

.. code-block:: python

    sql_stmt = """
        SELECT city_code
              ,city_name
              ,COUNT(*) AS count
              ,SUM(ST_Area({geometrycolumn})) AS total_area
          FROM "{input_layer}" layer
         GROUP BY city_code, city_name
    """
    stats_df = gfo.read_file(path="file.gpkg", sql_stmt=sql_stmt)
    stats_df.to_excel("stats.xlsx", index=False)


Runtime Options
---------------
Geofileops has several runtime options that can be used to tune its behavior. These can
be set using the :mod:`geofileops.options` module.

Some options can help with debugging, like disabling the removal of temporary files,
others can help improve performance depending on the use case, like setting the
type of workers to use.

Information about all runtime options and how to use them can be found here:
:ref:`Runtime Options<reference-runtime-options>`.
