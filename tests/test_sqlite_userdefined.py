import pytest
import shapely
from shapely import MultiPolygon, Point, Polygon
from shapely.testing import assert_geometries_equal

from geofileops.util import _sqlite_userdefined as sqlite_userdefined


def test_gfo_difference_collection():
    # Difference of polygons gives a polygon
    box0_5 = shapely.box(0, 0, 5, 5)
    box0_10 = shapely.box(0, 0, 10, 10)
    assert (
        sqlite_userdefined.gfo_difference_collection(box0_10.wkb, box0_5.wkb)
        == shapely.difference(box0_10, box0_5).wkb
    )
    # Difference of polygons gives a linestring to test -> No testcase at hand
    assert (
        sqlite_userdefined.gfo_difference_collection(
            box0_10.wkb, box0_5.wkb, keep_geom_type=1
        )
        == shapely.difference(box0_10, box0_5).wkb
    )

    # Result of the difference is None.
    assert (
        sqlite_userdefined.gfo_difference_collection(
            shapely.Point(1, 1).wkb, box0_10.wkb
        )
        is None
    )


@pytest.mark.parametrize(
    "test_id, geom, geoms_to_subtract, exp_result",
    [
        (1, None, None, None),
        (2, shapely.Point().wkb, None, shapely.Point().wkb),
        (3, shapely.Point().wkb, shapely.Point(1, 1).wkb, shapely.Point().wkb),
        (4, None, shapely.Point(1, 1).wkb, None),
        (5, None, shapely.Point(1, 1).wkb, None),
        (6, shapely.Point(1, 1).wkb, None, shapely.Point(1, 1).wkb),
        (7, shapely.Point(1, 1).wkb, shapely.Point().wkb, shapely.Point(1, 1).wkb),
    ],
)
def test_gfo_difference_collection_empty_geoms(
    test_id, geom, geoms_to_subtract, exp_result
):
    result = sqlite_userdefined.gfo_difference_collection(geom, geoms_to_subtract)
    if exp_result is None:
        assert result is None, f"Issue with test {test_id}"
    else:
        assert result == exp_result, f"Issue with test {test_id}"


def test_difference_collection_invalid_params():
    # geom_to_subtract is not a wkb
    with pytest.raises(TypeError, match="Expected bytes or string, got Point"):
        sqlite_userdefined.gfo_difference_collection(
            shapely.Point(1, 1).wkb, shapely.Point(1, 1)
        )
    # geom is not a wkb
    with pytest.raises(TypeError, match="Expected bytes or string, got Point"):
        sqlite_userdefined.gfo_difference_collection(
            shapely.Point(1, 1), shapely.Point(1, 1).wkb
        )

    # keep_geom_type should be int (0 or 1)
    with pytest.raises(TypeError, match="keep_geom_type must be int"):
        sqlite_userdefined.gfo_difference_collection(
            shapely.Point(1, 1).wkb, shapely.Point(1, 1).wkb, keep_geom_type="TRUE"
        )
    with pytest.raises(ValueError, match="keep_geom_type has invalid value"):
        sqlite_userdefined.gfo_difference_collection(
            shapely.Point(1, 1).wkb, shapely.Point(1, 1).wkb, keep_geom_type=5
        )


@pytest.mark.parametrize(
    "test_descr, geom, exp_result",
    [
        ("None", None, None),
        ("empty", Point(), Point()),
        ("point", Point(1, 1), Point(1, 1)),
        ("sliver", Polygon([(0, 0), (10, 0), (10, 0.5), (0, 0)]), None),
        (
            "poly + sliver",
            MultiPolygon(
                [
                    Polygon([(0, 5), (5, 5), (5, 10), (0, 10), (0, 5)]),
                    Polygon([(0, 0), (10, 0), (10, 0.5), (0, 0)]),
                ]
            ),
            Polygon([(0, 5), (5, 5), (5, 10), (0, 10), (0, 5)]),
        ),
    ],
)
def test_gfo_reduceprecision(test_descr, geom, exp_result):
    geom_wkb = None if geom is None else geom.wkb

    result = sqlite_userdefined.gfo_reduceprecision(geom_wkb, gridsize=1)

    result = shapely.from_wkb(result)
    if exp_result is None:
        assert result is None, f"Issue with test {test_descr}"
    else:
        # Depending on the version of geos, sometimes result is a multipolygon...
        if isinstance(exp_result, Polygon):
            exp_result = MultiPolygon([exp_result])
        if isinstance(result, Polygon):
            result = MultiPolygon([result])
        assert_geometries_equal(
            result, exp_result, normalize=True, err_msg=f"Issue with test {test_descr}"
        )
