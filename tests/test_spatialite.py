# -*- coding: utf-8 -*-
"""
Tests for functionalities in ogr_util.
"""

import pytest

import geofileops as gfo
from tests import test_helper


@pytest.mark.skipif(
    not test_helper.RUNS_LOCAL,
    reason="Don't this run on CI: just to followup odd behaviour in spatialite.",
)
def test_st_difference_null(tmp_path):
    """
    ST_difference returns NULL when 2nd argument is NULL, which is odd.

    In several spatial operations IIF statements are used to avoid this behaviour.
    """
    input_path = test_helper.get_testfile(testfile="polygon-parcel")

    sql_stmt = """
        SELECT *
          FROM "{input_layer}"
         WHERE ST_difference({geometrycolumn}, NULL) IS NULL
    """
    output_path = tmp_path / "output.gpkg"
    gfo.select(input_path, output_path, sql_stmt=sql_stmt)

    input_gdf = gfo.read_file(input_path)
    output_gdf = gfo.read_file(output_path)
    assert len(input_gdf) == len(output_gdf)
