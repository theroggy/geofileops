.. currentmodule:: geofileops

===
FAQ
===

.. _FAQ-standalone-scripts:

Standalone python scripts
-------------------------

Because geofileops makes extensive use of multiprocessing, it is a good idea to always
use the following construct in standalone scripts.

.. code-block:: python

    import geofileops as gfo

    if __name__ == "__main__":
        gfo. ...

Not using this can lead to the following `RuntimeError` being thrown: `An attempt has
been made to start a new process before the current process has finished its
bootstrapping phase.`
You can find more details on why this is needed in the 
`python multiprocessing docs <https://docs.python.org/3/library/multiprocessing.html#the-spawn-and-forkserver-start-methods>`_

.. _FAQ-supported-file-formats:

Supported file formats
----------------------

The spatial functionalities of geofileops are supported on standard geopackage and
shapefile input/output files. However, geopackage is highly recommended because it will
offer better performance in geofileops as well as for the reasons listed here: 
`www.switchfromshapefile.org <http://www.switchfromshapefile.org>`_.

Most general file/layer operations can be used on all vector formats supported by
`GDAL <https://gdal.org/drivers/vector/index.html>`_ as well as on paths using
`GDAL VSI handlers <https://gdal.org/en/stable/user/virtual_file_systems.html>`_.

Runtime configuration options
-----------------------------

GeofileOps supports some runtime configuration options that can be set using environment
variables:

- `GFO_IO_ENGINE`: the IO engine to use when reading and writing GeoDataFrames. Valid
  options are "pyogrio" and "fiona". The "fiona" option is deprecated and will be
  ignored in a future version. Defaults to "pyogrio".
- `GFO_ON_DATA_ERROR`: the action to take when a data error occurs while processing a
  tile during dissolve. Data errors are e.g. invalid geometries encountered/created
  during processing. Valid options are "raise" and "warn". The "warn" option will lead
  to the data OF THE ENTIRE TILE being "dropped", so use with care! Defaults to "raise".
- `GFO_REMOVE_TEMP_FILES`: whether to remove temp files being created after use, e.g.
  for debugging purposes. Valid values are e.g. "TRUE" or "FALSE". Defaults to "TRUE".
- `GFO_TMPDIR`: directory to be used by geofileops to put temporary files. If not
  specified, defaults to the default python temp directory as returned by
  `tempfile.gettempdir <https://docs.python.org/3/library/tempfile.html#tempfile.gettempdir>`_.
- `GFO_WORKER_TYPE`: the type of worker to use for parallel processing.
  Valid options are:
  
    - **"processes"**: batches are processed in parallel processes. This typically enables
      true concurrency so all CPU cores can be optimally used.
    - **"threads"**: batches are processed in parallel threads. Due to the python "Global
      Interpreter Lock" (GIL), the amount of actual concurrency depends on how the
      operation is implemented.
    - **"auto"**: for small files threads are used, for larger files processes. At the
      time of writing a small file is a file with maximum 100 rows. On Windows creating
      a process is quite expensive, so using threads is often more efficient to process
      small files.

You can use the :class:`.TempEnv` context manager if you want to set a configuration
option temporarily:

.. code-block:: python

    import geofileops as gfo

    if __name__ == "__main__":
        with gfo.TempEnv({"GFO_REMOVE_TEMP_FILES", "False"}):
            gfo. ...
