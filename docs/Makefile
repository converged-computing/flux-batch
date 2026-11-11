# Build the docs locally:
#   pip install -r requirements.txt
#   make html        # then open _build/html/index.html
#   make serve       # preview at http://localhost:8000

SPHINXOPTS ?= -W --keep-going
BUILDDIR    = _build

.PHONY: html serve clean
html:
	sphinx-build -b html $(SPHINXOPTS) . $(BUILDDIR)/html

serve: html
	python3 -m http.server --directory $(BUILDDIR)/html 8000

clean:
	rm -rf $(BUILDDIR)
