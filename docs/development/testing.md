# Testing

## Without Flux

These run anywhere: no Flux, podman or Kubernetes needed.

```bash
# Usernetes orchestration end to end, with kubectl, make, flux and the
# usernetes service scripts stubbed. Add -v to print the launcher logs.
./tests/test_usernetes_launchers.sh

# Template rendering for the usernetes module
python3 -m pytest tests/test_usernetes_module.py
```

The launcher test covers the stale join command guard, cluster bring-up,
the readiness gate, bursting, departures, teardown and failure paths.

## With Flux

Inside a Flux instance, this submits a small batch job with a prolog and
epilog:

```bash
flux start
flux python ./tests/test_flux_batch.py
```

```console
$ flux jobs -a
       JOBID USER     NAME       ST NTASKS NNODES     TIME INFO
   ƒMX29AwFu vscode   test-batch CD      1      1   6.354s 68e8c4399c15
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
