import json
import os
import stat
import subprocess
import tempfile

import flux
import flux.job

import flux_batch.models as models
import flux_batch.service as services
import flux_batch.utils as utils


def setup(spec):
    """
    shared function to generate services / modules from a spec.
    """
    # Provision services (like flux-scribe) if requested
    for service in spec.services:
        services.ensure_user_service(service)
    for module in spec.modules:
        services.ensure_modprobe_scripts(module)


def generate_jobspec(spec, script, wrapper_path):
    """
    Shared function to write a script to a wrapper path and generate
    a jobspec for it via flux batch --dry-run.
    """
    utils.write_file(script, wrapper_path)

    # Make the script executable so 'flux batch' can analyze it
    os.chmod(wrapper_path, os.stat(wrapper_path).st_mode | stat.S_IEXEC)

    # Generate the RFC 25 Jobspec JSON via the Flux CLI
    # This handles all resource mapping (-N, -n, etc.)
    cmd = ["flux", "batch"] + spec.get_cli_flags() + ["--dry-run", wrapper_path]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error during flux batch dryrun: {e.stderr}")
        raise
    return result.stdout


def preview(spec: models.BatchJobV1) -> int:
    """
    Preview the jobspec.
    """
    setup(spec)

    with tempfile.TemporaryDirectory() as tmpdir:

        # Write the wrapper script (handling prologs, services, and jobs)
        wrapper_path = os.path.join(tmpdir, "wrapper.sh")
        script = spec.generate_wrapper_script()
        jobspec = generate_jobspec(spec, script, wrapper_path)
        return json.loads(jobspec)


def submit(handle: flux.Flux, spec: models.BatchJobV1, dry_run=False) -> int:
    """
    Orchestrates the submission process:
    1. Provisions any required user-space services.
    2. Generates the wrapper shell script.
    3. Uses 'flux batch --dryrun' to compile the Jobspec JSON.
    4. Submits the Jobspec to the Flux instance.
    """
    setup(spec)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Write the wrapper script (handling prologs, services, and jobs)
        wrapper_path = os.path.join(tmpdir, "wrapper.sh")

        # dry run here just displays it
        script = spec.generate_wrapper_script()
        if dry_run:
            return script

        jobspec = generate_jobspec(spec, script, wrapper_path)

        # Submit the JSON string to the Flux instance
        # The result.stdout contains the raw JSON Jobspec
        return flux.job.submit(handle, jobspec)
