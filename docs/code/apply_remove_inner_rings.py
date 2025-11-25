"""Example of applying the pygeoops remove_inner_rings function to a polygon."""

import tempfile
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import pygeoops
import shapely
from figures import BLUE, GRAY, W
from shapely import MultiPoint

import geofileops as gfo

fig, (ax1, ax2) = plt.subplots(nrows=1, ncols=2, figsize=(W, W / 2), dpi=90)

polygon_small_island = shapely.Polygon(
    shell=[(40, 40), (40, 50), (50, 50), (50, 40), (40, 40)],
    holes=[
        [(42, 42), (42, 43), (43, 43), (43, 42), (42, 42)],
        [(45, 45), (45, 48), (48, 48), (48, 45), (45, 45)],
    ],
)
tmp_dir = Path(tempfile.gettempdir())

# Apply remove_inner_rings
# ------------------------
poly_gdf = gpd.GeoDataFrame(geometry=[polygon_small_island], crs="EPSG:31370")
poly_path = tmp_dir / "polygon_small_island.gpkg"
poly_gdf.to_file(poly_path)

removed_path = tmp_dir / "polygon_small_island_removed.gpkg"
gfo.apply(
    input_path=poly_path,
    output_path=removed_path,
    func=lambda geom: pygeoops.remove_inner_rings(geom, min_area_to_keep=1, crs=None),
    force=True,
)
removed_gdf = gpd.read_file(removed_path)

ax1.set_title("a) input: 2 inner rings")
poly_gdf.plot(ax=ax1, color=GRAY, alpha=0.5, linewidth=3, edgecolor=GRAY)
poly_gdf["geometry"].apply(lambda x: MultiPoint(shapely.get_coordinates(x))).plot(
    ax=ax1, color=GRAY, alpha=0.7
)

ax2.set_title("b) output: small inner ring removed")
removed_gdf.plot(ax=ax2, color=BLUE, alpha=0.5, linewidth=3, edgecolor=BLUE)
removed_gdf["geometry"].apply(lambda x: MultiPoint(shapely.get_coordinates(x))).plot(
    ax=ax2, color=BLUE, alpha=0.7
)

plt.show()
