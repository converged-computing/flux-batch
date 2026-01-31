import flux
from rich import print

import flux_batch


def test_submission():
    print("Flux Batch Module Test")

    # 1. Initialize a Flux handle
    try:
        handle = flux.Flux()
        print("[OK] Connected to Flux.")
    except Exception as e:
        print(f"[FAIL] Could not connect to Flux: {e}")
        return

    # 2. Define a Batch of work (Multiple commands)
    print("[*] Creating batch jobs...")
    batch = flux_batch.BatchJobV1()
    batch.add_job(["/bin/echo", "Job 1 starting"])
    batch.add_job(["/bin/sleep", "5"])
    batch.add_job(["/bin/echo", "Job 2 finished"])

    # 3. Create the Jobspec with explicit attributes
    # These match the allowed arguments defined in models.py
    print("[*] Mapping attributes to BatchJobspecV1...")
    jobspec = flux_batch.BatchJobspecV1.from_jobs(
        batch, nodes=1, nslots=1, time_limit="10m", job_name="test-batch"
    )

    # 4. Add the Scribe Service
    # This will trigger the logic in service.py to write the ~/.config file
    # jobspec.add_service("flux-scribe")

    # 5. Add a simple Prolog/Epilog
    jobspec.add_prolog("echo 'Batch Wrapper Starting'")
    jobspec.add_epilog("echo 'Batch Wrapper Finished'")

    # Submit! The dryrun returns the script
    try:
        print("[*] Previewing submission (Dryrun -> Wrapper)...")
        print(flux_batch.submit(handle, jobspec, dry_run=True))
        print("[*] Performing submission (Dryrun -> Wrapper -> Submit)...")
        jobid = flux_batch.submit(handle, jobspec)
        print(f"[SUCCESS] Batch submitted! Flux Job ID: {jobid}")
    except Exception as e:
        print(f"[FAIL] Submission failed: {e}")
        return

    # 7. Verification of Systemd Provisioning
    # TODO need to write / test
    # service_path = os.path.expanduser("~/.config/systemd/user/flux-scribe.service")
    # if os.path.exists(service_path):
    #    print(f"[OK] Systemd service was provisioned at {service_path}")
    # else:
    #    print("[FAIL] Systemd service was NOT found.")


if __name__ == "__main__":
    test_submission()
