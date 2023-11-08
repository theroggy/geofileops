"""
Setup file to package geofileops.
"""

import setuptools

with open("README.md") as fh:
    long_description = fh.read()

with open("geofileops/version.txt") as file:
    version = file.readline()

setuptools.setup(
    name="geofileops",
    version=version,
    author="Pieter Roggemans",
    author_email="pieter.roggemans@gmail.com",
    description="Package to do spatial operations on large geo files.",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/geofileops/geofileops",
    include_package_data=True,
    packages=setuptools.find_packages(),
    install_requires=[
        "cloudpickle",
        "fiona",
        "gdal>=3.6.3",
        "geopandas>=0.12,<0.14",
        "numpy",
        "packaging",
        "pandas",
        "psutil",
        # "pygeoops>=0.3,<0.4",
        "pygeoops==0.4.0a2",
        "pyogrio",
        "pyproj",
        "shapely>=2,<2.1",
        "topojson<2",
    ],
    extras_require={"full": ["simplification"]},
    classifiers=[
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
    ],
    python_requires=">=3.8",
)
