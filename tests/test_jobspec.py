"""
Unit tests for jobspec building: commands, the wrapper script, and the
flux batch flags. No Flux instance (or Flux python bindings) required.

Run with: pytest tests/test_jobspec.py
"""

import sys
import types

# flux_batch.submit imports flux at module import time (and annotates with
# flux.Flux); stub it so these rendering tests run without the bindings.
if "flux" not in sys.modules:
    flux_stub = types.ModuleType("flux")
    flux_stub.Flux = object
    flux_stub.job = types.ModuleType("flux.job")
    sys.modules["flux"] = flux_stub
    sys.modules["flux.job"] = flux_stub.job

import flux_batch  # noqa: E402


def make_batch(*commands):
    batch = flux_batch.BatchJobV1()
    for command in commands:
        batch.add_job(list(command))
    return batch


def test_single_job_runs_directly():
    batch = make_batch(["echo", "hello"])
    spec = flux_batch.BatchJobspecV1.from_jobs(batch, nodes=1, nslots=1)
    assert spec.commands == ["echo hello"]


def test_multiple_jobs_are_submitted_and_waited_on():
    batch = make_batch(["echo", "one"], ["echo", "two"])
    spec = flux_batch.BatchJobspecV1.from_jobs(batch, nodes=1, nslots=1)
    assert spec.commands == [
        "flux submit --wait echo one",
        "flux submit --wait echo two",
        "flux job wait --all",
    ]


def test_job_arguments_are_shell_quoted():
    batch = make_batch(["echo", "two words"])
    spec = flux_batch.BatchJobspecV1.from_jobs(batch, nodes=1, nslots=1)
    assert spec.commands == ["echo 'two words'"]


def test_from_command():
    spec = flux_batch.BatchJobspecV1.from_command(["sleep", "10"], job_name="nap")
    assert spec.commands == ["sleep 10"]
    assert spec.attributes.job_name == "nap"


def test_wrapper_script_order():
    batch = make_batch(["echo", "work"])
    spec = flux_batch.BatchJobspecV1.from_jobs(batch, nodes=1, nslots=1)
    spec.add_prolog("echo prolog")
    spec.add_epilog("echo epilog")
    script = spec.generate_wrapper_script()

    lines = script.splitlines()
    assert lines[0] == "#!/bin/bash"
    assert lines.index("echo prolog") < lines.index("echo work") < lines.index("echo epilog")


def test_cli_flags_simple_mapping():
    batch = make_batch(["echo", "hello"])
    spec = flux_batch.BatchJobspecV1.from_jobs(
        batch, nodes=2, nslots=4, queue="pall", time_limit="1h", job_name="demo"
    )
    flags = spec.get_cli_flags()
    for pair in (["-N", "2"], ["-n", "4"], ["-q", "pall"], ["-t", "1h"], ["--job-name", "demo"]):
        index = flags.index(pair[0])
        assert flags[index + 1] == pair[1]


def test_cli_flags_booleans():
    batch = make_batch(["echo", "hello"])
    spec = flux_batch.BatchJobspecV1.from_jobs(batch, nodes=1, nslots=1)
    assert "--exclusive" not in spec.get_cli_flags()
    assert "-u" not in spec.get_cli_flags()

    spec.attributes.exclusive = True
    spec.attributes.unbuffered = True
    flags = spec.get_cli_flags()
    assert "--exclusive" in flags
    assert "-u" in flags


def test_cli_flags_multi_use():
    batch = make_batch(["echo", "hello"])
    spec = flux_batch.BatchJobspecV1.from_jobs(
        batch, nodes=1, nslots=1, env=["A=1", "B=2"], setattr=["dw=#DW jobdw"]
    )
    flags = spec.get_cli_flags()
    joined = " ".join(flags)
    assert "--env A=1" in joined
    assert "--env B=2" in joined
    assert "-S dw=#DW jobdw" in joined


def test_modules_add_conf_and_modprobe_path(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    batch = make_batch(["echo", "hello"])
    spec = flux_batch.BatchJobspecV1.from_jobs(batch, nodes=1, nslots=1, job_name="demo")
    spec.add_module("usernetes", cluster_name="demo")
    joined = " ".join(spec.get_cli_flags())
    assert "--conf usernetes=true" in joined
    assert f"FLUX_MODPROBE_PATH_APPEND={tmp_path}/.flux-batch/demo" in joined


def test_no_module_no_conf():
    batch = make_batch(["echo", "hello"])
    spec = flux_batch.BatchJobspecV1.from_jobs(batch, nodes=1, nslots=1)
    joined = " ".join(spec.get_cli_flags())
    assert "--conf" not in joined
    assert "FLUX_MODPROBE_PATH_APPEND" not in joined


def test_modprobe_dir_is_scoped_by_job_name():
    batch = make_batch(["echo", "hello"])
    cluster = flux_batch.BatchJobspecV1.from_jobs(batch, job_name="cluster")
    burst = flux_batch.BatchJobspecV1.from_jobs(batch, job_name="burst")
    unnamed = flux_batch.BatchJobspecV1.from_jobs(batch)
    assert cluster.modprobe_dir != burst.modprobe_dir
    assert unnamed.modprobe_dir.endswith("default")
