import json
import os
import shlex
import uuid

import flux_batch.utils as utils
from flux_batch.service.service import Service

# The usernetes module drives a usernetes checkout (hetchy branch) that
# provides the hardened per-node scripts under <usernetes_root>/service/.
# flux-batch only ships thin launchers (script/launch-*.sh) that orchestrate
# startup order, readiness, and teardown around those scripts:
#
#   cluster mode (default): rank 0 starts the control plane, every other rank
#   starts a worker that waits for the join command. User jobs are gated on
#   the whole cluster being Ready.
#
#   worker mode (bursting): EVERY rank starts a worker that joins an existing
#   cluster, identified by cluster_name. The control plane of the original
#   job reconciles the new nodes (sync-external-ip, calico-node restarts) and
#   deletes them again when the burst job ends.
#
# State is shared through <shared_root>/<cluster_name> on a shared filesystem.

START_CLUSTER_TEMPLATE = """
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
        command=["/bin/bash", "-c", {{control_plane_command}}],
        label="{{service_name}}",
        nodeid=0,
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
        command=["/bin/bash", "-c", {{worker_command}}],
        label="{{service_name}}-worker",
    )
"""

# Burst job: every rank (rank 0 included) is a worker.
START_WORKERS_TEMPLATE = """
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
        command=["/bin/bash", "-c", {{worker_command}}],
        label="{{service_name}}",
        nodeid=0,
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
        command=["/bin/bash", "-c", {{worker_command}}],
        label="{{service_name}}-worker",
    )
"""

# SIGTERM (15) so the launcher traps fire: workers leave a departure marker
# (the control plane deletes their node objects) and both run 'make down-v'.
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
    subprocess.kill(context.handle, signum=15, label="{{service_name}}").get()
    try:
        status = subprocess.wait(context.handle, label="{{service_name}}").get()["status"]
        print(status)
    except Exception:
        pass

@task(
    "stop-{{service_name}}-worker",
    ranks=">0",
    needs_config=["{{service_name}}"],
    before=["resource", "job-list"],
)
def stop_{{service_func}}_worker(context):
    subprocess.kill(context.handle, signum=15, label="{{service_name}}-worker").get()
    try:
        status = subprocess.wait(context.handle, label="{{service_name}}-worker").get()["status"]
        print(status)
    except Exception:
        pass
