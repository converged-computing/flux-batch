import os
import shlex
from typing import List

import flux_batch.models as models
import flux_batch.script as scripts


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

    def add_service(self, service: str):
        self.services.append(service)

    def add_prolog(self, cmd: str):
        self.prologs.append(cmd)

    def add_epilog(self, cmd: str):
        self.epilogs.append(cmd)

    def add_module(self, service_name: str):
        self.modules.append(service_name)

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
        if attr.exclusive:
            flags.append("-x")
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
            # Tell Flux to look in our user home for rc scripts
            modprobe_path = os.path.expanduser("~/.flux-batch")
            flags.extend(["--env", f"FLUX_MODPROBE_PATH_APPEND={modprobe_path}"])

            # If modules are used, we need to pass the service names into the Flux config
            # so the @task 'needs_config' filter allows them to run
            for mod in self.modules:
                flags.extend(["--conf", f"{mod}=true"])

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
            lines.append(f"systemctl --user start {s}")

        # commands that are derived from jobs or command
        lines.extend(self.commands)

        # stop services
        for s in reversed(self.services):
            lines.append(f"systemctl --user stop {s}")

        # epilogs
        lines.extend(self.epilogs)

        # custom user scripts
        if self.attributes.logs_dir is not None:
            lines.append(self.script_save_logs())
        return "\n".join(lines)

    def script_save_logs(self):
        """
        Custom saving of logs. This is what we wrote for our peformance study!
        """
        script_path = scripts.get_script("save_logs.sh")

        # Determine output directory (use home default if not defined)
        return f"bash {script_path} {self.attributes.logs_dir}"
