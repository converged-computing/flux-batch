"""
Deploy user space Kubernetes (usernetes, hetchy branch) under a flux batch job.

Rank 0 of the batch job starts the control plane; every other rank starts a
worker that waits for the join command on the shared filesystem. The batch
wrapper waits until the cluster (and every node of this job) is Ready before
running the jobs below. See examples/usernetes_burst.py for adding workers
from a second job.
"""

import argparse

import flux

import flux_batch

# for pretty printing
from rich import print

parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
parser.add_argument("--nodes", type=int, default=2, help="nodes in this job (default: 2)")
parser.add_argument("--cluster-name", default="demo", help="cluster to create or join (default: demo)")
args = parser.parse_args()

handle = flux.Flux()

# Create your batch job with some number of commands.
# We assume this is work that needs the usernetes cluster.
batch = flux_batch.BatchJobV1()
batch.add_job(["kubectl", "get", "nodes", "-o", "wide"])
# The cluster is torn down when these jobs finish, so hold it open until the
# job is cancelled or the allocation ends.
batch.add_job(["sleep", "infinity"])

# Wrap it up into a jobspec
spec = flux_batch.BatchJobspecV1.from_jobs(
    batch,
    nodes=args.nodes,
    nslots=args.nodes,
    # No time_limit: inside an allocation the job runs until the allocation ends,
    # and a limit longer than the time left is rejected.
    job_name="usernetes-cluster",
)

# Deploy usernetes across the job: rank 0 control plane, ranks >0 workers.
# cluster_name identifies the cluster so a later burst job can join it.
# usernetes_root must be a checkout of the hetchy branch, visible on every
# node (it defaults to $USERNETES_ROOT, then /usr/workspace/usernetes/usernetes-wip).
spec.add_module(
    "usernetes",
    cluster_name=args.cluster_name,
    # usernetes_root="/usr/workspace/usernetes/usernetes-wip",
    # container_tech="podman",
    # wait_timeout=3600,
    # use_ssh=False,  # default True: ssh to each node for a systemd user session
    # usernetes_env={"USERNETES_STORAGE_ROOT": "/tmp/$USER/podman-storage"},
)

# Preview the wrapper script, then submit
print(flux_batch.submit(handle, spec, dry_run=True))
print("flux batch " + " ".join(spec.get_cli_flags()))
jobid = flux_batch.submit(handle, spec)
print(jobid)
