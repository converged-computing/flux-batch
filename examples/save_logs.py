import flux
import flux_batch

# for pretty printing
from rich import print

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
    job_name="test-batch",
    # Add saving of logs, info, and metadata
    logs_dir="./logs",
)

# Add a prolog and epilog
jobspec.add_prolog("echo 'Batch Wrapper Starting'")
jobspec.add_epilog("echo 'Batch Wrapper Finished'")

# Preview it
print(flux_batch.submit(handle, jobspec, dry_run=True))

# Submit that bad boi.
jobid = flux_batch.submit(handle, jobspec)
