"""Example for union_full_self."""

import tempfile
from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import shapely
from figures import BLUE, GRAY, W
from shapely import MultiPoint, box

import geofileops as gfo

fig, (ax1, ax2) = plt.subplots(nrows=1, ncols=2, figsize=(W, W / 2), dpi=90)

boxes = [box(0, 0, 10, 10), box(8, 0, 18, 10), box(0, 8, 10, 18), box(8, 8, 18, 18)]
tmp_dir = Path(tempfile.gettempdir())

# Apply union_full_self
# ---------------------
poly_gdf = gpd.GeoDataFrame(geometry=boxes, crs="EPSG:31370")
poly_path = tmp_dir / "boxes.gpkg"
poly_gdf.to_file(poly_path)

union_full_path = tmp_dir / "boxes_union_full.gpkg"
gfo.union_full_self(
    input_path=poly_path,
    output_path=union_full_path,
    intersections_as="LISTS",
    force=True,
)
union_full_gdf = gpd.read_file(union_full_path)

ax1.set_title("a) input: 4 intersecting boxes")
poly_gdf.plot(ax=ax1, color=GRAY, alpha=0.3, linewidth=3, edgecolor=GRAY)
poly_gdf["geometry"].apply(lambda x: MultiPoint(shapely.get_coordinates(x))).plot(
    ax=ax1, color=GRAY, alpha=0.7
)

ax2.set_title("b) output: cut at intersection borders")
union_full_gdf.plot(ax=ax2, color=BLUE, alpha=0.5, linewidth=3, edgecolor=BLUE)
union_full_gdf["geometry"].apply(lambda x: MultiPoint(shapely.get_coordinates(x))).plot(
    ax=ax2, color=BLUE, alpha=0.7
)
union_full_gdf.apply(
    lambda x: ax2.annotate(
        text=x["nb_intersecting"],
        xy=x.geometry.representative_point().coords[0],
        ha="center",
    ),
    axis=1,
)
plt.show()
