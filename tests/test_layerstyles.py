"""
Tests for functionalities in helpers.layer_styles.
"""

import pytest

import geofileops as gfo
from geofileops.helpers import layerstyles
from tests import test_helper


def test_has_layerstyles_table(tmp_path):
    test_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)

    assert not layerstyles._has_layerstyles_table(test_path)
    layerstyles._init_layerstyles(test_path)
    assert layerstyles._has_layerstyles_table(test_path)


def test_add_get_remove_layer_styles(tmp_path):
    test_path = test_helper.get_testfile("polygon-parcel", dst_dir=tmp_path)

    assert not layerstyles._has_layerstyles_table(test_path)
    layerstyles._init_layerstyles(test_path)
    assert layerstyles._has_layerstyles_table(test_path)

    # Add layer style to "parcel" layer
    with open(test_helper.data_dir / "polygonstyle.sld") as file:
        sld = file.read()
    with open(test_helper.data_dir / "polygonstyle.qml") as file:
        qml = file.read()
    gfo.add_layerstyle(
        path=test_path,
        layer="parcels",
        name="test_style",
        sld=sld,
        qml=qml,
        use_as_default=True,
    )
    layerstyles_df = gfo.get_layerstyles(test_path)
    assert len(layerstyles_df) == 1

    # Adding the same style again should give an error
    with pytest.raises(ValueError, match="layer style already exists: "):
        gfo.add_layerstyle(
            path=test_path, layer="parcels", name="test_style", qml="test_qml"
        )

    # Backup the styled file to be a able to check it manually in QGIS
    styled_path = tmp_path / f"{test_path.stem}_styled{test_path.suffix}"
    gfo.copy(src=test_path, dst=styled_path)

    # Remove the style again
    gfo.remove_layerstyle(test_path, id=1)
    layerstyles_df = gfo.get_layerstyles(test_path)
    assert len(layerstyles_df) == 0

    # Removing a style that doesn't exist is OK
    gfo.remove_layerstyle(test_path, id=1)
