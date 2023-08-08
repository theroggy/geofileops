"""
Module with some helpers functions to validate, parse,... parameters with a complex
structure that are typically reused in different functions in geofileops.
"""


def validate_agg_columns(agg_columns: dict):
    """
    Validates if the agg_columns parameter is properly formed.

    If an problem is found, an error is raised.

    Typically used in dissolve functions.

    Args:
        agg_columns (dict): the agg_columns parameter value dict to check.

    Raises:
        ValueError: if any error is encountered.
    """
    # Check agg_columns param
    if agg_columns is None:
        return

    base_message = (
        '{"json": [<list_columns>]} '
        'or {"columns": [{"column": "...", "agg": "...", "as": "..."}, ...]}'
    )

    # It should be a dict with one key
    if (
        agg_columns is None
        or not isinstance(agg_columns, dict)
        or len(agg_columns) != 1
    ):
        message = "agg_columns must be a dict with exactly one top-level key"
        raise ValueError(f"{message}: {base_message}")

    if "json" in agg_columns:
        # The value should be a list or None
        if agg_columns["json"] is None:
            return
        if not isinstance(agg_columns["json"], list):
            message = 'agg_columns["json"] does not contain a list of strings'
            raise ValueError(f"{message}: {agg_columns['json']}: {base_message}")

        # Loop through all elements
        for agg_column in agg_columns["json"]:
            # It should be a str
            if not isinstance(agg_column, str):
                message = 'agg_columns["json"] list contains a non-string element'
                raise ValueError(f"{message}: {agg_column}: {base_message}")
    elif "columns" in agg_columns:
        supported_aggfuncs = [
            "count",
            "sum",
            "mean",
            "min",
            "max",
            "median",
            "concat",
        ]
        # The value should be a list
        if not isinstance(agg_columns["columns"], list):
            message = 'agg_columns["columns"] does not contain a list of dicts'
            raise ValueError(f"{message}: {agg_columns['columns']}: {base_message}")

        # Loop through all elements
        for agg_column in agg_columns["columns"]:
            # It should be a dict
            if not isinstance(agg_column, dict):
                message = 'agg_columns["columns"] list contains a non-dict element'
                raise ValueError(f"{message}: {agg_column}: {base_message}")

            # Check if column exists + set casing same as in data
            if "column" not in agg_column:
                message = 'each dict in agg_columns["columns"] needs a "column" element'
                raise ValueError(f"{message}: {agg_column}")
            if "agg" not in agg_column:
                message = 'each dict in agg_columns["columns"] needs an "agg" element'
                raise ValueError(f"{message}: {agg_column}")
            if "as" not in agg_column:
                message = 'each dict in agg_columns["columns"] needs an "as" element'
                raise ValueError(f"{message}: {agg_column}")
            if agg_column["agg"].lower() not in supported_aggfuncs:
                raise ValueError(
                    'agg_columns["columns"] contains unsupported aggregation '
                    f'{agg_column["agg"]}, use one of {supported_aggfuncs}'
                )
            if not isinstance(agg_column["as"], str):
                raise ValueError(
                    f'agg_columns["columns"], "as" value should be string: {agg_column}'
                )
    else:
        message = (
            f"agg_columns has invalid top-level key: {list(agg_columns.keys())[0]}"
        )
        raise ValueError(f"{message}: {base_message}")
