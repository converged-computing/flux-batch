import os
import re
import sys

sys.path.insert(0, os.path.abspath(".."))

# Importing flux_batch.version would import the package, and with it flux,
# before autodoc_mock_imports takes effect.
with open(os.path.join(os.path.dirname(__file__), "..", "flux_batch", "version.py")) as fd:
    __version__ = re.search(r'__version__ = "([^"]+)"', fd.read()).group(1)

project = "flux-batch"
author = "Vanessa Sochat"
copyright = "2025-2026, Lawrence Livermore National Security, LLC"
version = __version__
release = __version__

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx_copybutton",
]

source_suffix = {".md": "markdown", ".rst": "restructuredtext"}
master_doc = "index"
exclude_patterns = ["_build"]

myst_enable_extensions = ["colon_fence", "deflist", "attrs_inline"]
myst_heading_anchors = 3

# The flux python bindings only exist inside a Flux install
autodoc_mock_imports = ["flux"]
autodoc_member_order = "bysource"
autodoc_typehints = "description"

html_theme = "furo"
html_title = "flux-batch"
html_logo = "../img/flux-batch-small.png"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_theme_options = {
    "source_repository": "https://github.com/converged-computing/flux-batch",
    "source_branch": "main",
    "source_directory": "docs/",
    "light_css_variables": {
        "color-brand-primary": "#0f6ab4",
        "color-brand-content": "#0f6ab4",
    },
    "dark_css_variables": {
        "color-brand-primary": "#5ab0f2",
        "color-brand-content": "#5ab0f2",
    },
}
copybutton_prompt_text = r"\$ "
copybutton_prompt_is_regexp = True
