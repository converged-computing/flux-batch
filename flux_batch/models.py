from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union


@dataclass
class BatchJobV1:
    """
    Commands to be run within the batch wrapper.

    This should mirror JobspecV1
    """

    jobs: List[str] = field(default_factory=list)

    def add_job(self, command: List[str]):
        import shlex

        self.jobs.append(shlex.join(command))


@dataclass
class BatchAttributesV1:
    """
    Explicitly defined arguments allowed by flux batch for V1 spec
    """

    # Resources
    nslots: Optional[int] = None  # -n
    cores_per_slot: Optional[int] = None  # -c
    gpus_per_slot: Optional[int] = None  # -g
    nodes: Optional[int] = None  # -N
    exclusive: bool = False  # -x

    # Basic Options
    bank: Optional[str] = None  # -B
    queue: Optional[str] = None  # -q
    time_limit: Optional[str] = None  # -t
    urgency: Optional[int] = None  # --urgency
    job_name: Optional[str] = None  # --job-name
    cwd: Optional[str] = None  # --cwd

    # More complex options
    setopt: List[str] = field(default_factory=list)  # -o
    setattr: List[str] = field(default_factory=list)  # -S
    add_file: List[str] = field(default_factory=list)  # --add-file
    env: List[str] = field(default_factory=list)  # --env
    env_remove: List[str] = field(default_factory=list)  # --env-remove
    env_file: List[str] = field(default_factory=list)  # --env-file
    rlimit: List[str] = field(default_factory=list)  # --rlimit
    conf: List[str] = field(default_factory=list)  # --conf

    # Other Attributes
    dependency: Optional[str] = None  # --dependency
    requires: Optional[str] = None  # --requires
    begin_time: Optional[str] = None  # --begin-time
    signal: Optional[str] = None  # --signal
    broker_opts: Optional[str] = None  # --broker-opts
    dump: Optional[str] = None  # --dump

    # Flags
    unbuffered: bool = False  # -u
    wrap: bool = False  # --wrap
    flags: Optional[str] = None  # --flags (debug, waitable, etc)
