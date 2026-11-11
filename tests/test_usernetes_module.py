"""
Unit tests for the usernetes module: template rendering, modes, and the
wrapper script. No Flux instance (or Flux python bindings) required.

Run with: pytest tests/test_usernetes_module.py
"""

import os
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
from flux_batch.service.usernetes.service import UsernetesService  # noqa: E402


def make_spec(**module_kwargs):
    batch = flux_batch.BatchJobV1()
    batch.add_job(["echo", "hello"])
    spec = flux_batch.BatchJobspecV1.from_jobs(
        batch, nodes=2, nslots=2, time_limit="1h", job_name="u7s-test"
    )
    module = spec.add_module("usernetes", **module_kwargs)
    return spec, module


def test_cluster_mode_templates():
    spec, module = make_spec(cluster_name="demo", usernetes_root="/some/checkout")
    assert module.mode == "cluster"

    start = module.module_start_template
    # Rank 0 runs the control plane, other ranks run workers
    assert "launch-control-plane.sh" in start
    assert "launch-worker.sh" in start
    assert 'ranks="0"' in start
    assert 'ranks=">0"' in start
    assert "USERNETES_CLUSTER_NAME=demo" in start
    assert "USERNETES_ROOT=/some/checkout" in start
    assert "USERNETES_EXPECTED_NODES=2" in start
    # The same launch id is rendered into both commands
    assert start.count(f"USERNETES_LAUNCH_ID={module.launch_id}") == 2

    stop = module.module_shutdown_template
    assert "signum=15" in stop


def test_worker_mode_templates():
    spec, module = make_spec(mode="worker", cluster_name="demo")
    assert module.mode == "worker"
    start = module.module_start_template
    # Every rank is a worker in a burst job
    assert "launch-control-plane.sh" not in start
    assert start.count("launch-worker.sh") == 2
    assert "USERNETES_MODE=worker" in start


def test_burst_is_worker_mode():
    _, module = make_spec(mode="burst")
    assert module.mode == "worker"


def test_unique_launch_ids_per_submission():
    _, first = make_spec()
    _, second = make_spec()
    assert first.launch_id != second.launch_id


def test_wrapper_script_gates_on_readiness():
    spec, module = make_spec(cluster_name="demo")
    script = spec.generate_wrapper_script()
    assert "wait-for-ready.sh" in script
    assert "${HOME}/.usernetes/clusters/demo" in script
    # Rank 0 of a cluster-mode job is the control plane node
    assert "export KUBECONFIG=" in script
    # The gate comes before the workload
    assert script.index("wait-for-ready.sh") < script.index("echo hello")


def test_worker_mode_wrapper_has_no_kubeconfig():
    spec, _ = make_spec(mode="worker", cluster_name="demo")
    script = spec.generate_wrapper_script()
    assert "wait-for-ready.sh" in script
    assert "export KUBECONFIG=" not in script


def test_ssh_wrapping_is_default():
    _, module = make_spec()
    assert "ssh -tt -o BatchMode=yes $(hostname)" in module.module_start_template


def test_ssh_wrapping_can_be_disabled():
    _, module = make_spec(use_ssh=False)
    start = module.module_start_template
    assert "ssh " not in start
    assert "exec /bin/bash" in start


def test_usernetes_env_passthrough():
    _, module = make_spec(usernetes_env={"USERNETES_STORAGE_ROOT": "/tmp/me/storage"})
    assert "USERNETES_STORAGE_ROOT=/tmp/me/storage" in module.module_start_template


def test_cli_flags_use_spec_modprobe_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    spec, _ = make_spec()
    flags = spec.get_cli_flags()
    joined = " ".join(flags)
    assert f"FLUX_MODPROBE_PATH_APPEND={tmp_path}/.flux-batch/u7s-test" in joined
    assert "usernetes=true" in joined


def test_setup_writes_modprobe_scripts(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    spec, module = make_spec(cluster_name="one")
    module.setup(base_dir=spec.modprobe_dir)
    rc1 = os.path.join(spec.modprobe_dir, "rc1.d", "usernetes.py")
    rc3 = os.path.join(spec.modprobe_dir, "rc3.d", "usernetes.py")
    assert os.path.exists(rc1) and os.path.exists(rc3)
    with open(rc1) as fd:
        content = fd.read()
    assert "USERNETES_CLUSTER_NAME=one" in content
    assert "start_usernetes" in content

    # A re-submission with a different configuration overwrites the scripts
    spec2, module2 = make_spec(cluster_name="two")
    module2.setup(base_dir=spec2.modprobe_dir)
    with open(rc1) as fd:
        assert "USERNETES_CLUSTER_NAME=two" in fd.read()


def test_invalid_mode_rejected():
    _, module = make_spec(mode="sideways")
    try:
        module.mode
    except ValueError:
        return
    raise AssertionError("mode 'sideways' should be rejected")


def test_launcher_scripts_exist():
    service = UsernetesService(is_service=False, is_module=True, attributes={})
    for script in (
        "launch-common.sh",
        "launch-control-plane.sh",
        "launch-worker.sh",
        "wait-for-ready.sh",
    ):
        assert os.path.exists(os.path.join(service.script_dir, script)), script


def test_usernetes_requests_exclusive_nodes():
    spec, _ = make_spec(mode="worker", cluster_name="demo")
    assert "--exclusive" in spec.get_cli_flags()
