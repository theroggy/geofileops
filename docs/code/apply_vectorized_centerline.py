"""Example of applying the pygeoops centerline function to a set of polygons."""

import tempfile
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pygeoops
import shapely
from figures import BLUE, GRAY, W
from shapely import MultiPoint

import geofileops as gfo

fig, ax = plt.subplots(figsize=(W, W / 2), dpi=90)

fancy_t_poly_wkt = (
    "POLYGON ((3 0, 9 0, 7 2, 7 10, 12 10, 12 12, 0 12, 0 10, 5 10, 5 2, 3 0))"
)
tmp_dir = Path(tempfile.gettempdir())

# Just a single example
# ---------------------
poly1 = shapely.from_wkt(fancy_t_poly_wkt)
poly2 = shapely.transform(poly1, lambda x, y: (x + 15, y), interleaved=False)
poly_gdf = gpd.GeoDataFrame(geometry=[poly1, poly2], crs="EPSG:31370")
poly_path = tmp_dir / "fancy_t_polygons.gpkg"
poly_gdf.to_file(poly_path)

centerline_path = tmp_dir / "fancy_t_centerlines.gpkg"
gfo.apply_vectorized(
    input_path=poly_path,
    output_path=centerline_path,
    func=lambda geom: pygeoops.centerline(geom),
)
centerlines_gdf = gpd.read_file(centerline_path)
poly_gdf.plot(ax=ax, color=GRAY, alpha=0.3)
centerlines_gdf.plot(ax=ax, color=BLUE, alpha=0.7)
centerlines_gdf["geometry"].apply(
    lambda x: MultiPoint(shapely.get_coordinates(x))
).plot(ax=ax, color=BLUE, alpha=0.7)

plt.show()
