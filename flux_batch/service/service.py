import os
import re
import subprocess
import sys

from jinja2 import Template

import flux_batch.utils as utils


class Service:
    """
    A service is a courtesy wrapper to handle exposing
    templates to write a service. If the user service exists, this is
    merely a handle to interact. If not, or if this is a service we are
    orchestrating, we can customize the class to add our own logic.
    """

    # Modules that cannot share a node with another job set this, and the
    # batch job is then submitted with exclusive node allocation (--exclusive).
    exclusive_nodes = False

    def __init__(self, name=None, is_module=False, is_service=True, attributes=None):
        self.name = self.get_service_name(name)
        self.is_service = is_service
        self.is_module = is_module
        self.attributes = attributes or {}
        print(f"Discovered service {self.name}")

    # Module start / shutdown templates. We currently assume we just need one

    @property
    def module_start_template(self):
        pass

    @property
    def module_shutdown_template(self):
        pass

    @property
    def module_name(self):
        """
        Default module name assumes being in flux-batch: the service package
        (which has a __main__.py), not the service.py submodule.
        """
        # flux_batch.service.scribe.service -> flux_batch.service.scribe
        module = self.__class__.__module__
        return module.rsplit(".service", 1)[0] if module.endswith(".service") else module

    def __eq__(self, other):
        """
        Determine equality with another object.
        """
        if not isinstance(other, Service):
            return False
        return self.name == other.name

    def __hash__(self):
        """
        Hash can be used to determine uniqueness / add lists to set.
        """
        return hash(self.name)

    def get_service_name(self, name=None):
        """
        FluxScribeService -> flux-scribe
        """
        name = name or re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", self.__class__.__name__)
        return name.lower().replace("-service", "")

    def setup(self, base_dir=None):
        """
        Setup the service and modules.
        """
        if self.is_service:
            self.setup_service()
        if self.is_module:
            self.setup_module(base_dir=base_dir)

    def setup_service(self):
        """
        Checks for the existence of a systemd service file in the user's home.
        If it doesn't exist, it creates it and reloads the daemon.
        """
        # If we don't have templates, we assume it's a known existing service
        if not self.service_templates:
            print(f"[*] Service {self.name} is not known, assuming exists.")

        # A service that isn't provisioned here will not have these templates
        else:
            self.ensure_services()

    def setup_module(self, base_dir=None):
        """
        Setup modprobe scripts.

        Ensures rc1.d (start) and rc3.d (stop) scripts exist for the service.
        The base directory must match the FLUX_MODPROBE_PATH_APPEND the
        jobspec passes, so concurrent jobs with different configurations
        (e.g., a cluster and a burst of workers) do not clobber each other.
        """
        # Cut out early if no stop/shutdown
        if not self.module_shutdown_template and not self.module_start_template:
            return

        base_dir = base_dir or os.path.expanduser("~/.flux-batch")
        for subdir in ["rc1.d", "rc3.d"]:
            os.makedirs(os.path.join(base_dir, subdir), exist_ok=True)

        service_func = self.name.replace("-", "_")
        args = {
            "service_name": self.name,
            "service_func": service_func,
            "python_bin": sys.executable,
            "module_name": self.module_name,
        }

        # Path for rc1.d (startup)
        if self.module_start_template:
            rc1_path = os.path.join(base_dir, "rc1.d", f"{self.name}.py")
            write_modprobe_script(rc1_path, self.module_start_template, args=args)

        # Path for rc3.d (shutdown)
        if self.module_shutdown_template:
            rc3_path = os.path.join(base_dir, "rc3.d", f"{self.name}.py")
            write_modprobe_script(rc3_path, self.module_shutdown_template, args=args)

    def ensure_services(self):
        """
        Ensure that service templates are written.
        """
        user_systemd_dir = os.path.expanduser("~/.config/systemd/user")
        os.makedirs(user_systemd_dir, exist_ok=True)
        new_services = False

        for service_file, template in self.service_templates.items():
            service_path = os.path.join(user_systemd_dir, service_file)

            # We have already written the template
            if os.path.exists(service_path):
                continue

            # We need to write it still.
            new_services = True
            print(f"[*] Provisioning {self.name} at {service_path}")
            args = dict(self.attributes)
            args.update({"python_path": sys.executable})
            render = Template(template).render(**args)
            utils.write_file(render, service_path)

        # Reload the user-session manager to recognize the new unit
        if new_services:
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)

    def generate_start(self):
        """
        Generate lines to add to the flux-batch script to start the service.
        """
        if self.is_service:
            return [f"systemctl start --user {self.name}"]
        return []

    def generate_stop(self):
        """
        Generate lines for the flux batch script to stop the service.
        """
        if self.is_service:
            return [f"systemctl stop --user {self.name}"]
        return []

    def generate_batch_prolog(self):
        """
        Lines placed in the batch wrapper before the user's jobs (for example,
        to wait until the thing the module deploys is ready).
        """
        return []

    def generate_batch_epilog(self):
        """
        Lines placed in the batch wrapper after the user's jobs.
        """
        return []

    @property
    def status(self):
        if self.is_service:
            return f"systemctl status --user {self.name}"
        return ""

    @property
    def module_templates(self):
        """
        Module templates - key value pairs of basename files and templates
        """
        return {}

    @property
    def service_templates(self):
        """
        Service templates - key value pairs of basename files and templates
        """
        return {}


def write_modprobe_script(rc_path, script, args=None):
    """
    Shared function to write a modprobe rc script. Always overwritten: the
    rendered content depends on the jobspec (mode, cluster name, launch id),
    so a stale script from a previous submission must never win.
    """
    args = args or {}
    utils.write_file(Template(script).render(**args), rc_path)
