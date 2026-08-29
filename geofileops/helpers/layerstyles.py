"""Module to save layer styles in Geopackage files."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import pandas as pd
from osgeo import gdal, ogr

from geofileops import fileops

gdal.UseExceptions()
ogr.UseExceptions()


@dataclass
class LayerStyle:
    """Class to hold information about a layer style.

    In practice, the fields map to the QGIS GeoPackage styling extension columns, but
    use Python-friendly names where possible.

    Attributes:
        id: Unique style identifier in the ``layer_styles`` table.
        table_catalog: Catalog name of the styled table (typically empty in GPKG).
        table_schema: Schema name of the styled table (typically empty in GPKG).
        layer: Name of the styled feature layer.
        geometry_column: Name of the styled geometry column.
        name: Style name as shown in QGIS.
        qml: Style definition in QML format.
        sld: Style definition in SLD format.
        use_as_default: True if this style is marked as default for the layer.
        description: Optional human-readable description.
        owner: Optional owner/author of the style.
        ui: Optional UI form/config payload.
        update_time: Last update timestamp if available.
    """

    id: int
    table_catalog: str
    table_schema: str
    layer: str
    geometry_column: str
    name: str
    qml: str
    sld: str
    use_as_default: bool
    description: str
    owner: str
    ui: str
    update_time: datetime | None = None


def get_layerstyles(
    path: Path, layer: str | None = None, name: str | None = None
) -> list[LayerStyle]:
    """Get the layer styles saved in the geofile.

    Only styles saved according to the QGIS Geopackage styling extension are read:
    https://github.com/pka/qgpkg/blob/master/qgis_geopackage_extension.md

    Args:
        path (Path): path to the geofile.
        layer (str, optional): the layer to get the styles for. If None, all styles
            regardless of the layer they belong to are returned. Defaults to None.
        name (str, optional): the name of the style to get. If None, all styles
            regardless of their name are returned. Defaults to None.

    Returns:
        list[LayerStyle]: the styles found.
    """
    if not _has_layerstyles_table(path):
        return []

    layer_styles_df = fileops.read_file(path, layer="layer_styles", fid_as_index=True)
    layer_styles_df.index.name = "id"
    if layer is not None:
        layer_styles_df = layer_styles_df.loc[layer_styles_df["f_table_name"] == layer]
    if name is not None:
        layer_styles_df = layer_styles_df.loc[layer_styles_df["styleName"] == name]

    layer_styles = [
        LayerStyle(
            id=int(row.Index),
            table_catalog=row.f_table_catalog,
            table_schema=row.f_table_schema,
            layer=row.f_table_name,
            geometry_column=row.f_geometry_column,
            name=row.styleName,
            qml=row.styleQML,
            sld=row.styleSLD,
            use_as_default=bool(row.useAsDefault),
            description=row.description,
            owner=row.owner,
            ui=row.ui,
            update_time=row.update_time.to_pydatetime()
            if not pd.isna(row.update_time)
            else None,
        )
        for row in layer_styles_df.itertuples(index=True)
    ]

    return layer_styles


def add_layerstyle(
    path: Path,
    layer: str,
    name: str,
    qml: str,
    sld: str = "",
    use_as_default: bool = False,
    description: str = "",
    owner: str = "",
    ui: str = "",
) -> None:
    """Add the layer style to the geofile.

    Remark: at the time of writing, QGIS only uses the qml field to interprete the
    style, so this field is mandatory and sld is not.

    The style is saved according to the QGIS Geopackage styling extension:
    https://github.com/pka/qgpkg/blob/master/qgis_geopackage_extension.md

    Args:
        path (Path): path to the geofile.
        layer (str): the layer the style is meant for.
        name (str): the name of the style.
        qml (str): the styling in qml format.
        sld (str, optional): the styling in sld format. Defaults to "" as it is not used
            by QGIS at the time of writing.
        use_as_default(bool, optional): True to use the style by default when opening
            the layer in QGIS.
        description (str, optional): description of the style, Defaults to "".
        owner (str, optional): owner of the style, Defaults to "".
        ui (str, optional): ui specification in ui format, Defaults to "".
    """
    # Make sure the layer_styles table exists
    _init_layerstyles(path, exist_ok=True)
    use_as_default_str = 1 if use_as_default else 0

    # Get existing layer styles
    layer_styles = get_layerstyles(path, layer=layer, name=name)

    # If the layer style already exists: error
    if len(layer_styles) > 0:
        styles_found = [
            {
                "id": layer_style.id,
                "layer": layer_style.layer,
                "name": layer_style.name,
            }
            for layer_style in layer_styles
        ]
        raise ValueError(f"layer style already exists: {styles_found}")

    # Insert style
    conn = sqlite3.connect(path)
    sql = """
        INSERT INTO layer_styles (
                id, f_table_catalog, f_table_schema, f_table_name,
                f_geometry_column, styleName, styleQML, styleSLD, useAsDefault,
                description, owner, ui
            )
            VALUES (NULL, '', '', ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    try:
        conn.execute(
            sql,
            (layer, "geom", name, qml, sld, use_as_default_str, description, owner, ui),
        )
        conn.commit()
    except Exception as ex:
        conn.rollback()
        raise Exception(f"Error {ex} executing {sql}") from ex
    finally:
        conn.close()


def remove_layerstyle(path: Path, id: int) -> None:  # noqa: A002
    """Remove a layer style.

    Only styles saved according to the QGIS Geopackage styling extension are removed:
    https://github.com/pka/qgpkg/blob/master/qgis_geopackage_extension.md

    Args:
        path (Path): path to the geo file.
        id (int): the id of the layer style to remove.
    """
    if not _has_layerstyles_table(path):
        return

    try:
        datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)

        sql = f"DELETE FROM layer_styles WHERE id = {id}"
        result = datasource.ExecuteSQL(sql, dialect="SQLITE")
        datasource.ReleaseResultSet(result)

    finally:
        datasource = None


