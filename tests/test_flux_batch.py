"""
Integration tests: submit real batch jobs and check what they ran.

These need the Flux python bindings and a live broker:

    flux start python3 -m pytest tests/test_flux_batch.py

They are skipped (not failed) when either is missing, so the full test
suite can still run on machines without Flux.
"""

import os

import pytest

flux = pytest.importorskip("flux", reason="flux python bindings not available")
import flux.job  # noqa: E402

import flux_batch  # noqa: E402


@pytest.fixture(scope="module")
def handle():
    try:
        return flux.Flux()
    except Exception:
        pytest.skip("no Flux broker (run under: flux start python3 -m pytest ...)")


def run_batch(handle, spec):
    """
    Submit and wait, asserting the batch job itself succeeded.
    """
    jobid = flux_batch.submit(handle, spec)
    result = flux.job.result(handle, jobid)
    assert result.returncode == 0, f"batch job failed: {result}"
    return result


def test_single_job_batch(handle, tmp_path):
    marker = tmp_path / "ran"
    batch = flux_batch.BatchJobV1()
    batch.add_job(["touch", str(marker)])
    spec = flux_batch.BatchJobspecV1.from_jobs(batch, nodes=1, nslots=1, job_name="t-single")
    run_batch(handle, spec)
    assert marker.exists()


def test_multi_job_batch(handle, tmp_path):
    """
    Multiple jobs become nested 'flux submit --wait' submissions.
    """
    batch = flux_batch.BatchJobV1()
    batch.add_job(["bash", "-c", f"hostname > {tmp_path}/one"])
    batch.add_job(["bash", "-c", f"echo two > {tmp_path}/two"])
    spec = flux_batch.BatchJobspecV1.from_jobs(batch, nodes=1, nslots=1, job_name="t-multi")
    run_batch(handle, spec)
    assert (tmp_path / "one").read_text().strip()
    assert (tmp_path / "two").read_text().strip() == "two"


def test_prolog_and_epilog_run_in_order(handle, tmp_path):
    log = tmp_path / "order"
    batch = flux_batch.BatchJobV1()
    batch.add_job(["bash", "-c", f"echo job >> {log}"])
    spec = flux_batch.BatchJobspecV1.from_jobs(batch, nodes=1, nslots=1, job_name="t-order")
    spec.add_prolog(f"echo prolog >> {log}")
    spec.add_epilog(f"echo epilog >> {log}")
    run_batch(handle, spec)
    assert log.read_text().split() == ["prolog", "job", "epilog"]


def test_dry_run_returns_wrapper(handle):
    batch = flux_batch.BatchJobV1()
    batch.add_job(["echo", "hello"])
    spec = flux_batch.BatchJobspecV1.from_jobs(batch, nodes=1, nslots=1, job_name="t-dry")
    script = flux_batch.submit(handle, spec, dry_run=True)
    assert isinstance(script, str)
    assert script.startswith("#!/bin/bash")
    assert "echo hello" in script

    # A dry run submits nothing: the job list has no job named t-dry
    jobs = flux.job.job_list(handle).get_jobs()
    assert not any(job["name"] == "t-dry" for job in jobs)


def test_batch_failure_is_reported(handle, tmp_path):
    batch = flux_batch.BatchJobV1()
    batch.add_job(["bash", "-c", "exit 7"])
    spec = flux_batch.BatchJobspecV1.from_jobs(batch, nodes=1, nslots=1, job_name="t-fail")
    jobid = flux_batch.submit(handle, spec)
    result = flux.job.result(handle, jobid)
    assert result.returncode != 0


def test_usernetes_module_flags_reach_flux(handle, tmp_path, monkeypatch):
    """
    The full submission path with a module: the rendered modprobe scripts are
    written, and the compiled jobspec carries the conf and the exclusive
    allocation. We stop at the compiled jobspec; running usernetes itself
    needs real nodes.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    import json

    from flux_batch.submit import generate_jobspec, setup

    batch = flux_batch.BatchJobV1()
    batch.add_job(["kubectl", "get", "nodes"])
    spec = flux_batch.BatchJobspecV1.from_jobs(batch, nodes=1, nslots=1, job_name="t-u7s")
    spec.add_module("usernetes", cluster_name="ci")

    setup(spec)
    wrapper_path = os.path.join(str(tmp_path), "wrapper.sh")
    compiled = generate_jobspec(spec, spec.generate_wrapper_script(), wrapper_path)
    jobspec = json.loads(compiled)

    # Rendered modprobe rc scripts: start (rc1.d) and stop (rc3.d) tasks
    modprobe_dir = os.path.join(str(tmp_path), ".flux-batch", "t-u7s")
    assert os.path.exists(os.path.join(modprobe_dir, "rc1.d", "usernetes.py"))
    assert os.path.exists(os.path.join(modprobe_dir, "rc3.d", "usernetes.py"))

    # The compiled jobspec asks for exclusive nodes and enables the module
    files = jobspec["attributes"]["system"]["files"]
    assert files["conf.json"]["data"] == {"usernetes": True}
    node = [r for r in jobspec["resources"] if r["type"] == "node"][0]
    assert node.get("exclusive") is True
    env = jobspec["attributes"]["system"]["environment"]
    assert env["FLUX_MODPROBE_PATH_APPEND"] == modprobe_dir

    # The wrapper gates the workload on cluster readiness before the job
    wrapper = files["script"]["data"]
    assert wrapper.index("wait-for-ready.sh") < wrapper.index("kubectl get nodes")
