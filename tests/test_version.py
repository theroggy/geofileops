# -*- coding: utf-8 -*-
"""
Test if backwards compatibility for old API still works.
"""

import geofileops as gfo


def test_version():
    assert "\n" not in gfo.__version__