def _has_layerstyles_table(path: Path) -> bool:
    """Check if the layer_styles table exists for the geo file specified.

    Args:
        path (Path): the path to the geofile.

    Returns:
        bool: True of the layer_styles table exists, False if not.
    """
    try:
        datasource = gdal.OpenEx(str(path))
        sql = """
            SELECT count(1) FROM sqlite_master
             WHERE name = 'layer_styles'
               AND type = 'table'
        """
        result = datasource.ExecuteSQL(sql, dialect="SQLITE")
        table_exists = result.GetNextFeature().GetField(0) == 1
        datasource.ReleaseResultSet(result)
    finally:
        datasource = None

    return table_exists


def _init_layerstyles(path: Path, exist_ok: bool = False) -> None:
    """Create a layer_styles attribute table to store style information in the QGIS way.

    The table is created according to the QGIS Geopackage styling extension:
    https://github.com/pka/qgpkg/blob/master/qgis_geopackage_extension.md

    Args:
        path (Path): the file to create the table in.
        exist_ok (bool, options): If True and the index already exists, don't
            throw an error.
    """
    try:
        # First check if it already exists
        if _has_layerstyles_table(path):
            if exist_ok:
                return
            else:
                raise ValueError(f"layer_styles table already exists in {path}")

        # Doesn't exist yet, so create the table
        datasource = gdal.OpenEx(str(path), nOpenFlags=gdal.OF_UPDATE)
        layer = datasource.CreateLayer(
            "layer_styles", geom_type=ogr.wkbNone, options=["FID=id"]
        )

        # Add the fields we're interested in
        field_name = ogr.FieldDefn("f_table_catalog", ogr.OFTString)
        field_name.SetWidth(256)
        layer.CreateField(field_name)
        field_region = ogr.FieldDefn("f_table_schema", ogr.OFTString)
        field_region.SetWidth(256)
        layer.CreateField(field_region)
        field_region = ogr.FieldDefn("f_table_name", ogr.OFTString)
        field_region.SetWidth(256)
        layer.CreateField(field_region)
        field_region = ogr.FieldDefn("f_geometry_column", ogr.OFTString)
        field_region.SetWidth(256)
        layer.CreateField(field_region)
        field_region = ogr.FieldDefn("styleName", ogr.OFTString)
        field_region.SetWidth(30)
        layer.CreateField(field_region)
        layer.CreateField(ogr.FieldDefn("styleQML", ogr.OFTString))
        layer.CreateField(ogr.FieldDefn("styleSLD", ogr.OFTString))
        layer.CreateField(ogr.FieldDefn("useAsDefault", ogr.OFSTBoolean))
        layer.CreateField(ogr.FieldDefn("description", ogr.OFTString))
        field_region = ogr.FieldDefn("owner", ogr.OFTString)
        field_region.SetWidth(30)
        layer.CreateField(field_region)
        field_region = ogr.FieldDefn("ui", ogr.OFTString)
        field_region.SetWidth(30)
        layer.CreateField(field_region)
        field_region = ogr.FieldDefn("update_time", ogr.OFTDateTime)
        field_region.SetDefault("CURRENT_TIMESTAMP")
        layer.CreateField(field_region)
    finally:
        datasource = None
        layer = None
