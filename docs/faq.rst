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

The spatial functionalities of geofileops are tested on geopackage and shapefile
input/output files. However, geopackage is highly recommended because it will offer
better performance in geofileops as well as for the reasons listed here: 
`www.switchfromshapefile.org <http://www.switchfromshapefile.org>`_.

Most general file/layer operations can be used on all vector formats supported by
`GDAL <https://gdal.org/drivers/vector/index.html>`_.

Runtime configuration options
-----------------------------

GeofileOps supports some runtime configuration options that can be set using environment
variables:

- `GFO_IO_ENGINE`: the IO engine to use when reading and writing GeoDataFrames. Valid
  options are "pyogrio" and "fiona". Defaults to "pyogrio".
- `GFO_REMOVE_TEMP_FILES`: whether to remove temp files being created after use, e.g. 
  for debugging purposes. Valid values are e.g. "TRUE" or "FALSE". Defaults to True.

You can use the :class:`.TempEnv` context manager if you want to set a configuration
option temporarily:

.. code-block:: python

    import geofileops as gfo

    if __name__ == "__main__":
        with gfo.TempEnv("GFO_REMOVE_TEMP_FILES", "False"):
            gfo. ...
