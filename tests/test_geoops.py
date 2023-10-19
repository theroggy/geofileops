import pytest

import geofileops as gfo
from tests import test_helper


@pytest.mark.parametrize(
    "testfile, input_layer, output_layer, close_internal_gaps, force, "
    "exp_featurecount",
    [
        ("polygon-twolayers", "parcels", "output_layername", True, True, 10),
        ("polygon-parcel", None, None, False, True, 11),
        ("polygon-parcel", None, None, False, False, None),
    ],
)
def test_dissolve_within_distance(
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
        input_path=input_path,
        input_layer=input_layer,
        output_path=output_path,
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
