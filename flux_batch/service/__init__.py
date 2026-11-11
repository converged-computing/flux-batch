from dataclasses import asdict, is_dataclass

import flux_batch.service.scribe as scribe
import flux_batch.service.usernetes as usernetes

from .service import Service

# Lookup of known services (and associated modules). Classes, not instances:
# every jobspec gets its own instance so per-submission state (attributes,
# launch ids) is never shared between jobs.
services = {
    "flux-scribe": (scribe.FluxScribeService, {"is_service": False, "is_module": True}),
    "usernetes": (usernetes.UsernetesService, {"is_service": False, "is_module": True}),
}


def new_service(name, attributes=None, **kwargs):
    """
    If a service is known, instantiate it here. Otherwise return a generic
    service. Extra keyword arguments become (or override) service attributes,
    e.g. add_module("usernetes", mode="worker", cluster_name="lammps").
    """
    if is_dataclass(attributes):
        attributes = asdict(attributes)
    attributes = dict(attributes or {})
    attributes.update(kwargs)

    # If it's a known, provisioned service, return the class
    if name in services:
        cls, init_kwargs = services[name]
        return cls(attributes=attributes, **init_kwargs)

    # Return what we assume to be a general service (no flux module)
    return Service(name, attributes=attributes)
