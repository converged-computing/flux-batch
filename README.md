# flux-batch

> Python SDK to generate Flux batch jobs and services

[![PyPI version](https://badge.fury.io/py/flux-batch.svg)](https://badge.fury.io/py/flux-batch)

![https://github.com/converged-computing/flux-batch/raw/main/img/flux-batch-small.png](https://github.com/converged-computing/flux-batch/raw/main/img/flux-batch-small.png)

## Related Projects

- [flux-mcp](https://github.com/converged-computing/flux-mcp): MCP functions for Flux.
- [flux-mcp-server](https://github.com/converged-computing/flux-mcp-server): MCP server.
- [fractale-mcp](https://github.com/compspec/fractale-mcp): (fractale) MCP orchestration (agents, databases, ui interfaces).
- [hpc-mcp](https://github.com/converged-computing/hpc-mcp): HPC tools for a larger set of HPC and converged computing use cases.

## Services

 - **flux-scribe**: Write job events to a local sqlite database via the JournalConsumer (not added yet, written and needs testing)

## Usage

This is a small Flux utility that makes it easy to create Flux batch jobs and services.
The use case is to submit work (one or more jobs) under an instance, and run a custom service, or epilog and prolog commands. We will provision several services here, and you can also provide your own name to start / stop.

### Setup

Install the library and start (or be in) a flux instance.

```bash
flux start
pip install -e . --break-system-packages
```

### Example

Run the controlled example to see a batch job with prolog and epilog run and complete:

```bash
python3 ./tests/test_flux_batch.py
```
```console
Flux Batch Module Test
[OK] Connected to Flux.
[*] Creating batch jobs...
[*] Mapping attributes to BatchJobspecV1...
[*] Previewing submission (Dryrun -> Wrapper)...
#!/bin/bash
echo 'Batch Wrapper Starting'
flux submit --wait /bin/echo 'Job 1 starting'
flux submit --wait /bin/sleep 5
flux submit --wait /bin/echo 'Job 2 finished'
flux job wait --all
echo 'Batch Wrapper Finished'
[*] Performing submission (Dryrun -> Wrapper -> Submit)...
[SUCCESS] Batch submitted! Flux Job ID: ƒMX29AwFu
```
```bash
$ flux jobs -a
       JOBID USER     NAME       ST NTASKS NNODES     TIME INFO
   ƒMX29AwFu vscode   test-batch  R      1      1   4.213s 68e8c4399c15
```
```bash
$ flux jobs -a
       JOBID USER     NAME       ST NTASKS NNODES     TIME INFO
   ƒMX29AwFu vscode   test-batch CD      1      1   6.354s 68e8c4399c15
```

Here is an explicit (manual) example to do the same:

```python
import flux
import flux_batch

# for pretty printing
# from rich import print

handle = flux.Flux()

# Create your batch job with some number of commands
batch = flux_batch.BatchJobV1()
batch.add_job(["echo", "Job 1 starting"])
batch.add_job(["sleep", "5"])
batch.add_job(["echo", "Job 2 finished"])

# Wrap it up into a jobspec
jobspec = flux_batch.BatchJobspecV1.from_jobs(
    batch,
    nodes=1,
    nslots=1,
    time_limit="10m",
    job_name="test-batch"
)

# Add a prolog and epilog
jobspec.add_prolog("echo 'Batch Wrapper Starting'")
jobspec.add_epilog("echo 'Batch Wrapper Finished'")

# Add a service (this assumes user level that exists)
# jobspec.add_service("my-service'")

# Preview it
print(flux_batch.submit(handle, jobspec, dry_run=True))

# Submit that bad boi.
jobid = flux_batch.submit(handle, jobspec)
```

## TODO

- Option for controlled output (that we can easily get after)
- Create flux-scribe service, add example (need to test on cluster with systemctl)

## License

HPCIC DevTools is distributed under the terms of the MIT license.
All new contributions must be made under this license.

See [LICENSE](https://github.com/converged-computing/cloud-select/blob/main/LICENSE),
[COPYRIGHT](https://github.com/converged-computing/cloud-select/blob/main/COPYRIGHT), and
[NOTICE](https://github.com/converged-computing/cloud-select/blob/main/NOTICE) for details.

SPDX-License-Identifier: (MIT)

LLNL-CODE- 842614
