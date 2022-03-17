import setuptools

with open('README.md', 'r') as fh:
    long_description = fh.read()

with open('geofileops/version.txt', mode='r') as file:
    version = file.readline()

setuptools.setup(
    name='geofileops', 
    version=version,
    author='Pieter Roggemans',
    author_email='pieter.roggemans@gmail.com',
    description='Package to do spatial operations on geo files.',
    long_description=long_description,
    long_description_content_type='text/markdown',
    url='https://github.com/geofileops/geofileops',
    include_package_data=True,
    packages=setuptools.find_packages(),
    install_requires=['cloudpickle', 'geopandas>=0.10', 'pygeos', 'pyproj', 'psutil'],
    extras_require = {
        'full': ['simplification']
    },
    classifiers=[
        'Programming Language :: Python :: 3',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.8',
)