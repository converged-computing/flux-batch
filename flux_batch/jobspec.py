import os
import shlex
from typing import List

import flux_batch.models as models
import flux_batch.script as scripts
import flux_batch.service as services


class BatchJobspecV1:
    """
    A BatchJobspecV1 mirrors a JobspecV1. We need to:

    1. Add some number of commands or a script
    2. Add optional services (start/stop)
    """

    def __init__(self, attributes: models.BatchAttributesV1 = None):
        self.attributes = attributes or models.BatchAttributesV1()
        self.commands: List[str] = []
        self.prologs: List[str] = []
        self.epilogs: List[str] = []
        self.services: List[str] = []
        self.modules: List[str] = []

    @classmethod
    def from_command(cls, command: List[str], **kwargs):
        inst = cls(models.BatchAttributesV1(**kwargs))
        inst.commands = [shlex.join(command)]
        return inst

    @classmethod
    def from_jobs(cls, batch: models.BatchJobV1, **kwargs):
        """
        Generate the batch script from a set of jobs.

        With more than one job, we assume we are waiting.
        """
        inst = cls(models.BatchAttributesV1(**kwargs))
        if len(batch.jobs) > 1:
            for job_str in batch.jobs:
                inst.commands.append(f"flux submit --wait {job_str}")
            # Assume we want to wait for all jobs
            inst.commands.append("flux job wait --all")
        else:
            inst.commands = batch.jobs
        return inst

    def add_service(self, name: str, **kwargs):
        """
        Add a service by name. Services can be started one off (a la-carte) separate
        from any kind of proper flux module. Keyword arguments become service
        attributes, on top of the batch attributes.
        """
        service = services.new_service(name, attributes=self.attributes, **kwargs)
        self.services.append(service)
        return service

    def add_prolog(self, cmd: str):
        self.prologs.append(cmd)

    def add_epilog(self, cmd: str):
        self.epilogs.append(cmd)

    def add_module(self, name: str, **kwargs):
        """
        A module typically has a service name. E.g., flux-scribe is added as a module,
        and the module starts a service. Keyword arguments become service attributes,
        e.g. add_module("usernetes", mode="worker", cluster_name="lammps").
        """
        module = services.new_service(name, attributes=self.attributes, **kwargs)
        self.modules.append(module)
        return module

    @property
    def modprobe_dir(self):
        """
        Directory for the rendered modprobe rc scripts, passed to Flux via
        FLUX_MODPROBE_PATH_APPEND. Scoped by job name so concurrent jobs with
        different module configurations (a cluster and a burst of workers,
        say) do not overwrite each other's scripts.
        """
        slug = self.attributes.job_name or "default"
        return os.path.expanduser(f"~/.flux-batch/{slug}")

    def get_cli_flags(self) -> List[str]:
        """
        Converts BatchAttributesV1 into a list of strings for subprocess.
        """
        flags = []
        attr = self.attributes

        # Mapping table for simple flags
        mapping = {
            "nslots": "-n",
            "cores_per_slot": "-c",
            "gpus_per_slot": "-g",
            "nodes": "-N",
            "bank": "-B",
            "queue": "-q",
            "time_limit": "-t",
            "urgency": "--urgency",
            "job_name": "--job-name",
            "cwd": "--cwd",
            "dependency": "--dependency",
            "requires": "--requires",
            "begin_time": "--begin-time",
            "signal": "--signal",
            "broker_opts": "--broker-opts",
            "dump": "--dump",
            "flags": "--flags",
        }

        for field_name, flag in mapping.items():
            val = getattr(attr, field_name)
            if val is not None:
                flags.extend([flag, str(val)])

        # Boolean flags
        if attr.exclusive or any(m.exclusive_nodes for m in self.modules):
            flags.append("--exclusive")
        if attr.unbuffered:
            flags.append("-u")
        if attr.wrap:
            flags.append("--wrap")

        # Multi-use flags
        multi_mapping = {
            "setopt": "-o",
            "setattr": "-S",
            "add_file": "--add-file",
            "env": "--env",
            "env_remove": "--env-remove",
            "env_file": "--env-file",
            "rlimit": "--rlimit",
            "conf": "--conf",
        }
        for field_name, flag in multi_mapping.items():
            for val in getattr(attr, field_name):
                flags.extend([flag, str(val)])

        # If we have modules, ensure they are added --conf <module>=true
        if self.modules:
            # Tell Flux to look in this spec's directory for rc scripts
            flags.extend(["--env", f"FLUX_MODPROBE_PATH_APPEND={self.modprobe_dir}"])

            # If modules are used, we need to pass the service names into the Flux config
            # so the @task 'needs_config' filter allows them to run
            for mod in self.modules:
                flags.extend(["--conf", f"{mod.name}=true"])

        return flags

    def render(self) -> str:
        """
        Generate the jobspec.
        """
        return self.generate_wrapper_script()

    def generate_wrapper_script(self) -> str:
        """
        Generate the wrapper script.

        1. Start with hashbang!
        2. Add prologs
        3. Add services start
        4. Add jobs/commands
        5. Stop services
        6. And epilogs
        7. Custom scripts

        Yes, it's redundant to write them as comments but I like the organization. -v
        """
        # hashbang
        lines = ["#!/bin/bash"]

        # prologs
        lines.extend(self.prologs)
        for s in self.services:
            lines.extend(s.generate_start())

        # modules can gate the workload (e.g., wait for the cluster to be ready)
        for m in self.modules:
            lines.extend(m.generate_batch_prolog())

        # commands that are derived from jobs or command
        lines.extend(self.commands)

        # module epilogs
        for m in reversed(self.modules):
            lines.extend(m.generate_batch_epilog())

        # stop services
        for s in reversed(self.services):
            lines.extend(s.generate_stop())

        # epilogs
        lines.extend(self.epilogs)

        # custom user scripts
        if self.attributes.logs_dir is not None:
            lines.append(self.script_save_logs())
        return "\n".join(lines)

    def script_save_logs(self):
        """
        Custom saving of logs. This is what we wrote for our performance study.
        """
        script_path = scripts.get_script("save_logs.sh")

        # Determine output directory (use home default if not defined)
        return f"bash {script_path} {self.attributes.logs_dir}"
