# Python API

## Building jobs

```{eval-rst}
.. autoclass:: flux_batch.BatchJobV1
   :members:

.. autoclass:: flux_batch.BatchJobspecV1
   :members: from_command, from_jobs, add_prolog, add_epilog, add_service, add_module, get_cli_flags, generate_wrapper_script

.. autoclass:: flux_batch.models.BatchAttributesV1
```

## Submitting

```{eval-rst}
.. autofunction:: flux_batch.submit

.. autofunction:: flux_batch.jobspec
```

## Modules

```{eval-rst}
.. autoclass:: flux_batch.service.usernetes.service.UsernetesService
   :members: mode, cluster_name, usernetes_root, launcher_command
```
