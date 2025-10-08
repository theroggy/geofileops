# CHANGELOG

## 0.11.0 (yyyy-mm-dd)

### Deprecations and compatibility notes

- Minimum version of dependencies updated to spatialite 5.1.

### Improvements

- Add `concat` function (#746, #747)
- Add `write_mode="append_add_fields"` option to `copy_layer` (#750)
- Add `zip_geofile` and `unzip_geofile` functions (#754, #743)
- Add support for ".gpkg.zip" and ".shp.zip" input and output files for geo operations
  (#754)
- Improve performance of clip with a complex clip layer (#740)
- Improve performance of most operations by using a direct gpkg to gpkg append via
  sqlite where possible (#728)
- Improve performance of the subdividividing used in many operations (#730)
- Improve performance of `dissolve` (#748)
- Improve performance of two-layer operations using `nb_parallel=1` (#692)
- Alternative query for clip + default subdivide_coords to 15000 (#450)
- Ensure that the featurecount is properly cached in GPKG files, also for older GDAL
  versions + small refactor (#693)
- Add checks on invalid values in `ConfigOptions` (#711)
- Add worker_type used to progress logging (#715)
- Write gdal log files to `GFO_TMPDIR` if specified (#727)
- Reduce memory being committed on hardware with many cores (#739, #717)

### Bugs fixed

- `copy_layer` should give an error if `src_layer` is not specified for multi-layer src
  files (#745)

## 0.10.2 (2025-08-20)

### Improvements

- Improve performance of `makevalid` by using `apply_vectorized` under the hood (#713)
- Support to specify the directory used by geofileops to put temporary files via an
  environment variable (GFO_TMPDIR) (#707)

### Bugs fixed

- Disable arrow in `gdal.VectorTranslate` to avoid random crashes (#714)
- Fix `copy_file` for some special vsi cases (#703)
- Fix handling `None` values for environment variables in the `gfo.TempEnv` context
  manager (#710)

## 0.10.1 (2025-05-16)

### Deprecations and compatibility notes

- Add warning when the GFO_IO_ENGINE configuration option is used with engine "fiona"
  that this is deprecated and will be removed/ignored in a future version (#688, #701)

### Improvements

- Don't pin maximum versions of dependencies for e.g. geopandas, shapely, pyogrio (#685)

### Bugs fixed

- Don't throw error when running `create_spatial_index` on a read-only file if the index
  exists already (#686)
- Fix `join_by_location` when using "contains" (#694)
- Fix that on some input files spatial operations take significant time, even though
  the output exists already and `force=False` (#696)

## 0.10.0 (2025-03-26)

### Deprecations and compatibility notes

- Worker processes are now being created using "forkserver" on linux. This solves risks
  of deadlocks and the corresponding warning for that. Consequence is that also on linux
  the `if __name__ == "__main__":` construct needs to be used in scripts. Some more info
  can be found in the geofileops FAQ (#675).
- `erase` was renamed to `difference`, as most other open source applications/libraries
  use this terminology. `erase` just keeps existing for backwards compatibility for now,
  but a warning is shown that it might be removed in the (distant) future. (#595)
- In `copy_layer` and `append_to` the default `dst_layer` was, contrary to the
  documentation, not the stem of the destination filename. This is corrected now. (#648)
- In `copy_layer`, the `append` parameter is deprecated and replaced by the `write_mode`
  parameter that accepts e.g. "append" as value (#663).
- The `append_to` function is deprecated, as it is almost identical to `copy_layer` with
  `write_mode="append"` (#669).

### Improvements

- Add function `apply_vectorized` to apply a vectorized function on a geometry column
  and use it internally where possible (#588, #594)
- Improve performance of `erase` and `intersection` for very complex input geometries.
  This gives similar improvements for such datasets to `identity`,
  `symmetric_difference` and `union`. (#585, #601, #591, #614)
- Improve performance of `export_by_location` and `join_by_location` for simple queries
  (#548)
- Add support for `query=""` in `export_by_location` (#597)
- Add support for GDAL vsi handlers in paths in most general file/layer operations (#669)
- Add basic support for ".gpkg.zip" and ".shp.zip" files in most general file/layer
  operations (#673)
- Add support to rename columns and layers with only a difference in casing (#549, #593)
- Use `ST_Equals` and add priority feature to `delete_duplicate_geometries` (#638)
- Avoid integer overflow when gpkg written by geofileops is read from .NET (#612)
- Speed up processing many small files, mainly on windows:
    - reduce calls to `gdal.OpenEx` (#622, #625, #677)
    - improvements in sqlite3 code for 2 layer operations: start transactions
      explicitly, remove obsolete GPKG triggers, use a :memory: temp file where possible
      (#626, #628, #630)
- Add support to pass a single string for all `column` type parameters if a single
  column should be retained (#523)
- Enable "CURVE" geometrytype files to be processed in the general file and
  layer operations (#558)
- Replace `append` parameter by `write_mode` in `copy_file` (#663)
- Don't convert to multi-part geometries by default in `copy_layer`,... (#570)
- In `add_column`, don't add column if update expression is invalid (#650)
- Add configuration option to only warn on dissolve errors (#561)
- For `dissolve`, apply `grid_size` within `union_all` (#566)
- Add some pre-flight checks when geofileops is imported (#573, #627)
- For `select_two_layers`, add the `gpkg_ogr_contents` table + fill out extents in the
  `gpkg_contents` table in the output file (#647)
- When using join_nearest with spatialite version >= 5.1,
  show ST_distance between the two geometries instead of 
  the distance between the centroid of the two geometries (#634)

### Bugs fixed

- Fix `copy_layer` to a gpkg.zip file (#604)
- Fix GDAL input open options being ignored in `copy_layer` (#632)
- Fix `missing_ok` parameter in `remove` being ~ignored (#605)
- Fix `dissolve` with `agg_columns` on sqlite 3.49.1 (#636)
- Fix an invalid output .gpkg file being created when e.g. `copy_layer` is ran with an
  invalid sql statement (#641)
- Fix wrong results for `export_by_location` with queries != "intersects is True" (#617)
- Fix listlayers returns layer name for a non-existing .shp (#672)

## 0.9.1 (2024-07-18)

### Bugs fixed

- For `dissolve`, `agg_columns` aggregations sometimes give wrong results (#541)

## 0.9.0 (2024-05-26)

### Deprecations and compatibility notes

- Set the default value of `keep_empty_geoms` to `False` for all standard operations.
  This changes the default for `make_valid` and in some cases for `simplify`. The only
  exception is `select`, where the default stays `True`. (#472, #499)
- Up to now, geofileops always tried to create spatial indexes on output files. For some
  formats this has disadvantages thought. Hence, and for consistency, from now on the
  default behaviour regarding spatial index creation of GDAL will be followed. E.g.
  default a spatial index for "GPKG", but no index for "ESRI Shapefile". (#511)
- The default filter clause for `export_by_location` is now "intersects is True" while 
  in previous versions it was "intersects is True and touches is False", to be in line with `join_by_location`, other libraries and use for non-polygon data. (#508)
- When `join_by_location` was applied, a column "spatial_relation" with the spatial
  relation between the geometries was added. This is no longer the case. (#475)

### Improvements

- Add support for self-overlays in overlay operations (#468)
- Add support for a spatial query in `export_by_location` (#508)
- Improve `dissolve_within_distance` results (#494)
- Improve performance of `join_by_location` for relation "intersects is True" and for 
  complex polygon features in layer to compare with (#502, #519)
- Improve handling of queries evaluating to True for disjoint features in
  `join_by_location` (#509)
- Make fiona an optional depencency (#301)
- Add configuration option GFO_REMOVE_TEMP_FILES that can be used to avoid temp files
  being removed for debugging purposes (#480)
- Add a context manager, TempEnv, to set temporary env variables (#481)
- Don't copy both input files if only one is not spatialite based in two layer
  operations (#247)
- If an output_dir doesn't exist yet, avoid processing being done before an error is
  raised. (#518)
- Small changes to support geopandas 1.0 (#529)
- Linting improvements: ruff version to 0.4.4 + apply import sorting (#531)

## 0.8.2 (2024-05-25)

### Improvements

- Small changes to support gdal 3.9 (#528)
- Several improvements to documentation: new FAQ, improved user guide,...
  (#465, #469, #474)
- Linting improvements: use mypy + use ruff-format instead of black for formatting
  (#478, #479)

### Bugs fixed

- Fix crash when using e.g. `erase` with `gridsize <> 0.0` specified on input file
  containing an EMPTY geometry (#470)
- Fix `dissolve` possibly having EMPTY geometries as output if `gridsize <> 0.0` (#473)
- Fix wrong results from `join_by_location` if ran on result of `join_by_location`
  with `column_prefixes=""` (#475)
- Fix error in two layer operations if equal column aliases used based on a constant or
  a function result (#477)
- Fix `erase` (and depending two layer operations like `union`,...) giving wrong results
  if `subdivide_coords` < 1 (#489)
- Fix two-layer operations with `gridsize` sometimes outputting NULL geometries (#495)

## 0.8.1 (2024-01-13)

### Bugs fixed

- Fix error in `erase` if `erase_path` countains multiple layers (#451)
- Fix error in `dissolve` on polygon input if a pass that is not the last one has 0 
  onborder polygons in its result (#459, #461)
- Fix `groupby` parameter becoming case sensitive in `dissolve` when `agg_columns` is
  also specified (#462)

## 0.8.0 (2023-11-24)

### Improvements

- Add support to read/add/remove embedded layer styles in gpkg (#263)
- Add `gridsize` parameter to most spatial operations (#261, #407, #413)
- Add `keep_empty_geoms` and `where_post` parameters to many single layer spatial operations
  (#262, #398)
- Add `where_post` parameter to many two layer spatial operations (#312)
- Add `columns`, `sql` and `where` parameters to `copy_layer` and `append_to` (#311, #432)
- Add `dissolve_within_distance` operation (#409)
- Add support for lang+ algorithm in `simplify` (#334)
- Add support to use `select` and `select_two_layers` on attribute tables (= tables
  without geometry column) and/or have an attribute table as result (#322, #379)
- Add support to process all file types supported by gdal in most general file and layer
  operations, e.g. `get_layerinfo`, `read_file`,... (#402)
- Add support for files with Z/M dimensions in the general file and layer operations (#369)
- Add support for spatialite 5.1 in `join_nearest` (#412)
- Improve performance of `makevalid` and `isvalid` (#258)
- Improve performance of `intersection`, 30% faster for typical data, up to 4x faster
  for large input geometries (#340, #358)
- Improve performance of `clip`: 3x faster for typical data (#358)
- Improve performance of `export_by_location`, especially when `area_inters_column_name`
  and `min_area_intersect` are `None`: a lot faster + 10x less memory usage (#370)
- Improve performance of `erase`, `identity`, `symmetric difference` and `union` by
  applying on-the-fly subdividing of complex geometries to speed up processing. The new
  parameter `subdivide_coords` can be used to control the feature. For files with very
  large input geometries, up to 100x faster + 10x less memory usage.
  (#329, #330, #331, #357, #396, #427, #438, #446)
- Improve performance of spatial operations when only one batch is used (#271)
- Improve performance of single layer operations (#375)
- Improve performance of some geopandas/shapely based operations (#342, #408)
- Add checks that `output_path` must not be equal to the/an `input_path` for geo
  operations (#246)
- Follow geopandas behaviour of using shapely2 and/or pygeos instead of forcing pygeos
  (#294)
- Improve handling of "SELECT * ..." style queries in `select` and `select_two_layers`
  (#283)
- Improve handling + tests regarding empty input layers/NULL geometries (#320)
- Improve logging: use geo operation being executed as `logger name` (#410)
- Many small improvements to logging, documentation, (gdal)error messages,...
  (#321, #366, #394, #439,...)
- Use smaller footprint conda packages for tests (use `geopandas-base`, `nomkl`) (#377)
- Use ruff instead of flake8 for linting (#317)

### Bugs fixed

- Fix parameter `index` in `to_file` being ~ ignored (#285)
- Fix `fid` column in output having only null values in e.g. `union` (#362)
- Fix "json" aggregate column handling in dissolve on line and point input files gives
  wrong results (#257)
- Fix error in `read_file` when `read_geometry=False` and `columns` specified (#393)
- Fix error in `copy_layer`/`convert` with `explodecollections` on some input files
  (#395)
- Fix dissolve forcing output to wrong geometrytype in some cases (#424)

### Deprecations and compatibility notes

- Drop support for shapely1 (#329, #338)
- Parameter `precision` of `makevalid` is renamed to `gridsize` as this is the typical
  terminology in other libraries (#273)
- When `join_nearest` is used with spatialite, >= 5.1, two additional mandatory
  parameters need to be specified: `distance` and `expand` (#412)
- Parameter `area_inters_column_name` in `export_by_location` now defaults to `None`
  instead of "area_inters" (#370)
- Deprecate `convert` and rename to `copy_layer` (#310)
- Deprecate `split` and rename to `identity` (#397)
- Deprecate `is_geofile` and `is_geofile_ext` (#402)
- Make the `GeofileType` enum private, in preparation of probably removing it later on
  (#402)
- Remove the long-deprecated functions `get_driver_for_ext`, `to_multi_type` and
  `to_generaltypeid`  (#276)
- Remove the long-deprecated `vector_util`, `geofileops.geofile` and
  `geofileops.geofileops` namespaces (#276)
- Remove `geometry_util`, `geoseries_util` and `grid_util` (#339):
   - Most functions were moved to `pygeoops` because they are generally reusable.
   - Remaining functions are moved either to `_geometry_util` or `_geoseries_util` to
     make it clearer they are not public.
 
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
- Preserve `fid` values in single layer operations when possible (#)
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
(intersect, union, identity/split,...).

### Improvements

- Improved performance for all operations that involve overlays between 2 
  layers (intersect, union, identity/split,...). Especially if the input files are in 
  Geopackage format the improvement should be significant because in this case 
  the input data isn't copied to temp files anymore.
- Added the method geofile.execute_sql() to be able to execute a DML/DDL sql 
  statement to a geofile.
- Smaller code cleanups to improve readability on several places.

### Bugs fixed

- In the identity/split and union operations, in some cases (mainly when input layers 
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
