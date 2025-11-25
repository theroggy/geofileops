# Configuration file for the Sphinx documentation builder.
#
# This file only contains a selection of the most common options. For a full
# list see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.
#
import os
import sys

sys.path.insert(0, os.path.abspath(".."))

# This will include the necessary source files folders in the PATH to be able to
# generate the documentation from.
devdir = "./"
# try:
# if os.environ['DEVDIR']:
#    devdir = os.environ['DEVDIR']
# except KeyError:
#    print('Unable to obtain $DEVDIR from the environment.')
#    exit(-1)

# -- Project information -----------------------------------------------------

project = "geofileops"
copyright = "2025, Pieter Roggemans"
author = "Pieter Roggemans"

# The full version, including alpha/beta/rc tags
# The version info for the project you're documenting, acts as replacement for
# |version| and |release|, also used in various other places throughout the
# built documents.
import geofileops  # noqa: E402

version = release = geofileops.__version__

# -- General configuration ---------------------------------------------------

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    "matplotlib.sphinxext.plot_directive",
    "sphinx_automodapi.automodapi",
    "sphinx_copybutton",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
]

autosummary_generate = True
autodoc_member_order = "bysource"

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path.
exclude_patterns = [
    "_build",
    "Thumbs.db",
    ".DS_Store",
    "_build",
    "../tests",
    "../samples",
    "../install_scripts",
    "../benchmark",
    "../geofileops/util",
]

# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
html_theme = "pydata_sphinx_theme"

html_title = f"{project} {release}"

# Theme options are theme-specific and customize the look and feel of a theme
# further.  For a list of options available for each theme, see the
# documentation.
html_theme_options = {
    "icon_links": [
        {
            "name": "GitHub",
            "url": "https://github.com/geofileops/geofileops",
            "icon": "fab fa-github-square fa-xl",
        }
    ]
}

html_sidebars: dict[str, list[str]] = {
    "installation": [],
    "user_guide": [],
    "reference": [],
    "faq": [],
    "development": [],
}

# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["_static"]
