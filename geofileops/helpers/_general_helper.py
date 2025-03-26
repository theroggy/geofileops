"""General helper functions, specific for geofileops."""

from geofileops.helpers._configoptions_helper import ConfigOptions


def use_threads(input_layer_featurecount: int) -> bool:
    worker_type = ConfigOptions.worker_type
    if worker_type == "thread":
        return True
    elif worker_type == "process":
        return False

    # Processing in threads is 2x faster for small datasets
    if input_layer_featurecount <= 100:
        return True

    return False
