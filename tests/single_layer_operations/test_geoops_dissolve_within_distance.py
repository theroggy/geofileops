import shutil

import pytest

import geofileops as gfo
from tests import test_helper
from tests.test_helper import assert_geodataframe_equal


@pytest.mark.parametrize(
    "testfile, input_layer, output_layer, close_internal_gaps, force, exp_featurecount",
    [
        ("polygon-twolayers", "parcels", "output_layername", True, True, 11),
        ("polygon-parcel", None, None, False, True, 11),
        ("polygon-parcel", None, None, False, False, None),
    ],
)
def test_basic(
    tmp_path,
    testfile,
    input_layer,
    output_layer,
    close_internal_gaps,
    force,
    exp_featurecount,
):
    # Prepare test data
    input_path = test_helper.get_testfile(testfile)
    output_path = tmp_path / "output.gpkg"
    # Create an empty file to test force
    output_path.touch()

    # Test
    gfo.dissolve_within_distance(
        input_path=str(input_path),
        input_layer=input_layer,
        output_path=str(output_path),
        output_layer=output_layer,
        distance=10,
        gridsize=0.0001,
        close_internal_gaps=close_internal_gaps,
        force=force,
    )

    # Check result
    if not force:
        # If force is False, the empty output file that was created will still be there
        assert output_path.stat().st_size == 0
        return

    assert output_path.exists()
    assert output_path.stat().st_size > 0
    if output_layer is None:
        # If no layername specified, layer has the default lauer name
        assert gfo.listlayers(output_path) == [output_path.stem]
    else:
        assert gfo.listlayers(output_path) == [output_layer]
    output_info = gfo.get_layerinfo(output_path)
    assert output_info.featurecount == exp_featurecount


def test_gapfill_touches_segment(tmp_path):
    """
    The part that fills the gap between 2 polygons only touches a line segment.

    When determining the number of neighbours, this example is sensitive to having only
    one neighbour being detected for the part that filles up the gap. This is due to
    rounding issues because the gap points only touches a segment at one polygon.
    """
    # Prepare test data
    input_dir = test_helper.data_dir / "dissolve_within_distance"
    input_zip = input_dir / "gapfill_touches_segment.gpkg.zip"
    input_path = tmp_path / input_zip.stem
    shutil.unpack_archive(input_zip, input_path.parent)
    output_path = tmp_path / "output.gpkg"

    # Test
    with gfo.TempEnv({"GFO_REMOVE_TEMP_FILES": False}):
        gfo.dissolve_within_distance(
            input_path=input_path,
            output_path=output_path,
            distance=10,
            gridsize=0.001,
        )

    assert output_path.exists()
    # They should be merged, so output feature count should be 1.
    assert gfo.get_layerinfo(output_path).featurecount == 1


def test_neg_buffer_makes_smaller(tmp_path):
    """
    Polygon becomes slightly smaller due to positive and negative buffer.
    """
    # Prepare test data
    input_dir = test_helper.data_dir / "dissolve_within_distance"
    input_zip = input_dir / "neg_buffer_makes_smaller.gpkg.zip"
    input_path = tmp_path / input_zip.stem
    shutil.unpack_archive(input_zip, input_path.parent)
    output_path = tmp_path / "output.gpkg"

    # Test
    gfo.dissolve_within_distance(
        input_path=input_path, output_path=output_path, distance=10, gridsize=0.0
    )

    assert output_path.exists()
    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)

    assert_geodataframe_equal(
        input_gdf, output_gdf, normalize=True, promote_to_multi=True
    )
