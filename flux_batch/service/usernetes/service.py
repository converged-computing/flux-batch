import os
import tempfile
import uuid

import flux_batch.utils as utils
from flux_batch.service.service import Service

# NOTE: these are not currently used - hard to run systemd services under Flux
START_CONTROL_PLANE_SERVICE = """[Unit]
Description=User Space Kubernetes Control Plane (Usernetes)
After=network-online.target

[Service]
Type=simple
ExecStart={{install_dir}}/script/start-control-plane.sh {{container_tech}}
LimitMEMLOCK=infinity

# Standard output and error
# Customize this to where you want it.
StandardOutput=file:{{logs_dir}}/control-plane.log
StandardError=file:{{logs_dir}}/control-plane.log

# KillMode=process is important. When the service stops, systemd will only kill
# the main process (sleep infinity). The Kubernetes components run inside containers
# managed by Podman/Docker, which `make down-v` (or manual podman commands) should handle
# on a clean shutdown. If the node is just "cleaned up" (deallocated), then everything dies anyway.
KillMode=process

# Start when the user's session starts
[Install]
WantedBy=default.target
"""

START_WORKER_SERVICE = """[Unit]
Description=User Space Kubernetes Worker (Usernetes)
After=network-online.target

[Service]
Type=simple
ExecStart={{install_dir}}/script/usernetes-start-worker.sh {{container_tech}}
LimitMEMLOCK=infinity

# Logging
StandardOutput=file:{{logs_dir}}/worker.log
StandardError=file:{{logs_dir}}/worker.log
KillMode=process

# Start when the user's session starts
[Install]
WantedBy=default.target
"""

START_MODULE_TEMPLATE = """
from flux.modprobe import task
import flux.subprocess as subprocess

@task(
    "start-{{service_name}}",
    ranks="0",
    needs_config=["{{service_name}}"],
    after=["resource", "job-list"],
)
def start_{{service_func}}(context):
    subprocess.rexec_bg(
        handle=context.handle,
        command=["/bin/bash", "-c", "ssh $(hostname) {{install_dir}}/script/start-control-plane.sh {{ container_tech }} {{ flux_id }}"],
        label="{{service_name}}",
        nodeid=0
    )

@task(
    "start-{{service_name}}-worker",
    ranks=">0",
    needs_config=["{{service_name}}"],
    after=["resource", "job-list"],
)
def start_{{service_func}}_worker(context):
    subprocess.rexec_bg(
        handle=context.handle,
        command=["/bin/bash", "-c", "ssh $(hostname) {{install_dir}}/script/start-worker.sh {{ container_tech }} {{ flux_id }}"],
        label="{{service_name}}"
    )
"""

STOP_MODULE_TEMPLATE = """
from flux.modprobe import task
import flux.subprocess as subprocess

@task(
    "stop-{{service_name}}",
    ranks="0",
    needs_config=["{{service_name}}"],
    before=["resource", "job-list"],
)
def stop_{{service_func}}(context):
    subprocess.kill(context.handle, signum=2, label="{{service_name}}").get()
    try:
        status = subprocess.wait(context.handle, label="{{service_name}}").get()["status"]
        print(status)
    except:
        pass

        @task(
@task(
    "stop-{{service_name}}-worker",
    ranks=">0",
    needs_config=["{{service_name}}"],
    before=["resource", "job-list"],
)
def stop_{{service_func}}_worker(context):
    subprocess.kill(context.handle, signum=2, label="{{service_name}}-worker").get()
    try:
        status = subprocess.wait(context.handle, label="{{service_name}}-worker").get()["status"]
        print(status)
    except:
        pass
"""


class UsernetesService(Service):

    @property
    def module_template_args(self):
        """
        Shared module template args.
        """
        # Location of this file to target executable script
        install_dir = os.path.dirname(__file__)
        container_tech = self.attributes.get("container_tech") or "podman"
        flux_id = str(uuid.uuid4())

        # Either write to temporary directory or defined user logs directory
        # TODO can we pipe into logs dir?
        logs_dir = self.attributes.get("logs_dir") or tempfile.gettempdir()
        return {
            "logs_dir": logs_dir,
            "install_dir": install_dir,
            "container_tech": container_tech,
            "flux_id": flux_id,
        }

    @property
    def module_start_template(self):
        return utils.undefined_template(START_MODULE_TEMPLATE).render(**self.module_template_args)

    @property
    def module_shutdown_template(self):
        return utils.undefined_template(STOP_MODULE_TEMPLATE).render(**self.module_template_args)
