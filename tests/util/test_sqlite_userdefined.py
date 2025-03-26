import pytest
import shapely
import shapely.ops
from shapely import MultiPolygon, Point, Polygon
from shapely.testing import assert_geometries_equal

from geofileops.util import _sqlite_userdefined


def test_gfo_difference_collection():
    # Difference of polygons gives a polygon
    box0_5 = shapely.box(0, 0, 5, 5)
    box0_10 = shapely.box(0, 0, 10, 10)
    assert (
        _sqlite_userdefined.gfo_difference_collection(box0_10.wkb, box0_5.wkb)
        == shapely.difference(box0_10, box0_5).wkb
    )
    # Difference of polygons gives a linestring to test -> No testcase at hand
    assert (
        _sqlite_userdefined.gfo_difference_collection(
            box0_10.wkb, box0_5.wkb, keep_geom_type=1
        )
        == shapely.difference(box0_10, box0_5).wkb
    )

    # Result of the difference is None.
    assert (
        _sqlite_userdefined.gfo_difference_collection(
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
    result = _sqlite_userdefined.gfo_difference_collection(geom, geoms_to_subtract)
    if exp_result is None:
        assert result is None, f"Issue with test {test_id}"
    else:
        assert result == exp_result, f"Issue with test {test_id}"


def test_gfo_difference_collection_invalid_params():
    # geom_to_subtract is not a wkb
    with pytest.raises(TypeError, match="Expected bytes or string, got Point"):
        _sqlite_userdefined.gfo_difference_collection(
            shapely.Point(1, 1).wkb, shapely.Point(1, 1)
        )
    # geom is not a wkb
    with pytest.raises(TypeError, match="Expected bytes or string, got Point"):
        _sqlite_userdefined.gfo_difference_collection(
            shapely.Point(1, 1), shapely.Point(1, 1).wkb
        )

    # keep_geom_type should be int (0 or 1)
    with pytest.raises(TypeError, match="keep_geom_type must be int"):
        _sqlite_userdefined.gfo_difference_collection(
            shapely.Point(1, 1).wkb, shapely.Point(1, 1).wkb, keep_geom_type="TRUE"
        )
    with pytest.raises(ValueError, match="keep_geom_type has invalid value"):
        _sqlite_userdefined.gfo_difference_collection(
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
    # Prepare test data
    geom_wkb = None if geom is None else geom.wkb

    # Run test
    result_wkb = _sqlite_userdefined.gfo_reduceprecision(geom_wkb, gridsize=1)

    # Check result
    result = shapely.from_wkb(result_wkb)
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


@pytest.mark.parametrize("test", ["poly", "multipoly", "None"])
def test_gfo_split(test):
    box1_4 = shapely.box(1, 0, 4, 4)
    blade = shapely.LineString([(0, 2), (11, 2)])

    if test == "poly":
        # Split of polygon with linestring blade gives collection of polygons
        result = shapely.from_wkb(_sqlite_userdefined.gfo_split(box1_4.wkb, blade.wkb))
        assert result == shapely.ops.split(box1_4, blade)

    elif test == "multipoly":
        # Split of multipolygon
        box5_9 = shapely.box(5, 0, 9, 4)
        multipoly = MultiPolygon([box1_4, box5_9])
        result = shapely.from_wkb(
            _sqlite_userdefined.gfo_split(multipoly.wkb, blade.wkb)
        )
        expected_result = """
            GEOMETRYCOLLECTION (POLYGON ((4 2, 4 0, 1 0, 1 2, 4 2)),
            POLYGON ((1 2, 1 4, 4 4, 4 2, 1 2)),
            POLYGON ((9 2, 9 0, 5 0, 5 2, 9 2)),
            POLYGON ((5 2, 5 4, 9 4, 9 2, 5 2)))
        """
        expected_result = shapely.from_wkt(expected_result)
        assert result == expected_result

    elif test == "None":
        # Result of splitting None is None.
        assert _sqlite_userdefined.gfo_split(None, blade) is None

    else:
        raise ValueError(f"test not implemented: {test}")


@pytest.mark.parametrize(
    "test_id, geom, blade, exp_result",
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
def test_gfo_split_empty_geoms(test_id, geom, blade, exp_result):
    result = _sqlite_userdefined.gfo_split(geom, blade)
    if exp_result is None:
        assert result is None, f"Issue with test {test_id}"
    else:
        assert result == exp_result, f"Issue with test {test_id}"


@pytest.mark.parametrize(
    "test_descr, geom, subdivide_coords, exp_result",
    [
        ("None", None, 3, None),
        ("empty", Point(), 3, Point()),
        ("point", Point(1, 1), 3, Point(1, 1)),
        (
            "poly",
            Polygon([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]),
            3,
            shapely.GeometryCollection(
                [
                    Polygon([(0, 0), (0, 10), (5, 10), (5, 0), (0, 0)]),
                    Polygon([(5, 0), (5, 10), (10, 10), (10, 0), (5, 0)]),
                ]
            ),
        ),
        (
            "poly_nodivide",
            Polygon([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]),
            0,
            Polygon([(0, 0), (10, 0), (10, 10), (0, 10), (0, 0)]),
        ),
    ],
)
def test_gfo_subdivide(test_descr, geom, subdivide_coords, exp_result):
    # Prepare test data
    geom_wkb = None if geom is None else geom.wkb

    # Test
    result_wkb = _sqlite_userdefined.gfo_subdivide(geom_wkb, coords=subdivide_coords)

    # Check result
    result = shapely.from_wkb(result_wkb)
    if exp_result is None:
        assert result is None, f"test {test_descr} failed"
        return

    assert_geometries_equal(
        result, exp_result, normalize=True, err_msg=f"test {test_descr} failed"
    )
