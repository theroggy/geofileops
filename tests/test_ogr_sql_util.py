# -*- coding: utf-8 -*-
"""
Tests for functionalities in sql_util.
"""

from typing import Iterable, List, Optional

import pytest

from geofileops.util import _ogr_sql_util


@pytest.mark.parametrize(
    "descr, columns_specified, columns_available, table_alias, columnname_prefix, "
    "fid_column, "
    "exp_quoted, exp_prefixed, exp_prefixed_aliased, "
    "exp_null_aliased, exp_from_subselect",
    [
        (
            "2 columns asked out of 3 in layer",
            ["test1", "TesT2"],
            ["test1", "test3", "test2"],
            "",
            "",
            "fid",
            ',"test1", "test2"',
            ',"test1", "test2"',
            ',"test1" "test1", "test2" "TesT2"',
            ',NULL "test1", NULL "TesT2"',
            ',sub."test1", sub."TesT2"',
        ),
        (
            "fid asked as well as fid_1",
            ["fid", "fid_1", "test2"],
            ["fid_1", "fid_2", "test2"],
            "",
            "",
            "",  # No actual fid column, eg. shapefile
            ',"rowid", "fid_1", "test2"',
            ',"rowid", "fid_1", "test2"',
            ',"rowid" "fid_2", "fid_1" "fid_1", "test2" "test2"',
            ',NULL "fid_2", NULL "fid_1", NULL "test2"',
            ',sub."fid_2", sub."fid_1", sub."test2"',
        ),
        (
            "fid asked and fid_column is fid",
            ["fid", "test1", "test2"],
            ["test2", "test3", "test1"],
            "",
            "",
            "fid",  # Actual" fid" column, eg. geopackage
            ',CAST("fid" AS INT), "test1", "test2"',
            ',CAST("fid" AS INT), "test1", "test2"',
            ',CAST("fid" AS INT) "fid_1", "test1" "test1", "test2" "test2"',
            ',NULL "fid_1", NULL "test1", NULL "test2"',
            ',sub."fid_1", sub."test1", sub."test2"',
        ),
        (
            "fid asked with table alias",
            ["fid", "test1"],
            ["test2", "test3", "test1"],
            "table_alias1",
            "",
            "fid",  # Actual "fid" column, eg. geopackage
            ',CAST("fid" AS INT), "test1"',
            ',CAST(table_alias1."fid" AS INT), table_alias1."test1"',
            ',CAST(table_alias1."fid" AS INT) "fid_1", table_alias1."test1" "test1"',
            ',NULL "fid_1", NULL "test1"',
            ',sub."fid_1", sub."test1"',
        ),
        (
            "fid asked with table alias and prefix",
            ["fid", "test1"],
            ["test2", "test3", "test1"],
            "table_alias1",
            "l1_",
            "ogc_fid",  # Actual fid column named "ogc_fid", eg. sqlite
            ',"ogc_fid", "test1"',
            ',table_alias1."ogc_fid", table_alias1."test1"',
            ',table_alias1."ogc_fid" "l1_fid", table_alias1."test1" "l1_test1"',
            ',NULL "l1_fid", NULL "l1_test1"',
            ',sub."l1_fid", sub."l1_test1"',
        ),
        ("No columns asked", [], ["test1"], "", "", "fid", "", "", "", "", ""),
    ],
)
def test_ColumnFormatter(
    descr: str,
    columns_specified: Optional[List[str]],
    columns_available: Iterable[str],
    table_alias: str,
    columnname_prefix: str,
    fid_column: str,
    exp_quoted: str,
    exp_prefixed: str,
    exp_prefixed_aliased: str,
    exp_null_aliased: str,
    exp_from_subselect: str,
):
    column_frmt = _ogr_sql_util.ColumnFormatter(
        columns_asked=columns_specified,
        columns_in_layer=columns_available,
        fid_column=fid_column,
        table_alias=table_alias,
        column_alias_prefix=columnname_prefix,
    )
    assert column_frmt.quoted() == exp_quoted
    assert column_frmt.prefixed() == exp_prefixed
    assert column_frmt.prefixed_aliased() == exp_prefixed_aliased
    assert column_frmt.null_aliased() == exp_null_aliased
    assert column_frmt.from_subselect() == exp_from_subselect


def test_ColumnFormatter_invalidcolumn():
    with pytest.raises(ValueError, match="columns_asked contains columns not in"):
        _ogr_sql_util.ColumnFormatter(
            columns_asked=["test"],
            columns_in_layer=["test1"],
            fid_column="fid",
        )
