# Testing

All of these run in CI (`.github/workflows/test.yaml`) inside the
`fluxrm/flux-sched:jammy` container on every pull request.

## Without Flux

These run anywhere: no Flux, podman or Kubernetes needed.

```bash
# Usernetes orchestration end to end, with kubectl, make, flux and the
# usernetes service scripts stubbed. Add -v to print the launcher logs.
./tests/test_usernetes_launchers.sh

# Jobspec building: commands, the wrapper script, flux batch flags
python3 -m pytest tests/test_jobspec.py

# Template rendering for the usernetes module
python3 -m pytest tests/test_usernetes_module.py
```

The launcher test covers the stale join command guard, cluster bring-up,
the readiness gate, bursting, departures, the one-node-per-host lock,
teardown and failure paths.

## With Flux

Under a broker, these submit real batch jobs and check what ran: single
and multi-job batches, prolog and epilog order, dry runs, failure
reporting, and the compiled jobspec for a usernetes job (exclusive
nodes, the module conf, the readiness gate in the wrapper). They skip
instead of failing when there is no broker.

```bash
flux start python3 -m pytest tests/test_flux_batch.py
```

## On a cluster

To check the usernetes module for real, follow
[Deploy a cluster](../modules/usernetes.md#deploy-a-cluster) and then
[Burst workers into it](../modules/usernetes.md#burst-workers-into-it). Three
things only a real run confirms: that the modprobe tasks start under your Flux
version, that `ssh $(hostname)` works without a password on every node (the
default `use_ssh=True` depends on it), and that `flux hostlist --expand local` works inside the
batch job.

## Docs

```bash
cd docs
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
make serve    # http://localhost:8000
```
