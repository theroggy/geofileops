.. currentmodule:: geofileops

=============
API Reference
=============

The API Reference provides an overview of all public objects, functions and 
methods implemented in GeofileOps.

.. _reference-geometry-tools:

Geometry tools
--------------

.. autosummary::
   :toctree: api/

   apply
   apply_vectorized
   buffer
   clip_by_geometry
   convexhull
   delete_duplicate_geometries
   dissolve
   dissolve_within_distance
   export_by_bounds
   isvalid
   makevalid
   select
   simplify
   warp

.. _reference-spatial-overlays-joins:

Spatial overlays and joins
--------------------------

.. autosummary::
   :toctree: api/

   clip
   difference
   export_by_distance
   export_by_location
   intersection
   join
   join_by_location
   join_nearest
   select_two_layers
   identity
   symmetric_difference
   union
   union_full_self

.. _reference-general-layer-ops:

General layer operations
------------------------

.. autosummary::
   :toctree: api/

   append_to
   add_column
   add_columns
   add_layerstyle
   concat
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

.. _reference-general-file-ops:

General file operations
-----------------------

.. autosummary::
   :toctree: api/

   cmp
   copy
   get_driver
   listlayers
   move
   unzip_geofile
   remove
   zip_geofile

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
   TempEnv

.. _reference-runtime-options:

Runtime Options
---------------

Geofileps has several runtime options that can be used to tune its behavior. These can
be set using the helper functions below. The runtime options are saved to and read from
environment variables, so setting the environment variables directly is also possible.

All helper functions below can be used in two ways:
   1. Permanently set the option by calling the function directly.
   2. Temporarily set the option by using the function as a context manager.

.. autosummary::
   :toctree: api/

   options.set_copy_layer_sqlite_direct
   options.set_io_engine
   options.set_on_data_error
   options.set_remove_temp_files
   options.set_sliver_tolerance
   options.set_subdivide_check_parallel_fraction
   options.set_subdivide_check_parallel_rows
   options.set_tmp_dir
   options.set_worker_type
