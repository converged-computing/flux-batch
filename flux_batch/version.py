__version__ = "0.0.11"
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
SCRIBE_REQUIRES = (("sqlalchemy", {"min_version": None}), ("rich", {"min_version": None}))
INSTALL_REQUIRES_ALL = INSTALL_REQUIRES + TESTS_REQUIRES + SCRIBE_REQUIRES
