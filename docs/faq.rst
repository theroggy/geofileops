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

The spatial tools of geofileops (buffer, overlays,...) are only supported on geopackage
(".gpkg", ".gpkg.zip") and shapefile (".shp", ".shp.zip") input/output files.
However, uncompressed geopackages (".gpkg") will offer the best performance because
most spatial operations (overlays,...) in geofileops need the data to be in geopackage.
Hence, if the input and/or output is not ".gpkg", often extra conversions will be
happening under the hood.
Some other reasons to consider using Geopackage are listed here: 
`www.switchfromshapefile.org <http://www.switchfromshapefile.org>`_.

Most general file/layer operations can be used on all vector formats supported by
`GDAL <https://gdal.org/drivers/vector/index.html>`_ as well as on paths using
`GDAL VSI handlers <https://gdal.org/en/stable/user/virtual_file_systems.html>`_.
