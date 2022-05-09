.. currentmodule:: geofileops

=============
API Reference
=============

The API Reference provides an overview of all public objects, functions and 
methods implemented in GeofileOps. All classes and function exposed in 
``geofileops.*`` namespace plus those listed in the reference are public.

.. warning::
   The functionality in the "util" modules is typically relatively stable, but 
   because it is not "guaranteed", it is not included in the reference.

.. _API-reference-single-layer:

Spatial operations on a single layer
------------------------------------

.. autosummary::
   :toctree: api/

   apply
   buffer
   convexhull
   delete_duplicate_geometries
   dissolve
   isvalid
   makevalid
   select
   simplify

.. _API-reference-two-layers:

Spatial operations on two layers
--------------------------------

.. autosummary::
   :toctree: api/

   clip
   erase
   export_by_distance
   export_by_location
   intersection
   join_by_location
   join_nearest
   select_two_layers
   split
   symmetric_difference
   union

.. _API-general-layer-ops:

General layer operations
------------------------

.. autosummary::
   :toctree: api/

   append_to
   add_column
   convert
   create_spatial_index
   drop_column
   execute_sql
   get_crs
   get_default_layer
   get_layerinfo
   get_only_layer
   has_spatial_index
   read_file
   read_file_nogeom
   read_file_sql
   remove_spatial_index
   rename_column
   rename_layer
   update_column
   to_file

.. _API-general-file-ops:

General file operations
-----------------------

.. autosummary::
   :toctree: api/

   cmp
   copy
   is_geofile
   is_geofile_ext
   listlayers
   move
   remove

Classes
-------

.. autosummary::
   :toctree: api/

   BufferEndCapStyle
   BufferJoinStyle
   DataType
   GeofileType
   GeometryType
   LayerInfo
   PrimitiveType
   SimplifyAlgorithm
   