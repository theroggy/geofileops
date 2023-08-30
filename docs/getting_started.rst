
===============
Getting started
===============

Installation
------------
geofileops is written in python, but it relies on several other libraries that 
have dependencies written in C. Those C dependencies can be difficult to 
install, but luckily the conda package management system also gives an easy 
alternative.

The easy way
------------
If you don't have conda installed yet, you can install it using the
`miniforge installer`_.

Now start the conda prompt and create a new conda environment with the following
commands: ::

    conda create -n geo
    conda activate geo


If you use e.g. anaconda or miniconda instead of a miniforge installation, also run
following commands to specify that all depencencies should be installed from the
conda-forge channel. Mixing packages from multiple channels is bound to give problems
sooner or later: ::

    conda config --env --add channels conda-forge
    conda config --env --set channel_priority strict


Finally, you can install geofileops: ::

    conda install python=3.10 geofileops


The hard way
------------
If you are not able/willing to use conda to install the dependencies, please
follow the instructions to `install GeoPandas`_.

Afterwards you can install geofileops with pip.

.. _miniforge installer : https://github.com/conda-forge/miniforge#miniforge3
.. _install GeoPandas : https://geopandas.org/install.html
