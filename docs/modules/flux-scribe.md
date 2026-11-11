# flux-scribe

:::{warning}
flux-scribe is written but still needs testing.
:::

flux-scribe runs on rank 0 of the batch job and records every job event of the
instance to a database, using the Flux journal consumer. Install the extra
dependencies first:

```bash
flux python -m pip install --user "flux-batch[scribe]"
```

Then add the module and choose a database:

```bash
export FLUX_SCRIBE_DATABASE=sqlite:///flux-batch-job.db
flux python ./examples/flux_scribe_module.py
```

```python
spec.add_module("flux-scribe")
```

## Settings

| Variable | Default | Description |
| --- | --- | --- |
| `FLUX_SCRIBE_DATABASE` | `sqlite:///server_state.db` | Database URL to write events to. |
| `FLUX_SCRIBE_SSL` | unset | Set to anything except `no`, `false` or `off` to connect with SSL. |
| `FLUX_SCRIBE_UID` | unset | Identifier stored with every recorded event. |
