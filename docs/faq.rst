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
