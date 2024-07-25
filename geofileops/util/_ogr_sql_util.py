"""Module with utilities to format sql statements meant for use with ogr."""

from collections.abc import Iterable
from typing import Optional


class ColumnFormatter:
    """Format strings with the columns for use in sql statements.

    There are some specific hacks that are related to specific behaviours of ogr, mainly
    regarding the handling of the special "fid" column.
    """

    _aliases_cache: Optional[list[str]] = None

    def __init__(
        self,
        columns_asked: Optional[list[str]],
        columns_in_layer: Iterable[str],
        fid_column: str,
        table_alias: str = "",
        column_alias_prefix: str = "",
    ):
        """Format strings with column names for use in sql statements.

        Args:
            columns_asked (Optional[List[str]]): the column names to read from the
                file. If None, all available columns in the layer should be read.
                In addition to standard columns, it is also possible to specify "fid",
                a unique index available in all input files.
                Note that the "fid" will be aliased even if column_alias_prefix is "",
                eg. to "fid_1".
            columns_in_layer (Iterable[str]): the column names of the columns available
                in the layer that is being read from.
            fid_column (str): fid column name as reported by the gdal GetFIDColumn()
                function. For file types that don't store the fid this is "".
            table_alias (str, optional): table alias to be used.
                Defaults to "": no table alias.
            column_alias_prefix (str, optional): prefix to use for column aliases.
                Defaults to "": no prefix.

        Raises:
            ValueError: if columns are asked that are not available in the layer.
        """
        self._columns_in_layer = columns_in_layer
        self._fid_column = fid_column
        self._table_prefix = f"{table_alias}." if table_alias != "" else ""
        self._table_alias = table_alias
        self._columnname_prefix = column_alias_prefix

        # Now prepare the actual column list to use
        if columns_asked is not None:
            # Add special column "fid" to available columns so it can be specified
            columns_in_layer = list(columns_in_layer) + ["fid"]
            # Case-insensitive check if input1_columns contains columns not in layer...
            columns_in_layer_upper = {
                column.upper(): column for column in columns_in_layer
            }
            missing_columns = [
                col
                for col in columns_asked
                if (col.upper() not in columns_in_layer_upper)
            ]
            if len(missing_columns) > 0:
                raise ValueError(
                    "columns_asked contains columns not in columns_in_layer: "
                    f"{missing_columns}. Available: {columns_in_layer}"
                )

            # Create column list to keep in the casing of the original columns
            columns = [columns_in_layer_upper[col.upper()] for col in columns_asked]
        else:
            columns = list(columns_in_layer)
            columns_asked = columns

        self._columns = columns
        self._columns_asked = columns_asked

    def _columns_prefixed(self) -> list[str]:
        columns_prefixed = [
            f'{self._table_prefix}"{column}"' for column in self._columns
        ]
        columns_prefixed = self._fix_fid_columns(columns_prefixed)
        return columns_prefixed

    def _fix_fid_columns(self, columns: list[str]) -> list[str]:
        """Fix the fid columns.

        Useful if the "fid" special column needs some extra treatment:
            - if the fid_column name as reported by gdal is "", this means that the file
              format doesn't actually save the fid (eg. shapefile) but uses a row number
              in the file. When using sql in sql_dialect "SQLITE", "rowid" is the
              equivalent.
            - if the fid_column name as reported by gdal is "fid", ogr will treat the
              selected column as "fid" in the destination file as well, even if an alias
              is specified. To stop ogr from doing this, putting a CAST(... AS INT)
              around it prevents ogr from recognizing it.
              Remark: the ogr2ogr -unsetFid switch didn't help.
            - if the fid_column name as reported by gdal is some other string, "fid"
              just needs to be replaced by the fid_column value.
        """
        columns = list(columns)
        fid_column_indexes = [
            idx for idx, col in enumerate(self._columns) if col.upper() == "FID"
        ]
        if self._fid_column.lower() == "fid":
            # Put CAST() around "fid"
            for fid_column_index in fid_column_indexes:
                columns[fid_column_index] = f"CAST({columns[fid_column_index]} AS INT)"
        else:
            # Replace "fid" by the fid_column or rowid
            replace_fid_column = self._fid_column if self._fid_column != "" else "rowid"
            for fid_column_index in fid_column_indexes:
                columns[fid_column_index] = columns[fid_column_index].replace(
                    self._columns[fid_column_index], replace_fid_column
                )

        return columns

    def _aliases(self) -> list[str]:
        if self._aliases_cache is not None:
            return self._aliases_cache

        # Use columns_asked to keep asked casing
        aliases = [
            f"{self._columnname_prefix}{column}" for column in self._columns_asked
        ]

        # If no prefix, create a unique alias for fid column(s)
        if self._columnname_prefix == "":
            for alias_idx, alias in enumerate(aliases):
                if alias.lower() == "fid":
                    # If alias "fid", change it + make sure the alias isn't in use yet
                    for idx in range(1, 100):
                        alias_with_id = f"{alias}_{idx}"
                        if alias_with_id not in aliases:
                            aliases[alias_idx] = alias_with_id
                            break

        self._aliases_cache = aliases
        return self._aliases_cache

    def quoted(self) -> str:
        if len(self._columns) == 0:
            return ""

        columns_quoted = [f'"{column}"' for column in self._columns]
        columns_quoted = self._fix_fid_columns(columns_quoted)
        return f",{', '.join(columns_quoted)}"

    def prefixed(self) -> str:
        if len(self._columns) == 0:
            return ""
        return f",{', '.join(self._columns_prefixed())}"

    def prefixed_aliased(self):
        if len(self._columns) == 0:
            return ""

        columns_prefixed_aliased = [
            f'{column_prefixed} "{column_alias}"'
            for column_prefixed, column_alias in zip(
                self._columns_prefixed(), self._aliases()
            )
        ]
        return f",{', '.join(columns_prefixed_aliased)}"

    def null_aliased(self):
        if len(self._columns) == 0:
            return ""

        columns_null_aliased = [f'NULL "{alias}"' for alias in self._aliases()]
        return f",{', '.join(columns_null_aliased)}"

    def from_subselect(self, subselect_alias: str = "sub"):
        if len(self._columns) == 0:
            return ""

        prefix = "" if subselect_alias == "" else f"{subselect_alias}."
        columns_from_subselect = [f'{prefix}"{alias}"' for alias in self._aliases()]
        return f",{', '.join(columns_from_subselect)}"


def columns_quoted(columns: list[str]):
    if len(columns) == 0:
        return ""
    columns_quoted = [f'"{column}"' for column in columns]
    return f",{', '.join(columns_quoted)}"
