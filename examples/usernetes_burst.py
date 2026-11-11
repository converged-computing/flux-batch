"""
Burst more workers into an existing usernetes cluster.

Submit this while a cluster-mode job (examples/usernetes_module.py) is
running: EVERY node of this job starts a worker that joins the cluster named
below. The original control plane notices the new nodes, re-syncs their
external IPs (restarting calico-node where it autodetected the wrong
address), and deletes the node objects again when this job ends.
"""

import argparse

import flux

import flux_batch
from rich import print

parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
parser.add_argument("--nodes", type=int, default=2, help="nodes in this job (default: 2)")
parser.add_argument("--cluster-name", default="demo", help="cluster to create or join (default: demo)")
args = parser.parse_args()

handle = flux.Flux()

# The burst job's own workload: it can be empty (just add capacity for the
# cluster), or run jobs that use the newly added nodes. The nodes leave the
# cluster when these jobs finish, so hold them until the job is cancelled.
batch = flux_batch.BatchJobV1()
batch.add_job(["sleep", "infinity"])

spec = flux_batch.BatchJobspecV1.from_jobs(
    batch,
    nodes=args.nodes,
    nslots=args.nodes,
    # No time_limit: the job runs until its allocation ends.
    job_name="usernetes-burst",
)

# mode="worker": all ranks (rank 0 included) join the existing cluster.
# cluster_name must match the running cluster's name.
spec.add_module("usernetes", mode="worker", cluster_name=args.cluster_name)

print(flux_batch.submit(handle, spec, dry_run=True))
print("flux batch " + " ".join(spec.get_cli_flags()))
jobid = flux_batch.submit(handle, spec)
print(jobid)
