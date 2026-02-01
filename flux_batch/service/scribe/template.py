# Template for the Scribe Journal Consumer
SERVICE_TEMPLATE = """[Unit]
Description=Flux Scribe Journal Consumer
After=network.target

[Service]
ExecStart={python_path} -m flux_batch.service.scribe
Restart=on-failure

[Install]
WantedBy=default.target
"""

START_MODULE_TEMPLATE = """
from flux.modprobe import task
import flux.subprocess as subprocess

@task(
    "start-{service_name}",
    ranks="0",
    needs_config=["{service_name}"],
    after=["resource", "job-list"],
)
def start_{service_func}(context):
    # This triggers the systemd user service provisioned earlier
    # context.bash("systemctl --user start {service_name}")
    subprocess.rexec_bg(
        context.handle,
        ["{python_bin}", "-m", "{module_name}"],
        label="{service_name}",
        nodeid=0
    )
"""

STOP_MODULE_TEMPLATE = """
from flux.modprobe import task
import flux.subprocess as subprocess

@task(
    "stop-{service_name}",
    ranks="0",
    needs_config=["{service_name}"],
    before=["resource", "job-list"],
)
def stop_{service_func}(context):
    # context.bash("systemctl --user stop {service_name}")
    subprocess.kill(context.handle, signum=2, label="{service_name}").get()
    try:
        status = subprocess.wait(context.handle, label="{service_name}").get()["status"]
        print(status)
    except:
        pass
"""
