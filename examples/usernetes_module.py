import flux
import flux_batch

# for pretty printing
from rich import print

handle = flux.Flux()

# Create your batch job with some number of commands
# We assume this is some work that would require usernetes
batch = flux_batch.BatchJobV1()
batch.add_job(["echo", "Job 1 starting"])
batch.add_job(["sleep", "2000"])
batch.add_job(["echo", "Job 2 finished"])

# Wrap it up into a jobspec
# This will just start a control plane
spec = flux_batch.BatchJobspecV1.from_jobs(
    batch,
    nodes=2,
    nslots=2,
    time_limit="10m",
    job_name="test-usernetes",
)

# Add a prolog and epilog
spec.add_prolog("echo 'Batch Wrapper Starting'")
spec.add_epilog("echo 'Batch Wrapper Finished'")

# Adding the usernetes module will block / wait (maybe not)?
# If not, how do we ensure we wait?
spec.add_module("usernetes")

# Preview it
jobid = flux_batch.submit(handle, spec, dry_run=True)
jobspec = flux_batch.jobspec(spec)

# Submit that bad boi.
jobid = flux_batch.submit(handle, spec)
print(jobspec)
print(jobid)
