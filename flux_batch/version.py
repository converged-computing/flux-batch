__version__ = "0.0.0"
AUTHOR = "Vanessa Sochat"
AUTHOR_EMAIL = "vsoch@users.noreply.github.com"
NAME = "flux-batch"
PACKAGE_URL = "https://github.com/converged-computing/flux-batch"
KEYWORDS = "flux, flux framework, hpc, batch, workloads"
DESCRIPTION = "Python SDK for flux batch jobs and services"
LICENSE = "LICENSE"

INSTALL_REQUIRES = (
    ("pyyaml", {"min_version": None}),
    ("ply", {"min_version": None}),
)

TESTS_REQUIRES = (("pytest", {"min_version": "4.6.2"}),)
INSTALL_REQUIRES_ALL = INSTALL_REQUIRES + TESTS_REQUIRES
