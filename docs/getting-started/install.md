# Installation

flux-batch uses the Flux Python bindings, which ship with flux-core rather than
PyPI. Run everything through `flux python`: it starts the Python that Flux was
built against, with the bindings already on the path, so installs and scripts
always use the same interpreter.

```bash
git clone https://github.com/converged-computing/flux-batch
cd flux-batch
flux python -m pip install --user -e .
```

Or install the latest release from PyPI:

```bash
flux python -m pip install --user flux-batch
```

If pip refuses with an "externally managed environment" error, add
`--break-system-packages`.

Optional extras:

| Extra     | Install                                              | Needed for                                          |
| --------- | ---------------------------------------------------- | --------------------------------------------------- |
| `scribe`  | `flux python -m pip install --user -e ".[scribe]"`   | the [flux-scribe](../modules/flux-scribe.md) module |

## Running inside an allocation

flux-batch submits to whichever Flux instance `flux.Flux()` connects to. To run
work inside an allocation, connect to the allocation's instance first. Request
it in the background, then ssh to its first node:

```bash
flux alloc -q pall -N2 --setattr=dw="#DW jobdw capacity=400GiB type=xfs name=testfs" --bg -t 4h
flux jobs -a          # note the job id and the first node in its node list
ssh <first node>
```

On the node, point Flux at the allocation and check that it worked:

```bash
export FLUX_URI=$(flux uri --local <jobid>)
flux resource list    # should show the allocation's nodes, not the whole machine
```

`flux uri --local` only works on the allocation's first node, where its main
broker runs. Without `FLUX_URI`, a shell on a compute node talks to the
system instance, and batch jobs would go to the machine's queue as new jobs
instead of running inside your allocation.

Then run scripts with `flux python`:

```bash
cd flux-batch
flux python examples/save_logs.py
```
