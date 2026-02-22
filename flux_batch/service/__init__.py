from dataclasses import asdict

import flux_batch.service.scribe as scribe
import flux_batch.service.usernetes as usernetes

from .service import Service

# Lookup of known services (and associated modules)
# I started prototyping services but am not currently using
# flux doesn't easily support systemctl unless you use ssh after
services = {
    "flux-scribe": scribe.FluxScribeService(is_service=False, is_module=True),
    "usernetes": usernetes.UsernetesService(is_service=False, is_module=True),
}


def new_service(name, attributes=None):
    """
    If a service is known, retrieve here. Otherwise return
    generic service.
    """
    # If it's a known, provisioned service, return the class
    if name in services:
        service = services[name]
        service.attributes = asdict(attributes)
        return service

    # Return what we assume to be a general service (no flux module)
    return Service(name)
