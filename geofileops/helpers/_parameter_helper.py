"""Module with some helpers functions to validate, parse,... parameters.

Mainly used for parameters with a complex structure that are typically reused in
different functions in geofileops.
"""

from pathlib import Path

from geofileops import LayerInfo, fileops


def validate_agg_columns(agg_columns: dict) -> None:
    """Validates if the agg_columns parameter is properly formed.

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
                    f"{agg_column['agg']}, use one of {supported_aggfuncs}"
                )
            if not isinstance(agg_column["as"], str):
                raise ValueError(
                    f'agg_columns["columns"], "as" value should be string: {agg_column}'
                )
    else:
        message = (
            f"agg_columns has invalid top-level key: {next(iter(agg_columns.keys()))}"
        )
        raise ValueError(f"{message}: {base_message}")


def validate_params_single_layer(
    input_path: Path,
    output_path: Path,
    input_layer: str | LayerInfo | None,
    output_layer: str | None,
    operation_name: str,
) -> tuple[LayerInfo, str]:
    """Validate the input parameters, return the layer names.

    Args:
        input_path (Path): path to the input file
        output_path (Path): path to the output file
        input_layer (Optional[Union[str, LayerInfo]]): the layer name or the LayerInfo
            of the input file
        output_layer (Optional[str]): the layer name of the output file
        operation_name (str): the operation name, used to get clearer errors.

    Raises:
        ValueError: when an invalid parameter was passed.

    Returns:
        a tuple with the layers:
        input_layer (LayerInfo), output_layer (str)
    """
    if output_path == input_path:
        raise ValueError(f"{operation_name}: output_path must not equal input_path")
    if not input_path.exists():
        raise FileNotFoundError(f"{operation_name}: input_path not found: {input_path}")

    # Get layer info
    if not isinstance(input_layer, LayerInfo):
        input_layer = fileops.get_layerinfo(
            input_path, layer=input_layer, raise_on_nogeom=False
        )

    if output_layer is None:
        output_layer = fileops.get_default_layer(output_path)

    return input_layer, output_layer


def validate_params_two_layers(
    input1_path: Path,
    input2_path: Path | None,
    output_path: Path,
    input1_layer: str | LayerInfo | None,
    input2_layer: str | LayerInfo | None,
    output_layer: str | None,
    operation_name: str,
) -> tuple[LayerInfo, LayerInfo, str]:
    """Validate the input parameters, return the layer names.

    Args:
        input1_path (Path): path to the 1st input file
        input2_path (Path, optional): path to the 2nd input file
        output_path (Path): path to the output file
        input1_layer (Optional[Union[str, LayerInfo]]): the layer name or the LayerInfo
            of the 1st input file
        input2_layer (Optional[Union[str, LayerInfo]]): the layer name or the LayerInfo
            of the 2nd input file
        output_layer (Optional[str]): the layer name of the output file
        operation_name (str): the operation name, used to get clearer errors.

    Raises:
        ValueError: when an invalid parameter was passed.

    Returns:
        a tuple with the layers:
        input1_layer (LayerInfo), input2_layer (LayerInfo), output_layer (str)
    """
    if output_path in (input1_path, input2_path):
        raise ValueError(
            f"{operation_name}: output_path must not equal one of input paths"
        )
    if not input1_path.exists():
        raise FileNotFoundError(
            f"{operation_name}: input1_path not found: {input1_path}"
        )
    if input2_path is not None and not input2_path.exists():
        raise FileNotFoundError(
            f"{operation_name}: input2_path not found: {input2_path}"
        )

    # Get layer info
    if not isinstance(input1_layer, LayerInfo):
        input1_layer = fileops.get_layerinfo(
            input1_path, layer=input1_layer, raise_on_nogeom=False
        )
    if input2_path is not None and not isinstance(input2_layer, LayerInfo):
        input2_layer = fileops.get_layerinfo(
            input2_path, layer=input2_layer, raise_on_nogeom=False
        )

    if output_layer is None:
        output_layer = fileops.get_default_layer(output_path)

    return input1_layer, input2_layer, output_layer  # type: ignore[return-value]
