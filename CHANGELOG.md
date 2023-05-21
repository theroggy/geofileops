# CHANGELOG

## 0.8.0 (???)

## Improvements

- Add support to read/add/remove embedded layer styles in gpkg (#263)
- Add `gridsize` parameter to most spatial operations (#261)
- Add `keep_empty_geoms` and `where` parameters to many single layer spatial operations
  (#262)
- Add `where` parameter to `gfo.convert` and `gfo.append_to` (#311)
- Improve performance of makevalid and isvalid (#258)
- Improve performance of spatial operations when only one batch is used (#271)
- Add checks that `output_path` must not be equal to the/an `input_path` for geo
  operations (#246)
- Follow geopandas behaviour of using shapely2 and/or pygeos instead of forcing pygeos
  (#294)
- Improve handling of "SELECT * ..." style queries in `gfo.select` and 
  `gfo.select_two_layers` (#283)
- Many small improvements to logging, documentation, error messages,...

### Bugs fixed

- Fix parameter `index` in `to_file` being ~ ignored (#285)
- Fix "json" aggregate column handling in dissolve on line and point input files gives
  wrong results (#257)

### Deprecations and compatibility notes

- `makevalid` parameter `precision` is renamed to `gridsize` as this is the typical
  terminology in other libraries (#273)
- `keep_empty_geoms` parameters are added with default value `False` for most operations
  as this was the default behaviour for those operations in the past. This will be
  changed to `True` in a future version. This is also explained in a futurewarning (#262)
- removed the long-deprecated functions `get_driver`, `get_driver_for_ext`,
  `to_multi_type` and `to_generaltypeid`  (#276)
- removed the long-deprecated `vector_util`, `geofileops.geofile` and
  `geofileops.geofileops` namespaces (#276)

## 0.7.0 (2023-03-17)

### Improvements

- Use [pyogrio](https://github.com/geopandas/pyogrio) for GeoDataFrame io to improve
  performance for operations involving GeoDataFrames (#64, #217)
- Add possibility to backup the fid in output files when applying operations (#114)
- Add support to `to_file` to write empty dataframe + add basic support for
  `force_output_geometrytype` (#205)
- Add support to `read_file` to execute sql statements (#222)
- Add function `get_layer_geometrytypes` to get a list of all geometry types that
  are actually in a layer (#230)
- Add `fid_as_index` parameter to `read_file` (#215)
- Add `force_output_geometrytype` parameter to `apply` (#233)
- Add `fid_as_index` parameter to `read_file` (#215)
- Add `force_output_geometrytype` parameter to `apply` (#233)
- Optimize performance of operations when only one batch is used (#19)
- Optimize number batches for single layer sql operations (#214)
- Add check for select operations that if nb_parallel > 1, {batch_filter} is mandatory
  in sql_stmt (#208)
- Small improvements/code cleanup (#216, #223, #240,...)

### Deprecations and compatibility notes

- When a geo operation results in an empty result, gfo now always writes an empty output
  file instead of no output. This is also the behaviour of other high level libraries
  like in the toolbox of QGIS or ArcGIS. This behaviour needs gdal version >= 3.6.3 to
  be applied consistently. (#188)
- In `read_file` the columns in the output now reflect the casing used in the parameter
  rather than the casing in the source file (#229)
- Functions `read_file_sql` and `read_file_nogeom` are deprecated in favour of
  `read_file`. Mind: in read_file the sql_dialect default is None, not "SQLITE".
  (#222, #232, #236)
- The (private) util function `view_angles` is moved to 
  [pygeoops](https://github.com/pygeoops/pygeoops) (#209)

## 0.6.4 (2023-02-15)

### Improvements

- Support geopandas 12 with shapely 2.0 + pygeos (#191, #193)
- Support improvements in gdal 3.6.2 (#195)
- Improve performance of sql-based operations for very large input files (#201)
- Small improvements to formatting, linting,... (#202)

### Deprecations and compatibility notes

- Fix: Due to a change in fiona >= 1.9, using read_file on string columns with all None
  values ended up as a float64 column (#199)
- Because geofileops uses pygeos directly, pin geopandas to < 1.0. More info: 
  [geopandas#2691](https://github.com/geopandas/geopandas/issues/2691) (#200)

## 0.6.3 (2022-12-12)

### Improvements

- Make writing to gpkg more robust in locking situations (#179)
- Add create_spatial_index parameter to to_file (#183)
- Ignore pandas futurewarning in dissolve (#184)
- Improve dissolve performance (#185)
- Small general improvements (#180)

### Bugs fixed

- Fix groupby columns in dissolve sometimes becoming all NULL values (#181)

### Deprecations and compatibility notes

- In to_file, the default behaviour is now also for .shp to create a spatial index,
  consistent with convert,... (#183)

## 0.6.2 (2022-11-14)

### Bugs fixed

- Fix regression in to_file to support append to unexisting file (#177)

## 0.6.1 (2022-11-14)

### Improvements

- Add (private) function `is_valid_reason` for GeoSeries (#164)
- Small improvements in logging, formatting, avoid deprecation warnings,...
  (#163, #166, #171)
- Add CI tests for python 3.10 and 3.11. On python 3.11 the simplification library is 
  not available (#170) 

### Bugs fixed

- Fix groupby columns in dissolve not being treated case insensitive (#162)
- Fix to_file doesn't throw an error nor saves data when appending a dataframe with
  different columns than file (#159)
- Fix ValueError: max_workers must be <= 61 in dissolve (#160)
- Fix sql_dialect parameter is ignored in select operation (#115)

## 0.6.0 (2022-08-23)

### Improvements

- Add single layer function `gfo.export_by_bounds` (#149)
- Add single layer function `gfo.clip_by_geometry` (#150)
- Add single layer function `gfo.warp` to warp geometries based on GCP's (#151)
- Add (private) function to calculate view angles from a point towards a GeoDataFrame
  (#140)
- Add (private) function to calculate topologic simplify (#146)
- Small changes to support geopandas 0.11+, newer pandas versions,... (#143, #147, #153)

### Bugs fixed

- Fix typo in hardcoded 31370 custom prj string (#142)

## 0.5.0 (2022-06-08)

The main improvements in this version are the geo operations `gfo.clip` and
`gfo.symmetric_difference` that were added.

### Improvements

- Add `gfo.clip` geo operation, more info [here](https://geofileops.readthedocs.io/en/latest/api/geofileops.clip.html) (#4)
- Add `gfo.symmetric_difference` geo operation, more info [here](https://geofileops.readthedocs.io/en/latest/api/geofileops.symmetric_difference.html) (#85)
- Add support for all relevant spatial operations to join_by_location (#79)
- In `gfo.dissolve`, support aggregations on a groupby column and None data in aggregation columns (#130)
- Add support to reproject to `gfo.convert` (#89)
- Add function `gfo.drop_column` (#92)
- Add detailed column info in `gfo.get_layerinfo` (#110)
- Add support to specify (any) gdal options in relevant fileops (#83)
- Add support to write an attribute table (=no geometry column) to geopackage (#125)
- Don't list attribute tables in e.g. `gfo.listlayers` by default anymore (#124)
- Speed up creation of an index on a geopackage (#87)
- Add `view_angles` function for geometries, geoseries (#136)
- Some improvements to the benchmarks
- Use black to comply to pep8 + minor general improvements (#113)

### Bugs fixed

- Fix dissolve bugs (#93)
    - When `agg_columns="json"` is used and the dissolve needs multiple passes, 
      the json output is not correct.
    - when combining tiled output with `explodecollections=False`, the output 
      is still ~exploded.
- For e.g. `gfo.intersection` some attribute data is NULL if output format is .shp
  (#102)
- `gfo.dissolve` gives error if a linestring input layer contains special characters
  (#108)

### Deprecations and compatibility notes

- Property column of `gfo.get_layerinfo` is now a Dict[str, ColumnInfo] instead of a 
  List[str] (#110)
- For the simplify operation, use rdp version that preserves topology (#105)
- Removed redundant `verbose` parameter in all functions (#133)
- Attribute tables are not listed anymore by default in e.g. `gfo.listlayers` (#124)
- Rename some files in util that are rather private (#84)
- Remove long-time deprecated `clip_on_tiles` parameter in `gfo.dissolve` (#95)
- Deprecate `gfo.intersect` for new name `gfo.intersection` to be 
  consistent with most other libraries. Now a warning is given, in the future 
  `gfo.intersect` will be removed (#99).

## 0.4.0 (2022-03-31)

The main new features in this version are the simplified API, a new geo operation
"apply" and dissolve supporting aggregations on columns now.

### Improvements

- Add apply geo operation. Info on how to use it can be found [here](https://geofileops.readthedocs.io/en/latest/api/geofileops.apply.html#geofileops.apply) (#41)
- Add support for different aggregations on columns in dissolve operation. Info on how to use it can be found [here](https://geofileops.readthedocs.io/en/latest/api/geofileops.dissolve.html#geofileops.dissolve) (#3)
- Simplify API by removing the seperation in geofile versus geofileops (#52)
- Improve type annotations and documentation
- Increase test coverage, including tests on latlon files which weren't available yet
  (#32)
- Improve performance of buffer, simplify and complexhull by using the spatialite/sql
  implementation (#53)
- Improve benchmarks, eg. add graphs,... (#55)
- Improve performance of _harmonize_to_multitype + improve test (#56)

### Bugs fixed

- In the two-layer operations, in some cases columns could get "lost" in the output file (#67)

### Deprecations and compatibility notes

- Breaking change: in `gfo.dissolve`, the parameters `aggfunc` and `columns` are
  replaced by `agg_columns`. More info on the usage can be found
  [here](https://geofileops.readthedocs.io/en/latest/api/geofileops.dissolve.html#geofileops.dissolve).
- Due to flattening the API, using `from geofileops import geofile` and
  `from geofileops import geofileops` is deprecated, and you should use eg.
  `import geofileops as gfo`. A "FutureWarning" is shown now, in a future version this
  possibility will probably be removed.
- The following functions are deprecated. A "FutureWarning" is shown now, in a future
  version this function they will be removed: 
    - `gfo.get_driver(path)` can be replaced by `GeofileType(Path(path)).ogrdriver`.
    - `get_driver_for_ext(file_ext: str)` can be replaced by `GeofileType(file_ext).ogrdriver`.
    - `gfo.to_multi_type(geometrytypename: str)` can be replaced by `GeometryType(geometrytypename).to_multitype`.  
    - `gfo.to_generaltypeid(geometrytypename: str)` can be replaced by `GeometryType(geometrytypename).to_primitivetype.value`.

## 0.3.1 (2022-02-02)

Several improvements and fixes. Especially if you process large files (> 5 GB) some of
them will be very useful.

### Improvements

- Add options to choose the buffer style to use (#37).
- Add option in makevalid to specify precision to use.
- Add support for dissolve with groupby_columns=None + explodecollections=True
- add batchsize parameter to all geo operations to be able to limit memory usage if
  needed (#38).
- Decrease memory usage for most operations.
- Run processing in low CPU priority so the computer stays responding.

### Bugs fixed

- Fix error when processing very large files for buffer, convexhull, dissolve and
  simplify (IO timeouts).
- Fix error in simplify when points on geometries should be kept.
- Don't give an error when result is empty for sql based operations.
- Explodecollections=True doesn't work on operations on 2 layers.

## 0.3.0 (2021-06-18)

In this release, the main change is a new operation that has been added: nearest_join.

### Improvements

- New operation nearest_join() (#12).
- Improve performance for files where the rowid isn't consecutive (#14).
- Improve documentation, mainly for the select operations.
- Add check in get_layerinfo on column names containing illegal characters (='"').
- Suppress fiona warning "Sequential read of iterator was interrupted."
- Dissolve: output is sorted by a geohash instead of random, which 
  improves performance when reading the file afterwards.

### Changes that break backwards compatibility

- Drop support for spatialite < 5 and geopandas < 0.9.
- Bugfix: for the dissolve operation, when rows in the groupby columns 
  contained NULL/None/NaN values, those rows were dropped. This is the 
  default behaviour of (geo)pandas, but as the behaviour doesn't feel 
  very intuitive, it was decided to divert from it.  

## 0.2.2 (2021-05-05)

Improved performance for all operations that involve overlays between 2 layers 
(intersect, union, split,...).

### Improvements

- Improved performance for all operations that involve overlays between 2 
  layers (intersect, union, split,...). Especially if the input files are in 
  Geopackage format the improvement should be significant because in this case 
  the input data isn't copied to temp files anymore.
- Added the method geofile.execute_sql() to be able to execute a DML/DDL sql 
  statement to a geofile.
- Smaller code cleanups to improve readability on several places.

### Bugs fixed

- In the split and union operations, in some cases (mainly when input layers 
  had self-intersections) intersections in the output were unioned instead of 
  keeping them as seperate rows.
- When using an input file with multiple layers (eg. a geopackage), this 
  sometimes resulted in data errors. 
- Fix an error in the lang simplification algorithm that occured in some edge 
  cases.

## 0.2.1 (2021-04-10)

This release mainly brings improvements and bugfixes when using the Lang 
simplification algorithm.

Additionally, this is the first version that gets a conda package.

### Improvements

- Support for all geometry types for Lang simplification
- Some code restructuring + code cleanup in util (backwards compatible for now, but
  isn't public interface anyway)
- Improve test coverage

### Bugs fixed

- preserve_topology wsn't always respected in Lang simplification
- clip_on_tiles=False in dissolve resulted in some polygons not being 
  dissolved. Because there is no easy solution, parameter is deprecated 
  and always treated as True.

## 0.2.0 (2021-02-15)

This release is mainly focused on improvements to the dissolve and simplify 
operations. 

It is important to note that for the dissolve operation the default parameters 
behave slightly different, so the change is not backwards compatible!

### Most important changes

- Dissolve
    - Different handling of default parameters (not backwards compatible!)
    - Better performance
    - Several bugfixes
- Simplify: add support for different simplification algorythms: 
  ramer-douglas-peucker, visvalingam-whyatt and lang.
- Many improvements to documentation
- Improvements to type annotations
- Some new undocumented (so use at own risk!) functions were added to 
  geofileops.vector_util. 
    - simplify_ext: an "extended" simplify function:
        - Supports multiple simplification algorythms: ramer-douglas-peucker, 
          visvalingam-whyatt and lang.
        - Option to specify a "points-to-keep geometry": points/nodes of the 
          geometries to be simplified that intersect it won't be removed by 
          the simplify operation.
    - count_number_points: count the number of coordinates that any shapely 
      geometry consists of

## 0.1.1 (2020-11-23)

This version contains quite some fixes and small improvements. The most 
important ones are listed here.

### Improvements

- Stop using sqlite WAL output format as default: gives locking issues when 
  using files on a file share
- Improve handling of output geometry type
- Add scripts, dependencies,... to use pytest-cov to report unit test coverage 
- Add first version of sphynx documentation
- Improve test coverage
- Improve benchmark tests

### Bugs fixed

- Negative buffer shouldn't output rows with empty geometries
- Dissolve gave an error in some specific cases 
- Join_by_location operation gave wrong results

## 0.1.0 (2020-11-05)

Most typical operations are now supported: buffer, simplify, 
export_by_location, intersect, union, erase, dissolve,...
