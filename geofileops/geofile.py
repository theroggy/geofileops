# -*- coding: utf-8 -*-
"""
Only for backwards compatibility.
"""

import warnings

warnings.warn(
    "using from geofileops import geofile is deprecated, "
    "please just use import geofileops",
    FutureWarning,
)

from .fileops import *  # noqa: F403, F401
