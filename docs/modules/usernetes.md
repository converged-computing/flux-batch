# Usernetes

The usernetes module deploys [user space Kubernetes](https://github.com/converged-computing/usernetes)
across the nodes of a batch job. The per-node work (rootless podman storage,
image builds, `kubeadm`) is done by the service scripts of a usernetes checkout,
under its `service/` directory. flux-batch orchestrates around them: which node
starts first, how workers find the join command, when your work may start, and
how nodes leave.

## Modes

**Cluster mode** (the default) builds a new cluster from the whole job.

1. Rank 0 starts the control plane.
2. Every other rank starts a worker, which waits for this job's join command.
3. Once the expected number of nodes has registered, rank 0 installs the CNI and syncs the external IPs of the nodes.
4. When every node is Ready, the batch wrapper runs your jobs, with `KUBECONFIG` exported.

**Worker mode** bursts more nodes into a cluster that is already running. Every rank of the job, rank 0 included, starts a worker that joins the existing cluster named by `cluster_name`. The control plane of the original job notices the new nodes, re-syncs their external IPs, and restarts calico-node on any node that picked up the wrong address. When the burst job ends, its nodes are deleted from the cluster.

## Deploy a cluster

Request an allocation with rabbit storage, then ssh to its first node:

```bash
flux alloc -q pall -N2 --setattr=dw="#DW jobdw capacity=400GiB type=xfs name=testfs" --bg -t 4h
flux jobs -a          # note the job id and the first node in its node list
ssh <first node>
```

Note that we still need to ssh in because `systemd` with `--user` is broken. When flux shell can set that up, we don't need to do that. On the node, connect to the allocation and launch:

```bash
# Submit into the allocation, not the system instance
# You can also flux proxy to the local:// socket path
export FLUX_URI=$(flux uri --local <jobid>)
flux resource list    # should show the allocation's 2 nodes
```
You can target a usernetes clone of your choice. This is a Usernetes checkout visible on every node, this is my development branch that uses the rabbit for container storage (podman and containerd within). See "hetchy" on https://github.com/converged-computing/usernetes.

```bash
export USERNETES_ROOT=/usr/workspace/usernetes/usernetes-wip

# Quick
cd flux-batch
flux python examples/usernetes_module.py --nodes 2 --cluster-name demo
```

The cluster name is important as it will share the join key in your `~/.usernetes/demo/join-command` for other jobs to find. You can tweak the number of nodes as you see fit.  The example adds the module like this:

```python
spec = flux_batch.BatchJobspecV1.from_jobs(
    batch, nodes=2, nslots=2, job_name="usernetes-cluster"
)
spec.add_module("usernetes", cluster_name="demo")
```

The cluster lives only as long as the batch job. When the last job finishes, the instance shuts down and every node runs `make down-v`. The cluster stays up until you `flux cancel` the job or the allocation ends. To use the cluster from a shell on the control plane node:

```bash
cd /tmp/$USER/usernetes && . source_env.sh
kubectl get nodes
```

## Burst workers into it

If we want to join nodes from different jobs, we can use bursting. While the cluster job is running, either from the same allocation (or a different one) again ssh to its first node, and connect to it:

```bash
export FLUX_URI=$(flux uri --local <second jobid>)
export USERNETES_ROOT=/usr/workspace/usernetes/usernetes-wip
cd flux-batch
flux python examples/usernetes_burst.py --nodes 1 --cluster-name demo
```

It will find the cluster join-command in the expected named path in your `$HOME` and use it to join to the cluster.  This is how it does that - it adds the module, but joins as a worker node.

```python
spec.add_module("usernetes", mode="worker", cluster_name="demo")
```

To try a burst without a second allocation, split one 2-node allocation into two 1-node jobs. The module always requests whole nodes (`flux batch --exclusive`), so each job gets its own node:

```bash
# control plane on one node
flux python examples/usernetes_module.py --nodes 1
# once kubectl get nodes shows it Ready, this is a worker on the other node
flux python examples/usernetes_burst.py --nodes 1
```

I have not yet tested this directly from a system instance, but I think it should work. Ideally we can do this without needing ssh, eventually. The `cluster_name` must match the running cluster. A burst worker waits until that cluster is ready, and fails after `wait_timeout` seconds if it never is.

## Attributes

Pass these to `add_module("usernetes", ...)`.

| Attribute | Default | Description |
| --- | --- | --- |
| `mode` | `cluster` | `cluster` to build a cluster, `worker` (or `burst`) to join one. |
| `cluster_name` | `default` | Names the cluster; a burst job joins by this name. |
| `usernetes_root` | `$USERNETES_ROOT`, then `/usr/workspace/usernetes/usernetes-wip` | Usernetes checkout whose `service/` scripts do the per-node work. Must be visible on every node. |
| `shared_root` | `$HOME/.usernetes/clusters` | Shared filesystem directory that holds the state of each cluster. |
| `wait_timeout` | `3600` | Seconds to wait for each phase: join command, registration, Ready. |
| `container_tech` | `podman` | Rootless container engine. |
| `logs_dir` | `/tmp/$USER` | Where launcher and service logs are written on each node. |
| `use_ssh` | `True` | Launch through `ssh -tt $(hostname)`, so each node has the systemd user session the usernetes preflight check needs. Requires passwordless ssh between nodes. Set `False` only where broker tasks already get a user session. |
| `usernetes_env` | `{}` | Extra environment for the usernetes service scripts, such as `USERNETES_STORAGE_ROOT`, `USERNETES_CNI` or `CALICO_VXLAN_IIFNAME`. |

## Where things are

You can always look at logs on each node (control plane or worker) to see what is going on.

| What | Where |
| --- | --- |
| Cluster state: join command, launch id, `ready`, `ready-nodes`, `workers/`, `leaving/` | `~/.usernetes/clusters/<cluster_name>` |
| Launcher logs | `/tmp/$USER/usernetes-control-plane-launcher.log`, `usernetes-worker-launcher.log` |
| Usernetes service logs | `/tmp/$USER/usernetes-control-plane.log`, `usernetes-worker.log` |
| Working copy and `source_env.sh` on each node | `/tmp/$USER/usernetes` |
| Rendered modprobe scripts | `~/.flux-batch/<job name>` |

## How it stays safe across jobs

- **No stale join commands.** Each submission gets a launch id, rendered into both the control plane and worker commands. The control plane clears the  cluster directory and then writes the id; workers ignore any join command until they see their own id, so leftovers from an earlier cluster with the same name are never used.
- **No forgotten nodes.** A worker that stops leaves a marker in `leaving/`, and the control plane deletes that node from the cluster. Technically, we could skip this step and the node would register as `NotReady` but I prefer the cleanup.
- **One usernetes node per host.** Two usernetes nodes on one host would share the working copy and podman state and tear each other down. The module submits with exclusive nodes, and each launcher holds a host lock (`/tmp/$USER/.flux-batch-usernetes.lock`). A second launcher on a busy host exits with an error without touching the running node. We obviously use `--exclusive`. If we want to get wild and crazy we could test without and have multiple usernetes installs, but I don't see the use case for that.
- **Clean shutdown.** When the job ends, each node runs `make down-v`, and the control plane removes the `ready` sentinel so anything still waiting fails quickly instead of hanging.

## Troubleshooting

- **Nothing happens on a node.** Read the launcher log first; it names the phase it is waiting on and prints the tail of the service log if the service script died.
- **Workers wait forever.** Check that `~/.usernetes/clusters/<name>/launch-id` exists and that the control plane launcher log shows the join command was written.
- **`systemd not running? file not found: .../user@<uid>.service/cgroup.controllers`** in the service log: the node has no systemd user session. Keep `use_ssh=True` (the default) and check that `ssh $(hostname) true` works without a password on every node.
- **Pods on different nodes cannot reach each other.** Run `<usernetes_root>/service/check-calico.sh --fix` on the control plane.
