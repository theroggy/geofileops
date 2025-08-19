"""General helper functions, specific for geofileops."""

from geofileops.helpers._configoptions_helper import ConfigOptions


def worker_type_to_use(input_layer_featurecount: int) -> str:
    worker_type = ConfigOptions.worker_type
    if worker_type in ("threads", "processes"):
        return worker_type

    # Processing in threads is 2x faster for small datasets
    if input_layer_featurecount <= 100:
        return "threads"

    return "processes"
