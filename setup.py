"""Setup file to package geofileops."""

from pathlib import Path

import setuptools

with Path("README.md").open() as fh:
    long_description = fh.read()

with Path("geofileops/version.txt").open() as file:
    version = file.readline()

setuptools.setup(
    name="geofileops",
    version=version,
    author="Pieter Roggemans",
    author_email="pieter.roggemans@gmail.com",
    description="Python toolbox to process large vector files faster.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/geofileops/geofileops",
    include_package_data=True,
    packages=setuptools.find_packages(
        exclude=("tests", "benchmark", "benchmark.*"),
        include=("geofileops", "geofileops.*"),
    ),
    install_requires=[
        "cloudpickle",
        "gdal>=3.8",
        "geopandas>=0.13",
        "numpy",
        "packaging",
        "pandas>=1.5",
        "psutil",
        "pyarrow",
        "pygeoops>=0.4",
        "pyogrio>=0.8",
        "pyproj",
        "shapely>=2",
    ],
    extras_require={"full": ["simplification"]},
    classifiers=[
        "Intended Audience :: Science/Research",
        "License :: OSI Approved :: BSD License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3 :: Only",
        "Topic :: Scientific/Engineering :: GIS",
    ],
    python_requires=">=3.10",
)