"""


class UsernetesService(Service):
    """
    Deploy user space Kubernetes (usernetes, hetchy branch) under a batch job.

    Attributes are set on the jobspec attributes or passed to add_module:

    usernetes_root
        Usernetes checkout whose service/ scripts do the per-node work
        (default: $USERNETES_ROOT in the submission environment, then
        /usr/workspace/usernetes/usernetes-wip).
    mode
        "cluster" (default) or "worker" (burst: all ranks join an existing
        cluster).
    cluster_name
        Name of the cluster; a burst job must use the name of the cluster it
        joins (default: "default").
    shared_root
        Shared-filesystem directory holding per-cluster state
        (default: ${HOME}/.usernetes/clusters).
    wait_timeout
        Seconds to wait for each phase (default: 3600).
    container_tech
        Rootless engine (default: podman).
    logs_dir
        Directory for launcher/service logs on each node (default: /tmp/$USER).
    use_ssh
        Launch through 'ssh $(hostname) ...' so the node has a systemd user
        session, which the usernetes preflight check requires and tasks
        started by the broker lack (default: True). Needs passwordless ssh
        between nodes.
    usernetes_env
        Dict of extra environment passed through to the usernetes service
        scripts (USERNETES_STORAGE_ROOT, USERNETES_CNI, CALICO_VXLAN_IIFNAME).
    """

    # The working copy, podman state and node container are per user and per
    # host: two usernetes jobs on one node tear each other down.
    exclusive_nodes = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # One id per submission: the control plane writes it to the cluster
        # directory after clearing stale state, and same-job workers refuse
        # to read a join command until they see it. A burst job does not use
        # it (it trusts the existing, ready cluster instead).
        self.launch_id = str(uuid.uuid4())

    # Attribute accessors with defaults

    @property
    def mode(self):
        mode = (self.attributes.get("mode") or "cluster").lower()
        if mode == "burst":
            mode = "worker"
        if mode not in ("cluster", "worker"):
            raise ValueError(f"Unknown usernetes mode '{mode}': use 'cluster' or 'worker'")
        return mode

    @property
    def usernetes_root(self):
        return (
            self.attributes.get("usernetes_root")
            or os.environ.get("USERNETES_ROOT")
            or "/usr/workspace/usernetes/usernetes-wip"
        )

    @property
    def cluster_name(self):
        return self.attributes.get("cluster_name") or "default"

    @property
    def shared_root(self):
        # Rendered into bash, so ${HOME} expands on the compute node.
        return self.attributes.get("shared_root") or "${HOME}/.usernetes/clusters"

    @property
    def shared_dir(self):
        return f"{self.shared_root}/{self.cluster_name}"

    @property
    def wait_timeout(self):
        return int(self.attributes.get("wait_timeout") or 3600)

    @property
    def script_dir(self):
        return os.path.join(os.path.dirname(__file__), "script")

    # Launcher command construction

    def launcher_environment(self):
        """
        Environment rendered into the launcher invocations. Values the user
        did not set are left to the launchers' own defaults.
        """
        env = {
            "USERNETES_ROOT": self.usernetes_root,
            "USERNETES_CLUSTER_NAME": self.cluster_name,
            "USERNETES_MODE": self.mode,
            "USERNETES_LAUNCH_ID": self.launch_id,
            "USERNETES_WAIT_TIMEOUT": str(self.wait_timeout),
        }
        if self.attributes.get("shared_root"):
            env["USERNETES_SHARED_ROOT"] = self.attributes["shared_root"]
        if self.attributes.get("nodes"):
            env["USERNETES_EXPECTED_NODES"] = str(self.attributes["nodes"])
        if self.attributes.get("container_tech"):
            env["USERNETES_CONTAINER_TECH"] = self.attributes["container_tech"]
        if self.attributes.get("logs_dir"):
            env["USERNETES_LOG_DIR"] = str(self.attributes["logs_dir"])
        # Anything else the usernetes service scripts understand
        env.update(self.attributes.get("usernetes_env") or {})
        return env

    def launcher_command(self, script):
        """
        One shell command string running a launcher with its environment.
        """
        env = self.launcher_environment()
        assignments = " ".join(f"{key}={shlex.quote(str(value))}" for key, value in env.items())
        script_path = os.path.join(self.script_dir, script)
        command = f"{assignments} exec /bin/bash {shlex.quote(script_path)}"
        if self.attributes.get("use_ssh", True):
            # -tt: when Flux kills the ssh client, the remote pty hangs up and
            # the launcher gets SIGHUP, so its teardown still runs.
            command = f"ssh -tt -o BatchMode=yes $(hostname) {shlex.quote(command)}"
        return command

    @property
    def module_template_args(self):
        # json.dumps gives valid Python string literals for the modprobe file.
        return {
            "control_plane_command": json.dumps(self.launcher_command("launch-control-plane.sh")),
            "worker_command": json.dumps(self.launcher_command("launch-worker.sh")),
        }

    # Hooks used by Service.setup_module / the jobspec

    @property
    def module_start_template(self):
        template = START_CLUSTER_TEMPLATE if self.mode == "cluster" else START_WORKERS_TEMPLATE
        return utils.undefined_template(template).render(**self.module_template_args)

    @property
    def module_shutdown_template(self):
        return utils.undefined_template(STOP_MODULE_TEMPLATE).render(**self.module_template_args)

    def generate_batch_prolog(self):
        """
        Lines placed before user jobs in the batch wrapper: gate the workload
        on the cluster (and every node of this job) being Ready.
        """
        wait_script = os.path.join(self.script_dir, "wait-for-ready.sh")
        lines = [
            "",
            "# usernetes: wait until the cluster and every node of this job are Ready",
            f'/bin/bash {shlex.quote(wait_script)} "{self.shared_dir}" {self.wait_timeout}',
            f'export USERNETES_SHARED_DIR="{self.shared_dir}"',
        ]
        if self.mode == "cluster":
            # Rank 0 of a cluster-mode batch job is the control plane node.
            lines.append('export KUBECONFIG="/tmp/$(whoami)/usernetes/kubeconfig"')
        lines.append("")
        return lines

    def setup(self, base_dir=None):
        """
        Validate what we can at submit time, then write the modprobe scripts.
        """
        root = self.usernetes_root
        marker = os.path.join(root, "service", "usernetes-start-control-plane.sh")
        if not os.path.exists(marker):
            print(
                f"WARNING: {marker} not found from the submission host. "
                "usernetes_root must be a usernetes checkout (hetchy branch) "
                "visible on every compute node; the launchers will fail fast "
                "if it is missing there."
            )
        super().setup(base_dir=base_dir)
