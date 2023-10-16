.. currentmodule:: geofileops

=============
API Reference
=============

The API Reference provides an overview of all public objects, functions and 
methods implemented in GeofileOps.

.. _API-reference-single-layer:

Spatial operations on a single layer
------------------------------------

.. autosummary::
   :toctree: api/

   apply
   buffer
   clip_by_geometry
   convexhull
   delete_duplicate_geometries
   dissolve
   export_by_bounds
   isvalid
   makevalid
   select
   simplify
   warp

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
   identity
   symmetric_difference
   union

.. _API-general-layer-ops:

General layer operations
------------------------

.. autosummary::
   :toctree: api/

   append_to
   add_column
   add_layerstyle
   copy_layer
   create_spatial_index
   drop_column
   execute_sql
   get_crs
   get_default_layer
   get_layer_geometrytypes
   get_layerinfo
   get_layerstyles
   get_only_layer
   has_spatial_index
   read_file
   remove_layerstyle
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
   get_driver
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
   LayerInfo
   PrimitiveType
   SimplifyAlgorithm
   