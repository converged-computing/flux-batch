# flux-batch

**A Python SDK to generate Flux batch jobs and the services that run alongside them.**

flux-batch builds a batch job from a list of commands, wraps it with prologs,
epilogs and services, and submits it to a [Flux](https://flux-framework.org)
instance. Modules go further: they deploy something across every node of the
batch job before your work starts. The [usernetes module](modules/usernetes.md),
for example, stands up a user space Kubernetes cluster inside the allocation.

```python
import flux
import flux_batch

batch = flux_batch.BatchJobV1()
batch.add_job(["echo", "hello from flux-batch"])

spec = flux_batch.BatchJobspecV1.from_jobs(batch, nodes=1, time_limit="10m")
jobid = flux_batch.submit(flux.Flux(), spec)
```

:::{note}
flux-batch is experimental. If you are looking for the `flux batch` command
itself, see its [manual page](https://flux-framework.readthedocs.io/projects/flux-core/en/latest/man1/flux-batch.html).
:::

```{toctree}
:caption: Getting started
:maxdepth: 2

getting-started/install
getting-started/batch-jobs
```

```{toctree}
:caption: Modules and services
:maxdepth: 2

modules/index
modules/usernetes
modules/flux-scribe
```

```{toctree}
:caption: Reference
:maxdepth: 2

development/testing
api
related
```
