# -*- coding: utf-8 -*-
"""
Test if backwards compatibility for old API still works.
"""

from pathlib import Path
import sys

# Add path so the local geofileops packages are found 
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import geofileops as gfo
import test_helper

def test_version():
    assert "\n" not in gfo.__version__
    
if __name__ == '__main__':
    # Init
    tmpdir = test_helper.init_test_for_debug(Path(__file__).stem)

    # Test functions to run...
    test_version()
