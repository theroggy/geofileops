
Development
===========

The source code can be found on the `GeofileOps git repositry`_.

If you want to do feature requests or file bug reports, that's the place to 
be as well.

Create development environment
------------------------------

If you don't have miniconda or anaconda installed yet, here is a link to the 
`miniconda installer`_

Then you'll need to create a new conda environment with the necessary 
dependencies::

    conda create -n geofileopsdev
    conda activate geofileopsdev
    conda config --env --add channels conda-forge
    conda config --env --set channel_priority strict
    conda install python=3.8 geopandas=0.8 psutil
    conda install pylint pytest rope pydata-sphinx-theme sphinx-automodapi

Now, if you fork the `GeofileOps git repositry`_, you should be able to run/debug the code.

.. _miniconda installer : https://conda.io/projects/conda/en/latest/user-guide/install/index.html
.. _GeofileOps git repositry : https://github.com/theroggy/geofileops