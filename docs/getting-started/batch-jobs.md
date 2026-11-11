# Batch jobs

A batch job is built in three steps: collect the commands, wrap them into a
jobspec with resources and options, then preview or submit it.

## Build and submit

```python
import flux
import flux_batch

handle = flux.Flux()

# 1. Commands to run inside the batch job
batch = flux_batch.BatchJobV1()
batch.add_job(["echo", "Job 1 starting"])
batch.add_job(["sleep", "5"])
batch.add_job(["echo", "Job 2 finished"])

# 2. Resources and options (these mirror the flux batch flags)
spec = flux_batch.BatchJobspecV1.from_jobs(
    batch,
    nodes=1,
    nslots=1,
    time_limit="10m",
    job_name="test-batch",
)

# Commands to run before and after the work
spec.add_prolog("echo 'Batch Wrapper Starting'")
spec.add_epilog("echo 'Batch Wrapper Finished'")

# 3. Preview the wrapper script, inspect the jobspec, then submit
print(flux_batch.submit(handle, spec, dry_run=True))
jobspec = flux_batch.jobspec(spec)
jobid = flux_batch.submit(handle, spec)
```

With more than one job, each is run with `flux submit --wait` and the wrapper
ends with `flux job wait --all`. A single command runs as-is. To run one
command directly, use `BatchJobspecV1.from_command(["hostname"], nodes=1)`.

The preview above prints the generated wrapper:

```bash
#!/bin/bash
echo 'Batch Wrapper Starting'
flux submit --wait /bin/echo 'Job 1 starting'
flux submit --wait /bin/sleep 5
flux submit --wait /bin/echo 'Job 2 finished'
flux job wait --all
echo 'Batch Wrapper Finished'
```

## What goes into the wrapper

The wrapper script is assembled in this order:

1. Prologs (`add_prolog`)
2. Service start commands (`add_service`)
3. Module gates, for example waiting for a cluster to be ready (`add_module`)
4. Your jobs or command
5. Module and service teardown, in reverse order
6. Epilogs (`add_epilog`)
7. Log saving, if `logs_dir` is set

## Job attributes

Keyword arguments to `from_jobs` and `from_command` become
{class}`flux_batch.models.BatchAttributesV1` fields and map onto `flux batch`
flags:

| Attribute | Flag | Attribute | Flag |
| --- | --- | --- | --- |
| `nodes` | `-N` | `job_name` | `--job-name` |
| `nslots` | `-n` | `cwd` | `--cwd` |
| `cores_per_slot` | `-c` | `dependency` | `--dependency` |
| `gpus_per_slot` | `-g` | `requires` | `--requires` |
| `exclusive` | `-x` | `begin_time` | `--begin-time` |
| `time_limit` | `-t` | `signal` | `--signal` |
| `bank` | `-B` | `broker_opts` | `--broker-opts` |
| `queue` | `-q` | `flags` | `--flags` |
| `urgency` | `--urgency` | `unbuffered` | `-u` |

These take lists and repeat the flag once per value: `setopt` (`-o`),
`setattr` (`-S`), `add_file`, `env`, `env_remove`, `env_file`, `rlimit`, and
`conf`.

## Saving logs

Set `logs_dir` and the wrapper saves the output, jobspec and event log of
every job in the instance to that directory before it exits:

```python
spec = flux_batch.BatchJobspecV1.from_jobs(
    batch, nodes=1, time_limit="10m", logs_dir="./logs"
)
```

See `examples/save_logs.py` in the repository.
