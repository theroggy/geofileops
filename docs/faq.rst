
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
