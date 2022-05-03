# -*- coding: utf-8 -*-
"""
Only for backwards compatibility.
"""

import warnings

warnings.warn(
    "using from geofileops import geofileops is deprecated, "
    "please just use import geofileops",
    FutureWarning,
)

from .geoops import *  # noqa: F403, F401
