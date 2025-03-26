"""
Tests for functionalities in _processing_util.
"""

import os

from geofileops.util import _processing_util


def test_processnice():
    # Test setting and getting some values for nice
    # Remark: the nice values tests are spcifically written to accomodate for
    # windows specificalities:
    #     - windows only supports 6 niceness classes. setprocessnice en
    #       getprocessnice maps niceness values to these classes.
    #     - when setting REALTIME priority (-20 niceness) apparently this
    #       results only to HIGH priority.
    nice_orig = _processing_util.getprocessnice()
    for niceness in [-15, -10, 0, 10, 19]:
        # Decreasing niceness (sometimes) isn't possible on linux, so skip
        if os.name != "nt":
            continue

        # Test!
        _processing_util.setprocessnice(niceness)
        nice = _processing_util.getprocessnice()
        assert nice == niceness

    # Test invalid values for nice value
    try:
        _processing_util.setprocessnice(20)
        exception_raised = False
    except ValueError:
        exception_raised = True
    assert exception_raised is True
    try:
        _processing_util.setprocessnice(-21)
        exception_raised = False
    except ValueError:
        exception_raised = True
    assert exception_raised is True

    # Reset niceness to original value before test
    _processing_util.setprocessnice(nice_orig)
